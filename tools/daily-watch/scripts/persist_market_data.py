"""日报持久化钩子（spec §5.1）：快照原样落盘 + watchlist series 快照级追加。

钩子=快照级写者：同日只补 null、绝不覆盖非空（spec §5.2 写者身份表）。
nasdaq 源行须过「美股 session 已收盘」闸门（_us_session_closed）：盘前/盘中
报价只进快照不进 series（friction 2026-11-03 第 2 次修根）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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


_ET = ZoneInfo("America/New_York")  # 与 market_data_io._ET 同源（美股日期口径一致）
_US_REG_CLOSE_ET = dt_time(16, 0)   # 美股常规收盘；半日提前收盘不细分——当晚少写一行，次日 asOf<今天 自然补上


def _us_session_closed(row_day: str, source: str | None, now_et: datetime) -> bool:
    """nasdaq 源的 series 行闸门：asOf 日的美股 session 已收盘才可信为该日收盘价。

    两个已发生的错写形态（2026-11-03 坐实）：①盘前抓取——价格=上一收盘、
    asOf=当日 → 周五价被写成 11-02 行（^SOX 10,687.62 vs 真实周一收盘
    10,328.33，险些漏判 H1 破线）；②个股盘前指示价（NVDA 有盘前交易）被写成
    当日收盘行。规则：asOf < 今天(ET) → 写（昨收及更早——指数 asOf 天然是最后
    交易日，隔天抓取恰好正确落行）；asOf == 今天且 ET ≥ 16:00 → 写（刚收盘）；
    asOf == 今天且未收盘、asOf > 今天（时钟错乱）→ 不写。其余源不过此门：CN 侧
    由批量权威写者覆盖，eod/fred 本就是收盘口径，sina/eastmoney 是连续市场
    现价口径（日期=抓取日，自洽）。
    """
    if source != "nasdaq":
        return True
    try:
        day = date.fromisoformat(row_day)
    except ValueError:
        return False
    today = now_et.date()
    if day < today:
        return True
    if day == today:
        return now_et.time() >= _US_REG_CLOSE_ET
    return False


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


def append_series_from_snapshot(snapshot: dict[str, Any], data_root: Path,
                                now_et: datetime | None = None) -> int:
    """watchlist 全部票快照级 upsert（幂等可重入）；返回写入行数。

    now_et 可注入（测试用）；nasdaq 源行过「session 已收盘」闸门（_us_session_closed），
    盘前/盘中报价只进快照不进 series。
    """
    clock = now_et or datetime.now(_ET)
    total = 0
    for quote in snapshot.get("quotes") or []:
        ticker = quote.get("ticker")
        row = quote_to_series_row(quote)
        if not ticker or row is None:
            if ticker:
                log(f"Warning: {ticker} tradeDate 不可解析，只进快照不进 series: {quote.get('tradeDate')!r}")
            continue
        if not _us_session_closed(row["date"], quote.get("source"), clock):
            log(f"Warning: {ticker} nasdaq 盘前/盘中报价（asOf {quote.get('tradeDate')!r}），"
                "只进快照不进 series——ET 16:00 收盘后的抓取才可信为当日收盘")
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
