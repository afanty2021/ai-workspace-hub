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
4. **票级历史主源**：^SOX 东财 251.SOX K 线深度受限（2026-11-09 实测仅
   2026-07-06 起 89 行），历史主源改走 Nasdaq 官方 historical API
   （NASDAQ_HISTORY_SYMBOLS，exchange 官方数据 548 行覆盖全窗，双锚点
   11-05 9011.14 / 11-06 9390.25 与档案逐位一致；失败降级东财——浅历史强于无）。
   XAUUSD=X（伦敦金）无东财 secid（119.XAU 探测无数据），历史主源走新浪全球
   期货日线（SINA_HISTORY_SYMBOLS，与其 hf_XAU 实时快照同源族同日切口径：
   2026-11-09 探测 11-06 行全 OHLC 与快照行逐位一致；2006 年起全史返回，
   本地按回补窗过滤；无东财降级，主源失败按 fail 计）。
   其余 8 票东财 klines 仍为主源（实测 548-571 行全窗；^GSPC/^DJI 2026-11-11
   接线，100 段=东财美股指数，11-10 收盘对拍 AP/CNBC 逐位一致）。腾讯 ifzq 对
   usSOX 只有实时 qt 档、日线 K 线为空数组，不接入。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
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
    # ^GSPC/^DJI（2026-11-11 接线）：100 段=东财美股指数。实时/回补同 secid；
    # 11-10 收盘 SPX 7520.93/-0.38%、DJI 52231.89/-0.30% 对拍 AP/CNBC 逐位一致，
    # 昨收 7549.94/52389.75 与 push2his 11-09 行逐位一致。100.DJI/100.SP500 无效。
    "^GSPC": "100.SPX",
    "^DJI": "100.DJIA",
    "^SOX": "251.SOX",
    "^TNX": "171.US10Y",
    "NQ00Y": "103.NQ00Y",
    "DX-Y.NYB": "100.UDI",
    "HG=F": "109.LCPT",
    "HG00Y": "101.HG00Y",
    "HSTECH": "124.HSTECH",
}

# 票级历史主源覆盖（东财深度受限的票）： Nasdaq 官方 historical API 主源、
# 东财降级。secid 表保留 ^SOX 条目作降级路径与 --tickers 校验白名单。
NASDAQ_HISTORY_SYMBOLS: dict[str, str] = {"^SOX": "SOX"}

NASDAQ_HISTORICAL_URL = "https://api.nasdaq.com/api/quote/{symbol}/historical"
NASDAQ_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# 新浪全球期货日线（伦敦金现货同源族）：实时快照走 hf_XAU（hq.sinajs），历史走
# GlobalFuturesService（stock2.finance.sina.cn），日期切口径实测一致。
SINA_HISTORY_SYMBOLS: dict[str, str] = {"XAUUSD=X": "XAU"}

SINA_GLOBAL_HISTORY_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php"
                           "/var%20t=/GlobalFuturesService.getGlobalFuturesDailyKLine")
SINA_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Referer": "https://finance.sina.com.cn",
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


def parse_nasdaq_history(table_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nasdaq historical tradesTable.rows → series 行（升序输出）。

    口径：日期 MM/DD/YYYY→ISO；数字自带千分位逗号；指数无成交量（"--"→None）、
    无官方成交额（amount=None）；source="nasdaq-historical"（写者指纹，区别于
    eastmoney-kline 的 amount 恒非 None）。坏行跳过（同 parse_klines 语义）。"""
    rows: list[dict[str, Any]] = []
    for item in table_rows:
        try:
            day = datetime.strptime(str(item["date"]).strip(), "%m/%d/%Y").date().isoformat()
            volume_raw = str(item.get("volume", "--")).replace(",", "").strip()
            rows.append({
                "date": day,
                "open": float(str(item["open"]).replace(",", "")),
                "close": float(str(item["close"]).replace(",", "")),
                "high": float(str(item["high"]).replace(",", "")),
                "low": float(str(item["low"]).replace(",", "")),
                "volume": float(volume_raw) if volume_raw not in ("--", "", "None", "N/A", "n/a") else None,
                "amount": None,
                "source": "nasdaq-historical",
            })
        except (KeyError, ValueError, TypeError):
            continue  # 坏行跳过（与 parse_klines 同语义）
    rows.sort(key=lambda r: r["date"])
    return rows


def fetch_nasdaq_history_rows(symbol: str, from_iso: str, to_iso: str) -> list[dict[str, Any]]:
    """Nasdaq 官方指数历史（assetclass=index）。1 次重试（同 fetch_kline_rows）。"""
    params = {"assetclass": "index", "fromdate": from_iso, "todate": to_iso, "limit": "9999"}
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            resp = requests.get(NASDAQ_HISTORICAL_URL.format(symbol=symbol),
                                params=params, headers=NASDAQ_HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            table = data.get("tradesTable") or {}
            return parse_nasdaq_history(table.get("rows") or [])
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            time.sleep(5.0)
    raise RuntimeError(f"nasdaq historical 请求失败（含 1 次重试）: {last_exc}")


def parse_sina_global_history(payload: str) -> list[dict[str, Any]]:
    """新浪全球期货日线 JSONP（`/*<script>*/\\nvar t=([{...},...]);`）→ series 行（升序）。

    口径：日期 "YYYY-MM-DD" 直用；数值自带引号字符串；现货无量（API 的
    volume/position 恒 "0" → 不入库，与 hf_XAU 快照行 volume null 一致）、
    无官方成交额（amount=None）；source="sina-global"（写者指纹）。坏行跳过
    （同 parse_klines 语义）；JSONP 外壳缺失/数组解析失败返回 []。"""
    start, end = payload.find("["), payload.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        items = json.loads(payload[start:end + 1])
    except ValueError:
        return []
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            rows.append({
                "date": str(item["date"]),
                "open": float(item["open"]),
                "close": float(item["close"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "volume": None,
                "amount": None,
                "source": "sina-global",
            })
        except (KeyError, ValueError, TypeError):
            continue
    rows.sort(key=lambda r: r["date"])
    return rows


def fetch_sina_global_history_rows(symbol: str, from_iso: str, to_iso: str) -> list[dict[str, Any]]:
    """新浪全球期货日线（API 全量返回，本地按回补窗过滤）。1 次重试（同族惯例）。"""
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            resp = requests.get(SINA_GLOBAL_HISTORY_URL, params={"symbol": symbol},
                                headers=SINA_HEADERS, timeout=30)
            resp.raise_for_status()
            rows = parse_sina_global_history(resp.text)
            return [r for r in rows if from_iso <= r["date"] <= to_iso]
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            time.sleep(5.0)
    raise RuntimeError(f"sina global history 请求失败（含 1 次重试）: {last_exc}")


def update_ticker(data_root: Path, ticker: str, secid: str, *,
                  backfill_days: int = 800, force: bool = False,
                  history_source: str = "eastmoney",
                  sink: list[tuple[Path, str]] | None = None,
                 sources_used: set[str] | None = None) -> str:
    """三态 'written' / 'empty' / 'fail'（无锁分支：钩子 16:30 前不与批量同跑，
    锁冲突按 fail 语义计，次日自愈）。sink 非空时收集 (series 路径, upsert 后
    尾行日期)——运行账本 data-close 的行锚定三元组（batch_ledger 接线）。
    sources_used 非空时同步收集写入行内 source 指纹（nasdaq 主源降级东财时
    记的是实际写入的源，而非分发意图，max 评审 M-3）。"""
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
    fetched: list[dict[str, Any]] = []
    if history_source == "nasdaq" and ticker in NASDAQ_HISTORY_SYMBOLS:
        try:
            fetched = fetch_nasdaq_history_rows(
                NASDAQ_HISTORY_SYMBOLS[ticker],
                f"{beg[:4]}-{beg[4:6]}-{beg[6:]}",  # YYYYMMDD → ISO
                date.today().isoformat(),
            )
            if not fetched:
                # 200 + data:null（典型反爬形态）不算异常但等于主源失效——
                # 留痕再降级，否则 ^SOX 会悄悄退化回东财 89 行浅历史而无人察觉
                log(f"Warning: {ticker} Nasdaq 历史返回空（疑似反爬 data:null），降级东财 klines")
        except RuntimeError as exc:
            log(f"Warning: {ticker} Nasdaq 历史失败，降级东财 klines: {exc}")
            fetched = []
    elif history_source == "sina" and ticker in SINA_HISTORY_SYMBOLS:
        try:
            fetched = fetch_sina_global_history_rows(
                SINA_HISTORY_SYMBOLS[ticker],
                f"{beg[:4]}-{beg[4:6]}-{beg[6:]}",  # YYYYMMDD → ISO
                date.today().isoformat(),
            )
        except RuntimeError as exc:
            log(f"Warning: {ticker} 新浪历史失败: {exc}")
            fetched = []
    if not fetched:
        if not secid:  # 新浪族票无东财降级（XAUUSD=X 无 secid）——失败如实计 fail
            log(f"Warning: {ticker} 主源失败且无东财降级 secid，本次未回补")
            return "fail"
        fetched = fetch_kline_rows(secid, beg)
    if not fetched:
        return "empty"
    with series_lock(data_root, path.name) as acquired:
        if not acquired:
            log(f"Warning: {ticker} 锁被其它进程持有，本次未更新")
            return "fail"
        changed = upsert_series_rows(path, fetched, writer="batch")
        if sink is not None:
            rows_now = read_series_rows(path)
            if rows_now:
                sink.append((path, rows_now[-1]["date"]))
                if sources_used is not None and rows_now[-1].get("source"):
                    sources_used.add(rows_now[-1]["source"])
    log(f"{ticker}: 拉取 {len(fetched)} 行（beg={beg}，source={history_source}），合并变更 {changed} 行")
    return "written"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跨资产票历史日线回补（东财 push2his 主源 + Nasdaq/新浪票级覆盖，Q-20261109-04）")
    parser.add_argument("--backfill", type=int, default=800,
                        help="回补窗口天数（默认 800≈3.3 年；首次全量与 --force 都按此窗口）")
    parser.add_argument("--tickers", help=f"逗号分隔子集，只接受 "
                        f"{sorted({**CROSS_ASSET_HISTORY_SECIDS, **SINA_HISTORY_SYMBOLS})}")
    parser.add_argument("--force", action="store_true",
                        help="忽略 series 尾行、重拉整个回补窗口（快照脏数据修复用）")
    parser.add_argument("--throttle", type=float, default=3.0,
                        help="票间间隔秒数（push2his IP 级限流防御，默认 3.0）")
    args = parser.parse_args(argv)
    allowed = {**CROSS_ASSET_HISTORY_SECIDS, **SINA_HISTORY_SYMBOLS}
    if args.tickers:
        tickers = []
        for raw in args.tickers.split(","):
            ticker = raw.strip().upper()
            if ticker not in allowed:
                parser.error(f"--tickers 只接受 {sorted(allowed)}（得到 {raw!r}）")
            tickers.append(ticker)
    else:
        tickers = list(CROSS_ASSET_HISTORY_SECIDS) + list(SINA_HISTORY_SYMBOLS)
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    from batch_ledger import close_batch, open_batch

    run_id = open_batch("batch-crossasset", data_root)
    written: list[tuple[Path, str]] = []
    used: set[str] = set()  # 实际写入行内 source 指纹（含降级路径的真实源，max 评审 M-3）
    failed_tickers: list[str] = []
    stats = {"ok": 0, "skip": 0, "fail": 0}
    for idx, ticker in enumerate(tickers):
        secid = CROSS_ASSET_HISTORY_SECIDS.get(ticker, "")
        if ticker in NASDAQ_HISTORY_SYMBOLS:
            source = "nasdaq"
        elif ticker in SINA_HISTORY_SYMBOLS:
            source = "sina"
        else:
            source = "eastmoney"
        try:
            outcome = update_ticker(data_root, ticker, secid,
                                    backfill_days=args.backfill, force=args.force,
                                    history_source=source, sink=written,
                                    sources_used=used)
        except Exception as exc:  # noqa: BLE001 — 单票失败不中断
            outcome = "fail"
            log(f"Warning: {ticker} 回补失败: {exc}")
        if outcome == "written":
            stats["ok"] += 1
        elif outcome == "fail":
            stats["fail"] += 1
            failed_tickers.append(ticker)
        else:
            stats["skip"] += 1
        if idx < len(tickers) - 1 and args.throttle > 0:
            time.sleep(args.throttle)
    log(f"cross-asset-history 汇总: {stats}")
    close_batch(run_id, written, data_root, sources=sorted(used),
                missing=[{"item": t, "reason": "cross-asset batch update fail"}
                         for t in failed_tickers])
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
