"""日报持久化钩子（spec §5.1）：快照原样落盘 + watchlist series 快照级追加。

钩子=快照级写者：同日只补 null、绝不覆盖非空（spec §5.2 写者身份表）。
实时报价源（nasdaq/fmp/finnhub/yfinance）行须过「美股 session 已收盘」闸门
（_us_session_closed）：盘前/盘中报价只进快照不进 series（friction 2026-11-03
第 2 次修根；第五轮评审 I-1 把 fmp/finnhub/yfinance 并入受闸集合）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
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
# 盘前可产出「当日戳+实时价」的源（第五轮评审 I-1）。nasdaq 是浏览器头抓取型端点、
# 失败即降级，下一环（fmp/quote 配 key 即成美股主源、finnhub /quote、yfinance 最新
# bar）顶上即事故复发。eod/fred 收盘口径、sina/eastmoney 现价口径（日期=抓取日，
# 自洽）、CN 侧批量权威覆盖——均不过闸。非美股票经四源抓取最坏延一天，永不丢行。
_US_REALTIME_SOURCES = frozenset({"nasdaq", "fmp", "finnhub", "yfinance"})


def _us_session_closed(row_day: str, source: str | None, now_et: datetime) -> bool:
    """实时报价源的 series 行闸门：asOf 日的美股 session 已收盘才可信为该日收盘价。

    两个已发生的错写形态（2026-11-03 坐实）：①盘前抓取——价格=上一收盘、
    asOf=当日 → 周五价被写成 11-02 行（^SOX 10,687.62 vs 真实周一收盘
    10,328.33，险些漏判 H1 破线）；②个股盘前指示价（NVDA 有盘前交易）被写成
    当日收盘行。规则：asOf < 今天(ET) → 写（昨收及更早——指数 asOf 天然是最后
    交易日，隔天抓取恰好正确落行）；asOf == 今天且 ET ≥ 16:00 → 写（刚收盘）；
    asOf == 今天且未收盘、asOf > 今天（时钟错乱）→ 不写。豁免源不过此门：CN 侧
    由批量权威写者覆盖，eod/fred 本就是收盘口径，sina/eastmoney 是连续市场
    现价口径（日期=抓取日，自洽）。
    """
    if source not in _US_REALTIME_SOURCES:
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
                                now_et: datetime | None = None,
                                written: list[tuple[Path, str, str]] | None = None) -> int:
    """watchlist 全部票快照级 upsert（幂等可重入）；返回写入行数。

    now_et 可注入（测试用）；实时报价源行过「session 已收盘」闸门（_us_session_closed），
    盘前/盘中报价只进快照不进 series。written 传入时收集本轮实际写入的
    (series 路径, 行日期, source) 三元组（运行账本 data-close 用）。
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
            log(f"Warning: {ticker} {quote.get('source')} 盘前/盘中报价（asOf {quote.get('tradeDate')!r}），"
                "只进快照不进 series——ET 16:00 收盘后的抓取才可信为当日收盘")
            continue
        path = series_file(data_root, ticker)
        with series_lock(data_root, path.name) as acquired:
            if not acquired:
                continue
            total += upsert_series_rows(path, [row], writer="snapshot")
            if written is not None:
                written.append((path, row["date"], row["source"] or "snapshot"))
    return total


# ---------------------------------------------------------------------------
# 运行账本接线（spec §3.3 拍板 #3：persist 挂钩导入式自动记账）
# ---------------------------------------------------------------------------

def _load_run_archive():
    """跨目录导入 system/scripts/run_archive.py（sys.path 注入与 tests/_test_paths 同法）。"""
    repo_root = Path(__file__).resolve().parents[3]
    script_dir = str(repo_root / "system" / "scripts")
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import run_archive  # noqa: PLC0415 — 延迟导入：账本模块缺失不应影响持久化本身
    return run_archive


def _ledger_failed(data_root: Path, step: str, exc: Exception) -> None:
    """账本子步骤失败：stderr + sentinel（时间+异常），不抛（spec §3.2「账本写不吞」的可感知降级）。"""
    log(f"Warning: 运行账本 {step} 失败（写 sentinel，日报继续）: {exc}")
    try:
        sentinel = sentinel_of(data_root)
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        with sentinel.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {step} "
                     f"{type(exc).__name__}: {exc}\n")
    except Exception as nested:  # noqa: BLE001 — sentinel 本身也写不进时只剩 stderr
        log(f"Warning: run-log.error sentinel 写入失败: {nested}")


def sentinel_of(data_root: Path) -> Path:
    """sentinel 路径：优先复用 run_archive.sentinel_path（单一事实源），导入失败回退本地实现。"""
    try:
        return Path(_load_run_archive().sentinel_path(data_root))
    except Exception:  # noqa: BLE001 — best-effort 复用，账本模块不可用时不能连 sentinel 都写不了
        return Path(data_root) / ".state" / "run-log.error"


def _degradations_from_meta(market_data: dict[str, Any]) -> list[Any]:
    """meta.quotes.degradations 透传（spec §3.3 拍板 #2 ③）：形状不做假设，非法类型丢弃。"""
    meta = market_data.get("meta") or {}
    items = ((meta.get("quotes") or {}).get("degradations")) or []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _macro_missing(macro_meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """宏观 meta 的 missing_symbols → data-close missing 条目（4c 宏观前移后可进 hook）。"""
    if not macro_meta:
        return []
    symbols = macro_meta.get("missing_symbols")
    if not isinstance(symbols, list):
        return []
    reason = macro_meta.get("reason") or "macro symbol missing"
    return [{"item": str(sym), "reason": str(reason)} for sym in symbols]


def _run_log_enabled(run_log: bool) -> bool:
    """逃生门双通道：函数参数 run_log=False 或 env RUN_LOG_DISABLE=1（spec §3.3）。"""
    if not run_log:
        return False
    return os.environ.get("RUN_LOG_DISABLE", "").strip() != "1"


def _ledger_target_spec(data_root: Path, path: Path, anchor_date: str) -> str:
    """series 目标 → 账本 `path#date` 串；路径取 data_root 父目录（仓库根）相对，出界用绝对路径。"""
    return f"{_ledger_repo_rel(data_root, path)}#{anchor_date}"


def _ledger_repo_rel(data_root: Path, path: Path) -> str:
    """账本路径归一：data_root 父目录（仓库根）相对；出界（tmp 冒烟等）用绝对路径。"""
    try:
        rel = path.resolve().relative_to(Path(data_root).resolve().parent)
        return str(Path(*rel.parts))
    except ValueError:
        return str(path.resolve())


def run_persist_hook(market_data: dict[str, Any], data_root: Path | None = None,
                     run_log: bool = True,
                     macro_meta: dict[str, Any] | None = None) -> None:
    """generate_daily_report 调用入口；持久化失败永不阻塞日报（spec §3）。

    run_log=True 时写运行账本：进入即 open（kind=watch，started_at=persist 被调时刻），
    snapshot+series 落盘成功后 data-close（series 行锚定三元组 / sources 从行内 source
    汇总 / missing 从 meta 降级清单+宏观 missing_symbols 透传）。账本子步骤单独捕获，
    失败只写 sentinel 不抛；macro_meta 为 4c 宏观前移后传入的 fetch_macro_data meta。
    """
    try:
        root = data_root or resolve_data_root()
    except Exception as exc:  # noqa: BLE001 — 设计要求吞掉一切
        log(f"Warning: 持久化钩子失败（不阻塞日报）: {exc}")
        return

    run_id: str | None = None
    if _run_log_enabled(run_log):
        try:
            archive = _load_run_archive()
            trade_date = _fetched_day(market_data) or datetime.now().strftime("%Y-%m-%d")
            run_id = archive.append_open(root, kind="watch", trade_date=trade_date)
        except Exception as exc:  # noqa: BLE001 — 账本失败不吞：stderr+sentinel
            _ledger_failed(root, "open", exc)

    written: list[tuple[Path, str, str]] = []
    snapshot_files: list[Path] = []
    try:
        snapshot_files.append(save_daily_snapshot(market_data, root))
        append_series_from_snapshot(market_data, root, written=written)
    except Exception as exc:  # noqa: BLE001 — 设计要求吞掉一切
        log(f"Warning: 持久化钩子失败（不阻塞日报）: {exc}")
        return  # 落盘失败不写 data-close：open 留给 verify 的孤儿判定（spec §3.2 I3）

    if run_id:
        try:
            archive = _load_run_archive()
            targets: dict[Path, str] = {}
            for path, row_date, _source in written:
                targets[path] = max(targets.get(path, row_date), row_date)
            # 快照 .json（market/daily/<day>.json）随 data-close 记整文件 sha256
            # （非 .jsonl 不带锚）：同日重跑会先重写快照再记账，后写哈希天然覆盖。
            specs: list = [{"path": _ledger_repo_rel(root, path)} for path in snapshot_files]
            specs += [_ledger_target_spec(root, path, anchor) for path, anchor in targets.items()]
            archive.append_data_close(
                root, run_id,
                specs,
                sorted({source for _p, _d, source in written}),
                _degradations_from_meta(market_data) + _macro_missing(macro_meta),
            )
        except Exception as exc:  # noqa: BLE001 — 账本失败不吞：stderr+sentinel
            _ledger_failed(root, "data-close", exc)


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
