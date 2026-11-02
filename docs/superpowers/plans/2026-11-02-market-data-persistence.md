# 市场数据持久化层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 spec 落地 daily-watch 本地持久化层：全市场行情/板块时序、日报快照、新闻快照、财务快照、自定义序列（JSONL 落盘 + DuckDB 查询）。

**Architecture:** 逐票 JSONL 文件为真相源，`market_data_io.py` 提供原子写/三档 upsert/命名契约等基座；五个写入脚本（日报钩子、盘后批量×2、自定义、新闻）+ 一个 DuckDB 查询 CLI。零服务、零守护进程；duckdb 仅查询层可选依赖。多写者由「写者身份表」约束：批量=权威写者（同日按字段覆盖），日报钩子=快照级（只补 null）。

**Tech Stack:** Python 3.11（conda env `Quant-3.11`）、mootdx 0.11.7（复用 `mootdx_source` RLock 单例）、duckdb（查询层）、unittest+pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-11-02-market-data-persistence-design.md`（v0.3，已批准）。执行者必须同时读 spec——本计划只写「怎么做」，「为什么/口径」在 spec。
- 修订：v2（2026-11-02 第二轮评审后落档，7 Critical/8 Important/15 Minor 全实证修订：交易日闸门改 canary 文件（钩子行 source 无法区分写者）、财务 GP 兜底改 run 级 config.set、财务目录预建 + Financial 正确导入路径、epoch 期望值与互斥测试修正、查询视图按需创建 + ignore_errors + 板块路由、csv/新闻边界加固、git add 显式化）
- 修订：v3（2026-11-02 复查后落档，1 Critical + 3 阻塞级 + 6 Minor 全实证修订：**N1 交易日闸门 canary 文件改 `data/.state/` per-scope 完成标记**（`--scope sectors` 会写脏 canary → 11.7 全量初始化静默短路 + cron fail>0 同日补跑失效；标记写入条件 `not tickers and fail==0 and latest 已知`）；Task 3 测试预置补父目录 mkdir；Task 6 重复 kwargs 改 dict 覆盖；p_list F841；GP 兜底持 `_MOOTDX_LOCK` + 双通道全灭干净报错 + gp_fallback≠None 主路径补测；`--scope sectors --tickers` argparse 拒绝；11.7/11.8 计时口径随标记方案重写；spec §5.2 同步标记语义（v0.3）；`tail_date` 随闸门方案一并移除）；N4 e2e 修正见 Task 8 注记

## Global Constraints

- **Python 解释器**：一律 conda env Quant-3.11。沙箱内 `conda run` 的 shim 可能被权限挡（2026-11-02 实测），直接用绝对路径：`PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python`。
- **测试**：全部封闭 tmp 目录、mootdx 一律 mock，不联网；真实连通性只在 Task 11 e2e。测试放仓库根 `tests/`，unittest.TestCase 风格，文件头 `from _test_paths import REPO_ROOT  # noqa: F401`（它会注入 sys.path），然后 `import <script模块名>`。运行：`$PY -m pytest tests/test_xxx.py -v`。
- **lint**：`$PY -m ruff check tools/daily-watch/scripts tests`。规则分两套：`tools/daily-watch/scripts` 按同目录 `pyproject.toml`（line-length 100、select E/F/W、ignore E501）；`tests/` 不在该 pyproject 管辖路径下，走 ruff 内置默认规则（E4/E7/E9/F）——两套都以这条命令通过为准。若 env 缺 ruff 先 `$PY -m pip install ruff`。
- **mootdx 单 socket**：一切行情取数走 `mootdx_source._mootdx_call(method, **kwargs)`（RLock 单例，`tools/daily-watch/scripts/mootdx_source.py:270`），**禁止自建 pytdx/tdxpy 连接**。日志用 `mootdx_source.log`（打 stderr）。
- **git**：直提 main、每个 Task 一个 commit（按关注点）、**不 push**（push 等用户点名）。仓库无 PR 流程——spec 中「写进 PR 描述」的校验记录落进对应 commit 的 message body。
- **执行摩擦**：发现文档/计划与实际不符 → 当场记 `workspace/meta/friction-log.md`（AGENTS.md 硬规则），不要悄悄绕过。
- **TDD 纪律**：每个用例先跑红（失败原因正确）再实现转绿；不许先写实现。
- `data/` 是运行时数据目录：测试一律用 `tempfile.TemporaryDirectory()` 下的假 data_root，绝不写仓库根的真实 `data/`（Task 11 e2e 除外——那是真实数据落盘点）。

## File Structure

```
tools/daily-watch/scripts/
├── market_data_io.py            # [新建] 存储基座：原子写、目录锁、三档 upsert、
│                                #   命名契约 normalize、tradeDate 归一、前缀白名单
├── persist_market_data.py       # [新建] 日报钩子：快照落盘 + watchlist series 追加 + CLI
├── update_market_series.py      # [新建] 盘后批量：全市场个股 + 板块指数（--scope）
├── update_finance_snapshots.py  # [新建] 财务快照：gpcw hash 台账 + 按位置映射
├── save_custom_data.py          # [新建] 自定义数值序列：registry + append/csv-import CLI
├── save_news_snapshot.py        # [新建] 新闻原文快照：URL dedup + frontmatter
├── query_market.py              # [新建] DuckDB 查询 CLI（唯一依赖 duckdb 的组件）
├── mootdx_source.py             # [只读复用] _mootdx_call / log / is_mootdx_ticker
├── workspace_paths.py           # [修改] +resolve_market_data_dir
└── generate_daily_report.py     # [修改] :932 后插入 persist 钩子（try/except）
tools/daily-watch/
├── requirements-market-data.txt # [新建] 仅 duckdb
└── README.md                    # [修改] +「本地持久化」章节
tests/
├── test_market_data_io.py       # [新建] Task 1
├── test_persist_market_data.py  # [新建] Task 2
├── test_update_market_series.py # [新建] Task 3+4
├── test_update_finance_snapshots.py  # [新建] Task 5
├── test_save_custom_data.py     # [新建] Task 6
├── test_save_news_snapshot.py   # [新建] Task 7
└── test_query_market.py         # [新建] Task 8
```

分解理由：基座（IO/合并规则）被三个写者共用必须独立成模块先测透；五个写者各自独立 CLI 可单独评审；查询层依赖 duckdb 放最后，装不上不阻塞前七个 Task。

---

### Task 1: 存储基座 `market_data_io.py`

**Files:**
- Create: `tools/daily-watch/scripts/market_data_io.py`
- Modify: `tools/daily-watch/scripts/workspace_paths.py`（追加一个函数）
- Test: `tests/test_market_data_io.py`

**Interfaces:**
- Consumes: `workspace_paths.find_workspace_root(start_dir: Path) -> Path`
- Produces（后续 Task 全依赖，签名不得改动）:
  - `resolve_data_root(start_dir: Path | None = None) -> Path`
  - `series_file(data_root: Path, ticker: str) -> Path`、`sector_series_file(data_root: Path, code: str) -> Path`
  - `normalize_cn_symbol(code: str, market: int) -> str`（market: 0=SZ, 1=SH → `"600276.SH"`）
  - `is_cn_series_symbol(code: str, market: int) -> bool`（§5.2 前缀白名单）
  - `parse_trade_date(value: Any) -> str | None`（""/epoch/8位/ISO/英文长戳 → `"YYYY-MM-DD"` 或 None）
  - `atomic_write_text(path: Path, text: str) -> None`
  - `series_lock(data_root: Path, name: str, *, timeout_s: float = 1.0)` contextmanager → yield `bool`（False=拿不到锁，调用方跳过）
  - `read_series_rows(path: Path) -> list[dict]`（容忍末尾 torn 行；中段坏行 raise）
  - `upsert_series_rows(path: Path, incoming: list[dict], writer: str) -> int`（"batch"=权威覆盖 / "snapshot"=只补 null；返回变更行数）
  - 常量 `SERIES_NUMERIC_FIELDS = ("open", "high", "low", "close", "volume", "amount")`

- [ ] **Step 1.1: workspace_paths.py 追加数据目录解析**

在 `workspace_paths.py` 末尾（`resolve_hypothesis_config_path` 之后）追加：

```python
MARKET_DATA_DIRNAME = "data"


def resolve_market_data_dir(workspace_root: Path) -> Path:
    """市场数据持久化目录（运行时数据，整目录 gitignore）。"""
    return workspace_root / MARKET_DATA_DIRNAME
```

- [ ] **Step 1.2: 写失败测试**

`tests/test_market_data_io.py`：

```python
"""market_data_io 单测（全封闭 tmp 目录）。三档 upsert 是 spec §5.2 的根规则。"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401

import market_data_io as mio  # noqa: E402


class NamingTests(unittest.TestCase):
    def test_normalize_market_suffix(self) -> None:
        self.assertEqual(mio.normalize_cn_symbol("600276", 1), "600276.SH")
        self.assertEqual(mio.normalize_cn_symbol("300476", 0), "300476.SZ")

    def test_whitelist_positive(self) -> None:
        for code, market in (("600519", 1), ("688981", 1), ("513880", 1),
                             ("512000", 1), ("560010", 1), ("002545", 0),
                             ("301358", 0), ("159915", 0), ("162411", 0)):
            self.assertTrue(mio.is_cn_series_symbol(code, market), (code, market))

    def test_whitelist_negative(self) -> None:
        # SH: 88/89 板块段、20x 回购、50x LOF（有意不对称，spec §5.2）
        for code in ("880301", "890001", "204001", "500001"):
            self.assertFalse(mio.is_cn_series_symbol(code, 1), code)
        # SZ: 债券/回购、B股、指数
        for code in ("120400", "131810", "200004", "399106", "100001"):
            self.assertFalse(mio.is_cn_series_symbol(code, 0), code)
        # 北交所 43/83/87/92 在两个市场表里都不该过
        for code in ("430047", "830799", "872925", "920002"):
            self.assertFalse(mio.is_cn_series_symbol(code, 0), code)
            self.assertFalse(mio.is_cn_series_symbol(code, 1), code)
        self.assertFalse(mio.is_cn_series_symbol("6002", 1))  # 非 6 位


class TradeDateTests(unittest.TestCase):
    def test_digits_and_iso(self) -> None:
        self.assertEqual(mio.parse_trade_date("20261102"), "2026-11-02")
        self.assertEqual(mio.parse_trade_date("2026-11-02"), "2026-11-02")

    def test_epoch_seconds_and_millis(self) -> None:
        # 1761950400 = 2025-10-31 22:40 UTC = 18:40 EDT（美东收盘后），两时区同日
        self.assertEqual(mio.parse_trade_date(1761950400), "2025-10-31")
        self.assertEqual(mio.parse_trade_date(1761950400000), "2025-10-31")

    def test_english_long_stamp(self) -> None:
        self.assertEqual(mio.parse_trade_date("November 2, 2026 4:00PM ET"), "2026-11-02")
        self.assertEqual(mio.parse_trade_date("November 2, 2026"), "2026-11-02")

    def test_garbage_and_empty_return_none(self) -> None:
        for bad in ("", None, "垃圾", "Nov-x"):
            self.assertIsNone(mio.parse_trade_date(bad), bad)


class UpsertTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "600276.SH.jsonl"
        self.path.write_text(
            '{"date": "2026-10-30", "open": 71.0, "high": 73.0, "low": 70.0, "close": 71.0, "volume": 100, "amount": null, "source": "mootdx"}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_new_date_inserted_in_order(self) -> None:
        n = mio.upsert_series_rows(self.path, [self._row("2026-10-28", close=69.0)], "batch")
        self.assertEqual(n, 1)
        dates = [r["date"] for r in mio.read_series_rows(self.path)]
        self.assertEqual(dates, ["2026-10-28", "2026-10-30"])  # 升序插入非纯 append

    def test_batch_authoritative_overwrites(self) -> None:
        n = mio.upsert_series_rows(self.path, [self._row("2026-10-30", close=99.9)], "batch")
        self.assertEqual(n, 1)
        self.assertEqual(mio.read_series_rows(self.path)[-1]["close"], 99.9)

    def test_snapshot_fills_null_never_overwrites(self) -> None:
        # 预置行 amount=null（批量未跑过）；钩子行 close=99.9、amount=7100：
        # snapshot 档只补 null 空位 → amount 补上、close 保留 71.0，n==1
        row = self._row("2026-10-30", close=99.9, amount=7100.0)
        n = mio.upsert_series_rows(self.path, [row], "snapshot")
        self.assertEqual(n, 1)
        got = mio.read_series_rows(self.path)[-1]
        self.assertEqual(got["close"], 71.0)     # 非空没被覆盖
        self.assertEqual(got["amount"], 7100.0)  # null 被补上

    def test_no_change_returns_zero(self) -> None:
        row = self._row("2026-10-30", close=71.0, amount=None)  # 与预置行一致（amount 均 null）
        n = mio.upsert_series_rows(self.path, [row], "batch")
        self.assertEqual(n, 0)

    def test_torn_tail_tolerated_middle_raises(self) -> None:
        ok = self.root / "a.jsonl"
        ok.write_text('{"date": "2026-11-01", "close": 1.0}\n{"date": "2026-11', encoding="utf-8")
        self.assertEqual(len(mio.read_series_rows(ok)), 1)
        bad = self.root / "b.jsonl"
        bad.write_text('{"date": "2026-11-01", "close": 1.0}\n坏行\n{"date": "2026-11-02", "close": 2.0}\n', encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            mio.read_series_rows(bad)

    def _row(self, d: str, close: float, amount: float | None = 7100.0) -> dict:
        return {"date": d, "open": None, "high": None, "low": None, "close": close,
                "volume": None, "amount": amount, "source": "mootdx"}


class AtomicAndLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_atomic_write_leaves_no_tmp(self) -> None:
        p = self.root / "sub" / "x.jsonl"
        mio.atomic_write_text(p, "hello\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "hello\n")
        self.assertEqual(list((self.root / "sub").glob("*.tmp")), [])

    def test_lock_exclusive_and_stale_takeover(self) -> None:
        with mio.series_lock(self.root, "t") as ok:
            self.assertTrue(ok)
            with mio.series_lock(self.root, "t", timeout_s=0.2) as ok2:
                self.assertFalse(ok2)  # 同名锁非阻塞拿不到
        lock = self.root / ".locks" / "t.lock"
        lock.write_text("dead", encoding="utf-8")
        os.utime(lock, (time.time() - 700, time.time() - 700))  # 伪装 10 分钟前的陈旧锁
        with mio.series_lock(self.root, "t") as ok3:
            self.assertTrue(ok3)  # 陈旧锁被接管


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.3: 跑红**

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pytest tests/test_market_data_io.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'market_data_io'`）

- [ ] **Step 1.4: 实现 `market_data_io.py`**

```python
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
```

- [ ] **Step 1.5: 跑绿**

Run: `$PY -m pytest tests/test_market_data_io.py -v`
Expected: PASS（全部用例）

- [ ] **Step 1.6: ruff + 全量回归**

Run: `$PY -m ruff check tools/daily-watch/scripts/market_data_io.py tests/test_market_data_io.py && $PY -m pytest tests/ -q`
Expected: ruff 干净；全量测试无回归

- [ ] **Step 1.7: Commit**

```bash
git add tools/daily-watch/scripts/market_data_io.py tools/daily-watch/scripts/workspace_paths.py tests/test_market_data_io.py
git commit -m "feat: 市场数据持久化基座 market_data_io——原子写/目录锁/三档upsert/命名契约/tradeDate归一"
```

---

### Task 2: 日报钩子 `persist_market_data.py`

**Files:**
- Create: `tools/daily-watch/scripts/persist_market_data.py`
- Modify: `tools/daily-watch/scripts/generate_daily_report.py`（:932 `market_data = ...` 之后插钩子）
- Test: `tests/test_persist_market_data.py`

**Interfaces:**
- Consumes: Task 1 全部；fetch payload 结构 `{quotes: [...18 字段 quote...], movers, earnings, meta}`（`fetch_market_data.py:1450-1464`）
- Produces:
  - `save_daily_snapshot(snapshot: dict, data_root: Path, today: str | None = None) -> Path`（today 可注入，测试防跨午夜假红）
  - `append_series_from_snapshot(snapshot: dict, data_root: Path) -> int`
  - `quote_to_series_row(quote: dict) -> dict | None`（tradeDate 解析失败 → None）
  - `run_persist_hook(market_data: dict, data_root: Path | None = None) -> None`（吞一切异常）
  - CLI：`--snapshot-file <json>`

- [ ] **Step 2.1: 写失败测试**

`tests/test_persist_market_data.py`：

```python
"""persist_market_data 单测。钩子的天条：失败永不阻塞日报（spec §3）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _test_paths import REPO_ROOT  # noqa: F401

import persist_market_data as pmd  # noqa: E402
from market_data_io import read_series_rows, series_file  # noqa: E402


def _quote(ticker: str, **over: dict) -> dict:
    base = {"ticker": ticker, "price": 71.54, "open": 71.0, "dayHigh": 73.2, "dayLow": 70.5,
            "volume": 123456.0, "tradeDate": "2026-11-02", "source": "mootdx"}
    base.update(over)
    return base


def _snapshot(quotes: list[dict]) -> dict:
    return {"quotes": quotes, "movers": [], "earnings": [],
            "meta": {"fetched_at": "2026-11-02T08:30:00+00:00", "quotes": {"state": "ok"}}}


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_snapshot_wraps_full_payload_and_overwrites_same_day(self) -> None:
        path1 = pmd.save_daily_snapshot(_snapshot([_quote("600276.SH")]), self.root, today="2026-11-02")
        self.assertEqual(json.loads(path1.read_text(encoding="utf-8"))["payload"]["meta"]["quotes"]["state"], "ok")
        self.assertEqual(path1.name, "2026-11-02.json")
        path2 = pmd.save_daily_snapshot(_snapshot([_quote("300476.SZ")]), self.root, today="2026-11-02")
        self.assertEqual(path1, path2)  # 同日覆盖
        payload = json.loads(path2.read_text(encoding="utf-8"))["payload"]
        self.assertEqual(payload["quotes"][0]["ticker"], "300476.SZ")


class SeriesAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_quote_maps_to_series_row(self) -> None:
        row = pmd.quote_to_series_row(_quote("600276.SH"))
        self.assertEqual(row["date"], "2026-11-02")
        self.assertEqual(row["close"], 71.54)
        self.assertEqual(row["high"], 73.2)
        self.assertIsNone(row["amount"])  # 钩子路径无 amount（spec §4.2）

    def test_unparseable_tradedate_returns_none(self) -> None:
        self.assertIsNone(pmd.quote_to_series_row(_quote("^SOX", tradeDate="")))

    def test_appends_per_ticker_and_skips_bad_dates(self) -> None:
        n = pmd.append_series_from_snapshot(
            _snapshot([_quote("600276.SH"), _quote("^SOX", tradeDate="garbage")]), self.root)
        self.assertEqual(n, 1)
        self.assertTrue(series_file(self.root, "600276.SH").exists())
        self.assertFalse(series_file(self.root, "^SOX").exists())  # 坏日期只进快照不进 series

    def test_snapshot_writer_fills_null_only(self) -> None:
        # 预置批量权威行（完整 OHLCV），钩子行只能补 null 不能覆盖
        pmd.append_series_from_snapshot(_snapshot([_quote("600276.SH")]), self.root)
        path = series_file(self.root, "600276.SH")
        mio_rows = read_series_rows(path)
        mio_rows[0]["amount"] = 88900000.0
        path.write_text("".join(json.dumps(r) + "\n" for r in mio_rows), encoding="utf-8")
        pmd.append_series_from_snapshot(
            _snapshot([_quote("600276.SH", price=999.0)]), self.root)  # 盘中价乱值
        self.assertEqual(read_series_rows(path)[-1]["close"], 71.54)  # 没被覆盖


class HookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_hook_swallows_exceptions(self) -> None:
        with patch.object(pmd, "save_daily_snapshot", side_effect=RuntimeError("boom")):
            pmd.run_persist_hook(_snapshot([_quote("600276.SH")]), self.root)  # 不抛即通过

    def test_report_source_wires_hook(self) -> None:
        source = (REPO_ROOT / "tools/daily-watch/scripts/generate_daily_report.py").read_text(encoding="utf-8")
        self.assertIn("_persist_market_data_hook(market_data)", source)
        self.assertIn("def _persist_market_data_hook(", source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2.2: 跑红**

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pytest tests/test_persist_market_data.py -v`
Expected: FAIL（`No module named 'persist_market_data'`；wiring 断言也红）

- [ ] **Step 2.3: 实现 `persist_market_data.py`**

```python
"""日报持久化钩子（spec §5.1）：快照原样落盘 + watchlist series 快照级追加。

钩子=快照级写者：同日只补 null、绝不覆盖非空（spec §5.2 写者身份表）。
"""

from __future__ import annotations

import argparse
import json
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
        return float(val) if val is not None else None

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
```

- [ ] **Step 2.4: generate_daily_report.py 接钩子**

在 `run_json_script`（:62-85）函数之后追加 helper：

```python
def _persist_market_data_hook(market_data: dict[str, Any]) -> None:
    """持久化钩子（spec §3：失败永不阻塞日报，只 log warning）。"""
    try:
        import persist_market_data

        persist_market_data.run_persist_hook(market_data)
    except Exception as exc:  # noqa: BLE001
        log(f"Warning: persist hook failed (report continues): {exc}")
```

在 `:932` 的 `market_data = run_json_script(workspace_root, "fetch_market_data.py")` 行后插入一行：

```python
    _persist_market_data_hook(market_data)
```

（`import persist_market_data` 放函数内：让 persist 模块缺失、损坏或 import 期的一切异常都落进同一个 try/except 吞掉路径——持久化是可选组件，任何失败不得改动日报主流程。）

- [ ] **Step 2.5: 跑绿 + 回归**

Run: `$PY -m pytest tests/test_persist_market_data.py tests/test_market_data_io.py -v && $PY -m ruff check tools/daily-watch/scripts/persist_market_data.py tests/test_persist_market_data.py`
Expected: PASS，ruff 干净

- [ ] **Step 2.6: Commit**

```bash
git add tools/daily-watch/scripts/persist_market_data.py tools/daily-watch/scripts/generate_daily_report.py tests/test_persist_market_data.py
git commit -m "feat: 日报持久化钩子 persist_market_data——快照嵌套落盘+watchlist series 快照级追加"
```

---

### Task 3: 全市场批量 `update_market_series.py`（stocks）

**Files:**
- Create: `tools/daily-watch/scripts/update_market_series.py`（本 Task 只做 stocks；sectors 在 Task 4 补齐）
- Test: `tests/test_update_market_series.py`

**Interfaces:**
- Consumes: Task 1 全部；`mootdx_source._mootdx_call`、`log`
- Produces（Task 4 复用）:
  - `fetch_server_latest_trade_date() -> str | None`（服务器最新交易日探测：canary=`index_bars("880301")` 一次调用，与完成标记无关）
  - `last_round_date(data_root: Path, scope: str) -> str | None` / `write_round_marker(data_root: Path, scope: str, date: str) -> None`——交易日闸门的完成标记，住 `data/.state/last_{scope}_round`。**为什么是旁路标记而不是数据文件**（N1）：① canary 板块文件会被 `--scope sectors` 单独执行写脏（e2e 11.2、局部补跑都走这条路），以它当 stocks 完成标志会把「板块已更」误判成「个股已更」，全市场初始化整轮静默短路；② market 文件由钩子与批量共同写，钩子行 source 同为 `"mootdx"` 按写者区分不可行，日报先于 16:30 跑会把当日误判「已批量」→ 当日 T+1。标记写入条件收严为 **`not tickers and fail == 0 and latest is not None`**——tickers 抽查（e2e 11.1）写标记会挡住 11.7 全量初始化；fail>0 写标记会让 cron 同日补跑失效
  - `bars_to_rows(df, *, source: str) -> list[dict]`（含 index_bars 的 up_count/down_count 分支）
  - `run_stocks_update(data_root: Path, *, backfill: int = 30, tickers: list[str] | None = None, latest: str | None = None) -> dict`（返回 `{"ok": int, "skip": int, "fail": int}`）
  - `run_sectors_update(data_root: Path, *, backfill: int = 30, latest: str | None = None) -> dict`（Task 4 实现，本 Task 先定义签名占位 raise——不，直接在 Task 4 一起实现；本 Task 的 CLI `--scope` 先支持 stocks|all 中 stocks 部分，sectors 分支 Task 4 接入）
  - CLI：`--scope stocks|sectors|all`、`--backfill N`（默认 30）、`--tickers A,B`（仅 stocks/all 有效，`--scope sectors --tickers X` 在 argparse 层报错拒绝，不静默丢弃）；fail>0 exit 1

- [ ] **Step 3.1: 写失败测试**

`tests/test_update_market_series.py`：

```python
"""update_market_series 单测（mock _mootdx_call，不联网）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from _test_paths import REPO_ROOT  # noqa: F401

import update_market_series as ums  # noqa: E402
from market_data_io import read_series_rows, sector_series_file, series_file, upsert_series_rows  # noqa: E402


def _bars_frame(dates: list[str], closes: list[float], **extra: dict) -> pd.DataFrame:
    data = {"open": [c - 1 for c in closes], "high": [c + 1 for c in closes],
            "low": [c - 2 for c in closes], "close": closes,
            "volume": [100.0] * len(dates), "amount": [8.0e7] * len(dates)}
    data.update(extra)
    return pd.DataFrame(data, index=pd.to_datetime(dates))


def _stocks_frame(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["code", "name"])


class FakeMootdx:
    """按 method 分发的 _mootdx_call 替身。用法：FakeMootdx(stocks=..., bars=..., index_bars=...)。"""

    def __init__(self, *, stocks=None, bars=None, index_bars=None) -> None:
        self.calls: list[str] = []
        self._stocks = stocks
        self._bars = bars
        self._index_bars = index_bars

    def __call__(self, method: str, **kwargs):
        self.calls.append(
            f"{method}:{kwargs.get('symbol', kwargs.get('market', ''))}:off{kwargs.get('offset')}")
        table = {"stocks": self._stocks, "bars": self._bars, "index_bars": self._index_bars}[method]
        if table is None:
            raise RuntimeError(f"unexpected call {method}")
        if method == "bars" and callable(table):
            return table(kwargs.get("symbol"))
        return table


class GateTests(unittest.TestCase):
    def test_canary_reads_last_index_bar(self) -> None:
        fake = FakeMootdx(index_bars=_bars_frame(["2026-11-02"], [3300.0]))
        with patch.object(ums, "_mootdx_call", fake):
            self.assertEqual(ums.fetch_server_latest_trade_date(), "2026-11-02")

    def test_gate_short_circuits_whole_round(self) -> None:
        # N1：闸门只认 data/.state/ 完成标记（批量写者独占的旁路状态），
        # 数据文件有当日行也不触发（那可能是钩子写的）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ums.write_round_marker(root, "stocks", "2026-11-02")
            market = series_file(root, "600276.SH")
            market.parent.mkdir(parents=True, exist_ok=True)
            market.write_text('{"date": "2026-11-02", "close": 71.5, "source": "mootdx"}\n',
                              encoding="utf-8")
            fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]))
            with patch.object(ums, "_mootdx_call", fake):
                stats = ums.run_stocks_update(root, latest="2026-11-02")
            self.assertEqual(stats, {"ok": 0, "skip": 0, "fail": 0})  # 整轮零调用
            self.assertFalse(any(c.startswith("stocks:") for c in fake.calls))

    def test_gate_ignores_hook_written_market_files(self) -> None:
        # I7：只有日报钩子写过的 market 文件（16:30 批量未跑、无标记）不得让闸门短路
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            market = series_file(root, "600276.SH")
            market.parent.mkdir(parents=True, exist_ok=True)
            market.write_text('{"date": "2026-11-02", "close": 71.5, "source": "mootdx"}\n',
                              encoding="utf-8")
            fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]),
                              bars=_bars_frame(["2026-11-02"], [71.54]))
            with patch.object(ums, "_mootdx_call", fake):
                stats = ums.run_stocks_update(root, latest="2026-11-03")  # 服务器已有 11-03，本地钩子只写到 11-02
            self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})  # 批量照常执行

    def test_marker_written_only_for_clean_full_round(self) -> None:
        # N1 补充点①：tickers 抽查轮与 fail>0 轮都不得写标记——前者会挡住 11.7
        # 全量初始化，后者会让 cron 同日补跑被闸门吃掉。三轮日期递进，保证
        # 失败轮不被「tail==latest 逐票 skip」挡住而真打到 bars。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeMootdx(stocks=_stocks_frame([("600276", "a")]),
                              bars=_bars_frame(["2026-11-03"], [71.54]))
            with patch.object(ums, "_mootdx_call", fake):
                ums.run_stocks_update(root, tickers=["600276.SH"], latest="2026-11-03")
            self.assertIsNone(ums.last_round_date(root, "stocks"))  # tickers 轮：无标记

            def boom(symbol: str):
                raise RuntimeError("socket dead")

            with patch.object(ums, "_mootdx_call",
                              FakeMootdx(stocks=_stocks_frame([("600276", "a")]), bars=boom)):
                stats = ums.run_stocks_update(root, latest="2026-11-04")  # 服务器前进一日 → 票不被逐票 skip 挡住
            self.assertEqual(stats, {"ok": 0, "skip": 0, "fail": 1})
            self.assertIsNone(ums.last_round_date(root, "stocks"))  # fail>0 轮：无标记

            with patch.object(ums, "_mootdx_call", fake):
                ums.run_stocks_update(root, latest="2026-11-04")
            self.assertEqual(ums.last_round_date(root, "stocks"), "2026-11-04")  # 干净全量轮：写标记


class StocksUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_enumerate_filter_normalize_upsert(self) -> None:
        stocks = _stocks_frame([("600276", "恒瑞医药"), ("300476", "胜宏科技"),
                                ("880301", "板块占位"), ("204001", "回购"), ("430047", "北交所")])
        fake = FakeMootdx(stocks=stocks, bars=_bars_frame(["2026-11-01", "2026-11-02"], [70.0, 71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(stats, {"ok": 2, "skip": 0, "fail": 0})
        rows = read_series_rows(series_file(self.root, "600276.SH"))
        self.assertEqual([r["date"] for r in rows], ["2026-11-01", "2026-11-02"])
        self.assertEqual(rows[-1]["source"], "mootdx")
        self.assertEqual(rows[-1]["amount"], 8.0e7)
        self.assertTrue(series_file(self.root, "300476.SZ").exists())
        self.assertFalse(series_file(self.root, "880301.SH").exists())  # 白名单外不建文件

    def test_tail_equals_latest_skips_ticket(self) -> None:
        # 与闸门的分工：闸门管「整轮」（.state 标记）；逐票 skip 管 tickers 子集等闸门旁路路径
        market = series_file(self.root, "600276.SH")
        market.parent.mkdir(parents=True, exist_ok=True)
        market.write_text(
            '{"date": "2026-11-02", "close": 71.5, "source": "mootdx"}\n', encoding="utf-8")
        fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]),
                          bars=_bars_frame(["2026-11-02"], [71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, tickers=["600276.SH"], latest="2026-11-02")
        self.assertEqual(stats["skip"], 1)
        self.assertFalse(any(c.startswith("bars:") for c in fake.calls))  # 没打服务器

    def test_single_failure_counted_others_continue(self) -> None:
        def bars_by_symbol(symbol: str):
            if symbol == "600276":
                raise RuntimeError("socket dead")
            return _bars_frame(["2026-11-02"], [71.54])

        fake = FakeMootdx(stocks=_stocks_frame([("600276", "a"), ("300476", "b")]), bars=bars_by_symbol)
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 1})
        self.assertTrue(series_file(self.root, "300476.SZ").exists())

    def test_tickers_subset_overrides_enumeration(self) -> None:
        fake = FakeMootdx(bars=_bars_frame(["2026-11-02"], [71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, backfill=800, tickers=["600276.SH"], latest="2026-11-03")
        self.assertEqual(stats["ok"], 1)
        self.assertIn("bars:600276:off800", fake.calls)  # --backfill 透传到 bars offset

    def test_invalid_ticker_argument_rejected(self) -> None:
        # M3：无后缀/海外票入参在 argparse 层拒绝（600276 会被拼成错市场的 .SZ）
        for bad in ("600276", "^SOX", "00700.HK"):
            with self.assertRaises(SystemExit, msg=bad):
                ums.main(["--tickers", bad, "--scope", "stocks"])

    def test_batch_overwrites_snapshot_written_intraday_row(self) -> None:
        # spec §9 端到端：钩子先写盘中价 → 批量权威覆盖为收盘价
        upsert_series_rows(
            series_file(self.root, "600276.SH"),
            [{"date": "2026-11-02", "open": None, "high": None, "low": None, "close": 70.01,
              "volume": None, "amount": None, "source": "mootdx"}], writer="snapshot")
        fake = FakeMootdx(bars=_bars_frame(["2026-11-02"], [71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            ums.run_stocks_update(self.root, tickers=["600276.SH"], latest="2026-11-03")
        row = read_series_rows(series_file(self.root, "600276.SH"))[-1]
        self.assertEqual(row["close"], 71.54)   # 盘中价被权威覆盖
        self.assertEqual(row["amount"], 8.0e7)  # null 被批量补齐

    def test_rerun_resumes_after_partial_failure(self) -> None:
        # spec §9 断点续传：首跑一票失败，重跑只补失败票、已成功票 skip
        stocks = _stocks_frame([("600276", "a"), ("300476", "b")])

        def bars_by_symbol(symbol: str):
            if symbol == "600276":
                raise RuntimeError("socket dead")
            return _bars_frame(["2026-11-02"], [71.54])

        with patch.object(ums, "_mootdx_call", FakeMootdx(stocks=stocks, bars=bars_by_symbol)):
            first = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(first, {"ok": 1, "skip": 0, "fail": 1})
        self.assertIsNone(ums.last_round_date(self.root, "stocks"))  # fail>0 不写标记（N1），同日补跑不被挡
        with patch.object(ums, "_mootdx_call",
                          FakeMootdx(stocks=stocks, bars=_bars_frame(["2026-11-02"], [71.54]))):
            second = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(second, {"ok": 1, "skip": 1, "fail": 0})
        self.assertEqual(ums.last_round_date(self.root, "stocks"), "2026-11-02")  # 补跑干净才写标记


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3.2: 跑红**

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pytest tests/test_update_market_series.py -v`
Expected: FAIL（`No module named 'update_market_series'`）

- [ ] **Step 3.3: 实现（stocks 部分 + CLI 骨架）**

```python
"""盘后批量：全市场个股 + 板块指数时序（spec §5.2）。

交易日闸门 → canary 一次调用拿服务器最新交易日，≤ data/.state/ 该 scope 完成标记
即整轮短路（非交易日「成本近零」靠这个成立）。批量=权威写者（三档合并的 batch 档）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from market_data_io import (
    atomic_write_text,
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
    尾部：not tickers and fail == 0 and latest is not None）。
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
            return float(val) if val is not None else None

        row = {"date": pd.Timestamp(ts).date().isoformat(), "open": num("open"), "high": num("high"),
               "low": num("low"), "close": num("close"), "volume": num("volume"),
               "amount": num("amount"), "source": source}
        if "up_count" in rec:  # index_bars 板块行（spec §4.2）
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
                 index: bool = False) -> None:
    method = "index_bars" if index else "bars"
    df = _mootdx_call(method, symbol=code, frequency=9, offset=backfill)
    if df is None or df.empty:
        return
    with series_lock(data_root, path.name) as acquired:
        if not acquired:
            return
        upsert_series_rows(path, bars_to_rows(df, source=source), writer="batch")


def run_stocks_update(data_root: Path, *, backfill: int = 30,
                      tickers: list[str] | None = None, latest: str | None = None) -> dict:
    stats = {"ok": 0, "skip": 0, "fail": 0}
    latest = latest or fetch_server_latest_trade_date()
    last_round = last_round_date(data_root, "stocks")
    if latest and last_round and latest <= last_round and not tickers:
        log(f"交易日闸门：服务器最新 {latest} ≤ 上轮批量 {last_round}，整轮跳过")
        return stats
    if tickers:
        targets = [(t.rsplit(".", 1)[0], 1 if t.upper().endswith(".SH") else 0) for t in tickers]
    else:
        targets = list_cn_symbols()
    for code, market in targets:
        path = series_file(data_root, normalize_cn_symbol(code, market))
        try:
            rows = read_series_rows(path)
            if rows and latest and rows[-1]["date"] >= latest:
                stats["skip"] += 1
                continue
            _upsert_bars(path, data_root, code, backfill, source="mootdx")
            stats["ok"] += 1
        except Exception as exc:  # noqa: BLE001 — 单票失败不中断
            stats["fail"] += 1
            log(f"Warning: {code} 更新失败: {exc}")
    log(f"stocks 汇总: {stats}")
    if not tickers and latest is not None and stats["fail"] == 0:
        write_round_marker(data_root, "stocks", latest)  # 干净全量轮才记完成（N1 补充点①）
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="盘后批量更新全市场/板块时序（spec §5.2）")
    parser.add_argument("--scope", choices=["stocks", "sectors", "all"], default="all")
    parser.add_argument("--backfill", type=int, default=30,
                        help="增量 bars 数；800=回补约 3.3 年（服务器单次上限）")
    parser.add_argument("--tickers", help="逗号分隔子集，调试用（如 600276.SH,300476.SZ）")
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
    if tickers and args.scope == "sectors":
        parser.error("--tickers 只对 --scope stocks/all 有效（板块是枚举制清单，无子集路径，静默丢弃比报错更糟）")
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    stats = run_stocks_update(data_root, backfill=args.backfill, tickers=tickers)
    # sectors 在 Task 4 接入：--scope sectors/all 时 run_sectors_update(...)
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3.4: 跑绿 + ruff**

Run: `$PY -m pytest tests/test_update_market_series.py -v && $PY -m ruff check tools/daily-watch/scripts/update_market_series.py tests/test_update_market_series.py`
Expected: PASS

- [ ] **Step 3.5: Commit**

```bash
git add tools/daily-watch/scripts/update_market_series.py tests/test_update_market_series.py
git commit -m "feat: 全市场行情盘后批量 update_market_series——交易日闸门/白名单/权威upsert"
```

---

### Task 4: 板块指数（sectors）

**Files:**
- Modify: `tools/daily-watch/scripts/update_market_series.py`（接入 `run_sectors_update` + CLI 分支）
- Test: `tests/test_update_market_series.py`（追加 SectorTests 类）

**Interfaces:**
- Consumes: Task 3 的 `fetch_server_latest_trade_date / last_round_date / write_round_marker / _upsert_bars / bars_to_rows`；Task 1 的 `sector_series_file`
- Produces:
  - `build_sector_list(stocks_df: pd.DataFrame) -> list[dict]`（`[{"code","name","category"}]`，880300≤code≤881999，显式 sort）
  - `load_or_merge_sector_list(data_root: Path, stocks_df) -> tuple[list[dict], list[dict]]`（返回 (现行清单, 新增项)；消失项保留在清单里只打日志=文件冻结）
  - `run_sectors_update(data_root: Path, *, backfill: int = 30, latest: str | None = None) -> dict`

- [ ] **Step 4.1: 写失败测试（追加到 tests/test_update_market_series.py）**

```python
class SectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stocks_sh(self, rows: list[tuple[str, str]]) -> pd.DataFrame:
        return _stocks_frame(rows)

    def test_build_sector_list_filters_ranges_and_sorts(self) -> None:
        df = self._stocks_sh([("888880", "新标准券"), ("880324", "概念A"), ("880301", "行业A"),
                              ("880300", "下边界"), ("880099", "风格统计"), ("881270", "二级A"),
                              ("881999", "二级Z"), ("882001", "超上界"), ("600276", "个股混入")])
        got = ums.build_sector_list(df)
        codes = [x["code"] for x in got]
        self.assertEqual(codes, ["880300", "880301", "880324", "881270", "881999"])  # 边界含+过滤+排序
        self.assertEqual(got[0]["category"], "行业/概念")
        self.assertEqual(got[3]["category"], "二级行业")

    def test_first_run_writes_sector_list(self) -> None:
        # C7：首跑分支必须落盘，否则清单永远不存在、冻结/补录全是死代码
        df = self._stocks_sh([("880301", "行业A"), ("880099", "被过滤")])
        merged, added = ums.load_or_merge_sector_list(self.root, df)
        self.assertEqual([x["code"] for x in merged], ["880301"])
        on_disk = json.loads((self.root / "sector" / "sector-list.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, merged)  # 落盘成功
        self.assertEqual([x["code"] for x in added], ["880301"])

    def test_merge_keeps_frozen_and_picks_up_new(self) -> None:
        (self.root / "sector").mkdir(parents=True)
        (self.root / "sector" / "sector-list.json").write_text(
            json.dumps([{"code": "880301", "name": "行业A", "category": "行业/概念"},
                        {"code": "880999", "name": "已消失", "category": "行业/概念"}], ensure_ascii=False),
            encoding="utf-8")
        df = self._stocks_sh([("880301", "行业A改名"), ("880324", "新概念")])
        merged, added = ums.load_or_merge_sector_list(self.root, df)
        codes = [x["code"] for x in merged]
        self.assertIn("880999", codes)  # 消失项保留（文件冻结，不删）
        self.assertEqual([x["code"] for x in added], ["880324"])
        by_code = {x["code"]: x for x in merged}
        self.assertEqual(by_code["880301"]["name"], "行业A")  # 已登记项不覆盖

    def test_sectors_update_upserts_index_bars_with_counts(self) -> None:
        (self.root / "sector").mkdir(parents=True)
        df = self._stocks_sh([("880301", "行业A")])
        with patch.object(ums, "load_or_merge_sector_list", return_value=(
                [df.iloc[0].to_dict() | {"category": "行业/概念"}], [])):
            index_df = _bars_frame(["2026-11-02"], [3300.0], up_count=[16], down_count=[15])
            fake = FakeMootdx(stocks=df, index_bars=index_df)  # stocks 必须给：清单前的枚举调用
            with patch.object(ums, "_mootdx_call", fake):
                stats = ums.run_sectors_update(self.root, latest="2026-11-03")
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})
        row = read_series_rows(sector_series_file(self.root, "880301"))[-1]
        self.assertEqual(row["source"], "mootdx-index")
        self.assertEqual(row["up_count"], 16)
        self.assertEqual(row["down_count"], 15)

    def test_sectors_gate_reads_own_marker_not_stocks(self) -> None:
        # N1 核心：stocks 完成标记不得挡 sectors——canary 方案的病根就是 scopes 共享一个标志位
        ums.write_round_marker(self.root, "stocks", "2026-11-03")
        df = self._stocks_sh([("880301", "行业A")])
        index_df = _bars_frame(["2026-11-03"], [3300.0], up_count=[16], down_count=[15])
        fake = FakeMootdx(stocks=df, index_bars=index_df)
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_sectors_update(self.root, latest="2026-11-03")
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})  # stocks 标记在，sectors 照跑
        self.assertEqual(ums.last_round_date(self.root, "sectors"), "2026-11-03")  # 干净轮写自己的标记

    def test_sectors_gate_short_circuits_on_own_marker(self) -> None:
        ums.write_round_marker(self.root, "sectors", "2026-11-03")
        fake = FakeMootdx(stocks=_stocks_frame([("880301", "行业A")]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_sectors_update(self.root, latest="2026-11-03")
        self.assertEqual(stats, {"ok": 0, "skip": 0, "fail": 0})  # 整轮零调用
        self.assertFalse(fake.calls)  # 连清单枚举的 stocks 调用都没有（闸门在枚举之前）


if __name__ == "__main__":
    unittest.main()
```

注意：`tests/test_update_market_series.py` 顶部要补 `import json`（Task 3 的测试文件还没 import）；文件尾已有 `if __name__ == "__main__"` 块，下面代码段只追加类、**勿重复**文件尾块。脚本侧本 Task 顶部 import 区只新增 `import json`（`atomic_write_text` 已在 Task 3 为完成标记引入）。

- [ ] **Step 4.2: 跑红**

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pytest tests/test_update_market_series.py -v`
Expected: FAIL（`AttributeError: ... has no attribute 'build_sector_list'`）

- [ ] **Step 4.3: 实现 sectors**

在 `update_market_series.py` 追加以下函数（`import json` 与 `from market_data_io import atomic_write_text` 加进文件顶部 import 区，不放函数体内；并把 `main` 里 sectors 分支接上）：

```python
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


def run_sectors_update(data_root: Path, *, backfill: int = 30, latest: str | None = None) -> dict:
    stats = {"ok": 0, "skip": 0, "fail": 0}
    latest = latest or fetch_server_latest_trade_date()
    last_round = last_round_date(data_root, "sectors")  # per-scope 标记：stocks 完成与否不影响本闸门（N1）
    if latest and last_round and latest <= last_round:
        log(f"交易日闸门（sectors）：服务器最新 {latest} ≤ 上轮批量 {last_round}，整轮跳过")
        return stats  # 非交易日零服务器调用（spec §9 补注）
    stocks_df = _mootdx_call("stocks", market=1)
    merged, _added = load_or_merge_sector_list(data_root, stocks_df)
    for item in merged:
        code = item["code"]
        path = sector_series_file(data_root, code)
        try:
            rows = read_series_rows(path)
            if rows and latest and rows[-1]["date"] >= latest:
                stats["skip"] += 1
                continue
            _upsert_bars(path, data_root, code, backfill, source="mootdx-index", index=True)
            stats["ok"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["fail"] += 1
            log(f"Warning: 板块 {code} 更新失败: {exc}")
    log(f"sectors 汇总: {stats}")
    if latest is not None and stats["fail"] == 0:
        write_round_marker(data_root, "sectors", latest)
    return stats
```

`main()` 里 `--scope` 分支改为：

```python
    stats = {"ok": 0, "skip": 0, "fail": 0}
    if args.scope in ("stocks", "all"):
        stats = run_stocks_update(data_root, backfill=args.backfill, tickers=tickers)
    if args.scope in ("sectors", "all"):
        sec = run_sectors_update(data_root, backfill=args.backfill)
        for key in stats:
            stats[key] += sec[key]
    return 1 if stats["fail"] else 0
```

- [ ] **Step 4.4: 跑绿 + ruff + 回归**

Run: `$PY -m pytest tests/test_update_market_series.py -v && $PY -m ruff check tools/daily-watch/scripts/update_market_series.py tests/test_update_market_series.py`
Expected: PASS（含 Task 3 用例无回归）

- [ ] **Step 4.5: Commit**

```bash
git add tools/daily-watch/scripts/update_market_series.py tests/test_update_market_series.py
git commit -m "feat: 板块指数时序——880/881 段白名单/清单合并冻结/up_down_count 入库"
```

---

### Task 5: 财务快照 `update_finance_snapshots.py`

**Files:**
- Create: `tools/daily-watch/scripts/update_finance_snapshots.py`
- Test: `tests/test_update_finance_snapshots.py`

**Interfaces:**
- Consumes: `mootdx.affair.Affair`（files/parse）、`mootdx.financial.financial.Financial.fetch_only`、Task 1 的 `atomic_write_text`
- Produces:
  - `COLUMN_MAP: dict[str, tuple[str, int]]`（json_key → (gpcw 列名, 出现序号)；spec §4.3 映射表，**按位置取数的实现**）
  - `files_with_fallback() -> tuple[list[dict], tuple[str, int] | None]`（默认 GP 通 → `(files, None)`；不通 → 用行情服务器 GP 兜底取列表，并返回 `(ip, port)` 供 run 级 `_affair_gp_bestip` 钉住 download/parse——只包住 files() 一次调用的兜底是假兜底，spec §12）
  - `download_gpcw(filename: str, downdir: Path) -> None`、`parse_gpcw(downdir: Path, filename: str) -> pd.DataFrame`（薄封装，测试 patch 点）
  - `column_positions(columns) -> dict[str, int]`（(列名, 出现序号) → 列位置；找不到 raise——布局变了必须炸）
  - `rows_from_dataframe(df: pd.DataFrame, report_date: str, file_hash: str) -> list[dict]`
  - `run_finance_update(data_root: Path, *, backfill: int | str = 0) -> dict`（`0`=只盯最新期、`12`=补 3 年、`"all"`=全历史）
  - CLI：`--backfill N|all`

- [ ] **Step 5.1: 写失败测试**

`tests/test_update_finance_snapshots.py`：

```python
"""update_finance_snapshots 单测。重名列 fixture 验证「按位置+出现序号取数」（spec §4.3）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from _test_paths import REPO_ROOT  # noqa: F401

import update_finance_snapshots as ufs  # noqa: E402

# 19 列 fixture：重名列（净资产收益率/归母/扣非 ×2）模拟 659 列真实结构的关键陷阱
_COLS = [
    "基本每股收益", "扣除非经常性损益每股收益", "每股净资产", "净资产收益率",          # 0-3（第一次出现）
    "其中：营业收入", "归属于母公司所有者的净利润", "扣除非经常性损益后的净利润",     # 4-6（累计）
    "存货", "货币资金", "资产总计", "负债合计",                                      # 7-10
    "营业收入增长率(%)", "净利润增长率(%)", "扣非净利润同比(%)",                     # 11-13
    "业绩预告-本期净利润同比增幅下限%", "业绩预告-本期净利润同比增幅上限%",           # 14-15
    "净资产收益率", "归属于母公司所有者的净利润", "扣除非经常性损益后的净利润",       # 16-18（第二次出现=单季）
]


def _fixture_df() -> pd.DataFrame:
    data = [
        [3.63, 3.759, 38.98, 8.832, 18460532736.0, 3383763712.0, 3694268928.0,
         9249440768.0, 10276478976.0, 71296745472.0, 32984334336.0,
         30.77, 4.28, 13.74, 0.0, 0.0, 8.832, 526984832.0, 1276468352.0],   # 300476
        [60.0, 61.0, 300.0, 30.0, 1e11, 2e10, 2.1e10, 3e10, 5e10, 3e11, 1e11,
         15.0, 16.0, 17.0, 25.0, 35.0, 30.0, 2e9, 2.1e9],                     # 600519
    ]
    return pd.DataFrame(data, index=["300476", "600519"], columns=_COLS)


class ColumnMappingTests(unittest.TestCase):
    def test_positions_pin_first_occurrence(self) -> None:
        pos = ufs.column_positions(_COLS)
        self.assertEqual(pos["roe"], 3)                    # 第一次（每股指标段）
        self.assertEqual(pos["net_profit_parent"], 5)      # 累计口径
        self.assertEqual(pos["net_profit_deducted"], 6)

    def test_missing_column_raises(self) -> None:
        with self.assertRaises(ValueError):
            ufs.column_positions(["别的列", "基本每股收益"])  # 其余映射键找不到

    def test_rows_take_cumulative_and_nullify_zero_forecast(self) -> None:
        rows = ufs.rows_from_dataframe(_fixture_df(), "2026-09-30", "deadbeef")
        row = next(r for r in rows if r["code"] == "300476")
        self.assertEqual(row["net_profit_parent"], 3383763712.0)  # 累计，不是单季 526984832
        self.assertEqual(row["net_profit_deducted"], 3694268928.0)
        self.assertIsNone(row["forecast_min"])                    # 0 视为无预告（spec §4.3）
        self.assertEqual(row["market"], "SZ")
        self.assertEqual(rows[1]["market"], "SH")                 # 600519 → SH
        self.assertEqual(row["file_hash"], "deadbeef")
        self.assertEqual(row["schema_version"], 1)


class FinanceFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.files = [
            {"filename": "gpcw20261231.zip", "hash": "future", "filesize": 164},       # 占位
            {"filename": "gpcw20260930.zip", "hash": "h1", "filesize": 5488120},       # 最新期
            {"filename": "gpcw20260630.zip", "hash": "h2", "filesize": 5300000},       # 上一期
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_hash_unchanged_skips_zero_download(self) -> None:
        meta = self.root / "finance"
        meta.mkdir()
        (meta / "_meta.json").write_text(
            json.dumps({"gpcw20260930.zip": {"hash": "h1", "rows": 5571}}), encoding="utf-8")
        with patch.object(ufs, "files_with_fallback", return_value=(self.files, None)), \
             patch.object(ufs, "download_gpcw") as dl, \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()):
            stats = ufs.run_finance_update(self.root)
        self.assertEqual(stats, {"ok": 0, "skip": 1, "fail": 0})
        dl.assert_not_called()  # 零下载

    def test_changed_hash_rewrites_period_and_meta(self) -> None:
        with patch.object(ufs, "files_with_fallback", return_value=(self.files, None)), \
             patch.object(ufs, "download_gpcw") as dl, \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()) as parse:
            stats = ufs.run_finance_update(self.root)
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})
        dl.assert_called_once()
        parse.assert_called_once()
        out = self.root / "finance" / "gpcw-2026-09-30.jsonl"
        rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x]
        self.assertEqual(len(rows), 2)
        meta = json.loads((self.root / "finance" / "_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["gpcw20260930.zip"]["hash"], "h1")
        self.assertEqual(meta["gpcw20260930.zip"]["rows"], 2)

    def test_backfill_all_processes_every_period(self) -> None:
        with patch.object(ufs, "files_with_fallback", return_value=(self.files, None)), \
             patch.object(ufs, "download_gpcw"), \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()):
            stats = ufs.run_finance_update(self.root, backfill="all")
        self.assertEqual(stats, {"ok": 2, "skip": 0, "fail": 0})  # 两期都处理，占位被过滤

    def test_gp_fallback_pins_bestip_and_restores(self) -> None:
        # gp_fallback≠None 主路径此前零覆盖（复查）：ctx 内 GP 被钉住、退出恢复原值
        from mootdx import config as mootdx_config

        mootdx_config.setup()
        saved = mootdx_config.get("BESTIP")
        with ufs._affair_gp_bestip("203.0.113.7", 7709):
            self.assertEqual(mootdx_config.get("BESTIP")["GP"], ("203.0.113.7", 7709))
        self.assertEqual(mootdx_config.get("BESTIP"), saved)

    def test_run_with_gp_fallback_routes_through_pinned_channel(self) -> None:
        with patch.object(ufs, "files_with_fallback",
                          return_value=(self.files, ("203.0.113.7", 7709))), \
             patch.object(ufs, "_affair_gp_bestip", wraps=ufs._affair_gp_bestip) as gp_ctx, \
             patch.object(ufs, "download_gpcw"), \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()):
            stats = ufs.run_finance_update(self.root)
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})
        gp_ctx.assert_called_once_with("203.0.113.7", 7709)  # download/parse 全程钉在兜底服务器

    def test_files_with_fallback_clean_error_when_both_channels_dead(self) -> None:
        # N5：负缓存窗口内 _get_mootdx_client 直接 raise——不得以 CLI traceback 收场
        with patch("mootdx.affair.Affair.files", side_effect=RuntimeError("default GP dead")), \
             patch.object(ufs, "_fallback_gp_server", side_effect=RuntimeError("全网负缓存")):
            with self.assertRaisesRegex(RuntimeError, "均不可用"):
                ufs.files_with_fallback()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5.2: 跑红**

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pytest tests/test_update_finance_snapshots.py -v`
Expected: FAIL（`No module named 'update_finance_snapshots'`）

- [ ] **Step 5.3: 实现**

```python
"""财务快照（spec §4.3/§5.3）：gpcw 按报告期一文件，hash 台账零下载探测。

列映射铁律：659 列=403 中文名+256 无名 colNN+9 组重名（各 ×2）——按(列名, 出现序号)
钉死列位置，禁止按列名取值；mootdx 布局变化时 column_positions 直接 raise。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from market_data_io import atomic_write_text
from mootdx_source import _MOOTDX_LOCK, _candidate_tdx_servers, _get_mootdx_client, log

COLUMN_MAP: dict[str, tuple[str, int]] = {
    "eps_basic": ("基本每股收益", 0),
    "eps_deducted": ("扣除非经常性损益每股收益", 0),
    "bps": ("每股净资产", 0),
    "roe": ("净资产收益率", 0),                                  # 第一次出现=每股指标段
    "revenue": ("其中：营业收入", 0),                            # 累计口径（非后段单季「营业收入」）
    "net_profit_parent": ("归属于母公司所有者的净利润", 0),      # 第一次=累计
    "net_profit_deducted": ("扣除非经常性损益后的净利润", 0),    # 第一次=累计
    "inventory": ("存货", 0),
    "monetary_funds": ("货币资金", 0),
    "total_assets": ("资产总计", 0),
    "total_liabilities": ("负债合计", 0),
    "revenue_yoy": ("营业收入增长率(%)", 0),
    "net_profit_yoy": ("净利润增长率(%)", 0),
    "deducted_yoy": ("扣非净利润同比(%)", 0),
    "forecast_min": ("业绩预告-本期净利润同比增幅下限%", 0),
    "forecast_max": ("业绩预告-本期净利润同比增幅上限%", 0),
}

_PLACEHOLDER_MAX_BYTES = 1024 * 1024  # 未来期 164B 占位空壳，>1MB 才是真文件（spec §12）
_MARKET_BY_FIRST_CHAR = {"6": "SH", "0": "SZ", "3": "SZ", "4": "BJ", "8": "BJ", "9": "BJ"}


@contextmanager
def _affair_gp_bestip(ip: str, port: int):
    """整 run 级把 GP 文件服务钉到已验证服务器（files/download/parse 共用一条通道）。

    BaseFinancial.__init__ 读 config.get('BESTIP')['GP']（financial/base.py:44）——
    run 级 set 覆盖全链，finally 恢复原值。0.11.7 的 config.set 只改内存不落盘
    （mootdx_source._preserve_mootdx_bestip 同款机制与结论），不污染后续行情连接。
    """
    from mootdx import config as mootdx_config

    mootdx_config.setup()
    saved = mootdx_config.get("BESTIP")
    merged = dict(saved) if isinstance(saved, dict) else {}
    merged["GP"] = (ip, int(port))
    mootdx_config.set("BESTIP", merged)
    try:
        yield
    finally:
        mootdx_config.set("BESTIP", saved)  # setup() 后 BESTIP 恒有值，无条件恢复原值


def _fallback_gp_server() -> tuple[str, int]:
    """已验证可用的行情服务器。client.server 是当前真实连接那台（mootdx_source:232
    显式传 server 构造）；裸 factory 分支 server=None（valid_server(None)），退回
    精选表头名（探测维持的优先表）。⚠️ 不能用 client.bestip——那是 BaseQuotes 的
    类属性 None，解包直接 TypeError。持 `_MOOTDX_LOCK` 再取单例（mootdx_source:188
    契约：调用方必须已持锁）；负缓存窗口内 _get_mootdx_client 会 raise，由
    files_with_fallback 收敛成干净报错。"""
    with _MOOTDX_LOCK:
        server = getattr(_get_mootdx_client(), "server", None)
    return tuple(server) if server else _candidate_tdx_servers()[0]


def files_with_fallback() -> tuple[list[dict], tuple[str, int] | None]:
    """默认 GP 通 → (files, None)；不通 → (经行情服务器取得的 files, (ip, port))。"""
    from mootdx.affair import Affair

    try:
        files = Affair.files()
        if files:
            return files, None
    except Exception as exc:  # noqa: BLE001
        log(f"Warning: Affair 默认 bestip 失败，改用行情服务器 GP 兜底: {exc}")
    try:
        ip_port = _fallback_gp_server()
        with _affair_gp_bestip(*ip_port):
            return (Affair.files() or []), ip_port
    except Exception as exc:  # noqa: BLE001 — 兜底也可能全灭（如全网负缓存窗口），收敛成干净报错
        raise RuntimeError("财务快照中止：Affair 默认通道与行情服务器兜底均不可用"
                           "（可能是全网负缓存窗口，稍后重试）") from exc


def download_gpcw(filename: str, downdir: Path) -> None:
    from mootdx.financial.financial import Financial  # financial/__init__.py 是 0 字节

    Financial().fetch_only(filename=filename, downdir=str(downdir))


def parse_gpcw(downdir: Path, filename: str) -> pd.DataFrame:
    from mootdx.affair import Affair

    return Affair.parse(downdir=str(downdir), filename=filename)


def column_positions(columns) -> dict[str, int]:
    """(列名, 出现序号) → 列位置。映射键找不到就 raise——静默错列比崩溃更糟。"""
    positions: dict[str, int] = {}
    for key, (name, occurrence) in COLUMN_MAP.items():
        hits = [i for i, col in enumerate(columns) if col == name]
        if len(hits) <= occurrence:
            raise ValueError(f"列映射失败: {key} <- '{name}'#{occurrence}（实际出现 {len(hits)} 次）"
                             "——mootdx gpcw 布局可能已变化")
        positions[key] = hits[occurrence]
    return positions


def rows_from_dataframe(df: pd.DataFrame, report_date: str, file_hash: str) -> list[dict]:
    pos = column_positions(df.columns)
    rows: list[dict] = []
    for code, record in df.iterrows():
        code = str(code).zfill(6)

        def val(key: str) -> float | None:
            raw = record.iloc[pos[key]]
            return None if pd.isna(raw) else float(raw)

        def forecast(key: str) -> float | None:
            raw = val(key)
            return None if raw == 0 else raw  # 0 视为无预告（spec §4.3）

        rows.append({
            "code": code,
            "market": _MARKET_BY_FIRST_CHAR.get(code[0], "SZ"),
            "report_date": report_date,
            **{key: val(key) for key in COLUMN_MAP if not key.startswith("forecast")},
            "forecast_min": forecast("forecast_min"),
            "forecast_max": forecast("forecast_max"),
            "file_hash": file_hash,
            "schema_version": 1,
        })
    return rows


def _report_date_from(filename: str) -> str:
    match = re.match(r"gpcw(\d{8})\.zip", filename)
    if not match:
        raise ValueError(f"非 gpcw 文件名: {filename}")
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def run_finance_update(data_root: Path, *, backfill: int | str = 0) -> dict:
    stats = {"ok": 0, "skip": 0, "fail": 0}
    finance_dir = data_root / "finance"
    raw_dir = finance_dir / "_raw"
    finance_dir.mkdir(parents=True, exist_ok=True)  # Financial.content 是裸 open()，目录必须先在
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_files, gp_fallback = files_with_fallback()
    files = [f for f in raw_files if f["filesize"] > _PLACEHOLDER_MAX_BYTES]
    files.sort(key=lambda x: x["filename"], reverse=True)  # 最新期在前
    count = len(files) if backfill == "all" else max(int(backfill), 1)
    targets = files[:count]
    log(f"财务快照：非占位 {len(files)} 期，本次处理 {len(targets)} 期（backfill={backfill}）")

    meta_path = finance_dir / "_meta.json"
    meta: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    gp_ctx = _affair_gp_bestip(*gp_fallback) if gp_fallback else contextlib.nullcontext()
    with gp_ctx:  # 默认 GP 不通时，download/parse 也钉在已验证服务器上（I3）
        for item in targets:
            filename = item["filename"]
            try:
                if meta.get(filename, {}).get("hash") == item["hash"]:
                    stats["skip"] += 1
                    continue
                download_gpcw(filename, raw_dir)
                df = parse_gpcw(raw_dir, filename)
                rows = rows_from_dataframe(df, _report_date_from(filename), item["hash"])
                atomic_write_text(
                    finance_dir / f"gpcw-{_report_date_from(filename)}.jsonl",
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
                meta[filename] = {"hash": item["hash"], "rows": len(rows),
                                  "fetched_at": datetime.now(timezone.utc).isoformat()}
                atomic_write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=1))
                stats["ok"] += 1
                log(f"财务快照 {filename}: {len(rows)} 行写入")
            except Exception as exc:  # noqa: BLE001
                stats["fail"] += 1
                log(f"Warning: {filename} 处理失败: {exc}")
    log(f"财务汇总: {stats}")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="gpcw 财务快照盘后检查（spec §5.3）")
    parser.add_argument("--backfill", default="0", help="期数 N 或 all；默认 0=只盯最新期")
    args = parser.parse_args(argv)
    backfill: int | str = args.backfill if args.backfill == "all" else int(args.backfill)
    from market_data_io import resolve_data_root

    try:
        stats = run_finance_update(resolve_data_root(), backfill=backfill)
    except RuntimeError as exc:  # 双通道全灭的干净收口（N5）：log + 退出码 1，不出 CLI traceback
        log(f"Error: {exc}")
        return 1
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5.4: 跑绿 + ruff**

Run: `$PY -m pytest tests/test_update_finance_snapshots.py -v && $PY -m ruff check tools/daily-watch/scripts/update_finance_snapshots.py tests/test_update_finance_snapshots.py`
Expected: PASS

- [ ] **Step 5.5: Commit**

```bash
git add tools/daily-watch/scripts/update_finance_snapshots.py tests/test_update_finance_snapshots.py
git commit -m "feat: 财务快照 update_finance_snapshots——hash 零下载探测/占位过滤/按位置列映射"
```

---

### Task 6: 自定义序列 `save_custom_data.py`

**Files:**
- Create: `tools/daily-watch/scripts/save_custom_data.py`
- Test: `tests/test_save_custom_data.py`

**Interfaces:**
- Consumes: Task 1 `atomic_write_text` / `resolve_data_root`
- Produces:
  - `append_record(data_root, *, series, name, date, value, unit, source, period=None, note=None, overwrite=False) -> Path`（同 (series,date) 默认 `ValueError`；`--overwrite` 才覆盖——人工数据不可静默重写，spec §5.4）
  - `list_series(data_root) -> dict`（registry）
  - `show_series(data_root, series, tail=None) -> list[dict]`
  - `import_csv(data_root, series, csv_path, *, overwrite=False) -> dict`（`{"imported": n, "skipped": m}`）
  - CLI 子命令：`append` / `list` / `show` / `csv-import`

- [ ] **Step 6.1: 写失败测试**

`tests/test_save_custom_data.py`：

```python
"""save_custom_data 单测。语义与行情层相反：默认拒绝覆盖（spec §5.4）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401

import save_custom_data as scd  # noqa: E402


class CustomSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_registers_and_records(self) -> None:
        scd.append_record(self.root, series="korea-semi-export", name="韩国半导体出口",
                          date="2026-11-01", period="2026-10", value=275.0,
                          unit="亿美元", source="韩国关税厅 1-20 日初步")
        registry = json.loads((self.root / "custom" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["korea-semi-export"]["unit"], "亿美元")
        rows = scd.show_series(self.root, "korea-semi-export")
        self.assertEqual(rows[0]["period"], "2026-10")
        self.assertIn("recorded_at", rows[0])
        self.assertIsNone(rows[0].get("note"))

    def test_duplicate_rejected_unless_overwrite(self) -> None:
        kwargs = dict(series="x", name="X", date="2026-11-01", value=1.0,
                      unit="件", source="s")
        scd.append_record(self.root, **kwargs)
        with self.assertRaises(ValueError):
            scd.append_record(self.root, **dict(kwargs, value=2.0))  # kwargs 已含 value，必须 dict 覆盖而非重复传参
        scd.append_record(self.root, **dict(kwargs, value=2.0), overwrite=True)
        self.assertEqual(scd.show_series(self.root, "x")[-1]["value"], 2.0)
        self.assertEqual(len(scd.show_series(self.root, "x")), 1)  # 覆盖不追加

    def test_csv_import_maps_columns_and_skips_existing(self) -> None:
        scd.append_record(self.root, series="x", name="X", date="2026-10-01",
                          value=9.0, unit="件", source="seed")
        csv = self.root / "in.csv"
        csv.write_text("date,period,value,unit,source,note,junk\n"
                       "2026-09-01,2026-09,3.0,件,s1,n1,忽略我\n"
                       "2026-10-01,,9.5,件,s2,,撞已有\n"
                       ",,坏行没日期,,,\n"
                       "2026-08-01,,不是数,件,s3,,\n", encoding="utf-8")
        stats = scd.import_csv(self.root, "x", csv)
        self.assertEqual(stats, {"imported": 1, "skipped": 3})
        rows = {r["date"]: r for r in scd.show_series(self.root, "x")}
        self.assertEqual(rows["2026-10-01"]["value"], 9.0)   # 撞已有跳过，没被改
        self.assertEqual(rows["2026-09-01"]["period"], "2026-09")
        self.assertNotIn("junk", rows["2026-09-01"])         # 其余列忽略


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6.2: 跑红**

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pytest tests/test_save_custom_data.py -v`
Expected: FAIL（`No module named 'save_custom_data'`）

- [ ] **Step 6.3: 实现**

```python
"""自定义数值序列（spec §4.4/§5.4）：人与 agent 共用入口。

date=真实日期（记录/发布日），period=数据所属期（可选）——月度数据不硬编假日期。
与行情层语义相反：同 (series,date) 默认拒绝，--overwrite 显式覆盖。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_data_io import atomic_write_text
from mootdx_source import log

_CSV_FIELDS = ("date", "period", "value", "unit", "source", "note")


def _series_path(data_root: Path, series: str) -> Path:
    return data_root / "custom" / f"{series}.jsonl"


def _load_registry(data_root: Path) -> dict:
    path = data_root / "custom" / "registry.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_registry(data_root: Path, registry: dict) -> None:
    atomic_write_text(data_root / "custom" / "registry.json",
                      json.dumps(registry, ensure_ascii=False, indent=1))


def _load_rows(data_root: Path, series: str) -> list[dict[str, Any]]:
    path = _series_path(data_root, series)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def append_record(data_root: Path, *, series: str, name: str, date: str, value: float,
                  unit: str, source: str, period: str | None = None,
                  note: str | None = None, overwrite: bool = False) -> Path:
    registry = _load_registry(data_root)
    if series not in registry:  # 首次自动注册
        registry[series] = {"name": name, "unit": unit, "category": "", "description": "",
                            "created_at": datetime.now(timezone.utc).isoformat()}
        _save_registry(data_root, registry)
    rows = _load_rows(data_root, series)
    record = {"date": date, "period": period, "value": float(value), "unit": unit,
              "source": source, "note": note,
              "recorded_at": datetime.now(timezone.utc).isoformat()}
    hit = [i for i, r in enumerate(rows) if r["date"] == date]
    if hit and not overwrite:
        raise ValueError(f"{series} 已有 {date} 的记录（value={rows[hit[0]]['value']}）；"
                         "人工数据不可静默重写，确认后用 --overwrite")
    if hit:
        rows[hit[0]] = record
    else:
        rows.append(record)
    rows.sort(key=lambda r: r["date"])
    path = _series_path(data_root, series)
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return path


def list_series(data_root: Path) -> dict:
    return _load_registry(data_root)


def show_series(data_root: Path, series: str, tail: int | None = None) -> list[dict]:
    rows = _load_rows(data_root, series)
    return rows[-tail:] if tail else rows


def import_csv(data_root: Path, series: str, csv_path: Path, *, overwrite: bool = False) -> dict:
    stats = {"imported": 0, "skipped": 0}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            record = {key: (raw.get(key) or None) for key in _CSV_FIELDS}
            if not record["date"] or record["value"] in (None, ""):
                stats["skipped"] += 1  # 空 date/value 是坏行：跳过计数，不写毒行、不炸整批
                continue
            try:
                append_record(data_root, series=series, name=series, date=record["date"],
                              value=float(record["value"]), unit=record["unit"] or "",
                              source=record["source"] or "", period=record["period"],
                              note=record["note"], overwrite=overwrite)
                stats["imported"] += 1
            except (ValueError, TypeError):
                stats["skipped"] += 1
    log(f"csv-import {series}: {stats}")
    return stats


def main(argv: list[str] | None = None) -> int:
    from market_data_io import resolve_data_root

    parser = argparse.ArgumentParser(description="自定义数值序列存储（spec §5.4）")
    sub = parser.add_subparsers(dest="command", required=True)
    p_append = sub.add_parser("append")
    p_append.add_argument("--series", required=True)
    p_append.add_argument("--name", required=True)
    p_append.add_argument("--date", required=True)
    p_append.add_argument("--value", type=float, required=True)
    p_append.add_argument("--unit", required=True)
    p_append.add_argument("--source", required=True)
    p_append.add_argument("--period")
    p_append.add_argument("--note")
    p_append.add_argument("--overwrite", action="store_true")
    sub.add_parser("list")  # 无参数子命令，不得赋值（F841）
    p_show = sub.add_parser("show")
    p_show.add_argument("--series", required=True)
    p_show.add_argument("--tail", type=int)
    p_csv = sub.add_parser("csv-import")
    p_csv.add_argument("--series", required=True)
    p_csv.add_argument("--file", required=True)
    p_csv.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    data_root = resolve_data_root()

    if args.command == "append":
        path = append_record(data_root, series=args.series, name=args.name, date=args.date,
                             value=args.value, unit=args.unit, source=args.source,
                             period=args.period, note=args.note, overwrite=args.overwrite)
        print(path)
    elif args.command == "list":
        print(json.dumps(list_series(data_root), ensure_ascii=False, indent=1))
    elif args.command == "show":
        print(json.dumps(show_series(data_root, args.series, args.tail),
                         ensure_ascii=False, indent=1))
    else:
        print(json.dumps(import_csv(data_root, args.series, Path(args.file),
                                    overwrite=args.overwrite), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6.4: 跑绿 + ruff + Commit**

Run: `$PY -m pytest tests/test_save_custom_data.py -v && $PY -m ruff check tools/daily-watch/scripts/save_custom_data.py tests/test_save_custom_data.py`
Expected: PASS

```bash
git add tools/daily-watch/scripts/save_custom_data.py tests/test_save_custom_data.py
git commit -m "feat: 自定义数值序列 save_custom_data——registry 自动注册/拒绝静默覆盖/csv-import"
```

---

### Task 7: 新闻快照 `save_news_snapshot.py`

**Files:**
- Create: `tools/daily-watch/scripts/save_news_snapshot.py`
- Test: `tests/test_save_news_snapshot.py`

**Interfaces:**
- Consumes: Task 1 `atomic_write_text`
- Produces:
  - `normalize_url(url: str) -> str`（scheme/host 小写、去 fragment、去 utm_* 参数、去尾斜杠）
  - `dedup_key(url: str) -> str`（normalize 后 md5 hex）
  - `find_existing(data_root: Path, url: str) -> Path | None`（扫 `data/news/**/*.md` frontmatter 的 dedup 字段）
  - `save_snapshot(data_root: Path, *, url: str, title: str, date: str, slug: str, input_path: Path, partial: bool = False) -> tuple[Path, str]`（返回 `(落盘路径, "saved"|"skipped")`；同日同 slug 撞名不同 URL → 文件名追加 md5 前 6 位）
  - CLI：`--url --title --date --slug --input [--partial]`

- [ ] **Step 7.1: 写失败测试**

`tests/test_save_news_snapshot.py`：

```python
"""save_news_snapshot 单测：URL 规范化 dedup、撞名后缀、partial 标记。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401

import save_news_snapshot as snp  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_dedup_equivalent_urls_share_key(self) -> None:
        a = "HTTPS://Example.com/News/Article/?utm_source=x&id=1#top"
        b = "https://example.com/News/Article?id=1"
        self.assertEqual(snp.normalize_url(a), snp.normalize_url(b))
        self.assertNotEqual(snp.dedup_key(a), snp.dedup_key("https://example.com/other"))


class SaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.body = self.root / "raw.md"
        self.body.write_text("标题党正文第一行。\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _save(self, url: str, slug: str = "tsmc-oct", **over):
        kwargs = dict(url=url, title="台积电 10 月营收", date="2026-11-10",
                      slug=slug, input_path=self.body)
        kwargs.update(over)
        return snp.save_snapshot(self.root, **kwargs)

    def test_save_then_dedup_skip(self) -> None:
        path, status = self._save("https://example.com/a?utm_source=rss")
        self.assertEqual(status, "saved")
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("dedup:", text)
        self.assertIn("台积电", text)          # frontmatter title
        self.assertIn("标题党正文第一行。", text)  # 原文保留
        again, status2 = self._save("https://example.com/a")  # 规范化后同 URL
        self.assertEqual(status2, "skipped")
        self.assertEqual(again, path)

    def test_same_slug_different_url_gets_hash_suffix(self) -> None:
        self._save("https://example.com/a", slug="dup")
        path2, status = self._save("https://example.com/b", slug="dup")
        self.assertEqual(status, "saved")
        self.assertNotEqual(path2.name, "2026-11-10-dup.md")
        self.assertIn("2026-11-10-dup-", path2.name)

    def test_partial_flag(self) -> None:
        path, _ = self._save("https://example.com/x", partial=True)
        self.assertIn("partial: true", path.read_text(encoding="utf-8"))

    def test_path_escape_slug_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._save("https://example.com/e", slug="../../evil")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7.2: 跑红**

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pytest tests/test_save_news_snapshot.py -v`
Expected: FAIL（`No module named 'save_news_snapshot'`）

- [ ] **Step 7.3: 实现**

```python
"""新闻原文快照（spec §4.5/§5.5）：markdown = frontmatter + 原文全文，URL 规范化 dedup。

agent 先抓原文存临时文件，本脚本只负责规范化落盘——不抓网页（抓取在日报 agent 流程里）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from market_data_io import atomic_write_text


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
              if not k.lower().startswith("utm_")]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def dedup_key(url: str) -> str:
    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()


def _frontmatter_field(text: str, field: str) -> str | None:
    match = re.search(rf"^{field}: (.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def find_existing(data_root: Path, url: str) -> Path | None:
    key = dedup_key(url)
    news_dir = data_root / "news"
    if not news_dir.exists():
        return None
    for path in sorted(news_dir.rglob("*.md")):
        if _frontmatter_field(path.read_text(encoding="utf-8"), "dedup") == key:
            return path
    return None


def save_snapshot(data_root: Path, *, url: str, title: str, date: str, slug: str,
                  input_path: Path, partial: bool = False) -> tuple[Path, str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError(f"slug 只接受 kebab-case（小写字母数字连字符）: {slug!r}")  # 防路径逃逸
    existing = find_existing(data_root, url)
    if existing:
        return existing, "skipped"
    out_dir = data_root / "news" / date[:4] / date[5:7]
    filename = f"{date}-{slug}.md"
    target = out_dir / filename
    if target.exists():  # 同日同 slug、不同 URL → md5 前 6 位后缀保唯一
        target = out_dir / f"{date}-{slug}-{dedup_key(url)[:6]}.md"
    body = input_path.read_text(encoding="utf-8")
    frontmatter = (
        "---\n"
        f"url: {url}\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"fetched_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"dedup: {dedup_key(url)}\n"
        f"partial: {'true' if partial else 'false'}\n"
        "---\n\n"
    )
    atomic_write_text(target, frontmatter + body)
    return target, "saved"


def main(argv: list[str] | None = None) -> int:
    from market_data_io import resolve_data_root

    parser = argparse.ArgumentParser(description="新闻原文快照落盘（spec §5.5）")
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--input", required=True, help="已抓取的原文 markdown 临时文件")
    parser.add_argument("--partial", action="store_true", help="标记不完整抓取")
    args = parser.parse_args(argv)
    path, status = save_snapshot(resolve_data_root(), url=args.url, title=args.title,
                                 date=args.date, slug=args.slug,
                                 input_path=Path(args.input), partial=args.partial)
    print(f"{status}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7.4: 跑绿 + ruff + Commit**

Run: `$PY -m pytest tests/test_save_news_snapshot.py -v && $PY -m ruff check tools/daily-watch/scripts/save_news_snapshot.py tests/test_save_news_snapshot.py`
Expected: PASS

```bash
git add tools/daily-watch/scripts/save_news_snapshot.py tests/test_save_news_snapshot.py
git commit -m "feat: 新闻原文快照 save_news_snapshot——URL 规范化 dedup/撞名后缀/partial"
```

---

### Task 8: DuckDB 查询层 `query_market.py`（含 duckdb 安装）

**Files:**
- Create: `tools/daily-watch/scripts/query_market.py`、`tools/daily-watch/requirements-market-data.txt`
- Test: `tests/test_query_market.py`

**Interfaces:**
- Consumes: Task 1-7 落盘的目录结构；`save_custom_data.show_series`
- Produces:
  - `ensure_view(con, data_root: Path, view: str) -> None`（按需建视图；无数据文件 raise RuntimeError 指向对应 update 脚本——I1）
  - 常量 `_VIEW_PATTERNS`（四视图 → glob 模式；视图名 `market_quotes` / `sector_index` / `finance` / `custom_series`，均带 `filename` 列）
  - `_view_for(ticker) -> str`（裸 6 位→`sector_index`，其余→`market_quotes`，I8 路由）
  - `query_quote(con, data_root, ticker) -> dict | None`、`query_range(con, data_root, ticker, start, end) -> list[dict]`
  - `query_finance(con, data_root, code, last=4) -> list[dict]`
  - `sector_top(con, data_root, top=20) -> list[dict]`（最后一日 vs 前一日涨跌幅）
  - `run_sql(con, sql) -> list[dict]`
  - CLI：`quote / range / finance / sector / custom / sql`；duckdb 未装 → exit 2 并指向 requirements-market-data.txt（不降级，spec §5.6）

- [ ] **Step 8.1: 装 duckdb + 写 requirements**

`tools/daily-watch/requirements-market-data.txt`：

```
# 查询层唯一额外依赖（spec §7）；批量更新脚本不 import duckdb
duckdb>=1.0
```

Run: `PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python && $PY -m pip install -r tools/daily-watch/requirements-market-data.txt`
Expected: 安装成功（`$PY -c "import duckdb; print(duckdb.__version__)"` 出版本号）

- [ ] **Step 8.2: 写失败测试**

`tests/test_query_market.py`：

```python
"""query_market 单测：fixture 目录树上的 DuckDB 视图查询（duckdb 未装则整文件 skip）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


def _make_tree(root: Path) -> None:
    (root / "market" / "series").mkdir(parents=True)
    (root / "market" / "series" / "600276.SH.jsonl").write_text(
        '{"date": "2026-11-03", "open": 71.0, "high": 73.0, "low": 70.5, "close": 72.0, "volume": 100.0, "amount": 7200000.0, "source": "mootdx"}\n'
        '{"date": "2026-11-04", "open": 72.0, "high": 74.0, "low": 71.5, "close": 73.0, "volume": 110.0, "amount": 8000000.0, "source": "mootdx"}\n',
        encoding="utf-8")
    (root / "sector" / "series").mkdir(parents=True)
    (root / "sector" / "series" / "880301.jsonl").write_text(
        '{"date": "2026-11-03", "close": 3300.0, "up_count": 16, "down_count": 15, "source": "mootdx-index"}\n'
        '{"date": "2026-11-04", "close": 3333.0, "up_count": 20, "down_count": 10, "source": "mootdx-index"}\n',
        encoding="utf-8")
    (root / "sector" / "series" / "881270.jsonl").write_text(
        '{"date": "2026-11-03", "close": 1000.0, "source": "mootdx-index"}\n'
        '{"date": "2026-11-04", "close": 990.0, "source": "mootdx-index"}\n',
        encoding="utf-8")
    (root / "finance").mkdir(parents=True)
    (root / "finance" / "gpcw-2026-09-30.jsonl").write_text(
        '{"code": "300476", "market": "SZ", "report_date": "2026-09-30", "eps_basic": 3.63, "revenue_yoy": 30.77, "file_hash": "h1", "schema_version": 1}\n',
        encoding="utf-8")
    (root / "finance" / "gpcw-2026-06-30.jsonl").write_text(  # 跨期 glob
        '{"code": "300476", "market": "SZ", "report_date": "2026-06-30", "eps_basic": 2.1, "revenue_yoy": 25.0, "file_hash": "h0", "schema_version": 1}\n',
        encoding="utf-8")
    (root / "custom").mkdir(parents=True)
    (root / "custom" / "korea-semi-export.jsonl").write_text(
        '{"date": "2026-10-21", "period": "2026-10", "value": 275.0, "unit": "亿美元", "source": "s"}\n',
        encoding="utf-8")
    (root / "custom" / "registry.json").write_text("{}", encoding="utf-8")  # 非 jsonl，不该进视图


@unittest.skipUnless(HAS_DUCKDB, "duckdb 未安装")
class QueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make_tree(self.root)
        self.con = duckdb.connect(":memory:")
        import query_market as qm

        self.qm = qm

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_quote_and_range(self) -> None:
        got = self.qm.query_quote(self.con, self.root, "600276.SH")
        self.assertEqual(got["close"], 73.0)
        rows = self.qm.query_range(self.con, self.root, "600276.SH", "2026-11-01", "2026-11-03")
        self.assertEqual([r["date"] for r in rows], ["2026-11-03"])

    def test_quote_routes_bare_code_to_sector(self) -> None:
        # I8：裸 6 位 = 板块代码 → sector_index 视图（spec §5.6 自动路由）
        got = self.qm.query_quote(self.con, self.root, "880301")
        self.assertEqual(got["close"], 3333.0)
        self.assertEqual(got["up_count"], 20)

    def test_finance_orders_across_periods(self) -> None:
        rows = self.qm.query_finance(self.con, self.root, "300476", last=4)
        self.assertEqual([r["report_date"] for r in rows], ["2026-09-30", "2026-06-30"])  # 跨期倒序
        self.assertEqual(rows[0]["revenue_yoy"], 30.77)

    def test_sector_top_orders_by_pct(self) -> None:
        rows = self.qm.sector_top(self.con, self.root, top=10)
        self.assertEqual(rows[0]["code"], "880301")  # +1.0% 在前
        self.assertAlmostEqual(rows[0]["pct_change"], 1.0)
        self.assertEqual(rows[1]["code"], "881270")  # -1.0%
        self.assertEqual(rows[0]["up_count"], 20)

    def test_sql_view_excludes_registry(self) -> None:
        for view in self.qm._VIEW_PATTERNS:  # sql 语义：能建的都建
            try:
                self.qm.ensure_view(self.con, self.root, view)
            except RuntimeError:
                pass
        rows = self.qm.run_sql(self.con, "SELECT count(*) AS n FROM custom_series")
        self.assertEqual(rows[0]["n"], 1)  # registry.json 没混进来

    def test_missing_dir_raises_clear_error(self) -> None:
        # I1：残缺目录树（如 Step 11.1 时 finance/ 尚未生成）必须报清晰错误而非 DuckDB IO Error
        empty = self.root / "empty-tree"
        empty.mkdir()
        with self.assertRaises(RuntimeError):
            self.qm.ensure_view(self.con, empty, "finance")

    def test_torn_tail_tolerated(self) -> None:
        # M11：read_json_auto 需 ignore_errors=true 才容忍 torn 尾行（默认坏行报错）
        market_file = self.root / "market" / "series" / "600276.SH.jsonl"
        market_file.write_text(market_file.read_text(encoding="utf-8") + '{"date": "2026-11-05", "clo',
                               encoding="utf-8")
        rows = self.qm.query_range(self.con, self.root, "600276.SH", "2026-11-01", "2026-12-31")
        self.assertEqual([r["date"] for r in rows], ["2026-11-03", "2026-11-04"])  # 半行被跳过


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8.3: 跑红**

Run: `$PY -m pytest tests/test_query_market.py -v`
Expected: FAIL（`No module named 'query_market'`）

- [ ] **Step 8.4: 实现**

> 注：e2e N4 修正（commit 8de008b）——duckdb 2.0 下 union_by_name 对数千文件逐文件 schema 并集探测会 OOM，实际落地为 glob 串 + 去 union + 保留存在性预检与 ignore_errors；下块为 v3 定稿原文留档。

```python
"""DuckDB 查询层（spec §5.6）——四个具名视图，唯一 import duckdb 的组件。

规模预期：~7000 文件 / ~450 万行全扫 Apple Silicon 秒级；视图按需创建
（ensure_view），torn 尾行靠 ignore_errors=true 跳过（原子写把概率压到最低）。
缺 duckdb 时 exit 2 指向 requirements，不降级。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from mootdx_source import log


def _require_duckdb():
    try:
        import duckdb

        return duckdb
    except ImportError:
        log("Error: duckdb 未安装。安装：python -m pip install -r tools/daily-watch/requirements-market-data.txt")
        sys.exit(2)


_VIEW_PATTERNS = {
    "market_quotes": "market/series/*.jsonl",
    "sector_index": "sector/series/*.jsonl",
    "finance": "finance/gpcw-*.jsonl",
    "custom_series": "custom/*.jsonl",  # registry.json 不是 .jsonl，天然排除
}


def ensure_view(con, data_root: Path, view: str) -> None:
    """按需建视图（I1）：目录还没有数据文件就 raise RuntimeError——DuckDB 对空 glob
    直接 IO Error，e2e 早期（finance/ 未生成时查行情）会当场崩。

    传显式文件列表而非 glob 串；ignore_errors=true 容忍 torn 尾行（M11：DuckDB
    默认对坏行报错，靠该参数跳过；原子写已把概率压到最低）。
    ⚠️ 已知验点（N4）：全量后 market_quotes 的显式列表 ~7000 文件（~0.5MB SQL
    字面量），DuckDB 该规模的解析未实证——11.8 首次全量查询是真实检验；若失败/
    超慢，退回「glob 串 + 保留存在性预检」方案并补 commit。
    """
    files = sorted(data_root.glob(_VIEW_PATTERNS[view]))
    if not files:
        raise RuntimeError(
            f"{view} 无数据文件（{data_root / _VIEW_PATTERNS[view]}）——先跑对应的 update/append 脚本")
    listing = ", ".join(f"'{f.resolve()}'" for f in files)
    con.execute(
        f"CREATE OR REPLACE VIEW {view} AS "
        f"SELECT * FROM read_json_auto([{listing}], union_by_name=true, filename=true, ignore_errors=true)")


def _view_for(ticker: str) -> str:
    """裸 6 位 = 板块代码 → sector_index；其余（.SH/.SZ 后缀、海外票）→ market_quotes。"""
    return "sector_index" if re.fullmatch(r"\d{6}", ticker) else "market_quotes"


def _rows(con, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(zip([d[0] for d in con.description], row)) for row in con.execute(sql, params).fetchall()]


def query_quote(con, data_root: Path, ticker: str) -> dict[str, Any] | None:
    view = _view_for(ticker)
    ensure_view(con, data_root, view)
    rows = _rows(con, f"SELECT * FROM {view} WHERE filename LIKE ? ORDER BY date DESC LIMIT 1",
                 (f"%{ticker}.jsonl",))
    return rows[0] if rows else None


def query_range(con, data_root: Path, ticker: str, start: str, end: str) -> list[dict[str, Any]]:
    view = _view_for(ticker)
    ensure_view(con, data_root, view)
    return _rows(con, f"SELECT * FROM {view} WHERE filename LIKE ? AND date BETWEEN ? AND ? "
                      "ORDER BY date", (f"%{ticker}.jsonl", start, end))


def query_finance(con, data_root: Path, code: str, last: int = 4) -> list[dict[str, Any]]:
    ensure_view(con, data_root, "finance")
    return _rows(con, "SELECT * FROM finance WHERE code = ? ORDER BY report_date DESC LIMIT ?",
                 (code.zfill(6), last))


def sector_top(con, data_root: Path, top: int = 20) -> list[dict[str, Any]]:
    ensure_view(con, data_root, "sector_index")
    sql = f"""
    WITH ranked AS (
      SELECT filename, date, close, up_count, down_count,
             ROW_NUMBER() OVER (PARTITION BY filename ORDER BY date DESC) AS rn
      FROM sector_index WHERE close IS NOT NULL
    )
    SELECT regexp_extract(l1.filename, '([0-9]{{6}})\\.jsonl$', 1) AS code,
           l1.date, l1.close,
           CASE WHEN l2.close IS NOT NULL AND l2.close <> 0
                THEN round((l1.close - l2.close) / l2.close * 100, 2) END AS pct_change,
           l1.up_count, l1.down_count
    FROM ranked l1 LEFT JOIN ranked l2
      ON l1.filename = l2.filename AND l2.rn = 2
    WHERE l1.rn = 1
    ORDER BY pct_change DESC NULLS LAST
    LIMIT {int(top)}
    """
    return _rows(con, sql)


def run_sql(con, sql: str) -> list[dict[str, Any]]:
    return _rows(con, sql)


def main(argv: list[str] | None = None) -> int:
    duckdb = _require_duckdb()
    from market_data_io import resolve_data_root
    from save_custom_data import show_series

    parser = argparse.ArgumentParser(description="市场数据 DuckDB 查询（spec §5.6）")
    sub = parser.add_subparsers(dest="command", required=True)
    p_quote = sub.add_parser("quote")
    p_quote.add_argument("--ticker", required=True)
    p_range = sub.add_parser("range")
    p_range.add_argument("--ticker", required=True)
    p_range.add_argument("--start", required=True)
    p_range.add_argument("--end", required=True)
    p_finance = sub.add_parser("finance")
    p_finance.add_argument("--ticker", required=True)
    p_finance.add_argument("--last", type=int, default=4)
    p_sector = sub.add_parser("sector")
    p_sector.add_argument("--top", type=int, default=20)
    p_custom = sub.add_parser("custom")
    p_custom.add_argument("--series", required=True)
    p_custom.add_argument("--tail", type=int)
    p_sql = sub.add_parser("sql")
    p_sql.add_argument("--sql", required=True)
    args = parser.parse_args(argv)
    data_root = resolve_data_root()

    if args.command == "custom":  # 不走 DuckDB，直接读文件
        print(json.dumps(show_series(data_root, args.series, args.tail), ensure_ascii=False, indent=1))
        return 0

    con = duckdb.connect(":memory:")
    if args.command == "quote":
        out = query_quote(con, data_root, args.ticker)
    elif args.command == "range":
        out = query_range(con, data_root, args.ticker, args.start, args.end)
    elif args.command == "finance":
        out = query_finance(con, data_root, args.ticker, args.last)
    elif args.command == "sector":
        out = sector_top(con, data_root, args.top)
    else:  # sql：能建的视图都建，缺组只警告（用户 SQL 没用到就能跑）
        for view in _VIEW_PATTERNS:
            try:
                ensure_view(con, data_root, view)
            except RuntimeError as exc:
                log(f"Warning: {exc}")
        out = run_sql(con, args.sql)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8.5: 跑绿 + ruff + Commit**

Run: `$PY -m pytest tests/test_query_market.py -v && $PY -m ruff check tools/daily-watch/scripts/query_market.py tests/test_query_market.py`
Expected: PASS

```bash
git add tools/daily-watch/scripts/query_market.py tools/daily-watch/requirements-market-data.txt tests/test_query_market.py
git commit -m "feat: DuckDB 查询层 query_market——四具名视图/sector 榜/缺口审计入口"
```

---

### Task 9: 调度注册（**主会话执行，不派 subagent**——定时任务绑定工作区会话）

**Files:** 无代码变更；产出是一条 ZCode automation。

spec §6 拍板：**独立每日自动化**。合并进 H1 月度巡检不可行——「每日 16:30」与「每月 3/8/10/21 20:00」无法用一条 5 字段 cron 表达；平台一会话限一条 cron，本（执行）会话尚无自有 cron，可直接注册。若 CronCreate 被平台拒绝：不硬试第二次，把本 Task 的完整注册参数（下方 title/cron/prompt 原文）交给用户在新会话注册，并在验收记录里注明。

- [ ] **Step 9.1: CronList 确认现状**

确认工作区现有「每月3/8/10/21日前导链巡检（H1）」不受影响；本会话未持有其它 cron。

- [ ] **Step 9.2: CronCreate**

- title：`每日16:30盘后数据批量：全市场行情+板块+财务（持久化层）`
- cron：`30 16 * * *`，recurring: true
- prompt（原文照抄）：

```
工作目录 /Users/berton/Github/Invest/ai-workspace-hub。跑市场数据持久化层的每日盘后批量，解释器一律用绝对路径 /opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python（别名 $PY），每条命令失败最多补跑一次：
1. $PY tools/daily-watch/scripts/update_market_series.py --scope all
2. $PY tools/daily-watch/scripts/update_finance_snapshots.py
两个脚本结尾都打印 ok/skip/fail 汇总；update_market_series 的 fail>0 时退出码 1。输出中文简报：两脚本各自的 ok/skip/fail；update_market_series 日志里「前缀白名单过滤后待更新: N 只」的 N；若日志出现「交易日闸门…整轮跳过」注明今日非交易日、当日零写入属正常。任何 fail>0：列出失败票/期（截前 10 个）；检查 data/.locks/ 是否有 mtime 超过 10 分钟的陈旧 .lock 残留（有则删除并重跑对应脚本一次——完成标记 data/.state/ 只在整轮零失败时写入，fail>0 的重跑不会被交易日闸门挡住）；不做当天第三次重试。除删陈旧锁外不要修改任何代码或配置，不写日报，不碰 hypothesis。
```

- [ ] **Step 9.3: 验证**

CronList 应出现新条目（enabled、cron `30 16 * * *`、recurring）。把 automationId 记进验收记录（Task 11 的 notes 文件）。

---

### Task 10: 文档六处同步 + .gitignore + CHANGELOG

**Files:**
- Modify: `tools/daily-watch/README.md`、`DATA-SOURCES.md`、`system/skills/daily-watch.md`、`AGENTS.md`、`CLAUDE.md`、`system/templates/AGENTS.md`、`system/templates/CLAUDE.md`、`workspace/workspace-config.md`、`system/templates/workspace-config.md`、`ARCHITECTURE.md`、`.gitignore`、`CHANGELOG.md`

（`tests/test_repository_contract.py` 会强制 AGENTS/CLAUDE 与模板同步——正本和模板必须同改，跑全量测试即验证。）

- [ ] **Step 10.1: `.gitignore` 追加 `data/`；CHANGELOG 追加条目**

CHANGELOG 在 `## Unreleased` 的 `### 新增` 段顶部追加（沿用现有格式，不自造日期节）：

```markdown
- 市场数据持久化层落地（spec：docs/superpowers/specs/2026-11-02-market-data-persistence-design.md）：全市场行情/板块时序、日报快照、新闻快照、财务快照、自定义序列 + DuckDB 查询；每日 16:30 定时盘后批量；`data/` 整目录 gitignore。
```

- [ ] **Step 10.2: README 新增「本地持久化」章节**

在 `tools/daily-watch/README.md` 末尾追加（这是 spec §10 要求的字段字典唯一口径源）：

```markdown
## 本地持久化（市场数据层）

设计 spec：`docs/superpowers/specs/2026-11-02-market-data-persistence-design.md`（v0.2）。目录 `data/` 整目录 gitignore。

### 目录与字段字典

    data/
    ├── market/daily/YYYY-MM-DD.json   # 日报快照：{schema_version, fetched_at, payload(原样)}
    ├── market/series/{TICKER}.jsonl   # 逐票日线：date/open/high/low/close/volume/amount/source
    ├── sector/series/{CODE}.jsonl     # 板块指数：上行的字段 + up_count/down_count
    ├── finance/gpcw-YYYY-MM-DD.jsonl  # 按报告期全市场财务快照（含北交所 353 行，series 层不含）
    ├── finance/_meta.json             # 各期 zip hash 台账（零下载探测）
    ├── custom/{slug}.jsonl + registry.json  # 自定义数值序列（date=记录日, period=所属期）
    ├── news/YYYY/MM/DD-{slug}.md      # 新闻原文（frontmatter 含 dedup=URL 规范化 md5）
    └── .state/                        # 批量完成标记 last_stocks_round/last_sectors_round（交易日闸门读它，与数据文件解耦）

口径铁律：
- **不复权原始价**，除权跳空原样保留；复权在查询层按需算。
- A 股 volume=手、amount=元，**amount 仅批量路径有值**（日报钩子无此字段）；海外票自启用日累积、缺字段 null；板块 volume 量纲与个股不同，原样保留。
- 文件名即主键：A 股 `{6位}.SH/.SZ`（枚举一律 normalize 后落盘）、海外票 watchlist 原样（`^SOX`/`NVDA`/`000660.KS`）、板块裸 6 位。
- 多写者规则：批量=权威写者（同日按字段覆盖），日报钩子=快照级（只补 null 绝不覆盖非空）；跨进程 `data/.locks/` 目录锁，拿不到即跳过。
- schema 演进只加字段不改语义；daily/finance 行带 schema_version，series/custom 逐行有意不带。
- 板块指数为通达信自编指数（非交易所/申万口径），引用需标 TDX。
- 存储满配约 1GB（market 3 年 ~650MB + finance 148 期 ~300MB + sector ~120MB）；退市票文件冻结不删、单调慢涨；文件无校验和，单文件损坏的恢复手段 = 该票 `--backfill` 重拉。

### CLI 示例

    # 盘后批量（定时任务每日 16:30 自动跑的就是这两条）
    python tools/daily-watch/scripts/update_market_series.py --scope all
    python tools/daily-watch/scripts/update_finance_snapshots.py
    # 首次部署：全量初始化（3 年回补的唯一路径）
    python tools/daily-watch/scripts/update_market_series.py --scope all --backfill 800
    # 查询
    python tools/daily-watch/scripts/query_market.py quote --ticker 600276.SH
    python tools/daily-watch/scripts/query_market.py finance --ticker 300476 --last 4
    python tools/daily-watch/scripts/query_market.py sector --top 20
    # 缺口审计：找 tail 落后超过 7 天的票（cron 停摆自检）
    python tools/daily-watch/scripts/query_market.py sql --sql "SELECT regexp_extract(filename, '([0-9]{6}\\.[A-Z]{2})\\.jsonl$', 1) AS ticker, max(date) AS last_date FROM market_quotes GROUP BY filename HAVING max(date) < current_date - INTERVAL 7 DAY"
```

- [ ] **Step 10.3: DATA-SOURCES.md mootdx 行扩展用途**

`DATA-SOURCES.md` 中 mootdx 行的「市场/用途」由「A 股 + ETF 实时行情（主源）」改为：

```markdown
A 股 + ETF 实时行情（主源）；财务快照（gpcw，148 期至 1988）；板块指数（880/881 段，通达信自编口径）
```

- [ ] **Step 10.4: AGENTS.md + CLAUDE.md + 两模板（四处同改）**

1. 数据源表 mootdx 行（AGENTS.md:106 及 CLAUDE.md/两模板对应行）的用途列同步为 Step 10.3 的新文本。
2. 核心路由表「日报监控」行「主要写入」列：`output/daily-watch/ + evidence/ + 假设引用` → `output/daily-watch/ + data/（持久化钩子）+ evidence/ + 假设引用`。

- [ ] **Step 10.5: workspace-config.md + 模板目录表加一行**

在「核心目录」表 `| \`output/daily-watch/\` | 日报输出 |` 之后插入：

```markdown
| `data/` | 市场数据持久化（gitignore 运行时生成；spec：docs/superpowers/specs/） |
```

- [ ] **Step 10.6: system/skills/daily-watch.md 加流程步骤**

在日报核心流程「2. 运行数据脚本：」步骤（以文件实际措辞为准）之后追加一步：「持久化钩子自动落 data/（失败不阻塞日报）；引用外链文章时 agent 顺手 `save_news_snapshot.py --input <临时md>` 存原文」；并在文末调度段补一句「每日 16:30 ZCode 定时批量跑 update_market_series + update_finance_snapshots（幂等，非交易日自动零增量）」。

- [ ] **Step 10.7: ARCHITECTURE.md 目录结构树补 `data/`**

在「目录结构」段的树里 `output/` 附近补一行 `data/`（市场数据持久化，gitignore）。

- [ ] **Step 10.8: 全量验证 + Commit**

Run: `$PY -m pytest tests/ -q && $PY -m ruff check tools/daily-watch/scripts tests`
Expected: 全绿（test_repository_contract 强制四处模板同步），ruff 干净

```bash
git add .gitignore CHANGELOG.md tools/daily-watch/README.md DATA-SOURCES.md \
        system/skills/daily-watch.md AGENTS.md CLAUDE.md \
        system/templates/AGENTS.md system/templates/CLAUDE.md \
        workspace/workspace-config.md system/templates/workspace-config.md ARCHITECTURE.md
git commit -m "docs: 持久化层六处文档同步+gitignore data/+CHANGELOG（README 字段字典为口径源）"
```

（显式清单、不用 `git add -A`——工作树里未跟踪的 `docs/superpowers/` 走下一个 Step 的独立 commit，绝不顺带卷进本 commit。）

- [ ] **Step 10.9: docs/superpowers 入库（用户 2026-11-02 拍板「全部入库」）**

```bash
git add docs/superpowers/specs/2026-11-02-market-data-persistence-design.md \
        docs/superpowers/plans/2026-11-02-market-data-persistence.md
git commit -m "docs: 市场数据持久化 spec v0.3 与实施计划 v3（两轮评审修订后）入库"
```

（e2e notes 由 Task 11 的 commit 自行提交；`docs/superpowers/` 不加 gitignore。）

---

### Task 11: E2E 验收（真网络，Quant-3.11；唯一允许写真实 `data/` 的 Task）

**Files:**
- Create: `docs/superpowers/notes/2026-11-02-market-data-e2e.md`（验收记录 + 计时落档）

前置：`PY=/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python`，工作目录仓库根。

- [ ] **Step 11.1: 回补抽查（spec §11.1）**

```bash
$PY tools/daily-watch/scripts/update_market_series.py --scope stocks --tickers 600276.SH,300476.SZ,513880.SH --backfill 800
$PY tools/daily-watch/scripts/query_market.py range --ticker 300476.SZ --start 2024-01-01 --end 2026-11-02 | head -40
```

300476 头三行与东财网页 K 线人工对照（价格不复权、日期对齐），对照结果写进 notes。

- [ ] **Step 11.2: 板块（spec §11.2）**

```bash
$PY tools/daily-watch/scripts/update_market_series.py --scope sectors --backfill 800
$PY -c "import json;print(len(json.load(open('data/sector/sector-list.json'))))"  # 记录实测数（不硬编 1037）
```

- [ ] **Step 11.3: 财务（spec §11.3）**

```bash
$PY tools/daily-watch/scripts/update_finance_snapshots.py
$PY tools/daily-watch/scripts/query_market.py finance --ticker 300476 --last 1
```

断言 `inventory == 9249440768`、`revenue_yoy ≈ 30.77`；再查 600519、601398 三票对照最新公告人工核对（校验记录写进 notes 与验收 commit 的 message body）。

- [ ] **Step 11.4: 自定义层读写回环（spec §11.4）**

```bash
$PY tools/daily-watch/scripts/save_custom_data.py append --series e2e-smoke --name "e2e冒烟" --date 2026-11-02 --value 1.0 --unit 件 --source e2e
$PY tools/daily-watch/scripts/save_custom_data.py append --series e2e-smoke --name "e2e冒烟" --date 2026-11-02 --value 2.0 --unit 件 --source e2e   # 期望：报错拒绝
$PY tools/daily-watch/scripts/save_custom_data.py append --series e2e-smoke --name "e2e冒烟" --date 2026-11-02 --value 2.0 --unit 件 --source e2e --overwrite
printf 'date,value,unit,source\n2026-11-01,3.0,件,e2e\n' > /tmp/e2e-custom.csv
$PY tools/daily-watch/scripts/save_custom_data.py csv-import --series e2e-smoke --file /tmp/e2e-custom.csv
$PY tools/daily-watch/scripts/query_market.py custom --series e2e-smoke   # 回读一致
rm -rf data/custom/e2e-smoke.jsonl && $PY - <<'EOF'
import json, pathlib
reg = json.loads(pathlib.Path("data/custom/registry.json").read_text())
reg.pop("e2e-smoke", None)
pathlib.Path("data/custom/registry.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1))
EOF
```

- [ ] **Step 11.5: 新闻 dedup（spec §11.5）**

```bash
printf '原文正文。\n' > /tmp/e2e-news.md
$PY tools/daily-watch/scripts/save_news_snapshot.py --url "https://example.com/e2e?utm_source=t" --title e2e --date 2026-11-02 --slug e2e --input /tmp/e2e-news.md
$PY tools/daily-watch/scripts/save_news_snapshot.py --url "https://example.com/e2e" --title e2e --date 2026-11-02 --slug e2e --input /tmp/e2e-news.md   # 期望输出 skipped
```

- [ ] **Step 11.6: 日报钩子 + 失败不阻塞（spec §11.6）**

```bash
$PY tools/daily-watch/scripts/generate_daily_report.py    # 跑通真流程
ls data/market/daily/ && ls data/market/series/ | head    # 快照 + watchlist series 追加
chmod 000 data/market/daily
$PY tools/daily-watch/scripts/generate_daily_report.py    # stderr 出持久化 warning，日报仍生成
chmod 755 data/market/daily
```

- [ ] **Step 11.7: 首次全量初始化计时（spec §11.7）**

```bash
ls data/.state/ 2>/dev/null   # 若已有 last_stocks_round（当日 cron 抢跑/手跑过），把原因记 notes
rm -f data/.state/last_stocks_round   # N1：stocks 完成标记在会让闸门短路全量初始化——先清再跑
time $PY tools/daily-watch/scripts/update_market_series.py --scope all --backfill 800
```

耗时、ok/skip/fail、退出码记 notes（这是「3 年回补」目标的唯一兑现路径）。计时口径注明：sectors 已在 11.2 完成当日初始化且有自己的标记，本次实际执行 stocks 部分（~6000 只 × 800 bars），sectors 段应为「闸门（sectors）…整轮跳过」零调用——日志里必须能看到这句，否则闸门 per-scope 隔离有问题，停下查。

- [ ] **Step 11.8: 日常增量计时 + 缺口审计（spec §11.8）**

```bash
# ① 同日重跑：两段闸门整轮短路，预期秒级、日志两处「整轮跳过」
time $PY tools/daily-watch/scripts/update_market_series.py --scope all
# ② 真实增量路径：临时移走完成标记（模拟次日首跑），预期 ~4 分钟内、几乎全 skip；
#    干净轮结束后标记自动重写，无须手工还原（若 ② fail>0，标记不重写属预期——幂等重跑即可）
mv data/.state/last_stocks_round data/.state/last_sectors_round /tmp/
time $PY tools/daily-watch/scripts/update_market_series.py --scope all
$PY tools/daily-watch/scripts/query_market.py sql --sql "SELECT regexp_extract(filename, '([0-9]{6}\\.[A-Z]{2})\\.jsonl$', 1) AS ticker, max(date) AS last_date FROM market_quotes GROUP BY filename HAVING max(date) < current_date - INTERVAL 7 DAY"
```

两段计时分别记 notes（① 是闸门短路成本，② 才是日常增量成本）。末条 SQL 是 ~7000 文件显式视图的首次真实检验（N4）：若 DuckDB 解析失败/超慢，按 Task 8 `ensure_view` docstring 的退路改 glob 串 + 保留存在性预检，并补 commit。缺口审计盲区注明：SQL 只看已有文件，「整批缺失」不可见——须以 ② 的 ok+skip 总数 ≈ 11.7 的 ok 数交叉印证没有整批漏网。

- [ ] **Step 11.9: 全量收口（spec §11.9）**

Run: `$PY -m pytest tests/ -q && $PY -m ruff check tools/daily-watch/scripts tests`
Expected: 全绿；六处文档逐项勾验（对照 spec §10 清单打勾，结果记 notes）。

- [ ] **Step 11.10: 验收记录落档 + Commit**

`docs/superpowers/notes/2026-11-02-market-data-e2e.md` 记录：各步结果、三票财务校验数值对照表、两次计时、sector 实测数、cron automationId、六处勾验清单。任一项不过 → 停下修复并重跑该项，不带病过关。

```bash
git add docs/superpowers/notes/2026-11-02-market-data-e2e.md
git commit -m "docs: 持久化层 e2e 验收记录——三票校验/计时/板块实测数/勾验清单

300476/600519/601398 财务三票对照公告：[执行时填入实测对照数值]
全量初始化耗时：[执行时填入]；日常增量耗时：[执行时填入]"
```

（commit message 里方括号占位由**执行时**填实测值——本 Task 的产出就是这些数字，不许留占位提交。若 e2e 期间逼出 spec/计划再修订（N4 退路等），追加一个 docs commit，不留未提交的文档漂移。）
