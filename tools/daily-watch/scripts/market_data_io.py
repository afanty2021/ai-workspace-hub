"""市场数据持久化层共享基座（spec §3/§4/§5）。

文件名即主键（§4.2 命名契约）；一切 series 落盘走原子写 + 三档 upsert（§5.2）：
- writer="batch"    批量任务=权威写者，同日按字段覆盖
- writer="snapshot" 日报钩子=快照级写者，同日只补 null 空位、绝不覆盖非空
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from mootdx_source import log
from workspace_paths import find_workspace_root, resolve_market_data_dir

SERIES_NUMERIC_FIELDS = ("open", "high", "low", "close", "volume", "amount")

# §5.2 前缀白名单（正列表天然排除 88/89 板块段、债券回购、北交所 4/8/9、B股）。
# LOF 口径两市场有意不对称：SH 50 段排除、SZ 16 段保留（spec §5.2 + §10 README 注记）。
_CN_PREFIX_WHITELIST: dict[int, tuple[str, ...]] = {
    1: ("60", "68", "51", "56", "58"),  # SH：主板/科创股票 + ETF
    0: ("00", "30", "15", "16"),        # SZ：主板/创业股票 + ETF（16=LOF）
}

_ET = ZoneInfo("America/New_York")  # 海外源 epoch 的交易所时区
_LOCK_STALE_S = 600.0  # 超过 10 分钟的锁视为崩溃残留，强制接管


def resolve_data_root(start_dir: Path | None = None) -> Path:
    base = start_dir or Path(__file__).resolve().parent
    return resolve_market_data_dir(find_workspace_root(base))


def series_file(data_root: Path, ticker: str) -> Path:
    return data_root / "market" / "series" / f"{ticker}.jsonl"


def sector_series_file(data_root: Path, code: str) -> Path:
    return data_root / "sector" / "series" / f"{code}.jsonl"


def normalize_cn_symbol(code: str, market: int) -> str:
    """裸 6 位 + tdx market（0=SZ, 1=SH）→ watchlist 标称记法（§4.2 命名契约）。"""
    return f"{code}.{'SH' if market == 1 else 'SZ'}"


def is_cn_series_symbol(code: str, market: int) -> bool:
    prefixes = _CN_PREFIX_WHITELIST.get(market, ())
    return bool(re.fullmatch(r"\d{6}", code)) and code.startswith(prefixes)


def parse_trade_date(value: Any) -> str | None:
    """各源 tradeDate → 'YYYY-MM-DD'；解析不了返回 None（spec §5.1：None 只进快照不进 series）。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / (1000.0 if value > 1e11 else 1.0)  # 13 位毫秒 / 10 位秒
        try:
            return datetime.fromtimestamp(seconds, tz=_ET).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    # Nasdaq 英文长戳："November 2, 2026 4:00PM ET"。%B 依赖英文 locale——当前及
    # 定时任务环境为 en_US；非英文 locale 下英文长戳退化为 None（只进快照），可接受。
    for fmt in ("%B %d, %Y %I:%M%p ET", "%B %d, %Y %I:%M %p", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def atomic_write_text(path: Path, text: str) -> None:
    """临时文件 + rename 原子替换（spec §3：禁止半行/半文件落盘）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def series_lock(data_root: Path, name: str, *, timeout_s: float = 1.0) -> Iterator[bool]:
    """data/.locks/ 目录锁：非阻塞语义，拿不到 → yield False（调用方跳过并告警）。

    陈旧锁接管：锁文件 mtime 超过 _LOCK_STALE_S 视为上次进程崩溃残留，删除重取——
    cron 进程被杀后锁不清理会把后续更新永久卡死。
    """
    lock_dir = data_root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"
    deadline = time.monotonic() + timeout_s
    acquired = False
    while time.monotonic() < deadline:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > _LOCK_STALE_S:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            time.sleep(0.05)
    if not acquired:
        log(f"Warning: 拿不到锁 {name}，跳过（另一进程可能正在写）")
    try:
        yield acquired
    finally:
        if acquired:
            lock_path.unlink(missing_ok=True)


def read_series_rows(path: Path) -> list[dict]:
    """读 series JSONL。末尾 torn 行容忍（原子写兜底下的极端残留），中段坏行必须炸。"""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
            log(f"Warning: {path.name} 末尾 torn 行已丢弃")
    return rows


def upsert_series_rows(path: Path, incoming: list[dict], writer: str) -> int:
    """三档合并（spec §5.2）。返回变更行数；调用方负责持锁。"""
    if not incoming:
        return 0
    existing = read_series_rows(path)
    by_date = {row["date"]: dict(row) for row in existing}
    changed = 0
    for new in incoming:
        day = new["date"]
        cur = by_date.get(day)
        if cur is None:  # ① 新日期：整行入库
            by_date[day] = dict(new)
            changed += 1
            continue
        merged = dict(cur)
        touched = False
        for key, val in new.items():
            if key == "date" or val is None:
                continue
            if writer == "batch":  # ② 权威写者：按字段覆盖
                if merged.get(key) != val:
                    merged[key] = val
                    touched = True
            else:  # ③ snapshot：只补 null 空位
                if merged.get(key) is None:
                    merged[key] = val
                    touched = True
        if touched:
            by_date[day] = merged
            changed += 1
    rows = [by_date[day] for day in sorted(by_date)]
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return changed
