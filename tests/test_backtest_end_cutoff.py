# tests/test_backtest_end_cutoff.py
"""run_backtest `--end` 显式截尾锁（Q-20261126-16，jinniu + stage-bottom）。

数据窗此前=缓存当日状态（隐式）：jinniu 全市场交替持仓随缓存窗摆动
（-0.05@11-10 / +0.57@11-24 / +0.79@11-25），「同窗对比」没有显式参数就不成立。
锁法=对拍 harness（行为零变化的等价类验证）：同一票，
① `--end X` 的输出必须**逐字节等于**「预截断到 ≤X 的缓存」跑全窗的输出——截尾必须发生在
   load 后、一切计算前（信号/基础率/交替回测/年化全部继承同一窗口；截晚了输出必不同）；
② 缺省不截尾 = 缓存全窗（行为零变化）；
③ `--end` = 末根日期 ≡ 不截尾（边界零变化）；
④ `--end` 在最少样本数之前 = 该票按既有 <120 门跳过，exit 0。
全部假数据，不读真实缓存。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import run_check

# 合成平价数据会触发生产码里 numpy 的退化切片警告（std ddof<=0 / 0/0）——
# 断言只看输出逐字节对拍，不要求无警告，模块级过滤防全量 warning 噪音。
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

JN = run_check._load_module(run_check.JN_NAME, run_check.JN_PATH)
SB = run_check._load_module(run_check.SB_NAME, run_check.SB_PATH)

N_BARS = 260          # ≈52 周：日线段活跃（≥120），周线段（<60 周）两侧一致跳过
CUT_IDX = 150         # 截尾点：两侧都 ≥120 根，日线臂都活着


def _synth(n=N_BARS):
    dates = [int(d.strftime("%Y%m%d")) for d in pd.bdate_range("2023-01-02", periods=n)]
    o = [10.0 + (i % 7) * 0.3 for i in range(n)]
    high = [p + 0.2 for p in o]
    low = [p - 0.2 for p in o]
    close = [p + 0.1 for p in o]
    return dates, o, high, low, close


def _write_cache(root: Path, dates, cols):
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "600519.SH.jsonl", "w") as fh:
        for d, o, h, lo, c in zip(dates, *cols):
            fh.write(json.dumps({"date": str(d), "open": o, "high": h, "low": lo, "close": c}) + "\n")


def _rows(out: Path) -> list[dict]:
    return [json.loads(x) for x in (out / "per_stock.jsonl").read_text().splitlines()]


def _run(mod, cache, argv, tmp_path, monkeypatch, tag):
    # 每次运行独立 out 目录——两run共目录会自我覆盖，逐字节对拍退化成「文件和自己比」恒真
    # （变异验证抓出过此 bug：忽略 --end 的变异两发全活）。tag 必须区分每次运行。
    out = tmp_path / f"out_{tag}"
    monkeypatch.setattr(mod, "CACHE", cache)
    rc = mod.main([*argv, "--out", str(out)])
    return rc, out


def test_jinniu_end_cutoff_equiv_pretruncated_cache(tmp_path, monkeypatch):
    dates, o, h, lo, c = _synth()
    cut_date = dates[CUT_IDX]
    full, cut = tmp_path / "full", tmp_path / "cut"
    _write_cache(full, dates, (o, h, lo, c))
    _write_cache(cut, dates[:CUT_IDX + 1], (o[:CUT_IDX + 1], h[:CUT_IDX + 1],
                                            lo[:CUT_IDX + 1], c[:CUT_IDX + 1]))

    rc1, out1 = _run(JN, full, ["--end", str(cut_date)], tmp_path, monkeypatch, "end")
    rc2, out2 = _run(JN, cut, [], tmp_path, monkeypatch, "cut")
    assert rc1 == rc2 == 0
    # 对拍核心：--end X ≡ 缓存只到 X（逐字节）
    assert (out1 / "per_stock.jsonl").read_text() == (out2 / "per_stock.jsonl").read_text()
    row = _rows(out1)[0]
    assert row["end"] == cut_date and row["n"] == CUT_IDX + 1 and row["start"] == dates[0]


def test_jinniu_default_no_cutoff_is_full_cache(tmp_path, monkeypatch):
    dates, o, h, lo, c = _synth()
    cache = tmp_path / "full"
    _write_cache(cache, dates, (o, h, lo, c))
    rc, out = _run(JN, cache, [], tmp_path, monkeypatch, "full")
    assert rc == 0
    row = _rows(out)[0]
    assert row["n"] == N_BARS and row["end"] == dates[-1]


def test_jinniu_end_at_last_bar_equiv_no_cutoff(tmp_path, monkeypatch):
    dates, o, h, lo, c = _synth()
    cache = tmp_path / "full"
    _write_cache(cache, dates, (o, h, lo, c))
    _, out1 = _run(JN, cache, ["--end", str(dates[-1])], tmp_path, monkeypatch, "end")
    _, out2 = _run(JN, cache, [], tmp_path, monkeypatch, "plain")
    assert (out1 / "per_stock.jsonl").read_text() == (out2 / "per_stock.jsonl").read_text()


def test_jinniu_end_before_min_bars_skips_symbol(tmp_path, monkeypatch):
    dates, o, h, lo, c = _synth()
    cache = tmp_path / "full"
    _write_cache(cache, dates, (o, h, lo, c))
    rc, out = _run(JN, cache, ["--end", str(dates[50])], tmp_path, monkeypatch, "early")  # 51 根 <120
    assert rc == 0 and _rows(out) == []


def test_stage_bottom_end_cutoff_equiv_pretruncated_cache(tmp_path, monkeypatch):
    dates, o, h, lo, c = _synth()
    cut_date = dates[CUT_IDX]
    full, cut = tmp_path / "full", tmp_path / "cut"
    _write_cache(full, dates, (o, h, lo, c))
    _write_cache(cut, dates[:CUT_IDX + 1], (o[:CUT_IDX + 1], h[:CUT_IDX + 1],
                                            lo[:CUT_IDX + 1], c[:CUT_IDX + 1]))

    rc1, out1 = _run(SB, full, ["--end", str(cut_date)], tmp_path, monkeypatch, "end")
    rc2, out2 = _run(SB, cut, [], tmp_path, monkeypatch, "cut")
    assert rc1 == rc2 == 0
    assert (out1 / "per_stock.jsonl").read_text() == (out2 / "per_stock.jsonl").read_text()
    row = _rows(out1)[0]
    assert row["end"] == cut_date and row["n"] == CUT_IDX + 1
