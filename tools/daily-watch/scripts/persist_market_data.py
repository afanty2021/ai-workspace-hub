"""日报持久化钩子（spec §5.1）：快照原样落盘 + watchlist series 快照级追加。

钩子=快照级写者：同日只补 null、绝不覆盖非空（spec §5.2 写者身份表）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime
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


def _fetched_day(snapshot: dict[str, Any]) -> str | None:
    """payload 自带 fetched_at（fetch_market_data 输出 UTC ISO）的日期段；非法/缺失返回 None。"""
    fetched = (snapshot.get("meta") or {}).get("fetched_at")
    if not isinstance(fetched, str):
        return None
    head = fetched[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", head):
        try:
            date.fromisoformat(head)  # 形状对也要过日历（02-31 之类）
            return head
        except ValueError:
            return None
    return None


def save_daily_snapshot(snapshot: dict[str, Any], data_root: Path, today: str | None = None) -> Path:
    """完整 payload 原样嵌套落盘（spec §4.1）；同日覆盖重写。today 可注入（测试用）。

    文件名日期优先取 payload 的 meta.fetched_at（复查 Minor③）：回填旧日期快照写旧
    日期文件——旧行为用墙钟命名，会把旧 payload 静默重写进当日快照；解析不出才退墙钟。
    """
    day = today or _fetched_day(snapshot) or datetime.now().strftime("%Y-%m-%d")
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
    snapshot = json.loads(Path(args.snapshot_file).read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        parser.error(f"--snapshot-file 顶层必须是 JSON 对象（得到 {type(snapshot).__name__}）")
    # 两种入参都接受（spec §5.1 CLI 手工补跑用）：fetch 原始输出（顶层 quotes 直接在）与
    # data/market/daily/ 落盘的 wrapper（顶层 payload）。直传 wrapper 不解包会零行追加、
    # 且把 wrapper 再包一层重写当日快照（静默数据损坏路径，friction-log 修根）
    if isinstance(snapshot.get("payload"), dict):
        snapshot = snapshot["payload"]
    if not isinstance(snapshot.get("quotes"), list):
        # 复查 Minor⑤：垃圾 JSON（传错文件）旧行为静默落盘快照+退出 0
        parser.error(f"--snapshot-file 顶层缺 quotes 数组（keys: {sorted(snapshot)}）"
                     "——既不是 fetch 输出也不是 daily wrapper")
    run_persist_hook(snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
