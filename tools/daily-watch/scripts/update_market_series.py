"""盘后批量：全市场个股 + 板块指数 + 交易所核心指数时序（spec §5.2）。

交易日闸门 → canary 一次调用拿服务器最新交易日，≤ data/.state/ 该 scope 完成标记
即整轮短路（非交易日「成本近零」靠这个成立）。批量=权威写者（三档合并的 batch 档）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from market_data_io import (
    atomic_write_text,
    index_series_file,
    is_cn_series_symbol,
    normalize_cn_symbol,
    read_series_rows,
    sector_series_file,
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
    尾部：not tickers and fail == 0 and latest is not None 且本轮无锁冲突——锁冲突轮
    有票确实没写，写标记会让闸门把它掩盖成「当日已完成」）。
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
            if val is None:
                return None
            val = float(val)
            return val if math.isfinite(val) else None  # NaN/inf → null：json.dumps 默认放行 NaN 字面量（非标 JSON）

        row = {"date": pd.Timestamp(ts).date().isoformat(), "open": num("open"), "high": num("high"),
               "low": num("low"), "close": num("close"), "volume": num("volume"),
               "amount": num("amount"), "source": source}
        if "up_count" in rec:  # index_bars 行：板块与交易所指数都返回涨跌家数（spec §4.2）
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
                 index: bool = False) -> str:
    """结果语义（I2）：'written'=真写；'empty'=服务器空返回；'locked'=锁被其它进程持有。

    调用方据此区分 ok/skip 与是否写完成标记——空/锁都不是 ok，静默 return 会让
    ok 虚高、锁冲突票当日被完成标记掩盖。
    """
    method = "index_bars" if index else "bars"
    df = _mootdx_call(method, symbol=code, frequency=9, offset=backfill)
    if df is None or df.empty:
        return "empty"
    with series_lock(data_root, path.name) as acquired:
        if not acquired:
            return "locked"
        upsert_series_rows(path, bars_to_rows(df, source=source), writer="batch")
    return "written"


def run_stocks_update(data_root: Path, *, backfill: int = 30,
                      tickers: list[str] | None = None, latest: str | None = None,
                      force: bool = False) -> dict:
    stats = {"ok": 0, "skip": 0, "fail": 0}
    latest = latest or fetch_server_latest_trade_date()
    last_round = last_round_date(data_root, "stocks")
    if latest and last_round and latest <= last_round and not tickers and not force:
        log(f"交易日闸门：服务器最新 {latest} ≤ 上轮批量 {last_round}，整轮跳过")
        return stats
    if tickers:
        targets = [(t.rsplit(".", 1)[0], 1 if t.upper().endswith(".SH") else 0) for t in tickers]
    else:
        targets = list_cn_symbols()
    lock_conflict = False
    for code, market in targets:
        path = series_file(data_root, normalize_cn_symbol(code, market))
        try:
            rows = read_series_rows(path)
            # amount 非空=批量已写（写者指纹，钩子行恒 amount=None）；同日钩子先写的票
            # 必须重拉让 batch 档权威覆盖（spec §9 当日可达，而非 T+1 自愈）
            # force=True（--force）跳过本判定：历史补全/修复用——尾行已最新的票
            # 按 skip 语义本来就该跳，但那样 backfill>增量 的重拉永远无法下发
            if (rows and latest and rows[-1]["date"] >= latest
                    and rows[-1].get("amount") is not None and not force):
                stats["skip"] += 1
                continue
            outcome = _upsert_bars(path, data_root, code, backfill, source="mootdx")
            if outcome == "written":
                stats["ok"] += 1
            else:
                stats["skip"] += 1
                if outcome == "locked":
                    lock_conflict = True
                    log(f"Warning: {code} 锁被其它进程持有，本次未更新——完成标记不写")
        except Exception as exc:  # noqa: BLE001 — 单票失败不中断
            stats["fail"] += 1
            log(f"Warning: {code} 更新失败: {exc}")
    log(f"stocks 汇总: {stats}")
    # empty（长期停牌/无数据票，e2e 实测 ~45 只）不阻止标记——这些票每天都会空返回，
    # 若按失败处理闸门永远不生效、非交易日零成本失效；锁冲突才阻止：那批票当日确实没写，
    # 写了标记会被闸门整轮短路掩盖掉（I2）
    if not tickers and latest is not None and stats["fail"] == 0 and not lock_conflict:
        write_round_marker(data_root, "stocks", latest)  # 干净全量轮才记完成（N1 补充点①）
    return stats


def build_sector_list(stocks_df: pd.DataFrame) -> list[dict[str, str]]:
    """SH 枚举 → 880300-881999 白名单 + 显式 sort（服务器返回未排序，spec §12）。"""
    out = []
    for code, name in zip(stocks_df["code"].astype(str), stocks_df["name"].astype(str)):
        if code.startswith("88") and 880300 <= int(code) <= 881999:
            out.append({"code": code, "name": name,
                        "category": "二级行业" if code.startswith("881") else "行业/概念"})
    return sorted(out, key=lambda x: x["code"])


def load_or_merge_sector_list(data_root: Path, stocks_df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """清单缺失→生成；已存在→合并（新增补录、消失保留=文件冻结，spec §5.2）。"""
    fresh = build_sector_list(stocks_df)
    list_path = data_root / "sector" / "sector-list.json"
    if not list_path.exists():
        atomic_write_text(list_path, json.dumps(fresh, ensure_ascii=False, indent=1))  # 首跑必须落盘
        return fresh, list(fresh)
    existing = json.loads(list_path.read_text(encoding="utf-8"))
    known = {x["code"] for x in existing}
    added = [x for x in fresh if x["code"] not in known]
    gone = known - {x["code"] for x in fresh}
    if gone:
        log(f"板块清单消失 {len(gone)} 项（文件冻结不删）: {sorted(gone)[:5]}...")
    merged = existing + added  # 已登记项保留原 name/category，不覆盖
    atomic_write_text(list_path, json.dumps(merged, ensure_ascii=False, indent=1))
    return merged, added


_CORE_INDICES = [  # 交易所核心指数（2026-11-03 用户拍板加入，spec §4.2/§5.2）
    # mootdx index_bars 路由：00/88/99 前缀→SH，其余→SZ——上证段 000xxx→SH、
    # 深指段 399xxx→SZ 恰好都对；北证50 899050（89 前缀）会路由 SZ，而 BSE 是
    # market=2 同样到不了——维持 spec 排除 BSE 口径不收
    {"code": "000001", "name": "上证指数"},
    {"code": "000016", "name": "上证50"},
    {"code": "000300", "name": "沪深300"},
    {"code": "000905", "name": "中证500"},
    {"code": "000852", "name": "中证1000"},
    {"code": "000688", "name": "科创50"},
    {"code": "399001", "name": "深证成指"},
    {"code": "399006", "name": "创业板指"},
]


def run_indices_update(data_root: Path, *, backfill: int = 30, latest: str | None = None,
                       force: bool = False) -> dict:
    """交易所核心指数批量（scope=indices，并入 all）：固定清单 + index_bars。

    与 sectors 同款：index 目录只有批量这一个写者（钩子不碰），skip 判定只需日期
    不需要 amount 指纹；per-scope 完成标记 last_indices_round（N1 同款隔离）。
    force 同 stocks：绕过闸门与逐票 skip（--force 全 scope 语义一致）。
    """
    stats = {"ok": 0, "skip": 0, "fail": 0}
    latest = latest or fetch_server_latest_trade_date()
    last_round = last_round_date(data_root, "indices")
    if latest and last_round and latest <= last_round and not force:
        log(f"交易日闸门（indices）：服务器最新 {latest} ≤ 上轮批量 {last_round}，整轮跳过")
        return stats
    lock_conflict = False
    for item in _CORE_INDICES:
        code = item["code"]
        path = index_series_file(data_root, code)
        try:
            rows = read_series_rows(path)
            if rows and latest and rows[-1]["date"] >= latest and not force:
                stats["skip"] += 1
                continue
            outcome = _upsert_bars(path, data_root, code, backfill, source="mootdx-index", index=True)
            if outcome == "written":
                stats["ok"] += 1
            else:
                stats["skip"] += 1
                if outcome == "locked":
                    lock_conflict = True
                    log(f"Warning: 指数 {code} 锁被其它进程持有，本次未更新——完成标记不写")
        except Exception as exc:  # noqa: BLE001
            stats["fail"] += 1
            log(f"Warning: 指数 {code} 更新失败: {exc}")
    log(f"indices 汇总: {stats}")
    if latest is not None and stats["fail"] == 0 and not lock_conflict:
        write_round_marker(data_root, "indices", latest)
    return stats


def run_sectors_update(data_root: Path, *, backfill: int = 30, latest: str | None = None,
                       force: bool = False) -> dict:
    stats = {"ok": 0, "skip": 0, "fail": 0}
    latest = latest or fetch_server_latest_trade_date()
    last_round = last_round_date(data_root, "sectors")  # per-scope 标记：stocks 完成与否不影响本闸门（N1）
    if latest and last_round and latest <= last_round and not force:
        log(f"交易日闸门（sectors）：服务器最新 {latest} ≤ 上轮批量 {last_round}，整轮跳过")
        return stats  # 非交易日零服务器调用（spec §9 补注）
    stocks_df = _mootdx_call("stocks", market=1)
    merged, _added = load_or_merge_sector_list(data_root, stocks_df)
    lock_conflict = False
    for item in merged:
        code = item["code"]
        path = sector_series_file(data_root, code)
        try:
            rows = read_series_rows(path)
            if rows and latest and rows[-1]["date"] >= latest and not force:
                stats["skip"] += 1
                continue
            outcome = _upsert_bars(path, data_root, code, backfill, source="mootdx-index", index=True)
            if outcome == "written":
                stats["ok"] += 1
            else:
                stats["skip"] += 1
                if outcome == "locked":
                    lock_conflict = True
                    log(f"Warning: 板块 {code} 锁被其它进程持有，本次未更新——完成标记不写")
        except Exception as exc:  # noqa: BLE001
            stats["fail"] += 1
            log(f"Warning: 板块 {code} 更新失败: {exc}")
    log(f"sectors 汇总: {stats}")
    # 与 stocks 同款（I2）：empty 不阻止标记（板块空返回=无该段数据，天天有），锁冲突阻止
    if latest is not None and stats["fail"] == 0 and not lock_conflict:
        write_round_marker(data_root, "sectors", latest)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="盘后批量更新全市场/板块/核心指数时序（spec §5.2）")
    parser.add_argument("--scope", choices=["stocks", "sectors", "indices", "all"], default="all")
    parser.add_argument("--backfill", type=int, default=30,
                        help="增量 bars 数；800=回补约 3.3 年（服务器单次上限）")
    parser.add_argument("--tickers", help="逗号分隔子集，调试用（如 600276.SH,300476.SZ）")
    parser.add_argument("--force", action="store_true",
                        help="绕过闸门与逐票 skip 强制重拉（历史回补/盘中数据修正用；tickers 路径不写完成标记）。"
                             "警告：15:00 收盘前执行会把动态 bar 当收盘写进 series 并推进完成标记，"
                             "收盘后须再跑一次同命令 --force 修正")
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
    if tickers and args.scope in ("sectors", "indices"):
        parser.error(f"--tickers 只对 --scope stocks/all 有效（{args.scope} 是清单制路径，无子集，静默丢弃比报错更糟）")
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    stats = {"ok": 0, "skip": 0, "fail": 0}
    if args.scope in ("stocks", "all"):
        stats = run_stocks_update(data_root, backfill=args.backfill, tickers=tickers,
                                  force=args.force)
    if args.scope in ("sectors", "all"):
        sec = run_sectors_update(data_root, backfill=args.backfill, force=args.force)
        for key in stats:
            stats[key] += sec[key]
    if args.scope in ("indices", "all"):
        idx = run_indices_update(data_root, backfill=args.backfill, force=args.force)
        for key in stats:
            stats[key] += idx[key]
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
