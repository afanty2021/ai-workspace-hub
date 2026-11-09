"""跨资产票历史日线回补（Q-20261109-04 出界项 C1）——东财 push2his 日 K。

与 update_market_series.py（A 股 mootdx 批量）的三个刻意差异：

1. **无交易日闸门**：跨资产多时区（美股 ET、港股 HK、美元/商品近 24h）没有统一的
   「服务器最新交易日」可做 canary；幂等改由每票自身 series 尾行决定增量起点
   （beg=尾行日，重拉当天让 batch 档用收盘价权威覆盖快照钩子的盘中值）。
2. **batch 档权威覆盖**：快照钩子行 amount=None、本脚本行 amount 恒非 None（写者
   指纹，同 spec §9）；同日冲突时收盘口径胜出——快照的抓取时点值（北京 16:30 抓
   美股=ET 盘中/前日）由此被修正为官方收盘。
3. **日期口径**：K 线日期=标的本地交易日（美股 ET、港股 HK）。探测实证：^SOX
   push2his 2026-11-05 收盘 9011.14 与 H1 档案一致，而快照钩子的 11-06 行 9390.25
   实为 ET 11-06 收盘——两条通路对同一 ET 交易日标注一致，可安全合流。

XAUUSD=X（伦敦金）无东财 secid（119.XAU 探测无数据），不回补——series 由日报
快照钩子逐日积累，5d/20d/60d 窗口在积累期内显示「—」属预期。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from market_data_io import read_series_rows, series_file, series_lock, upsert_series_rows
from mootdx_source import log

PUSH2HIS_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_PUSH_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Referer": "https://quote.eastmoney.com/",
}

# 回补映射（secid 与实时映射 EASTMONEY_GLOBAL_SYMBOLS 分离：DX-Y.NYB 实时走新浪、
# 回补走东财 100.UDI；HSTECH 实时/回补同 secid 124 段=东财港股指数）。
CROSS_ASSET_HISTORY_SECIDS: dict[str, str] = {
    "^IXIC": "100.NDX",
    "^SOX": "251.SOX",
    "^TNX": "171.US10Y",
    "NQ00Y": "103.NQ00Y",
    "DX-Y.NYB": "100.UDI",
    "HG=F": "109.LCPT",
    "HSTECH": "124.HSTECH",
}


def parse_klines(klines: list[str]) -> list[dict[str, Any]]:
    """`date,open,close,high,low,volume,amount` → series 行（amount 恒非 None=batch 指纹）。"""
    rows: list[dict[str, Any]] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            rows.append({
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "source": "eastmoney-kline",
            })
        except ValueError:
            continue  # 坏行跳过（与 read_json_auto ignore_errors 同语义）
    return rows


def fetch_kline_rows(secid: str, beg: str, end: str = "20500101") -> list[dict[str, Any]]:
    """带 1 次重试（datacenter 惯例）。push2his 与 push2 同域共享受 IP 级限流——
    连续大窗口请求会被 RemoteDisconnected（2026-11-09 实测 14 连发后整段断连），
    批量侧防御=票间节流（main 里 --throttle）+ 本函数重试。"""
    params = {
        "secid": secid, "klt": "101", "fqt": "1", "beg": beg, "end": end,
        "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            resp = requests.get(PUSH2HIS_URL, params=params,
                                headers=EM_PUSH_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            return parse_klines(data.get("klines") or [])
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            time.sleep(5.0)
    raise RuntimeError(f"push2his 请求失败（含 1 次重试）: {last_exc}")


def update_ticker(data_root: Path, ticker: str, secid: str, *,
                  backfill_days: int = 800, force: bool = False) -> str:
    """三态 'written' / 'empty' / 'fail'（无锁分支：钩子 16:30 前不与批量同跑，
    锁冲突按 fail 语义计，次日自愈）。"""
    path = series_file(data_root, ticker)
    try:
        rows = read_series_rows(path)
    except FileNotFoundError:
        rows = []
    window_start = (date.today() - timedelta(days=backfill_days)).strftime("%Y%m%d")
    if rows and not force:
        head = rows[0]["date"].replace("-", "")
        tail = rows[-1]["date"].replace("-", "")
        # 增量条件=series 首行早于等于窗口起点（历史已完整覆盖回补窗）——快照钩子
        # 攒出的浅 series（首行新、只有几天）必须全窗口拉，否则首次回补只拿增量
        # 1-2 行（2026-11-09 首跑实测踩过：尾行判定区分不了 5 行新票与完整历史）
        beg = tail if head <= window_start else window_start
    else:
        beg = window_start  # 全量 / force：整个回补窗口
    fetched = fetch_kline_rows(secid, beg)
    if not fetched:
        return "empty"
    with series_lock(data_root, path.name) as acquired:
        if not acquired:
            log(f"Warning: {ticker} 锁被其它进程持有，本次未更新")
            return "fail"
        changed = upsert_series_rows(path, fetched, writer="batch")
    log(f"{ticker}: 拉取 {len(fetched)} 行（beg={beg}），合并变更 {changed} 行")
    return "written"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跨资产票历史日线回补（东财 push2his，Q-20261109-04）")
    parser.add_argument("--backfill", type=int, default=800,
                        help="回补窗口天数（默认 800≈3.3 年；首次全量与 --force 都按此窗口）")
    parser.add_argument("--tickers", help=f"逗号分隔子集，只接受 {sorted(CROSS_ASSET_HISTORY_SECIDS)}")
    parser.add_argument("--force", action="store_true",
                        help="忽略 series 尾行、重拉整个回补窗口（快照脏数据修复用）")
    parser.add_argument("--throttle", type=float, default=3.0,
                        help="票间间隔秒数（push2his IP 级限流防御，默认 3.0）")
    args = parser.parse_args(argv)
    if args.tickers:
        tickers = []
        for raw in args.tickers.split(","):
            ticker = raw.strip().upper()
            if ticker not in CROSS_ASSET_HISTORY_SECIDS:
                parser.error(f"--tickers 只接受 {sorted(CROSS_ASSET_HISTORY_SECIDS)}（得到 {raw!r}）；"
                             "XAUUSD=X 无东财 secid 不支持回补（靠日报快照积累）")
            tickers.append(ticker)
    else:
        tickers = list(CROSS_ASSET_HISTORY_SECIDS)
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    stats = {"ok": 0, "skip": 0, "fail": 0}
    for idx, ticker in enumerate(tickers):
        secid = CROSS_ASSET_HISTORY_SECIDS[ticker]
        try:
            outcome = update_ticker(data_root, ticker, secid,
                                    backfill_days=args.backfill, force=args.force)
        except Exception as exc:  # noqa: BLE001 — 单票失败不中断
            outcome = "fail"
            log(f"Warning: {ticker} 回补失败: {exc}")
        if outcome == "written":
            stats["ok"] += 1
        elif outcome == "fail":
            stats["fail"] += 1
        else:
            stats["skip"] += 1
        if idx < len(tickers) - 1 and args.throttle > 0:
            time.sleep(args.throttle)
    log(f"cross-asset-history 汇总: {stats}")
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
