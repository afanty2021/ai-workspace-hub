"""盘后批量：全市场个股 + 板块指数时序（spec §5.2）。

交易日闸门 → canary 一次调用拿服务器最新交易日，≤ data/.state/ 该 scope 完成标记
即整轮短路（非交易日「成本近零」靠这个成立）。批量=权威写者（三档合并的 batch 档）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from market_data_io import (
    atomic_write_text,
    is_cn_series_symbol,
    normalize_cn_symbol,
    read_series_rows,
    sector_series_file,  # noqa: F401 — Task 4 sectors 接入后使用
    series_file,
    series_lock,
    upsert_series_rows,
)
from mootdx_source import _mootdx_call, log

_CANARY_SECTOR = "880301"


def fetch_server_latest_trade_date() -> str | None:
    try:
        df = _mootdx_call("index_bars", symbol=_CANARY_SECTOR, frequency=9, offset=1)
        if df is None or df.empty:
            return None
        return pd.Timestamp(df.index[-1]).date().isoformat()
    except Exception as exc:  # noqa: BLE001 — 闸门失败退化为逐票判断，不中断
        log(f"Warning: 交易日闸门 canary 失败，退化为逐票判断: {exc}")
        return None


def last_round_date(data_root: Path, scope: str) -> str | None:
    """上一轮该 scope 批量完成日 = `data/.state/last_{scope}_round` 标记内容。

    为什么用旁路标记而不是从数据文件推完成度（N1）：
    ① canary 板块文件会被 `--scope sectors` 单独执行写脏（e2e 11.2 与局部补跑
       都走这条路），以它当 stocks 完成标志会把「板块已更」误判成「个股已更」，
       全市场初始化整轮静默短路；
    ② market 文件由钩子与批量共同写，钩子行 source 同为 "mootdx"（fetch 口径），
       按 source 区分写者不可行；日报先于 16:30 跑会把当日误判为「已批量」
       → 当日全市场 T+1。
    标记与数据文件解耦，只在干净全量轮写入（见 run_stocks_update / run_sectors_update
    尾部：not tickers and fail == 0 and latest is not None）。
    """
    marker = data_root / ".state" / f"last_{scope}_round"
    if not marker.exists():
        return None
    text = marker.read_text(encoding="utf-8").strip()
    return text or None


def write_round_marker(data_root: Path, scope: str, date: str) -> None:
    state = data_root / ".state"
    state.mkdir(parents=True, exist_ok=True)
    atomic_write_text(state / f"last_{scope}_round", date + "\n")


def bars_to_rows(df: pd.DataFrame, *, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ts, rec in zip(df.index, df.to_dict("records")):
        def num(key: str) -> float | None:
            val = rec.get(key)
            return float(val) if val is not None else None

        row = {"date": pd.Timestamp(ts).date().isoformat(), "open": num("open"), "high": num("high"),
               "low": num("low"), "close": num("close"), "volume": num("volume"),
               "amount": num("amount"), "source": source}
        if "up_count" in rec:  # index_bars 板块行（spec §4.2）
            row["up_count"] = int(rec["up_count"]) if rec["up_count"] is not None else None
            row["down_count"] = int(rec["down_count"]) if rec["down_count"] is not None else None
        rows.append(row)
    return rows


def list_cn_symbols() -> list[tuple[str, int]]:
    """枚举全市场（前缀白名单过滤后），返回 (code, market)。数量以日志为准。"""
    out: set[tuple[str, int]] = set()
    for market in (0, 1):
        df = _mootdx_call("stocks", market=market)
        for raw in df["code"].astype(str):
            code = raw.zfill(6)
            if is_cn_series_symbol(code, market):
                out.add((code, market))
    log(f"前缀白名单过滤后待更新: {len(out)} 只")
    return sorted(out)


def _upsert_bars(path: Path, data_root: Path, code: str, backfill: int, *, source: str,
                 index: bool = False) -> None:
    method = "index_bars" if index else "bars"
    df = _mootdx_call(method, symbol=code, frequency=9, offset=backfill)
    if df is None or df.empty:
        return
    with series_lock(data_root, path.name) as acquired:
        if not acquired:
            return
        upsert_series_rows(path, bars_to_rows(df, source=source), writer="batch")


def run_stocks_update(data_root: Path, *, backfill: int = 30,
                      tickers: list[str] | None = None, latest: str | None = None) -> dict:
    stats = {"ok": 0, "skip": 0, "fail": 0}
    latest = latest or fetch_server_latest_trade_date()
    last_round = last_round_date(data_root, "stocks")
    if latest and last_round and latest <= last_round and not tickers:
        log(f"交易日闸门：服务器最新 {latest} ≤ 上轮批量 {last_round}，整轮跳过")
        return stats
    if tickers:
        targets = [(t.rsplit(".", 1)[0], 1 if t.upper().endswith(".SH") else 0) for t in tickers]
    else:
        targets = list_cn_symbols()
    for code, market in targets:
        path = series_file(data_root, normalize_cn_symbol(code, market))
        try:
            rows = read_series_rows(path)
            if rows and latest and rows[-1]["date"] >= latest:
                stats["skip"] += 1
                continue
            _upsert_bars(path, data_root, code, backfill, source="mootdx")
            stats["ok"] += 1
        except Exception as exc:  # noqa: BLE001 — 单票失败不中断
            stats["fail"] += 1
            log(f"Warning: {code} 更新失败: {exc}")
    log(f"stocks 汇总: {stats}")
    if not tickers and latest is not None and stats["fail"] == 0:
        write_round_marker(data_root, "stocks", latest)  # 干净全量轮才记完成（N1 补充点①）
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="盘后批量更新全市场/板块时序（spec §5.2）")
    parser.add_argument("--scope", choices=["stocks", "sectors", "all"], default="all")
    parser.add_argument("--backfill", type=int, default=30,
                        help="增量 bars 数；800=回补约 3.3 年（服务器单次上限）")
    parser.add_argument("--tickers", help="逗号分隔子集，调试用（如 600276.SH,300476.SZ）")
    args = parser.parse_args(argv)
    if args.tickers:  # 入参格式在动 data_root 之前就校验（M3：裸代码会被拼到错市场）
        tickers = []
        for raw in args.tickers.split(","):
            ticker = raw.strip().upper()
            if not re.fullmatch(r"\d{6}\.(SH|SZ)", ticker):
                parser.error(f"--tickers 只接受 6 位代码+.SH/.SZ（得到 {raw!r}）；海外票走日报钩子，不支持 bars 回补")
            tickers.append(ticker)
    else:
        tickers = None
    if tickers and args.scope == "sectors":
        parser.error("--tickers 只对 --scope stocks/all 有效（板块是枚举制清单，无子集路径，静默丢弃比报错更糟）")
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    stats = run_stocks_update(data_root, backfill=args.backfill, tickers=tickers)
    # sectors 在 Task 4 接入：--scope sectors/all 时 run_sectors_update(...)
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
