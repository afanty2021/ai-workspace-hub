"""日报持久化钩子（spec §5.1）：快照原样落盘 + watchlist series 快照级追加。

钩子=快照级写者：同日只补 null、绝不覆盖非空（spec §5.2 写者身份表）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from market_data_io import (
    atomic_write_text,
    parse_trade_date,
    resolve_data_root,
    series_file,
    series_lock,
    upsert_series_rows,
)
from mootdx_source import log


def save_daily_snapshot(snapshot: dict[str, Any], data_root: Path, today: str | None = None) -> Path:
    """完整 payload 原样嵌套落盘（spec §4.1）；同日覆盖重写。today 可注入（测试用）。"""
    day = today or datetime.now().strftime("%Y-%m-%d")
    out = data_root / "market" / "daily" / f"{day}.json"
    wrapper = {
        "schema_version": 1,
        "fetched_at": (snapshot.get("meta") or {}).get("fetched_at"),
        "payload": snapshot,
    }
    atomic_write_text(out, json.dumps(wrapper, ensure_ascii=False, indent=1))
    return out


def quote_to_series_row(quote: dict[str, Any]) -> dict[str, Any] | None:
    """fetch quote → series 行；tradeDate 解析失败返回 None（只进快照不进 series）。"""
    day = parse_trade_date(quote.get("tradeDate"))
    if day is None:
        return None

    def num(key: str) -> float | None:
        val = quote.get(key)
        if val is None:
            return None
        val = float(val)
        return val if math.isfinite(val) else None  # NaN/inf → null：非标 JSON 字面量不落盘

    return {
        "date": day, "open": num("open"), "high": num("dayHigh"), "low": num("dayLow"),
        "close": num("price"), "volume": num("volume"), "amount": None,
        "source": quote.get("source") or "snapshot",
    }


def append_series_from_snapshot(snapshot: dict[str, Any], data_root: Path) -> int:
    """watchlist 全部票快照级 upsert（幂等可重入）；返回写入行数。"""
    total = 0
    for quote in snapshot.get("quotes") or []:
        ticker = quote.get("ticker")
        row = quote_to_series_row(quote)
        if not ticker or row is None:
            if ticker:
                log(f"Warning: {ticker} tradeDate 不可解析，只进快照不进 series: {quote.get('tradeDate')!r}")
            continue
        path = series_file(data_root, ticker)
        with series_lock(data_root, path.name) as acquired:
            if not acquired:
                continue
            total += upsert_series_rows(path, [row], writer="snapshot")
    return total


def run_persist_hook(market_data: dict[str, Any], data_root: Path | None = None) -> None:
    """generate_daily_report 调用入口；持久化失败永不阻塞日报（spec §3）。"""
    try:
        root = data_root or resolve_data_root()
        save_daily_snapshot(market_data, root)
        append_series_from_snapshot(market_data, root)
    except Exception as exc:  # noqa: BLE001 — 设计要求吞掉一切
        log(f"Warning: 持久化钩子失败（不阻塞日报）: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist fetch payload snapshot + watchlist series")
    parser.add_argument("--snapshot-file", required=True, help="fetch_market_data.py > x.json 的重定向产物")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.snapshot_file).read_text(encoding="utf-8"))
    run_persist_hook(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
