"""mootdx (通达信 TCP 7709) A 股行情源 — daily-watch 的 A 股主源。

无 Key、协议级直连，覆盖沪深股票和 ETF（tushare `daily` 不含基金，东财/腾讯/新浪
是 HTTP 爬虫端点且东财在本机有反爬断连史）。客户端管理移植自
TradingAgents-astock `tradingagents/dataflows/a_stock.py`（本机已长期验证），
差异点：

1. **线程安全**：fetch_market_data.py 用 ThreadPoolExecutor 并发跑降级链，而
   pytdx 单 socket 非线程安全（并发请求会串包）——单例初始化与全部取数都持
   全局锁串行执行。单次 TDX 调用 ~20ms，全池 21 只票 <1s，可接受。
2. **精选服务器表用 2026-11-02 实测存活名单**：TradingAgents 2026-06 验证的
   华为云表中 3/10 已半死（TCP 握手通但协议取不到数）。就算这份表再次过时，
   候选表仍会合并 mootdx 自带 HQ_HOSTS 并逐台做真实取数验证，选服逻辑不依赖
   任何一台具体服务器活着。

字段口径（2026-11-02 实测）：
- `quotes()`：price / last_close / open / high / low / vol / amount；
  `vol` 单位是手（604325手×100股×48.8元 与 amount 29.49亿精确吻合），
  与 tushare `vol`、腾讯源字段 6 同口径；`servertime` 只有时刻没有日期。
- `bars(frequency=9)`：日线，`datetime` 索引同时重复出现为列，另附
  year/month/day/hour/minute 冗余列；盘中时最新一根就是当日实时快照。
- 昨收用 `last_close`（交易所官方昨收，除权日口径正确），不用前一根日线收盘。
"""

from __future__ import annotations

import contextlib
import re
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# Windows 控制台可能默认 cp1252/GBK，统一 UTF-8 输出避免中文触发 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 实测可用的通达信服务器（按延迟排序，2026-11-02 验证，均来自 mootdx 自带
# HQ_HOSTS）。只作优先顺序，正确性由下面的逐台真实取数验证保证——服务器随时
# 可能半死，候选表会再合并 HQ_HOSTS 全表兜底。
_TDX_SERVERS = [
    ("109.244.35.28", 7709), ("120.79.210.76", 7709), ("109.244.73.13", 7709),
    ("162.14.135.116", 7709), ("101.133.129.19", 7709), ("109.244.73.23", 7709),
    ("101.133.231.193", 7709), ("120.24.231.30", 7709),
]

# 探测用的探针股票：主板老票，任何通达信服务器都应能返回它的日线。
_TDX_CANARY_SYMBOL = "600519"

# 全部服务器都验不过之后，隔多久才允许再探一轮（秒）。没有这个负缓存，
# 每一次取数都会把整张服务器表重探一遍，把"取不到数"放大成"每个请求卡几十秒"。
_MOOTDX_RETRY_AFTER_S = 300.0

# TCP 预筛的单台超时（秒）。
_TDX_PROBE_TIMEOUT_S = 2.0

# ⚠️ 无点后缀：rpartition(".") 切出的 suffix 不带点（对齐 fetch_market_data 的
# _cn_quote_symbol 口径）；fetch_market_data 里 endswith 用的 CN_SUFFIXES 才带点。
CN_QUOTE_SUFFIXES = ("SH", "SZ")
# 600276.SH -> 600276；非 6 位数字一律不认（ETF 51/52/56/58、15/16/18 也是 6 位数字）。
_CN_CODE_RE = re.compile(r"^\d{6}$")


def is_mootdx_ticker(ticker: str) -> bool:
    """该 ticker 是否属于 mootdx 覆盖范围（沪深 A 股 + ETF，.SH/.SZ 6 位数字）。"""
    base, sep, suffix = ticker.strip().upper().rpartition(".")
    return bool(sep and suffix in CN_QUOTE_SUFFIXES and _CN_CODE_RE.match(base))


# ---------------------------------------------------------------------------
# mootdx 客户端单例（移植自 TradingAgents-astock，含线程安全适配）
# ---------------------------------------------------------------------------

_mootdx_client = None
_mootdx_unavailable_until = 0.0
_mootdx_import_failed = False
# pytdx 单 socket 非线程安全：初始化与每次取数都持这把锁，串行执行。
# 必须是可重入锁：fetch_mootdx_quotes 批量路径持锁后，逐票的 bars 取交易日
# 会再经 _mootdx_call 进来——普通 Lock 在这里自死锁（实测踩过）。
_MOOTDX_LOCK = threading.RLock()


def _candidate_tdx_servers() -> list[tuple[str, int]]:
    """待试的通达信服务器：先用实测精选的 `_TDX_SERVERS`，再补 mootdx 自带完整主机表。

    只试精选表不够——它们要是恰好都不可用，而 mootdx 自带表里还有活着的主机，
    就会被误判成"全网不可达"并记 5 分钟负缓存。合并去重后逐台验证。
    已知取舍：候选无上限（HQ_HOSTS 全表并入），极端网络下首轮逐台验证偏慢——
    用首跑时延换覆盖面，TCP 预筛 + timeout=6 已把单台代价压住，不加总数上限。
    """
    servers = list(_TDX_SERVERS)
    seen = set(servers)
    try:
        from mootdx.consts import HQ_HOSTS
        for entry in HQ_HOSTS:
            # 形如 ("深圳双线主站1", "110.41.147.114", 7709)
            host = (entry[1], entry[2]) if len(entry) >= 3 else None
            if host and host not in seen:
                seen.add(host)
                servers.append(host)
    except Exception as e:  # mootdx 版本变动导致取不到就只用精选表，不影响主流程
        log(f"Warning: 读取 mootdx HQ_HOSTS 失败，仅使用内置精选表: {e}")
    return servers


def _probe_tdx(ip: str, port: int, timeout: float) -> bool:
    """TCP 握手探测通达信服务器端口是否开着。

    ⚠️ 只是廉价预筛，通过不代表能取到数：实测存在大量"TCP 三次握手成功、
    通达信协议握手立刻被 RST"或直接不回数据的服务器。选服务器必须再走
    `_tdx_client_works()` 做一次真实取数验证。
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _reachable_tdx_servers(servers: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """并发做 TCP 预筛，返回可连的那些（保持原顺序）。

    只是把"等超时"这件事并行化，不改变优先级：返回顺序仍是候选表顺序。
    """
    if not servers:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(servers))) as pool:
        flags = list(pool.map(lambda s: _probe_tdx(s[0], s[1], _TDX_PROBE_TIMEOUT_S), servers))
    return [srv for srv, ok in zip(servers, flags) if ok]


def _tdx_client_works(client) -> bool:
    """真实拉一根 K 线来验证这个 client 确实能取数。"""
    try:
        df = client.bars(symbol=_TDX_CANARY_SYMBOL, frequency=9, offset=1)
        return df is not None and not df.empty
    except Exception:
        return False


@contextlib.contextmanager
def _preserve_mootdx_bestip():
    """探测期间保护 mootdx 的 BESTIP 内存状态，退出时按需还原。

    ⚠️ 0.11.7 的 `config.set()` 只改**内存** dict、不落盘（已核对 config.py），
    所以探测不存在跨进程污染——但 `setup()` 会把用户持久化的 config.json 读进
    内存，而 `_get_mootdx_client` 末尾的裸 factory 兜底正是靠 `config.get('BESTIP')`
    读这份内存值。逐台探测会把它覆写成最后一台**失败的**服务器，兜底路径就废了：
    必须先 `setup()` 再快照，探测失败时还原，裸 factory 读到的才是用户原本的配置。

    用法：`with _preserve_mootdx_bestip() as keep:` —— 选出可用服务器时调
    `keep()` 表示"这次的覆写是我们想要的，别还原"；不调就在退出时还原。
    （移植自 TradingAgents-astock #90 修复；威胁模型按 0.11.7 源码更正。）
    """
    saved = None
    try:
        from mootdx import config as _cfg
        _cfg.setup()
        saved = _cfg.get("BESTIP")
        if isinstance(saved, dict):
            saved = dict(saved)
    except Exception as e:  # 版本差异导致取不到就跳过保护，别影响主流程
        log(f"Warning: 读取 mootdx BESTIP 失败，本次探测不做保护: {e}")

    keep = {"flag": False}
    try:
        yield lambda: keep.__setitem__("flag", True)
    finally:
        if saved is not None and not keep["flag"]:
            try:
                from mootdx import config as _cfg2
                _cfg2.set("BESTIP", saved)
            except Exception as e:
                log(f"Warning: 恢复 mootdx BESTIP 失败: {e}")


def _get_mootdx_client():
    """返回健壮版 mootdx Quotes client 单例（调用方必须已持有 `_MOOTDX_LOCK`）。

    选服务器的顺序：精选表 + HQ_HOSTS 合并（TCP 预筛 + 真实取数验证）→
    裸 factory（用户 config 里已有 BESTIP 时直接可用）。每一级都必须真正取到
    数据才会被采用。全部失败时抛 RuntimeError，并在 `_MOOTDX_RETRY_AFTER_S`
    内直接快速失败，不再逐台重探。
    """
    global _mootdx_client, _mootdx_unavailable_until, _mootdx_import_failed
    if _mootdx_client is not None:
        return _mootdx_client

    now = time.time()
    if now < _mootdx_unavailable_until:
        raise RuntimeError(
            "mootdx 通达信服务器暂不可用（%.0f 秒内不再重试），请走降级源"
            % (_mootdx_unavailable_until - now)
        )
    if _mootdx_import_failed:
        raise RuntimeError("mootdx 未安装（已知），请走降级源")

    try:
        from mootdx.quotes import Quotes
    except ImportError as exc:
        _mootdx_import_failed = True
        _mootdx_unavailable_until = time.time() + _MOOTDX_RETRY_AFTER_S
        raise RuntimeError(
            "mootdx is not installed; run "
            "`pip install -r tools/daily-watch/requirements-mootdx.txt`"
            f"（原始错误: {exc}）"
        ) from exc

    # 探测会覆写 BESTIP 的内存值（兜底裸 factory 要读它）——包在这里，只有真选出
    # 可用服务器时才 keep()，其余每条退出路径（含异常）都自动还原。
    with _preserve_mootdx_bestip() as keep_bestip:
        # TCP 预筛并发跑：几十台里多数"连都连不上"，串行每台要等满超时。
        # 预筛纯粹是等 IO，并发不改变选取语义——下面仍按原顺序逐台做真实取数验证。
        reachable = _reachable_tdx_servers(_candidate_tdx_servers())

        for ip, port in reachable:
            # 「TCP 通但通达信协议不通」有两种表现：factory 建连时握手就被拒，
            # 或者建出来了但取不到数。两种都要算，否则快速失败判断失效。
            # timeout=6：实测半死服务器（TCP 通、协议无响应）canary 要 ~4s 才
            # 超时，默认 15s 太宽——几十台候选串行下来会把首次取数拖到分钟级。
            try:
                candidate = Quotes.factory(market="std", server=(ip, port), timeout=6)
            except Exception as exc:
                log(f"Warning: mootdx {ip}:{port} 握手失败（{type(exc).__name__}），换下一台")
                continue
            if _tdx_client_works(candidate):
                log(f"mootdx server selected: {ip}:{port}")
                keep_bestip()  # 这次的覆写正是我们想要的，别还原
                _mootdx_client = candidate
                return _mootdx_client
            log(f"Warning: mootdx {ip}:{port} 建连成功但取不到数，换下一台")

    # 逐台探测都没成——BESTIP 已还原成用户原本的配置，裸 factory 读的正是它。
    try:
        candidate = Quotes.factory(market="std", timeout=6)
    except Exception as exc:
        log(f"Warning: mootdx 裸 factory 失败: {exc}")
    else:
        if _tdx_client_works(candidate):
            log("mootdx client from 裸 factory（用户已有 BESTIP 配置）")
            _mootdx_client = candidate
            return _mootdx_client

    _mootdx_unavailable_until = time.time() + _MOOTDX_RETRY_AFTER_S
    raise RuntimeError(
        "mootdx 通达信服务器不可用（全部候选验证失败）。常见原因：代理/防火墙/"
        "公司网络拦截 TCP 7709。%.0f 秒内将直接快速失败，行情请走降级源。"
        % _MOOTDX_RETRY_AFTER_S
    )


def reset_mootdx_client() -> None:
    """丢弃缓存的 client，让下一次调用重新选服务器（取数失败时调用）。"""
    global _mootdx_client, _mootdx_unavailable_until
    with _MOOTDX_LOCK:
        _mootdx_client = None
        _mootdx_unavailable_until = 0.0


def _mootdx_call(method: str, **kwargs):
    """持锁调用 mootdx 的某个方法，失败就弃用当前服务器并抛出。

    选中的服务器随时可能挂掉；不弃用的话单例会一直指着它，之后每次取数都
    失败且永不重选。取 client 本身失败时不清缓存——那条路径已在
    `_get_mootdx_client` 里做了负缓存，清掉等于取消快速失败。
    """
    with _MOOTDX_LOCK:
        client = _get_mootdx_client()
        try:
            return getattr(client, method)(**kwargs)
        except Exception:
            reset_mootdx_client()
            raise


# ---------------------------------------------------------------------------
# 行情装配
# ---------------------------------------------------------------------------

def _quote_from_snapshot(ticker: str, row: dict[str, Any], trade_date: str) -> dict[str, Any] | None:
    """把 mootdx quotes() 的一行快照装配成与其它源一致的 quote dict。

    vol 单位是手（与 tushare `vol`、腾讯源同口径）；昨收用官方 last_close，
    除权日的涨跌幅口径才正确。
    """
    price = _to_float(row.get("price"))
    previous_close = _to_float(row.get("last_close"))
    if price is None or price <= 0:
        return None
    change = (
        round(price - previous_close, 6) if previous_close not in (None, 0) else None
    )
    change_pct = (
        round(change / previous_close * 100, 6)
        if change is not None and previous_close
        else None
    )
    return {
        "symbol": ticker,
        "price": price,
        "change": change,
        "changesPercentage": change_pct,
        "previousClose": previous_close,
        "open": _to_float(row.get("open")),
        "dayHigh": _to_float(row.get("high")),
        "dayLow": _to_float(row.get("low")),
        "volume": _to_float(row.get("vol")),
        "tradeDate": trade_date,
        "source": "mootdx",
    }


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        # round(…, 6)：TDX 协议解出的浮点带二进制噪声（如 48.460000000000001），
        # 6 位小数足以保留全部价格精度并消掉尾巴。
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


# 通达信单次快照请求的服务器端上限：pytdx 客户端不截断（stock_len 原样打包），
# 但服务器对超量请求只返回前 80 行、尾部静默丢弃（2026-11-02 实测 85 只请求
# 恰好回 80 行）。客户端必须自己分块，否则尾部票会静默缺数。
_TDX_MAX_BATCH = 80


def fetch_mootdx_quotes(tickers: list[str]) -> list[dict[str, Any]]:
    """批量取沪深 A 股/ETF 实时快照（主源路径）。

    `quotes()` 按 `_TDX_MAX_BATCH` 分块拉取，再逐票拉一根日线定交易日
    （停牌个股的交易日各自正确）。整体持锁串行，21 只票约 1 秒。
    单票失败只降级那一票，不影响其它票。
    """
    codes = [t for t in tickers if is_mootdx_ticker(t)]
    if not codes:
        return []

    quotes: list[dict[str, Any]] = []
    with _MOOTDX_LOCK:
        client = _get_mootdx_client()
        by_code: dict[str, dict[str, Any]] = {}
        batches = [
            codes[i : i + _TDX_MAX_BATCH] for i in range(0, len(codes), _TDX_MAX_BATCH)
        ]
        for batch in batches:
            try:
                snapshots = client.quotes(symbol=[c.split(".")[0] for c in batch])
            except Exception:
                reset_mootdx_client()
                raise
            if snapshots is None or snapshots.empty:
                log(f"Warning: mootdx quotes returned no data for {len(batch)} ticker(s)")
                continue
            by_code.update(
                {str(row["code"]): row for _, row in snapshots.iterrows()}
            )
        if not by_code:
            return []

        for ticker in codes:
            code = ticker.split(".")[0]
            row = by_code.get(code)
            if row is None:
                log(f"Warning: mootdx snapshot missing {ticker}")
                continue
            trade_date = _bars_trade_date(code)
            quote = _quote_from_snapshot(ticker, dict(row), trade_date)
            if quote:
                quotes.append(quote)
    return quotes


def fetch_mootdx_quote(ticker: str, market: str = "") -> dict[str, Any] | None:
    """单票入口（降级链用），与其它 fetch_*_quote(ticker, market) 同签名。"""
    if not is_mootdx_ticker(ticker):
        return None
    quotes = fetch_mootdx_quotes([ticker])
    return quotes[0] if quotes else None


def _bars_trade_date(code: str) -> str:
    """最新一根日线的交易日（ISO）。盘中即当日；周末/停牌冻结在上一交易日。

    已知取舍：bars 拉不到时记 warning 并返回空串——该票行情仍然入库，tradeDate
    落空由日报的数据覆盖口径标注；交易日缺失不升级为取数失败（那样会把一次
    bars 抖动放大成整票降级走 HTTP 爬虫链）。
    """
    # pandas 局部导入：能走到这里说明 mootdx 已成功 import，它自身强依赖 pandas，
    # 此时 pandas 必然可用（顶层条件导入不如放函数里直白）。
    import pandas as pd

    try:
        df = _mootdx_call("bars", symbol=code, frequency=9, offset=1)
        if df is None or df.empty:
            return ""
        return pd.Timestamp(df.index[-1]).date().isoformat()
    except Exception as exc:
        log(f"Warning: mootdx bars(交易日) failed for {code}: {exc}")
        return ""
