# tools/sector-rotation/backfill.py
"""881 二级行业指数与 ETF 候选池深回补（spec §3.2）。

start 分页沿用持久化 spec L284 口径（mootdx k() 同款）；写回走 market_data_io
upsert 正规通道（writer=batch，与 16:30 cron 同写者语义）。指数落
data/sector/series/{code}.jsonl，ETF 落 data/market/series/{sym}.jsonl。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from market_data_io import series_lock, upsert_series_rows  # noqa: E402
from mootdx_source import _mootdx_call, log  # noqa: E402

PAGE = 800
TOTAL = 2600          # ≈ 10.7 年日线
SECTOR_DIR = "sector/series"
ETF_DIR = "market/series"


def _row_date(row) -> str:
    """日线行的 ISO 日期。真实 mootdx 无 date 列——datetime 索引重复为列
    （2026-11-05 实测，mootdx_source 头注释同口径）；date 列仅测试夹具使用。"""
    import pandas as pd

    if "date" in row.index:
        ts = row["date"]
    elif "datetime" in row.index:
        ts = row["datetime"]
    else:
        ts = row.name                       # datetime 索引兜底
    return pd.Timestamp(ts).date().isoformat()


def fetch_bars_paginated(symbol: str, *, index: bool, total: int = TOTAL,
                         page: int = PAGE) -> list[dict]:
    """symbol：指数裸码（881101）或带后缀 ETF（512480.SH）；API 用裸 6 位码。"""
    method = "index_bars" if index else "bars"
    bare = symbol.rsplit(".", 1)[0]
    by_date: dict[str, dict] = {}
    start = 0
    while start < total:
        try:
            df = _mootdx_call(method, symbol=bare, frequency=9,
                              offset=page, start=start)
        except Exception as exc:  # noqa: BLE001 — 单段失败保住已拉数据
            log(f"Warning: {symbol} start={start} 回补失败: {exc}")
            break
        if df is None or df.empty:
            break
        new = 0
        for _, row in df.iterrows():
            rec = {k: row[k] for k in
                   ("open", "high", "low", "close", "volume", "amount")}
            rec["date"] = _row_date(row)
            rec["source"] = "mootdx-backfill"
            if rec["date"] not in by_date:
                by_date[rec["date"]] = rec
                new += 1
        if len(df) < page or new == 0:
            break
        start += page
    return [by_date[d] for d in sorted(by_date)]


def _target_path(data_root: Path, symbol: str, *, index: bool) -> Path:
    sub = SECTOR_DIR if index else ETF_DIR
    return data_root / sub / f"{symbol}.jsonl"


def run_backfill(targets: list[tuple[str, bool]], data_root: Path,
                 *, total: int = TOTAL) -> dict[str, int]:
    stats = {"ok": 0, "empty": 0, "skip": 0}
    for symbol, is_index in targets:
        existing = verify_depth([(symbol, is_index)], data_root,
                                expect_bars=total)[0]
        if existing["rows"] >= total:          # 评审 M13：断点续传，已够深跳过
            stats["skip"] += 1
            continue
        rows = fetch_bars_paginated(symbol, index=is_index, total=total)
        if not rows:
            stats["empty"] += 1
            log(f"Warning: {symbol} 空返回（指数可能新增短史/ETF 可能退市——verify 复核）")
            continue
        path = _target_path(data_root, symbol, index=is_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        with series_lock(data_root, path.name) as acquired:   # 评审 I14：调用方持锁
            if not acquired:
                stats["skip"] += 1
                log(f"Warning: {symbol} 锁被其它进程持有，本轮跳过（重跑可续）")
                continue
            # Q-20261110-08 A 案（评审 I-2 注记）：防改写门同样护 source 写者标签——
            # cron 先建仓的新候选票（31..total-1 行）此处重拉全史时，source
            # mootdx/mootdx-index → mootdx-backfill 的字段差异属预期拒绝（保留原
            # provenance），告警非回归；OHLCV 真差异被拒更是本意（改史须显式确认）。
            upsert_series_rows(path, rows, writer="batch")
        stats["ok"] += 1
    log(f"回补汇总: {stats}")
    return stats


def verify_depth(targets: list[tuple[str, bool]], data_root: Path,
                 *, expect_bars: int) -> list[dict]:
    report = []
    for symbol, is_index in targets:
        path = _target_path(data_root, symbol, index=is_index)
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                 if ln.strip()] if path.exists() else []
        # market_data_io 落盘是 json.dumps 默认分隔符（冒号后带空格），
        # 紧凑切分 '"date":"' 在真实文件上会 IndexError（实测踩过）。
        dates = [ln.split('"date":', 1)[1].lstrip().split('"', 1)[1][:10]
                 for ln in lines] if lines else []
        report.append({"code": symbol, "rows": len(lines),
                       "first": dates[0] if dates else "",
                       "last": dates[-1] if dates else "",
                       "shortfall": max(0, expect_bars - len(lines))})
    return report


def _sector_targets(data_root: Path) -> list[tuple[str, bool]]:
    import json
    listing = json.loads((data_root / "sector" / "sector-list.json").read_text())
    return [(x["code"], True) for x in listing if x["category"] == "二级行业"]


def ex_dividend_scan(data_root: Path, symbols: list[str]) -> list[dict]:
    """疑似除息事件粗检（评审 I9）：ETF 单日 close 跌幅 < -5% 记事件。
    通达信日线不复权、除息跳空保留——open→close 周收益会漏分红，方向为系统性
    低估收益；事件清单进 P0 数据现实报告声明偏差方向，不改价格序列。"""
    import json
    events = []
    for sym in symbols:
        path = data_root / "market" / "series" / f"{sym}.jsonl"
        if not path.exists():
            continue
        rows = [json.loads(ln) for ln in
                path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        for prev, cur in zip(rows, rows[1:]):
            if prev.get("close") and cur.get("close"):
                chg = cur["close"] / prev["close"] - 1.0
                if chg < -0.05:
                    events.append({"etf": sym, "date": cur["date"], "drop": chg})
    return events


def _read_candidates(path: Path) -> list[str]:
    # delisted-etf.txt 约定（Step 5）：每行一代码，整行 # 注释与行尾 # 来源注释都跳过
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        code = ln.split("#", 1)[0].strip()
        if code:
            out.append(code)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("indices", help="回补 881 全集二级行业指数")
    p_etf = sub.add_parser("etfs", help="回补候选池 ETF（含退市探测清单）")
    p_etf.add_argument("--candidates", type=Path, default=None)
    p_ver = sub.add_parser("verify", help="深度分布 + 退市可得性报告")
    p_ver.add_argument("--etf-candidates", type=Path, default=None)
    args = ap.parse_args(argv)
    data_root = REPO_ROOT / "data"
    cand_default = data_root / "sector-rotation" / "etf-candidates.txt"
    delist_default = data_root / "sector-rotation" / "delisted-etf.txt"
    if args.cmd == "indices":
        run_backfill(_sector_targets(data_root), data_root)
        return 0
    if args.cmd == "etfs":
        codes = _read_candidates(args.candidates or cand_default)
        if delist_default.exists():          # 退市代码同样试拉（spec §3.1 探测项）
            codes += _read_candidates(delist_default)
        run_backfill([(c, False) for c in codes], data_root)
        return 0
    targets = _sector_targets(data_root)
    etf_syms: list[str] = []
    for path in filter(None, (args.etf_candidates, cand_default, delist_default)):
        if path.exists():
            etf_syms += _read_candidates(path)
    targets += [(c, False) for c in etf_syms]
    for row in verify_depth(targets, data_root, expect_bars=TOTAL):
        print(row)
    if etf_syms:
        print("--- 疑似除息事件（评审 I9：偏差方向=周收益系统性低估，详见 P0 数据现实报告）---")
        for ev in ex_dividend_scan(data_root, sorted(set(etf_syms))):
            print(ev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
