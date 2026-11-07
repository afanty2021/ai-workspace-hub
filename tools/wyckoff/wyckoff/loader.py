"""数据加载：universe 解析 + 本地序列读取 + mootdx 深历史扩展。

数据链路（与 daily-watch 共用口径，但不写共享库——本工具自建缓存）：
- 自选股/ETF/.TDX：`data/market/series/{symbol}.jsonl`（共享持久化库，只读）；
- 交易所核心指数：`data/index/series/{code}.jsonl`（只读）；
- 深历史（2023-07 之前）：mootdx bars/index_bars 分页回拉，写
  `data/wyckoff/daily/{symbol}.jsonl`（本工具私有缓存，行格式与共享库一致）。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .machine import Bar

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class UniverseItem:
    symbol: str        # 序列键：600276.SH / 881075.TDX / IDX:000001
    name: str
    group: str         # watchlist 分组 / 核心指数
    store_path: Path | None   # 共享库路径（可能不存在）
    index: bool = False       # True → mootdx 走 index_bars


def repo_paths() -> tuple[Path, Path, Path]:
    market = _REPO_ROOT / "data" / "market" / "series"
    index = _REPO_ROOT / "data" / "index" / "series"
    cache = _REPO_ROOT / "data" / "wyckoff" / "daily"
    return market, index, cache


def sector_store_path(symbol: str) -> Path:
    """880/881 板块指数序列：data/sector/series/{code}.jsonl（market/series 下的
    .TDX 文件是日报钩子的单行残留，不是序列库）。"""
    return _REPO_ROOT / "data" / "sector" / "series" / f"{symbol.split('.')[0]}.jsonl"


def load_universe() -> list[UniverseItem]:
    """解析 config/daily-watchlist-watchlist.md 的 CN 行 + 8 个交易所核心指数。

    核心指数清单镜像 tools/daily-watch/scripts/update_market_series.py::_CORE_INDICES
    （该处是私有常量且 import 会拖入 mootdx 依赖，故此处带指针复制；两处若不同步
    以 daily-watch 为准）。
    """
    watchlist = _REPO_ROOT / "config" / "daily-watchlist-watchlist.md"
    market, index_dir, _ = repo_paths()
    items: list[UniverseItem] = []
    text = watchlist.read_text(encoding="utf-8")
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        m = re.match(r"^\|\s*([0-9]{6}\.(?:SH|SZ|TDX))\s*\|", line)
        if not m:
            continue
        symbol = m.group(1)
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        name = cols[1] if len(cols) > 1 else symbol
        if symbol.endswith(".TDX"):
            store = sector_store_path(symbol)
        else:
            store = market / f"{symbol}.jsonl"
        items.append(UniverseItem(
            symbol=symbol, name=name, group=section,
            store_path=store,
            index=symbol.endswith(".TDX"),
        ))
    core_indices = [
        ("000001", "上证指数"), ("000016", "上证50"), ("000300", "沪深300"),
        ("000905", "中证500"), ("000852", "中证1000"), ("000688", "科创50"),
        ("399001", "深证成指"), ("399006", "创业板指"),
    ]
    for code, name in core_indices:
        items.append(UniverseItem(
            symbol=f"IDX:{code}", name=name, group="核心指数",
            store_path=index_dir / f"{code}.jsonl", index=True,
        ))
    return items


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            rows.append(json.loads(ln))
    return rows


def rows_to_bars(rows: list[dict]) -> list[Bar]:
    """date 升序去重 → Bar；volume 缺失/为 0 时保留为 None（no-volume 模式）。"""
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r.get("date")
        if d:
            by_date[d] = r
    bars: list[Bar] = []
    for d in sorted(by_date):
        r = by_date[d]
        vol = r.get("volume")
        bars.append(Bar(
            date=d,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(vol) if vol else None,
        ))
    return bars


def load_symbol(item: UniverseItem) -> tuple[list[Bar], str]:
    """优先深历史缓存，合并共享库尾部；返回 (bars, 来源说明)。"""
    _, _, cache_dir = repo_paths()
    cache = cache_dir / f"{item.symbol.replace(':', '_')}.jsonl"
    rows = read_jsonl(cache)          # 深历史（可能不存在）
    n_cache = len(rows)
    rows += read_jsonl(item.store_path) if item.store_path else []
    bars = rows_to_bars(rows)
    src = f"cache({n_cache})+store" if n_cache else "store"
    return bars, src


# ---------------------------------------------------------------------------
# mootdx 深历史扩展（独立于 daily-watch 的批量写者；只写本工具缓存）
# ---------------------------------------------------------------------------


def fetch_deep_history(item: UniverseItem, start: str = "2016-01-01",
                       chunk: int = 700, max_pages: int = 20) -> tuple[int, str]:
    """回拉 start 之前的日线并合并进缓存；返回 (新增行数, 状态)。

    复用 daily-watch 的 mootdx_source（服务器验证/负缓存/RLock 都在那层），
    只是不走它的持久化写者——写 `data/wyckoff/daily/`。
    """
    dw_scripts = _REPO_ROOT / "tools" / "daily-watch" / "scripts"
    if str(dw_scripts) not in sys.path:
        sys.path.insert(0, str(dw_scripts))
    try:
        from mootdx_source import _mootdx_call  # 延迟 import：不联网时零依赖
    except Exception as exc:  # noqa: BLE001
        return 0, f"import-fail: {exc}"

    _, _, cache_dir = repo_paths()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{item.symbol.replace(':', '_')}.jsonl"
    existing = {r["date"]: r for r in read_jsonl(cache)}
    store_rows = read_jsonl(item.store_path) if item.store_path else []
    existing.update({r["date"]: r for r in store_rows})

    code = item.symbol.split(":")[-1].split(".")[0]
    method = "index_bars" if item.index else "bars"
    added = 0
    oldest: str | None = None
    for page in range(max_pages):
        try:
            df = _mootdx_call(method, symbol=code, frequency=9,
                              offset=chunk, start=page * chunk)
        except Exception as exc:  # noqa: BLE001
            return added, f"fetch-fail@page{page}: {exc}"
        if df is None or df.empty:
            break
        page_rows = _df_to_rows(df)
        if not page_rows:
            break
        for r in page_rows:
            if r["date"] not in existing:
                existing[r["date"]] = r
                added += 1
        dates = sorted(existing)
        oldest = dates[0]
        if oldest and oldest <= start:
            break
        # 该页全部早于已有最早日期 → 服务器历史到底
        if page_rows[-1]["date"] < (dates[0] if len(dates) > 1 else page_rows[-1]["date"]):
            break
    lines = [json.dumps(existing[d], ensure_ascii=False) for d in sorted(existing)]
    cache.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return added, f"ok oldest={oldest}"


def _df_to_rows(df) -> list[dict]:
    """mootdx bars/index_bars DataFrame → 序列行（口径同 update_market_series）。"""
    import pandas as pd

    idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df["datetime"])
    rows = []
    for ts, (_, r) in zip(idx, df.iterrows()):
        vol = r.get("vol")
        rows.append({
            "date": pd.Timestamp(ts).date().isoformat(),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(vol) if vol == vol and vol else None,  # NaN→None
            "amount": float(r["amount"]) if r.get("amount") == r.get("amount") else None,
            "source": "mootdx-wyckoff",
        })
    rows.sort(key=lambda x: x["date"])
    return rows
