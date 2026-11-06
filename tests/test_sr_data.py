# tests/test_sr_data.py
import json
from pathlib import Path

import numpy as np

from sector_rotation.data import build_weekly_frame
from sector_rotation.universe import Member, UniverseSpec

SPEC = UniverseSpec(
    members=[Member("881101", "工程机械", ("528030.SH", "528031.SH"), 0.10)],
    clusters={})


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


def _etf_rows(first: str, last: str, row=(1.0, 1.01, 3e8)) -> list[dict]:
    """显式日期区间的逐日行（评审 C7 修复附带：初版 fixture 1500 天止于 2024-02，
    盖不到 2026-11 决策周，valid 断言必失败——改为按区间生成）。"""
    from datetime import date, timedelta
    out, d, end = [], date.fromisoformat(first), date.fromisoformat(last)
    while d <= end:
        out.append({"date": d.isoformat(), "open": row[0], "close": row[1],
                    "amount": row[2]})
        d += timedelta(days=1)
    return out


def _build(root: Path, rows_528030: list[dict]):
    _write(root / "sector/series/881101.jsonl",
           [{"date": "2026-11-06", "close": 100.0},
            {"date": "2026-11-13", "close": 101.0},
            {"date": "2026-11-20", "close": 102.0}])
    _write(root / "market/series/528030.SH.jsonl", rows_528030)
    _write(root / "market/series/528031.SH.jsonl",
           _etf_rows("2025-06-02", "2026-11-13", (1.0, 1.01, 5e8)))
    _write(root / "market/series/510300.SH.jsonl",
           _etf_rows("2020-01-02", "2026-11-13", (1.0, 1.02, 1e9)))
    return build_weekly_frame(root, SPEC)


def test_point_in_time_symbol_selection(tmp_path: Path):
    _write(tmp_path / "sector/series/881101.jsonl",
           [{"date": "2026-11-06", "close": 100.0},
            {"date": "2026-11-13", "close": 101.0},
            {"date": "2026-11-20", "close": 102.0}])
    # 528030：2020 年上市且均额 3 亿（达标），日线止于 11-13；528031：2025 上市（不达标）
    _write(tmp_path / "market/series/528030.SH.jsonl",
           _etf_rows("2020-01-02", "2026-11-13"))
    _write(tmp_path / "market/series/528031.SH.jsonl",
           _etf_rows("2025-06-02", "2026-11-13", (1.0, 1.01, 5e8)))
    _write(tmp_path / "market/series/510300.SH.jsonl",
           _etf_rows("2020-01-02", "2026-11-13", (1.0, 1.02, 1e9)))
    wf = build_weekly_frame(tmp_path, SPEC)
    assert wf.etf_symbols[0][0] == "528030.SH"     # point-in-time 选中老 ETF
    assert wf.fridays == ["2026-11-06", "2026-11-13", "2026-11-20"]
    assert wf.valid[0][0]                          # 11-06 帧：执行周 11-09..13 存在
    assert not wf.valid[1][0] and not wf.valid[2][0]
    assert wf.dvalid[0][0] and wf.dvalid[1][0]     # 11-13 帧决策期有效（出信号场景）
    assert not wf.dvalid[2][0]                     # 11-20 帧 ETF 断档 → 决策期也无效
    assert wf.bench_300.shape == (len(wf.fridays),)


def test_split_guard_midweek_drop_masks_valid(tmp_path: Path):
    # 拆分防护（T4 修正案）：执行周内周二~周五生效的 >30% 单日跳空污染该周
    # open→close → valid=False 出宇宙一周；dvalid（决策期口径）与价格序列不动。
    base = _etf_rows("2020-01-02", "2026-11-13")
    split = [dict(r) for r in base]
    for r in split:                                # 2026-11-11（周三）起 close 减半：拆分形态
        if r["date"] >= "2026-11-11":
            r["close"] = 0.505
    wf_base = _build(tmp_path / "base", base)
    wf_split = _build(tmp_path / "split", split)
    assert wf_base.valid[0][0]                     # 基线：无跳空 → 执行周 11-09..13 有效
    assert not wf_split.valid[0][0]                # 周三生效 → 该 member-week 出宇宙
    assert wf_split.dvalid[0][0] == wf_base.dvalid[0][0]   # 决策期口径不受执行周污染
    # 只屏蔽、不改价格：执行周 open/close 照常记录（open=1.0，周五 close=0.505）
    assert wf_split.etf_open[0][0] == 1.0
    assert wf_split.etf_close[0][0] == 0.505


def test_split_guard_monday_jump_is_benign(tmp_path: Path):
    # 周一生效的拆分：整执行周 post-split，不标记 → valid 保持 True。
    split = [dict(r) for r in _etf_rows("2020-01-02", "2026-11-13")]
    for r in split:                                # 2026-11-09（周一）起 close 减半
        if r["date"] >= "2026-11-09":
            r["close"] = 0.505
    wf = _build(tmp_path, split)
    assert wf.valid[0][0]
    assert wf.dvalid[0][0]
    assert wf.etf_close[0][0] == 0.505             # 周一开盘 1.0 → 周五 0.505 是真实拆分周


def test_corrupt_threshold_disable(tmp_path: Path):
    # R20261106-02 §7 第 1 行：美股复权数据无拆分残留，拆分防护可参数化关闭
    # ——同一 30%+ 跳变数据，默认阈值屏蔽该周、corrupt_threshold=1e9 放行。
    split = _etf_rows("2020-01-02", "2026-11-13")
    for r in split:
        if r["date"] >= "2026-11-11":                 # 周三起 close 减半
            r["close"] = 0.505
    _build(tmp_path, split)                           # 布局落盘（帧用默认参数）
    wf_def = build_weekly_frame(tmp_path, SPEC)
    wf_off = build_weekly_frame(tmp_path, SPEC, corrupt_threshold=1e9)
    assert not wf_def.valid[0][0]                     # 默认 0.30：周二~周五生效跳变 → 屏蔽
    assert wf_off.valid[0][0]                         # 1e9：放行


def test_bench_symbol_param(tmp_path: Path):
    # R20261106-02 §7：bench_symbol 传入即用（美股 SPY），bench_300 字段名不动。
    _write(tmp_path / "sector/series/881101.jsonl",
           [{"date": "2026-11-06", "close": 100.0},
            {"date": "2026-11-13", "close": 101.0},
            {"date": "2026-11-20", "close": 102.0}])
    _write(tmp_path / "market/series/528030.SH.jsonl", _etf_rows("2020-01-02", "2026-11-13"))
    _write(tmp_path / "market/series/SPY.jsonl",
           _etf_rows("2020-01-02", "2026-11-13", (1.0, 1.05, 1e9)))
    wf = build_weekly_frame(tmp_path, SPEC, bench_symbol="SPY")
    assert np.isfinite(wf.bench_300[0]) and abs(wf.bench_300[0] - 0.05) < 1e-9


def test_pick_bypass_single_valid_from_first_data_week(tmp_path: Path):
    # R20261106-02 §7 第 5 行（计划评审 I-1）：单候选旁路后 valid 退化为数据
    # 齐备性——短史成员从首个执行周齐备周即 valid；默认路径上市<2 年
    # pick=None → valid 恒 False（不旁路则美股 2009-2010 静默缩宇宙且无警报，
    # 2012 年模型有效训练标签腰斩）。真实数据全窗 valid==11 断言在
    # repro_paper.py 自检（提案 §9）。
    spec1 = UniverseSpec([Member("881101", "工程机械", ("528030.SH",), 0.10)], {})
    _write(tmp_path / "sector/series/881101.jsonl",
           [{"date": d, "close": 100.0 + i}
            for i, d in enumerate(["2026-10-09", "2026-10-16", "2026-11-06"])])
    _write(tmp_path / "market/series/528030.SH.jsonl",
           _etf_rows("2026-10-02", "2026-11-13"))
    _write(tmp_path / "market/series/510300.SH.jsonl",
           _etf_rows("2020-01-02", "2026-11-13"))
    wf_def = build_weekly_frame(tmp_path, spec1)
    wf_byp = build_weekly_frame(tmp_path, spec1, pick_bypass_single=True)
    assert not wf_def.valid[:, 0].any()               # 默认：上市<2 年 → 恒 invalid
    assert wf_byp.valid[:, 0].all()                   # 旁路：数据齐备即 valid
