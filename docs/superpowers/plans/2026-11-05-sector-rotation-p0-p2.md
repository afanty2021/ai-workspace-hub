# 板块轮动策略 P0-P2（含 P3 信号工具）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 `workspace/proposals/2026-11-05-sector-rotation-design.md`（**v1.2，独立评审 1C+9I+8M 闭环版**）的 P0（数据回补 + point-in-time 宇宙 + 预注册）、P1（两档成本回测 + L0 检验矩阵）、P2（L2 论文复刻 + 消融），并交付 P3 纸面跟踪所需的周信号工具。

**Architecture:** 双层标的（信号层 = 通达信 881 二级行业指数，执行层 = 行业 ETF，**point-in-time 映射**：每周用当时达标 ETF，杜绝幸存者/前视偏差）。数据复用持久化层（mootdx 深回补走 `market_data_io` upsert 正规通道）；回测引擎以「周五决策帧」为原子单位，策略统一 `select(wf, t)` 协议；**统计纪律三禁**（映射/点差/标准化与簇相关性一律禁全样本信息）；成本两档制（10/20bp），闸门统一引用 spec §3.8 检验矩阵，两档各过、单侧 p<0.1。P1/P2 出口闸门是**实证判定**，不满足即停并写结案报告（spec §5）。

**Tech Stack:** Python 3.11（conda Quant-3.11）、mootdx（已在环境，start 分页见持久化 spec L284）、numpy/pandas（已在环境）、PyTorch（T12 安装，CPU/MPS 轮子）、pytest、ruff。

**Spec:** `workspace/proposals/2026-11-05-sector-rotation-design.md`（**v1.2**，commit c10dde2）。冲突以 spec 为准，本计划是它的任务化论证。本计划已对齐 v1.2 全部六处硬口径变更（point-in-time 映射 / 点差两档 / 训练窗标准化 / 滞后滚动簇 / 覆盖率起点 / 检验矩阵）。

## Global Constraints（全任务绑定）

1. **Python 一律 `conda run -n Quant-3.11 python ...`**（系统 Python 是 PEP 668 管理的 3.15）。
2. **测试**：`conda run -n Quant-3.11 python -m pytest tests/ -q` 全量必须保持全绿（当前 465+16 用例）；新测试放根级 `tests/test_sr_*.py`（沿 `test_masters_*.py` 命名惯例），输出必须干净。
3. **Lint**：`conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py`（规则集 E4/E7/E9/F）零告警。
4. **提交**：中文 `type: subject`，按关注点拆 commit，**不推送**；在 `feat/sector-rotation-design` 分支续做（已含 v1/v1.1/v1.2 与本计划），不切新分支。
5. **数据纪律**：`data/` 全部是 gitignore 运行时数据，绝不 `git add`；回测报告中的每一个数字必须来自真实运行输出，禁止编造（工作区标注纪律：`[本地]`/`[网页]`/`[推测]`）。
6. **mootdx 单 socket**：所有 bars 拉取必须经 `mootdx_source._mootdx_call`（内部已 RLock 串行化）；单页 ≤ 800 根，深回补走 start 分页（mootdx 库 `k()` 已支持，见 `docs/superpowers/specs/2026-11-02-market-data-persistence-design.md:284`），按 date 去重。
7. **不新建 skill、不动 AGENTS.md 路由表**（spec §4：P3 跑通前）。
8. **统计纪律三禁（spec v1.2 C-1/I-4）**：①ETF 映射 point-in-time——回测中每周只用**当时**达标者（上市满 2 年且当时 trailing 20 日均成交额 ≥ 1 亿元，同行业多只取当时 20 日均额最大者[规模 proxy，近似已声明待验证]），无达标 ETF 的行业当周出宇宙；②历史段禁用今日实测点差；③标准化统计量只在当前训练窗内重算（推理周沿用训练窗参数），簇相关性只用滞后窗（t 时点用 t-2 至 t-1 年收益，每 2 年再聚一次）。
9. **成本两档制（spec §3.7）**：佣金双边各 1bp；单边点差基准档 10bp / 压力档 20bp 两档并行；冲击 0 参数化预留；**所有出口闸门两档都必须通过**；成本拖累占比两档各一列；α 永远只报成本后。
10. **执行闸门与迟滞（spec §3.5/§3.1）**：周一开盘涨停（`open ≥ prev_close × (1 + limit_pct × 0.995)`）弃买；周五清仓跌停顺延下周一开盘卖（首版简化口径见 T9 注）；**入选严、周内宽**——入选 trailing 20d ≥ 1 亿（point-in-time），周内拦截线为执行周日均成交额 < 5000 万。
11. **风控参数（spec §3.6 初值）**：单行业周亏 ≥5% 移出下周清单；组合连亏 4 周停一周；年内回撤 ≥8% 降半仓至新高；单行业滚动 8 周胜率 <45% 进两周观察期；组合绝对亏损 10% 全停；同簇 ≤2 截断**持币不顺延**（截断资金不重新分配）。
12. **检验矩阵是唯一闸门口径（spec §3.8，别处只引用不另设数字）**：vs 随机 k=置换检验 ≥1000 次（单侧 p<0.1）；vs 等权 / vs 沪深300ETF / L1·L2 vs L0 = 配对周收益差 block bootstrap（块长 4 周 ≥1000 次，单侧 p<0.1）；全部两档各过。**L0 主检验配置 P0 末预注册**（k/方向/N/点差档各一值写死，落 spec 实施记录段 + config），P1 样本外只对预注册配置做一次确认性检验；其余变体标"探索性"只报告不判定。
13. **功效边界（spec §3.8 功效注释，写进 P1 出口一起读）**：样本外约 370 周，单侧 p<0.1 稳定检出年化 α ≈5-7%——P1 证伪的结案报告必须写"未检出 ≥5-7%/年的 α"，不得写成"A 股周频轮动无 α"的全称否定。
14. **闸门失败即停**：P1 未过 → 停 T12-15，写结案报告（含功效局限声明），单独 commit；P2 未过 → 停 T15，同样处理。

## 文件结构（决策锁定）

```
tools/sector-rotation/
  README.md                    # 模块说明 + 数据流 + CLI 速查 + 已知限制（T15 收口）
  requirements.txt             # torch>=2.2（可选依赖注释，T1 建，T12 安装）
  backfill.py                  # CLI：881 指数 + ETF 候选池深回补；verify 完整性/退市可得性
  build_universe.py            # CLI：候选池 + 行业→ETF 候选集 + 逐年宇宙曲线 + 滞后滚动簇
  backtest.py                  # CLI：检验矩阵回测（--level L0/L1/L2 --tier base/stress）→ 报告
  signal.py                    # CLI：每周五盘后出下周 ETF 交易信号（P3 工具，当日快照规则）
  sector_rotation/
    __init__.py
    universe.py                # Member/UniverseSpec/簇代 加载校验 + cluster_for(t)
    data.py                    # point-in-time WeeklyFrame（每周执行 ETF 选择）+ 300ETF 基准
    weekly.py                  # 窗口块 + 训练窗内标准化 + 毛/净标签
    cost.py                    # CostModel 两档（base/stress classmethod）
    metrics.py                 # 指标集 + 同簇触发频率
    baselines.py               # point-in-time 等权/动量/反转/随机（统一 select 协议）
    portfolio.py               # 执行闸门（含周内流动性迟滞）+ 风控 + 持币式同簇截断
    walkforward.py             # 引擎（覆盖率 ≥80% 起点）
    permtest.py                # 置换检验 + block bootstrap 配对检验
    models.py                  # L1 torch 线性 + L2 MIMO（训练窗标准化/MC dropout/ROC trailing）
config/sector-rotation-universe.md   # 宇宙 spec（候选集映射 + 全部簇代表，tracked）
data/sector-rotation/                # etf-candidates.txt / delisted-etf.txt / 曲线报告（gitignore）
output/sector-rotation/              # 回测报告与周信号（YYYY-MM/ 子目录）
tests/test_sr_*.py                   # 每任务配套测试（根级 tests/）
```

依赖方向（单向）：`backfill/build_universe → data/weekly → cost/portfolio/metrics/baselines/models → walkforward/permtest → backtest/signal`。

---

### Task 1: 脚手架 + universe.py（宇宙 spec 解析：候选集 + 簇代）

**Files:**
- Create: `tools/sector-rotation/requirements.txt`、`tools/sector-rotation/sector_rotation/__init__.py`、`tools/sector-rotation/sector_rotation/universe.py`
- Test: `tests/test_sr_universe.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Member:
    index_code: str
    index_name: str
    etf_candidates: tuple[str, ...]   # 候选 ETF（带后缀，多只；point-in-time 引擎每周择一）
    limit_pct: float                  # 主板 0.10 / 跟踪双创板指数 0.20

@dataclass(frozen=True)
class UniverseSpec:
    members: list[Member]
    clusters: dict[int, dict[str, str]]   # 簇代年 g → {index_code: cluster_id}
                                           # 代 g 的聚类窗 = [g, g+1]，g+2 年起可用

def load_universe(path: Path) -> UniverseSpec
def write_universe(path: Path, spec: UniverseSpec, *, status: str) -> None
def cluster_for(spec: UniverseSpec, friday: str) -> dict[str, str] | None
    # t 周用最新簇代 g 满足 g+2 ≤ t 年；无可用代（早期）→ None（同簇约束跳过并记录）
```

后续所有任务经此读宇宙。簇代序列 = {2017, 2019, 2021, 2023, 2025}（spec §3.6 每 2 年再聚）。

- [ ] **Step 1: 建目录与 requirements**

```bash
mkdir -p tools/sector-rotation/sector_rotation
cat > tools/sector-rotation/requirements.txt <<'EOF'
# 可选依赖：L1/L2 需要（spec §6 拍板 3）。安装：
#   conda run -n Quant-3.11 python -m pip install "torch>=2.2"
# CPU/MPS 轮子即可，模型为小型 MLP，无需 GPU。
torch>=2.2
EOF
touch tools/sector-rotation/sector_rotation/__init__.py
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_sr_universe.py
from pathlib import Path

import pytest

from sector_rotation.universe import (Member, UniverseSpec, cluster_for,
                                      load_universe, write_universe)


def _spec():
    return UniverseSpec(
        members=[
            Member("881101", "工程机械", ("528030.SH", "516810.SH"), 0.10),
            Member("881127", "半导体", ("512480.SH",), 0.10),
        ],
        clusters={2019: {"881101": "c-a", "881127": "c-b"},
                  2021: {"881101": "c-x", "881127": "c-x"}})


def test_roundtrip(tmp_path: Path):
    path = tmp_path / "universe.md"
    write_universe(path, _spec(), status="draft")
    assert load_universe(path) == _spec()


def test_cluster_for_uses_latest_available_generation():
    spec = _spec()
    assert cluster_for(spec, "2020-06-05") == {"881101": "c-a", "881127": "c-b"}
    assert cluster_for(spec, "2022-01-07") == {"881101": "c-x", "881127": "c-x"}
    assert cluster_for(spec, "2019-01-04") is None      # 2019 代（窗 2019-2020）2021 才可用


def test_load_rejects_bad_header(tmp_path: Path):
    p = tmp_path / "u.md"
    p.write_text("---\ntype: sector-rotation-universe\n---\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未解析到任何成员"):
        load_universe(p)
```

（注：`sector_rotation` 导入路径——先读 `tests/conftest.py`，若没有把 `tools/sector-rotation` 纳入 sys.path 的机制，追加 `sys.path.insert(0, str(REPO_ROOT / "tools/sector-rotation"))`；只在缺失时追加。）

- [ ] **Step 3: 跑测试确认失败**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_universe.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 4: 最小实现**

```python
# tools/sector-rotation/sector_rotation/universe.py
"""宇宙 spec（config/sector-rotation-universe.md）读写：候选集映射 + 簇代表。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HEADER = "type: sector-rotation-universe"
MEMBER_COLS = ["index_code", "index_name", "etf_candidates", "limit_pct"]
CLUSTER_COLS = ["generation", "index_code", "cluster"]


@dataclass(frozen=True)
class Member:
    index_code: str
    index_name: str
    etf_candidates: tuple[str, ...]
    limit_pct: float


@dataclass(frozen=True)
class UniverseSpec:
    members: list[Member]
    clusters: dict[int, dict[str, str]]


def load_universe(path: Path) -> UniverseSpec:
    text = path.read_text(encoding="utf-8")
    if HEADER not in text:
        raise ValueError(f"{path} 缺 frontmatter 标记 {HEADER}")
    members: list[Member] = []
    clusters: dict[int, dict[str, str]] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if section.startswith("成员") or section == "":
            if cells == MEMBER_COLS or cells[0] == "index_code":
                continue
            if len(cells) != len(MEMBER_COLS):
                raise ValueError(f"成员表列数不符：{line}")
            members.append(Member(cells[0], cells[1],
                                  tuple(cells[2].split(";")), float(cells[3])))
        elif section.startswith("簇"):
            if cells == CLUSTER_COLS or cells[0] == "generation":
                continue
            if len(cells) != len(CLUSTER_COLS):
                raise ValueError(f"簇表列数不符：{line}")
            clusters.setdefault(int(cells[0]), {})[cells[1]] = cells[2]
    if not members:
        raise ValueError(f"{path} 未解析到任何成员")
    return UniverseSpec(members, clusters)


def write_universe(path: Path, spec: UniverseSpec, *, status: str) -> None:
    lines = ["---", HEADER, f"status: {status}", "---", "",
             "## 成员（指数 → ETF 候选集，point-in-time 引擎每周择一）",
             "", "| " + " | ".join(MEMBER_COLS) + " |",
             "|" + "---|" * len(MEMBER_COLS)]
    for m in spec.members:
        lines.append(f"| {m.index_code} | {m.index_name} | "
                     f"{';'.join(m.etf_candidates)} | {m.limit_pct} |")
    lines += ["", "## 簇代（滞后滚动窗：代 g 用 [g, g+1] 年收益聚类，g+2 年起可用）",
              "", "| " + " | ".join(CLUSTER_COLS) + " |",
              "|" + "---|" * len(CLUSTER_COLS)]
    for gen in sorted(spec.clusters):
        for code in sorted(spec.clusters[gen]):
            lines.append(f"| {gen} | {code} | {spec.clusters[gen][code]} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cluster_for(spec: UniverseSpec, friday: str) -> dict[str, str] | None:
    year = int(friday[:4])
    usable = [g for g in spec.clusters if g + 2 <= year]
    return spec.clusters[max(usable)] if usable else None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_universe.py -v`
Expected: PASS（3 用例）

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/ tests/test_sr_universe.py
git commit -m "feat(sector-rotation): 脚手架 + 宇宙 spec 解析（候选集/簇代，Task 1）"
```

---

### Task 2: backfill.py——881 全集 + ETF 候选池深回补 + 数据现实报告

**Files:**
- Create: `tools/sector-rotation/backfill.py`
- Test: `tests/test_sr_backfill.py`

**Interfaces:**
- Consumes: `mootdx_source._mootdx_call`、`market_data_io.upsert_series_rows`（经 `sys.path` 注入 `tools/daily-watch/scripts` 导入；upsert 签名以 `grep -n 'def upsert_series_rows' tools/daily-watch/scripts/market_data_io.py` 实测为准，差异处按真实签名适配）。
- Produces: `fetch_bars_paginated(symbol: str, *, index: bool, total: int = 2600, page: int = 800) -> list[dict]`（symbol：指数裸码/ETF 带后缀，API 用裸码；date 去重升序行，字段 date/open/high/low/close/volume/amount/source）；CLI `backfill.py indices|etfs|verify`。`verify` 输出深度分布表（指数深度直方图 + ETF 上市年份分布 + 退市代码可得性行）——**数据现实曲线的机器可读底稿**（spec §5 P0 出口）。

- [ ] **Step 1: 写失败测试**（mootdx 全 mock，不发真实网络）

```python
# tests/test_sr_backfill.py
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

import backfill  # noqa: E402


def _page_df(dates: list[str]) -> "pd.DataFrame":
    n = len(dates)
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": [10.0] * n, "high": [11.0] * n,
        "low": [9.0] * n, "close": [10.5] * n,
        "volume": [1000.0] * n, "amount": [10500.0] * n,
    })


def test_fetch_paginated_dedupes_and_uses_start(monkeypatch):
    pages = [_page_df(["2026-11-02", "2026-10-30"]),
             _page_df(["2026-10-30", "2026-10-29"]),
             _page_df([])]
    calls = []

    def fake_call(method, **kw):
        calls.append((method, kw))
        return pages[len(calls) - 1]

    monkeypatch.setattr(backfill, "_mootdx_call", fake_call)
    rows = backfill.fetch_bars_paginated("881101", index=True, total=6, page=2)
    assert [r["date"] for r in rows] == ["2026-10-29", "2026-10-30", "2026-11-02"]
    assert calls[1][1]["start"] == 2          # start 分页（持久化 spec L284 口径）
    assert calls[0][0] == "index_bars" and calls[0][1]["frequency"] == 9


def test_fetch_etf_strips_suffix_for_api(monkeypatch):
    seen = {}

    def fake_call(method, **kw):
        seen["symbol"] = kw["symbol"]
        return _page_df(["2026-11-02"])

    monkeypatch.setattr(backfill, "_mootdx_call", fake_call)
    backfill.fetch_bars_paginated("512480.SH", index=False)
    assert seen["symbol"] == "512480"        # API 裸码，路径带后缀


def test_fetch_returns_empty_when_source_down(monkeypatch):
    def boom(method, **kw):
        raise RuntimeError("server down")

    monkeypatch.setattr(backfill, "_mootdx_call", boom)
    assert backfill.fetch_bars_paginated("881101", index=True) == []


def test_verify_depth_report(tmp_path: Path):
    d = tmp_path / "sector" / "series"
    d.mkdir(parents=True)
    (d / "881101.jsonl").write_text(
        '{"date":"2020-01-03","close":1.0}\n{"date":"2020-01-06","close":1.1}\n',
        encoding="utf-8")
    rows = backfill.verify_depth([("881101", True)], data_root=tmp_path,
                                 expect_bars=2500)
    assert rows[0] == {"code": "881101", "rows": 2, "first": "2020-01-03",
                       "last": "2020-01-06", "shortfall": 2498}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backfill.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 backfill.py**

```python
# tools/sector-rotation/backfill.py
"""881 二级行业指数与 ETF 候选池深回补（spec §3.2）。

start 分页沿用持久化 spec L284 口径（mootdx k() 同款）；写回走 market_data_io
upsert 正规通道（writer=batch，与 16:30 cron 同写者语义）。指数落
data/sector/series/{code}.jsonl，ETF 落 data/market/series/{sym}.jsonl。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from market_data_io import upsert_series_rows  # noqa: E402
from mootdx_source import _mootdx_call, log  # noqa: E402

PAGE = 800
TOTAL = 2600          # ≈ 10.7 年日线
SECTOR_DIR = "sector/series"
ETF_DIR = "market/series"


def fetch_bars_paginated(symbol: str, *, index: bool, total: int = TOTAL,
                         page: int = PAGE) -> list[dict]:
    """symbol：指数裸码（881101）或带后缀 ETF（512480.SH）；API 用裸 6 位码。"""
    method = "index_bars" if index else "bars"
    bare = symbol.rsplit(".", 1)[0]
    by_date: dict[str, dict] = {}
    start = 0
    while start < total:
        try:
            df = _mootdx_call(method, symbol=bare, frequency=9,
                              offset=page, start=start)
        except Exception as exc:  # noqa: BLE001 — 单段失败保住已拉数据
            log(f"Warning: {symbol} start={start} 回补失败: {exc}")
            break
        if df is None or df.empty:
            break
        new = 0
        for _, row in df.iterrows():
            rec = {k: row[k] for k in
                   ("open", "high", "low", "close", "volume", "amount")}
            rec["date"] = str(row["date"].date())
            rec["source"] = "mootdx-backfill"
            if rec["date"] not in by_date:
                by_date[rec["date"]] = rec
                new += 1
        if len(df) < page or new == 0:
            break
        start += page
    return [by_date[d] for d in sorted(by_date)]


def _target_path(data_root: Path, symbol: str, *, index: bool) -> Path:
    sub = SECTOR_DIR if index else ETF_DIR
    return data_root / sub / f"{symbol}.jsonl"


def run_backfill(targets: list[tuple[str, bool]], data_root: Path,
                 *, total: int = TOTAL) -> dict[str, int]:
    stats = {"ok": 0, "empty": 0}
    for symbol, is_index in targets:
        rows = fetch_bars_paginated(symbol, index=is_index, total=total)
        if not rows:
            stats["empty"] += 1
            log(f"Warning: {symbol} 空返回（指数可能新增短史/ETF 可能退市——verify 复核）")
            continue
        path = _target_path(data_root, symbol, index=is_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        upsert_series_rows(path, rows, writer="batch")
        stats["ok"] += 1
    log(f"回补汇总: {stats}")
    return stats


def verify_depth(targets: list[tuple[str, bool]], data_root: Path,
                 *, expect_bars: int) -> list[dict]:
    report = []
    for symbol, is_index in targets:
        path = _target_path(data_root, symbol, index=is_index)
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                 if ln.strip()] if path.exists() else []
        dates = [ln.split('"date":"')[1][:10] for ln in lines] if lines else []
        report.append({"code": symbol, "rows": len(lines),
                       "first": dates[0] if dates else "",
                       "last": dates[-1] if dates else "",
                       "shortfall": max(0, expect_bars - len(lines))})
    return report


def _sector_targets(data_root: Path) -> list[tuple[str, bool]]:
    import json
    listing = json.loads((data_root / "sector" / "sector-list.json").read_text())
    return [(x["code"], True) for x in listing if x["category"] == "二级行业"]


def _read_candidates(path: Path) -> list[str]:
    return [ln.strip() for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("indices", help="回补 881 全集二级行业指数")
    p_etf = sub.add_parser("etfs", help="回补候选池 ETF（含退市探测清单）")
    p_etf.add_argument("--candidates", type=Path, default=None)
    p_ver = sub.add_parser("verify", help="深度分布 + 退市可得性报告")
    p_ver.add_argument("--etf-candidates", type=Path, default=None)
    args = ap.parse_args(argv)
    data_root = REPO_ROOT / "data"
    cand_default = data_root / "sector-rotation" / "etf-candidates.txt"
    delist_default = data_root / "sector-rotation" / "delisted-etf.txt"
    if args.cmd == "indices":
        run_backfill(_sector_targets(data_root), data_root)
        return 0
    if args.cmd == "etfs":
        codes = _read_candidates(args.candidates or cand_default)
        if delist_default.exists():          # 退市代码同样试拉（spec §3.1 探测项）
            codes += _read_candidates(delist_default)
        run_backfill([(c, False) for c in codes], data_root)
        return 0
    targets = _sector_targets(data_root)
    for path in filter(None, (args.etf_candidates, cand_default, delist_default)):
        if path.exists():
            targets += [(c, False) for c in _read_candidates(path)]
    for row in verify_depth(targets, data_root, expect_bars=TOTAL):
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backfill.py -v`
Expected: PASS（4 用例）

- [ ] **Step 5: 真实冒烟 + 退市清单准备（一次性，允许 15-20 分钟）**

```bash
mkdir -p data/sector-rotation
printf '512480.SH\n512000.SH\n' > data/sector-rotation/etf-candidates.txt
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py etfs
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py verify | tail -5
head -1 data/market/series/512480.SH.jsonl; tail -1 data/market/series/512480.SH.jsonl
```
Expected: 512480 深度显著 > 802（start 分页生效）。同时**联网检索近 5 年清盘/退市行业 ETF 代码清单**（交易所公告/基金公告，exa 补充），落 `data/sector-rotation/delisted-etf.txt`（每行一代码，附来源行注释）；`backfill.py etfs` 重跑后 `verify` 检查退市代码行数——0 行 = 通达信不留退市数据，如实写入 P0 报告（该时段行业出宇宙，压力档兜底近似）。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backfill.py tests/test_sr_backfill.py
git commit -m "feat(sector-rotation): mootdx start 分页深回补 + 退市探测 CLI（Task 2）"
```

---

### Task 3: build_universe.py——候选池 + 行业→ETF 候选集 + 逐年宇宙曲线 + 滞后滚动簇

**Files:**
- Create: `tools/sector-rotation/build_universe.py`
- Test: `tests/test_sr_universe_build.py`

**Interfaces:**
- Consumes: Task 2 数据与候选池文件；Task 1 `write_universe`。
- Produces: `config/sector-rotation-universe.md`（UniverseSpec：候选集 + 全部簇代）；`data/sector-rotation/coverage-curve.md`（point-in-time 逐年可用宇宙规模曲线，供 review-queue）。函数：

```python
def filter_etf_candidates(listing: list[dict]) -> list[str]
def point_in_time_pick(candidates: list[str], bars: dict[str, list[dict]],
                       week_end: str, *, min_list_years: int = 2,
                       min_amount_wan: float = 10000.0) -> str | None
    # 上市满 2 年且 trailing 20 日均额 ≥ 1 亿，多只取均额最大 [规模 proxy 近似]
def cluster_by_correlation(returns: np.ndarray, codes: list[str], *,
                           threshold: float = 0.75) -> dict[str, str]
def coverage_by_year(...) -> list[tuple[int, float, int]]   # (年, 覆盖率, 可用行业数)
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_universe_build.py
import numpy as np

import build_universe  # noqa: E402


def _bar(d, amount):
    return {"date": d, "amount": amount}


def test_filter_etf_candidates_keeps_industry_etf():
    listing = [
        {"code": "512480", "name": "半导体ETF"}, {"code": "512000", "name": "券商ETF"},
        {"code": "510300", "name": "沪深300ETF"}, {"code": "513330", "name": "恒生互联网ETF"},
        {"code": "511990", "name": "华宝添益"}, {"code": "518880", "name": "黄金ETF"},
        {"code": "159915", "name": "创业板ETF"}, {"code": "562400", "name": "机器人ETF"},
    ]
    kept = build_universe.filter_etf_candidates(listing)
    assert {"512480", "512000", "562400"} <= set(kept)
    assert not ({"510300", "513330", "511990", "518880", "159915"} & set(kept))


def test_point_in_time_pick_respects_listing_age_and_liquidity():
    old = [_bar(f"2024-01-{i:02d}", 3e8) for i in range(2, 22)]     # 2024 起，>2 年史
    young = [_bar(f"2025-06-{i:02d}", 5e8) for i in range(2, 22)]   # 上市 <2 年
    thin = [_bar(f"2024-01-{i:02d}", 2e7) for i in range(2, 22)]    # 均额 2000 万 <1 亿
    bars = {"528030.SH": old, "516810.SH": young, "159999.SZ": thin}
    assert build_universe.point_in_time_pick(
        ["528030.SH", "516810.SH", "159999.SZ"], bars, "2026-11-06") == "528030.SH"
    assert build_universe.point_in_time_pick(["516810.SH"], bars, "2026-11-06") is None


def test_cluster_by_correlation_groups_high_corr():
    rng = np.random.default_rng(7)
    base = rng.normal(size=104)
    rets = np.column_stack([base, base + 0.05 * rng.normal(size=104),
                            rng.normal(size=104)])
    cl = build_universe.cluster_by_correlation(rets, ["A", "B", "C"])
    assert cl["A"] == cl["B"] != cl["C"]
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现 build_universe.py**

```python
# tools/sector-rotation/build_universe.py
"""宇宙构建（spec §3.1 point-in-time / §3.6 滞后簇 / §5 P0 数据现实曲线）。

产出一稿 config/sector-rotation-universe.md（候选集 + 簇代，status: draft）+
data/sector-rotation/coverage-curve.md（逐年可用宇宙曲线）。draft 走 review-queue。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from sector_rotation.universe import Member, UniverseSpec, write_universe  # noqa: E402
from mootdx_source import _mootdx_call  # noqa: E402

EXCLUDE = re.compile(
    r"沪深300|中证500|中证1000|中证A50|上证50|创业板指|科创50|双创|红利|低波|价值|成长|"
    r"纳指|纳斯达克|标普|美国|日经|恒生|香港|港股通|QDII|亚洲|新兴|德国|法国|沙特|"
    r"黄金|豆粕|有色期货|能源化工|原油|货币|债|国债|信用|转债|添益|理财")

KEYWORDS: dict[str, list[str]] = {
    "证券": ["证券", "券商"], "银行": ["银行"], "保险": ["保险"],
    "半导体": ["半导体", "芯片"], "软件服务": ["软件", "计算机"],
    "通信设备": ["通信", "5G"], "电子": ["电子"], "白酒": ["酒"],
    "食品饮料": ["食品饮料", "消费"], "医药": ["医药", "医疗", "创新药", "生物医药"],
    "中药": ["中药"], "煤炭": ["煤炭"], "钢铁": ["钢铁"],
    "有色": ["有色", "稀土", "黄金股"], "石油": ["石油", "油气"],
    "化工": ["化工", "碳中和"], "电力": ["电力"], "光伏": ["光伏"],
    "风电": ["风电"], "新能源车": ["新能源车", "智能汽车", "汽车"],
    "电池": ["电池"], "军工": ["军工", "国防"], "机械": ["机械", "智能制造"],
    "建筑": ["基建", "建筑材料"], "房地产": ["房地产"], "家用电器": ["家电"],
    "农业": ["农业", "养殖"], "运输设备": ["高铁"], "航空": ["航空"],
    "航运": ["航运"], "传媒": ["传媒", "游戏"], "教育": ["教育"],
}

CLUSTER_GENERATIONS = [2017, 2019, 2021, 2023, 2025]   # 代 g 聚类窗 [g, g+1]


def filter_etf_candidates(listing: list[dict]) -> list[str]:
    """行业/主题 ETF 候选池（宽基/跨境/商品/货币/债剔除；56 = 沪市新 ETF 段）。"""
    kept = []
    for item in listing:
        code, name = item["code"], (item.get("name") or "")
        if not re.match(r"^(51|15|56|58)\d{4}$", code):
            continue
        if "ETF" not in name or EXCLUDE.search(name):
            continue
        kept.append(f"{code}.SH" if code.startswith(("51", "56", "58"))
                    else f"{code}.SZ")
    return sorted(set(kept))


def load_bars(data_root: Path, symbol: str) -> list[dict]:
    path = data_root / "market" / "series" / f"{symbol}.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def point_in_time_pick(candidates: list[str], bars: dict[str, list[dict]],
                       week_end: str, *, min_list_years: int = 2,
                       min_amount_wan: float = 10000.0) -> str | None:
    """当时达标者：上市满 2 年 + trailing 20 日均额 ≥ 1 亿；多只取均额最大
    （规模 proxy 近似，spec §8 待验证——README 声明）。"""
    best, best_amt = None, 0.0
    for sym in candidates:
        rows = [r for r in bars.get(sym, []) if r["date"] <= week_end]
        if len(rows) < 20:
            continue
        first, recent = rows[0]["date"], rows[-20:]
        listed_years = (int(week_end[:4]) - int(first[:4]))
        if listed_years < min_list_years:
            continue
        amt = sum(r["amount"] for r in recent) / 20
        if amt >= min_amount_wan * 1e4 and amt > best_amt:
            best, best_amt = sym, amt
    return best


def cluster_by_correlation(returns: np.ndarray, codes: list[str],
                           *, threshold: float = 0.75) -> dict[str, str]:
    corr = np.corrcoef(returns, rowvar=False)
    n = len(codes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if np.isfinite(corr[i, j]) and corr[i, j] > threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return {codes[i]: f"cluster-{codes[min(g)]}" for g in groups.values() for i in g}


def _index_daily(data_root: Path, code: str) -> dict[str, float]:
    path = data_root / "sector" / "series" / f"{code}.jsonl"
    out: dict[str, float] = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                row = json.loads(ln)
                out[row["date"]] = float(row["close"])
    return out


def build(data_root: Path, out_config: Path) -> dict[str, int]:
    listing = []
    for market in (0, 1):
        df = _mootdx_call("stocks", market=market)
        listing += [{"code": str(c).zfill(6), "name": str(n).replace("\x00", "")}
                    for c, n in zip(df["code"], df["name"])]
    candidates = filter_etf_candidates(listing)
    (data_root / "sector-rotation").mkdir(parents=True, exist_ok=True)
    (data_root / "sector-rotation" / "etf-candidates.txt").write_text(
        "\n".join(candidates) + "\n", encoding="utf-8")
    bars = {sym: load_bars(data_root, sym) for sym in candidates}

    sector_list = json.loads((data_root / "sector" / "sector-list.json").read_text())
    lv2 = [x for x in sector_list if x["category"] == "二级行业"]
    name_by_code = {x["code"]: x["name"].replace("\x00", "") for x in lv2}
    members: list[Member] = []
    unmatched: list[str] = []
    for sec in lv2:
        idx_name = sec["name"].replace("\x00", "")
        cands = [sym for sym in candidates
                 if any(kw in next((n for c, n in ((x['code'], x['name'].replace(chr(0), ''))
                                                   for x in listing)) if c == sym.split('.')[0]), "")
                         for kw in KEYWORDS.get(idx_name, [idx_name[:2]]))]
        cands = sorted(set(cands))
        if not cands:                       # 今日一票未中 → 无候选集，出 unmatched 人工补
            unmatched.append(f"{sec['code']} {idx_name}")
            continue
        limit = 0.20 if any(k in idx_name for k in ("半导体", "芯片", "创新药", "生物")) \
            and any(s.startswith(("58", "15")) for s in cands) else 0.10
        members.append(Member(sec["code"], idx_name, tuple(cands), limit))

    # 滞后滚动簇：代 g 用 [g, g+1] 年指数日收益聚类（spec §3.6 禁全样本）
    clusters: dict[int, dict[str, str]] = {}
    codes = [m.index_code for m in members]
    series = {c: _index_daily(data_root, c) for c in codes}
    for g in CLUSTER_GENERATIONS:
        lo, hi = f"{g}-01-01", f"{g + 1}-12-31"
        dates = sorted(d for d in
                       (set().union(*(set(series[c]) for c in codes)))
                       if lo <= d <= hi)
        if len(dates) < 40:                 # 该代数据不足（指数未上线）→ 无簇代
            continue
        mat = np.array([[series[c].get(d, np.nan) for d in dates] for c in codes])
        rets = np.diff(np.log(mat), axis=1)
        keep = ~np.isnan(rets).all(axis=1)
        usable = rets[keep][:, ~np.isnan(rets[keep]).any(axis=0)]
        if usable.shape[1] < 40 or keep.sum() < 3:
            continue
        clusters[g] = cluster_by_correlation(usable.T, [c for c, k in zip(codes, keep) if k])

    # point-in-time 逐年覆盖曲线（每年末快照，spec §5 P0）
    cov_lines = ["| 年 | 覆盖率 | 可用行业数 |", "|---|---|---|"]
    for year in range(2017, 2027):
        week_end = f"{year}-12-31"
        n_ok = sum(point_in_time_pick(list(m.etf_candidates), bars, week_end) is not None
                   and len([d for d in series[m.index_code] if d <= week_end]) > 100
                   for m in members)
        cov_lines.append(f"| {year} | {n_ok / len(members):.0%} | {n_ok} |")
    (data_root / "sector-rotation" / "coverage-curve.md").write_text(
        "\n".join(cov_lines) + "\n", encoding="utf-8")
    (data_root / "sector-rotation" / "unmatched.txt").write_text(
        "\n".join(unmatched) + "\n", encoding="utf-8")
    write_universe(out_config, UniverseSpec(members, clusters), status="draft")
    return {"members": len(members), "unmatched": len(unmatched),
            "candidates": len(candidates), "cluster_generations": len(clusters)}


def main() -> int:
    stats = build(REPO_ROOT / "data", REPO_ROOT / "config" / "sector-rotation-universe.md")
    print(stats)
    print("草稿：config/sector-rotation-universe.md；曲线：data/sector-rotation/coverage-curve.md")
    print("unmatched.txt 人工补 KEYWORDS 后重跑；候选集含多只 ETF 供 point-in-time 引擎择一")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

（执行注 1：候选集关键词匹配那行内嵌推导可读性差，执行时拆成具名函数 `def _match(cands, idx_name, listing): ...`，语义不变。执行注 2：KEYWORDS 是底稿，首跑后按 unmatched.txt 补齐；limit_pct 的双创判定以候选集里实际存在 58/15 开头双创类 ETF 为准，人工复核时校正——这是粗判，宇宙确认时一并过目。执行注 3：跑本任务前须先 `backfill.py etfs` 把候选池日线补齐，否则 point_in_time_pick 全空。） 

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_universe_build.py -v`
Expected: PASS（3 用例）

- [ ] **Step 5: 真实数据全流程跑**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/build_universe.py
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py etfs   # 新候选补拉
conda run -n Quant-3.11 python tools/sector-rotation/build_universe.py  # 带流动性重跑
```
Expected: config（draft）+ coverage-curve.md + unmatched.txt。逐年曲线是 walk-forward 起点判定（T10）的输入，数字如实记录。

- [ ] **Step 6: L0 主检验配置预注册 + review-queue（P0 出口闸门，spec §3.8 变体协议）**

- 从 coverage-curve 取覆盖率首 ≥80% 年份，结合 L0 训练/验证段（样本外之前）网格 {k∈2,3,4} × {动量/反转} × {N∈1,4} 选出**主检验配置**（只看样本外前数据），把预注册行追加到 spec 文档「实施记录」段：`预注册（P0, 2026-11-XX）：k=? / 方向=? / N=? / 判定档=基准+压力双档`，单独 commit。
- review-queue 追加（pending）：`确认宇宙清单 + 数据现实曲线 + 预注册配置`（draft→confirmed，重点：映射候选集正确性、双创 limit_pct、簇代表、逐年覆盖曲线）。

- [ ] **Step 7: Commit**

```bash
git add tools/sector-rotation/build_universe.py tests/test_sr_universe_build.py config/sector-rotation-universe.md
git commit -m "feat(sector-rotation): point-in-time 宇宙构建 + 滞后簇 + 覆盖曲线（Task 3）"
```

---

### Task 4: data.py——point-in-time WeeklyFrame

**Files:**
- Create: `tools/sector-rotation/sector_rotation/data.py`
- Test: `tests/test_sr_data.py`

**Interfaces:**
- Consumes: Task 1 `UniverseSpec`；Task 2/3 数据布局。
- Produces:

```python
@dataclass
class WeeklyFrame:
    fridays: list[str]            # 决策日（当周最后交易日）
    index_close: np.ndarray       # (T, L) 指数周五收盘
    etf_symbols: list[list[str]]  # (T, L) 该周 point-in-time 选中的执行 ETF（''=无）
    etf_open: np.ndarray          # (T, L) 下周一开盘（'' 周为 nan）
    etf_close: np.ndarray         # (T, L) 下周五收盘
    etf_prev_close: np.ndarray    # (T, L) 上周五收盘（涨跌停基准）
    etf_week_amount: np.ndarray   # (T, L) 执行周日均成交额（周内 5000 万闸门用）
    members: list[Member]
    spec: UniverseSpec
    valid: np.ndarray             # (T, L) bool：point-in-time 达标（有执行 ETF 且三价齐）
    bench_300: np.ndarray         # (T,) 沪深300ETF 执行周收益（对照组④，close/open-1）

def build_weekly_frame(data_root: Path, spec: UniverseSpec,
                       *, bench_symbol: str = "510300.SH") -> WeeklyFrame
```

point-in-time 语义（spec §3.1）：每周 `etf_symbols[t,i]` = `point_in_time_pick(candidates, bars, fridays[t])`（复用 T3 函数，导入 build_universe 或下沉到共用模块——**下沉**：`point_in_time_pick` 移入 `universe.py`，build_universe 与 data 都从那里导入，避免 tools 顶层脚本被包内 import）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_data.py
import json
from pathlib import Path

from sector_rotation.data import build_weekly_frame
from sector_rotation.universe import Member, UniverseSpec

SPEC = UniverseSpec(
    members=[Member("881101", "工程机械", ("528030.SH", "528031.SH"), 0.10)],
    clusters={})


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


def _etf_rows(first, weekly):
    rows = []
    d = first
    for open_, close, amount in weekly:
        rows.append({"date": d, "open": open_, "close": close, "amount": amount})
        d = _next_day(d)
    return rows


def _next_day(d: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def test_point_in_time_symbol_selection(tmp_path: Path):
    _write(tmp_path / "sector/series/881101.jsonl",
           [{"date": "2026-11-06", "close": 100.0}, {"date": "2026-11-13", "close": 101.0}])
    # 528030：2020 年上市且均额 3 亿（达标）；528031：2025 年上市（不达标）
    _write(tmp_path / "market/series/528030.SH.jsonl",
           _etf_rows("2020-01-02", [(1.0, 1.01, 3e8)] * 1500))
    _write(tmp_path / "market/series/528031.SH.jsonl",
           _etf_rows("2025-06-02", [(1.0, 1.01, 5e8)] * 360))
    _write(tmp_path / "market/series/510300.SH.jsonl",
           _etf_rows("2020-01-02", [(1.0, 1.02, 1e9)] * 1500))
    wf = build_weekly_frame(tmp_path, SPEC)
    assert wf.etf_symbols[0][0] == "528030.SH"     # point-in-time 选中老 ETF
    assert wf.valid[0][0]
    assert wf.bench_300.shape == (len(wf.fridays),)
```

（执行注：构造 1500 根连续日历日虽含周末——point_in_time_pick 只比日期不比交易日，行为正确；`etf_open/close` 对齐逻辑若因周末日期错位导致 valid False，修 fixture 用真实周节奏 [周一..周五] × 300 周，断言不变。）

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现 data.py**

```python
# tools/sector-rotation/sector_rotation/data.py
"""point-in-time 周五决策帧（spec §3.1/§3.3）：每周执行 ETF 由当时达标规则择一。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from .universe import Member, UniverseSpec, point_in_time_pick

TWO_YEARS_DAYS = 730


@dataclass
class WeeklyFrame:
    fridays: list[str]
    index_close: np.ndarray
    etf_symbols: list[list[str]]
    etf_open: np.ndarray
    etf_close: np.ndarray
    etf_prev_close: np.ndarray
    etf_week_amount: np.ndarray
    members: list[Member] = field(repr=False)
    spec: UniverseSpec = field(repr=False)
    valid: np.ndarray
    bench_300: np.ndarray


def _load_daily(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                row = json.loads(ln)
                out[row["date"]] = row
    return out


def _week_key(d: str) -> int:
    day = date.fromisoformat(d)
    iso = day.isocalendar()
    return date.fromisocalendar(iso[0], iso[1], 1).toordinal()


def build_weekly_frame(data_root: Path, spec: UniverseSpec,
                       *, bench_symbol: str = "510300.SH") -> WeeklyFrame:
    members = spec.members
    idx_series = [_load_daily(data_root / "sector" / "series" / f"{m.index_code}.jsonl")
                  for m in members]
    all_etf_syms = sorted({s for m in members for s in m.etf_candidates})
    etf_data = {s: _load_daily(data_root / "market" / "series" / f"{s}.jsonl")
                for s in all_etf_syms}
    bars = {s: [row for row in series.values()]
            for s, series in ((s, dict(sorted(etf_data[s].items()))) for s in all_etf_syms)}

    week_last: list[dict[int, dict]] = []
    for series in idx_series:
        by_week: dict[int, dict] = {}
        for d in sorted(series):
            wk = _week_key(d)
            by_week[wk] = {"date": d, "row": series[d]}
        week_last.append(by_week)
    etf_bounds = []
    for s in all_etf_syms:
        first, last, prev_last, amt = {}, {}, {}, {}
        for d in sorted(etf_data[s]):
            wk = _week_key(d)
            if wk not in first:
                first[wk] = etf_data[s][d]
            prev_last[wk] = last.get(wk)
            last[wk] = etf_data[s][d]
        rows_by_week: dict[int, list[dict]] = {}
        for d in sorted(etf_data[s]):
            rows_by_week.setdefault(_week_key(d), []).append(etf_data[s][d])
        amt = {wk: sum(r["amount"] for r in rows) / len(rows)
               for wk, rows in rows_by_week.items()}
        etf_bounds.append((first, last, prev_last, amt))

    bench = _load_daily(data_root / "market" / "series" / f"{bench_symbol}.jsonl")
    bench_first, bench_last = {}, {}
    for d in sorted(bench):
        wk = _week_key(d)
        bench_first.setdefault(wk, bench[d])
        bench_last[wk] = bench[d]

    all_weeks = sorted({wk for by_week in week_last for wk in by_week})
    T, L = len(all_weeks), len(members)
    shape = (T, L)
    idx_close = np.full(shape, np.nan)
    etf_symbols = [[""] * L for _ in range(T)]
    etf_open = np.full(shape, np.nan)
    etf_close = np.full(shape, np.nan)
    etf_prev = np.full(shape, np.nan)
    etf_amt = np.full(shape, np.nan)
    valid = np.zeros(shape, dtype=bool)
    bench_ret = np.full(T, np.nan)
    fridays: list[str] = []
    for ti, wk in enumerate(all_weeks):
        fridays.append(max(by_week[wk]["date"] for by_week in week_last if wk in by_week))
        next_wk = next((c for c in (wk + 7, wk + 14) if c in bench_first), None)
        if next_wk is not None:
            bench_ret[ti] = (bench_last[next_wk]["close"]
                             / bench_first[next_wk].get("open",
                                                        bench_first[next_wk]["close"]) - 1)
        for li, m in enumerate(members):
            if wk in week_last[li]:
                idx_close[ti, li] = float(week_last[li][wk]["row"]["close"])
            pick = point_in_time_pick(list(m.etf_candidates), bars, fridays[-1])
            if pick is None:
                continue
            bi = all_etf_syms.index(pick)
            first, last, prev_last, amt = etf_bounds[bi]
            next_wk = next((c for c in (wk + 7, wk + 14) if c in first), None)
            if next_wk is None:
                continue
            etf_symbols[ti][li] = pick
            etf_open[ti, li] = float(first[next_wk].get("open", first[next_wk]["close"]))
            etf_close[ti, li] = float(last[next_wk]["close"])
            if wk in last:
                etf_prev[ti, li] = float(last[wk]["close"])
            etf_amt[ti, li] = float(amt.get(next_wk, np.nan))
            valid[ti, li] = bool(np.isfinite(idx_close[ti, li])
                                 and np.isfinite(etf_open[ti, li])
                                 and np.isfinite(etf_close[ti, li])
                                 and np.isfinite(etf_prev[ti, li]))
    return WeeklyFrame(fridays, idx_close, etf_symbols, etf_open, etf_close,
                       etf_prev, etf_amt, members, spec, valid, bench_ret)
```

（执行注：`point_in_time_pick` 从 Task 3 的 build_universe.py **下沉到 sector_rotation/universe.py**（连测试一起搬），build_universe 改为从包内导入——本任务 Step 3 一并完成该搬运并跑两个测试文件确认全绿。）

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_data.py tests/test_sr_universe_build.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/data.py tools/sector-rotation/sector_rotation/universe.py tools/sector-rotation/build_universe.py tests/test_sr_data.py tests/test_sr_universe_build.py
git commit -m "feat(sector-rotation): point-in-time WeeklyFrame（Task 4，含 pick 下沉）"
```

---

### Task 5: weekly.py——窗口块 + 训练窗内标准化 + 标签

**Files:**
- Create: `tools/sector-rotation/sector_rotation/weekly.py`
- Test: `tests/test_sr_weekly.py`

**Interfaces:**
- Consumes: Task 4 `WeeklyFrame`。
- Produces:

```python
def weekly_gross_returns(wf: WeeklyFrame) -> np.ndarray   # (T, L) close/open-1（毛口径）

def window_blocks(wf: WeeklyFrame, *, window: int = 13
                  ) -> tuple[np.ndarray, np.ndarray]:
    """→ (blocks, t_index)：blocks[i] = window×L 展平的原始（未标准化）特征块；
    t_index[i] = 可用决策帧行号（连续 window 个指数周齐）。"""

def standardize_fit_apply(blocks_train: np.ndarray, blocks_now: np.ndarray
                          ) -> np.ndarray:
    """训练窗内逐特征位 z-score（mu/sd 只来自 blocks_train），应用到当前帧。
    spec v1.2 I-4：禁止全样本统计——本函数是唯一标准化入口。"""
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_weekly.py
import numpy as np

from sector_rotation.data import WeeklyFrame
from sector_rotation.universe import Member, UniverseSpec
from sector_rotation.weekly import (standardize_fit_apply, weekly_gross_returns,
                                    window_blocks)

M1 = Member("881101", "机械", ("528030.SH",), 0.10)
SPEC = UniverseSpec([M1], {})


def _wf(T=15):
    rng = np.random.default_rng(3)
    return WeeklyFrame(
        fridays=[f"2026-w{i:02d}" for i in range(T)],
        index_close=rng.normal(100, 5, (T, 1)),
        etf_symbols=[["528030.SH"]] * T,
        etf_open=np.full((T, 1), 1.0), etf_close=np.full((T, 1), 1.02),
        etf_prev_close=np.full((T, 1), 0.99), etf_week_amount=np.full((T, 1), 2e8),
        members=[M1], spec=SPEC, valid=np.ones((T, 1), bool),
        bench_300=np.full(T, 0.001))


def test_gross_return_is_close_over_open_minus_1():
    assert np.allclose(weekly_gross_returns(_wf()), 0.02)


def test_standardize_uses_train_stats_only():
    train = np.array([[1.0, 10.0], [3.0, 30.0], [5.0, 50.0], [7.0, 70.0]])
    now = np.array([[4.0, 40.0]])
    out = standardize_fit_apply(train, now)
    # mu=(4,40), sd(train, ddof=0)=sqrt(5) 每列 → 4→0、40→0
    assert np.allclose(out, [[0.0, 0.0]])
    train2 = np.full((4, 2), 5.0)            # 零方差列 → sd 兜底 1，不除零
    assert np.isfinite(standardize_fit_apply(train2, now)).all()


def test_window_blocks_shape():
    blocks, t_index = window_blocks(_wf(T=15), window=4)
    assert blocks.shape == (11, 4) and t_index[0] == 4
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/weekly.py
"""特征窗口与标签（spec §3.3，v1.2 I-4：标准化只进训练窗统计）。"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame


def weekly_gross_returns(wf: WeeklyFrame) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        r = wf.etf_close / wf.etf_open - 1.0
    return np.where(np.isfinite(r), r, np.nan)


def window_blocks(wf: WeeklyFrame, *, window: int = 13
                  ) -> tuple[np.ndarray, np.ndarray]:
    ok = np.isfinite(wf.index_close).all(axis=1)
    feats, t_index = [], []
    for t in range(window, len(wf.fridays)):
        rows = np.arange(t - window, t)
        if ok[rows].all():
            feats.append(wf.index_close[rows, :].reshape(-1))
            t_index.append(t)
    return np.array(feats, dtype=float), np.array(t_index, dtype=int)


def standardize_fit_apply(blocks_train: np.ndarray, blocks_now: np.ndarray
                          ) -> np.ndarray:
    mu = blocks_train.mean(axis=0)
    sd = blocks_train.std(axis=0)
    sd = np.where((~np.isfinite(sd)) | (sd == 0), 1.0, sd)
    return (blocks_now - mu) / sd
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_weekly.py -v`
Expected: PASS（3 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/weekly.py tests/test_sr_weekly.py
git commit -m "feat(sector-rotation): 窗口块 + 训练窗标准化 + 标签（Task 5）"
```

---

### Task 6: cost.py——两档成本模型

**Files:**
- Create: `tools/sector-rotation/sector_rotation/cost.py`
- Test: `tests/test_sr_cost.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 1.0   # 万1 双边各收
    spread_bps: float = 10.0      # 全宽点差，每边计半宽；基准档 10 / 压力档 20（spec §3.7）
    impact_bps: float = 0.0

    @classmethod
    def base(cls) -> "CostModel":        # 10bp
    @classmethod
    def stress(cls) -> "CostModel":      # 20bp（闸门兜底档）
    def side_bps(self) -> float
    def roundtrip_bps(self) -> float
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_cost.py
from sector_rotation.cost import CostModel


def test_two_tiers():
    assert CostModel.base().spread_bps == 10.0
    assert CostModel.stress().spread_bps == 20.0
    assert CostModel.base().side_bps() == 1.0 + 5.0
    assert CostModel.stress().roundtrip_bps() == 2 * (1.0 + 10.0)
```

- [ ] **Step 2: 失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/cost.py
"""两档成本模型（spec §3.7 v1.2：历史段禁今日实测点差，闸门两档都过）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 1.0
    spread_bps: float = 10.0
    impact_bps: float = 0.0

    @classmethod
    def base(cls) -> "CostModel":
        return cls(spread_bps=10.0)

    @classmethod
    def stress(cls) -> "CostModel":
        return cls(spread_bps=20.0)

    def side_bps(self) -> float:
        return self.commission_bps + self.spread_bps / 2 + self.impact_bps

    def roundtrip_bps(self) -> float:
        return 2 * self.side_bps()
```

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_cost.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/cost.py tests/test_sr_cost.py
git commit -m "feat(sector-rotation): 两档成本模型（Task 6）"
```

---

### Task 7: metrics.py——指标集

**Files:**
- Create: `tools/sector-rotation/sector_rotation/metrics.py`
- Test: `tests/test_sr_metrics.py`

**Interfaces:**
- Produces:

```python
def compute_metrics(nav: np.ndarray, weekly_ret: np.ndarray, *,
                    benchmark_nav: np.ndarray | None = None,
                    turnover: float = 0.0, cost_drag: float = 0.0,
                    cluster_binds: int = 0, weeks_per_year: int = 52) -> dict[str, float]
# {"cagr","alpha","sharpe","max_dd","win_rate","turnover","cost_drag","cluster_binds"}
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_metrics.py
import numpy as np

from sector_rotation.metrics import compute_metrics


def test_flat_nav_metrics():
    m = compute_metrics(np.ones(53), np.zeros(52),
                        benchmark_nav=np.linspace(1, 1.1, 53),
                        turnover=2.0, cost_drag=0.0012, cluster_binds=3)
    assert m["cagr"] == 0.0 and m["alpha"] < 0 and m["win_rate"] == 0.0
    assert m["cluster_binds"] == 3


def test_steady_growth():
    r = np.full(52, 0.001)
    nav = np.concatenate([[1.0], np.cumprod(1 + r)])
    m = compute_metrics(nav, r)
    assert abs(m["cagr"] - (1.001 ** 52 - 1)) < 1e-9
    assert np.isnan(m["sharpe"])            # 零波动约定 nan，报告层注明
    assert m["win_rate"] == 1.0
```

- [ ] **Step 2: 失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/metrics.py
"""回测指标（spec §3.8；sharpe 零波动约定 nan）。"""
from __future__ import annotations

import numpy as np


def compute_metrics(nav: np.ndarray, weekly_ret: np.ndarray, *,
                    benchmark_nav: np.ndarray | None = None,
                    turnover: float = 0.0, cost_drag: float = 0.0,
                    cluster_binds: int = 0, weeks_per_year: int = 52) -> dict[str, float]:
    years = len(weekly_ret) / weeks_per_year
    cagr = float(nav[-1] / nav[0]) ** (1 / years) - 1 if years > 0 else 0.0
    if benchmark_nav is not None:
        bench = float(benchmark_nav[-1] / benchmark_nav[0]) ** (1 / years) - 1
        alpha = cagr - bench
    else:
        alpha = 0.0
    mu, sd = float(np.mean(weekly_ret)), float(np.std(weekly_ret, ddof=1))
    sharpe = float(mu / sd * np.sqrt(weeks_per_year)) if sd > 0 else float("nan")
    peak = np.maximum.accumulate(nav)
    return {"cagr": cagr, "alpha": alpha, "sharpe": sharpe,
            "max_dd": float((nav / peak - 1.0).min()),
            "win_rate": float((weekly_ret > 0).mean()),
            "turnover": turnover, "cost_drag": cost_drag,
            "cluster_binds": float(cluster_binds)}
```

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/metrics.py tests/test_sr_metrics.py
git commit -m "feat(sector-rotation): 指标集含同簇触发频率（Task 7）"
```

---

### Task 8: baselines.py——point-in-time 对照组 + L0

**Files:**
- Create: `tools/sector-rotation/sector_rotation/baselines.py`
- Test: `tests/test_sr_baselines.py`

**Interfaces:**
- Consumes: Task 4 `WeeklyFrame`。
- Produces（统一 `select(wf, t) -> dict[int, float]`）：

```python
def equal_weight(wf, t) -> dict[int, float]                  # 对照①：当周 valid 全体等权
def momentum_topk(wf, t, *, lookback: int = 1, k: int = 3)   # L0 动量（主检验配置之一）
def reversal_topk(wf, t, *, lookback: int = 1, k: int = 3)   # L0 反转
def random_k(wf, t, *, k: int = 3, seed: int = 0)            # 对照③：噪音
```

（对照②=L0 自身，对照④=沪深300 持有由 walkforward 层用 `wf.bench_300` 特判，不进策略协议。）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_baselines.py
import numpy as np

from sector_rotation.baselines import equal_weight, momentum_topk, random_k, reversal_topk
from sector_rotation.data import WeeklyFrame
from sector_rotation.universe import Member, UniverseSpec

M2 = [Member("881101", "机械", ("E1.SH",), 0.10),
      Member("881127", "半导体", ("E2.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def _wf(index_rows, valid=None):
    T, L = index_rows.shape
    return WeeklyFrame(
        fridays=[f"w{i}" for i in range(T)], index_close=index_rows,
        etf_symbols=[["E1.SH", "E2.SH"]] * T,
        etf_open=np.ones((T, L)), etf_close=np.ones((T, L)),
        etf_prev_close=np.ones((T, L)), etf_week_amount=np.full((T, L), 2e8),
        members=M2, spec=SPEC,
        valid=valid if valid is not None else np.ones((T, L), bool),
        bench_300=np.full(T, 0.001))


def test_momentum_picks_topk_by_trailing_return():
    idx = np.array([[100.0, 100.0], [101.0, 110.0], [101.0, 120.0]])
    assert momentum_topk(_wf(idx), 2, lookback=2, k=1) == {1: 1.0}
    assert reversal_topk(_wf(idx), 2, lookback=2, k=1) == {0: 1.0}


def test_equal_weight_only_valid_members():
    v = np.ones((3, 2), bool); v[2, 1] = False        # point-in-time：半导体当周出宇宙
    assert equal_weight(_wf(np.ones((3, 2)), v), 2) == {0: 1.0}


def test_random_k_deterministic():
    wf = _wf(np.ones((3, 2)))
    assert random_k(wf, 2, k=1, seed=7) == random_k(wf, 2, k=1, seed=7)
```

- [ ] **Step 2: 失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/baselines.py
"""对照组与 L0（spec §3.4/§3.8）。只选当周 valid（point-in-time 宇宙）成员。"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame


def _valid(wf: WeeklyFrame, t: int) -> list[int]:
    return [i for i in range(len(wf.members)) if wf.valid[t, i]]


def equal_weight(wf: WeeklyFrame, t: int) -> dict[int, float]:
    cols = _valid(wf, t)
    return {i: 1.0 / len(cols) for i in cols} if cols else {}


def _rank_topk(wf: WeeklyFrame, t: int, *, lookback: int, k: int,
               reverse: bool) -> dict[int, float]:
    cols = _valid(wf, t)
    rets = {i: wf.index_close[t, i] / wf.index_close[t - lookback, i] - 1.0
            for i in cols
            if t - lookback >= 0 and np.isfinite(wf.index_close[t - lookback, i])}
    ranked = sorted(rets, key=lambda i: rets[i], reverse=reverse)
    picked = ranked[:k]
    return {i: 1.0 / len(picked) for i in picked} if picked else {}


def momentum_topk(wf: WeeklyFrame, t: int, *, lookback: int = 1, k: int = 3
                  ) -> dict[int, float]:
    return _rank_topk(wf, t, lookback=lookback, k=k, reverse=True)


def reversal_topk(wf: WeeklyFrame, t: int, *, lookback: int = 1, k: int = 3
                  ) -> dict[int, float]:
    return _rank_topk(wf, t, lookback=lookback, k=k, reverse=False)


def random_k(wf: WeeklyFrame, t: int, *, k: int = 3, seed: int = 0
             ) -> dict[int, float]:
    cols = _valid(wf, t)
    if not cols:
        return {}
    rng = np.random.default_rng(seed * 10_000 + t)
    picked = list(rng.choice(cols, size=min(k, len(cols)), replace=False))
    return {i: 1.0 / len(picked) for i in picked}
```

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_baselines.py -v`
Expected: PASS（3 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/baselines.py tests/test_sr_baselines.py
git commit -m "feat(sector-rotation): point-in-time 对照组与 L0（Task 8）"
```

---

### Task 9: portfolio.py——执行闸门（含周内迟滞）+ 风控 + 持币式同簇截断

**Files:**
- Create: `tools/sector-rotation/sector_rotation/portfolio.py`
- Test: `tests/test_sr_portfolio.py`

**Interfaces:**
- Consumes: Task 4 `WeeklyFrame`、Task 1 `cluster_for`、Task 6 `CostModel`。
- Produces:

```python
class RiskState:
    def __init__(self, spec: UniverseSpec, *, enabled: bool = True): ...
    def apply(self, t: int, wf: WeeklyFrame, desired: dict[int, float],
              last_week_pos_returns: dict[int, float] | None) -> dict[int, float]
    # 持币式同簇截断（spec §3.6 v1.2）：簇内 >2 截断后**不重新归一**，空出资 = 现金；
    # 簇表用 cluster_for(spec, wf.fridays[t])，None 代 → 同簇约束跳过 + binds 不计数
    binds: int    # 同簇截断触发次数（报告披露）

def simulate_week(wf, t, weights_prev, weights_new, cost) -> tuple[float, dict, dict]
    # 涨停弃买 / 跌停顺延（简化口径）/ 周内流动性迟滞（etf_week_amount < 5000 万拦截）
    # → (周净收益, 各持仓毛收益, 明细)
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_portfolio.py
import numpy as np

from sector_rotation.cost import CostModel
from sector_rotation.data import WeeklyFrame
from sector_rotation.portfolio import RiskState, simulate_week
from sector_rotation.universe import Member, UniverseSpec

M4 = [Member("A1", "光伏", ("E1.SH",), 0.10), Member("A2", "风电", ("E2.SH",), 0.10),
      Member("A3", "储能", ("E3.SH",), 0.10), Member("B1", "银行", ("E4.SH",), 0.10)]
SPEC = UniverseSpec(M4, {2019: {"A1": "s", "A2": "s", "A3": "s", "B1": "o"}})


def _wf(open_, close_, prev_close, week_amount=None, valid=None, fridays=None):
    T, L = open_.shape
    return WeeklyFrame(
        fridays=fridays or ["2020-01-03"] * T, index_close=np.ones((T, L)),
        etf_symbols=[["E1.SH", "E2.SH", "E3.SH", "E4.SH"]] * T,
        etf_open=open_, etf_close=close_, etf_prev_close=prev_close,
        etf_week_amount=week_amount if week_amount is not None
        else np.full((T, L), 2e8),
        members=M4, spec=SPEC,
        valid=valid if valid is not None else np.ones((T, L), bool),
        bench_300=np.full(T, 0.0))


def test_cluster_cap_holds_cash_not_renormalized():
    rs = RiskState(SPEC)
    wf = _wf(np.full((1, 4), 1.0), np.full((1, 4), 1.01), np.full((1, 4), 0.99))
    got = rs.apply(0, wf, {0: 1 / 3, 1: 1 / 3, 2: 1 / 3}, None)
    same = [i for i in got if SPEC.clusters[2019][f"A{i + 1}"] == "s"]
    assert len(same) == 2 and rs.binds == 1
    assert sum(got.values()) < 1.0 - 1e-9      # 截断资金持币（每权 1/3，剩 2/3）


def test_no_cluster_generation_skips_constraint():
    rs = RiskState(SPEC)
    wf = _wf(np.full((1, 4), 1.0), np.full((1, 4), 1.01), np.full((1, 4), 0.99),
             fridays=["2018-06-01"])           # 2019 代 2021 年才可用
    got = rs.apply(0, wf, {0: 0.25, 1: 0.25, 2: 0.25}, None)
    assert len(got) == 3 and rs.binds == 0


def test_limit_up_blocks_buy_and_weekly_liquidity_gate():
    wf = _wf(np.array([[1.10, 1.0]]), np.array([[1.10, 1.02]]),
             np.array([[1.0, 1.0]]),
             week_amount=np.array([[2e8, 3e7]]))    # 2 号周内均额 3000 万 <5000 万
    net, pos, detail = simulate_week(wf, 0, {}, {0: 0.5, 1: 0.5}, CostModel.base())
    assert 0 not in pos and detail["blocked"][0] == "limit_up"
    assert 1 not in pos and detail["blocked"][1] == "liquidity"


def test_simulate_week_roundtrip_cost():
    wf = _wf(np.array([[1.0]]), np.array([[1.10]]), np.array([[0.99]]))
    net, pos, _ = simulate_week(wf, 0, {}, {0: 1.0}, CostModel.base())
    assert abs(pos[0] - 0.10) < 1e-12
    assert abs(net - (0.10 - CostModel.base().roundtrip_bps() / 1e4)) < 1e-9


def test_consecutive_loss_weeks_pause():
    rs = RiskState(SPEC)
    wf = _wf(np.full((5, 4), 1.0), np.full((5, 4), 0.99), np.full((5, 4), 1.0),
             fridays=[f"2020-01-{i:02d}" for i in range(1, 6)])
    out = {0: 0.5}
    for t in range(4):
        out = rs.apply(t, wf, {0: 0.5}, {0: -0.01})
    assert out == {}
```

- [ ] **Step 2: 失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/portfolio.py
"""执行闸门/风控/持币式同簇截断（spec §3.5/§3.6 v1.2）。"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .cost import CostModel
from .data import WeeklyFrame
from .universe import UniverseSpec, cluster_for

WEEKLY_MIN_AMOUNT_WAN = 5000.0


class RiskState:
    def __init__(self, spec: UniverseSpec, *, enabled: bool = True):
        self.spec = spec
        self.enabled = enabled
        self.loss_weeks = 0
        self.wins: dict[int, list[bool]] = {i: [] for i in range(len(spec.members))}
        self.cooldown: dict[int, int] = {}
        self.banned: set[int] = set()
        self.binds = 0

    def apply(self, t: int, wf: WeeklyFrame, desired: dict[int, float],
              last_week_pos_returns: dict[int, float] | None) -> dict[int, float]:
        if not self.enabled:
            return dict(desired)
        if last_week_pos_returns:
            if all(r < 0 for r in last_week_pos_returns.values()):
                self.loss_weeks += 1
            else:
                self.loss_weeks = 0
            for i, r in last_week_pos_returns.items():
                self.wins[i].append(r > 0)
                if r <= -0.05:
                    self.banned.add(i)
                hist = self.wins[i][-8:]
                if len(hist) == 8 and sum(hist) / 8 < 0.45:
                    self.cooldown[i] = 2
        if self.loss_weeks >= 4:
            self.loss_weeks = 0
            return {}
        cmap = cluster_for(self.spec, wf.fridays[t])   # None 代 → 约束跳过
        picked: dict[int, float] = {}
        cluster_cnt: Counter[str] = Counter()
        for i in sorted(desired, key=lambda j: -desired[j]):
            if i in self.banned or self.cooldown.get(i, 0) > 0:
                continue
            if cmap is not None:
                cl = cmap.get(wf.members[i].index_code)
                if cl is not None:
                    if cluster_cnt[cl] >= 2:
                        self.binds += 1              # 持币：不补位不归一
                        continue
                    cluster_cnt[cl] += 1
            picked[i] = desired[i]                   # 权重原值保留，截断资 = 现金
        for i in list(self.cooldown):
            self.cooldown[i] -= 1
            if self.cooldown[i] <= 0:
                del self.cooldown[i]
        self.banned.clear()
        return picked


def simulate_week(wf: WeeklyFrame, t: int, weights_prev: dict[int, float],
                  weights_new: dict[int, float], cost: CostModel
                  ) -> tuple[float, dict[int, float], dict[int, float]]:
    blocked: dict[int, str] = {}
    executed: dict[int, float] = {}
    for i, w in weights_new.items():
        member = wf.members[i]
        limit_up = wf.etf_prev_close[t, i] * (1 + member.limit_pct * 0.995)
        if not np.isfinite(wf.etf_open[t, i]) or wf.etf_open[t, i] >= limit_up:
            blocked[i] = "limit_up"
        elif (not np.isfinite(wf.etf_week_amount[t, i])
              or wf.etf_week_amount[t, i] < WEEKLY_MIN_AMOUNT_WAN * 1e4):
            blocked[i] = "liquidity"
        else:
            executed[i] = w
    gross = {i: wf.etf_close[t, i] / wf.etf_open[t, i] - 1.0 for i in executed}
    port_gross = sum(executed[i] * gross[i] for i in executed)
    sell_notional = sum(weights_prev.values())
    buy_notional = sum(executed.values())
    costs = (sell_notional + buy_notional) * cost.side_bps() / 1e4
    detail = {"blocked": blocked, "turnover": sell_notional + buy_notional,
              "gross": port_gross, "costs": costs}
    return port_gross - costs, gross, detail
```

（执行注：跌停顺延首版简化——周五清仓一律按 close 计损益，顺延只影响成本时点（周频口径影响 ≤1bp），README 已知限制声明；`etf_open` 为 nan 的 missing 情形并入 limit_up 拦截分支并记 `blocked="missing"`——执行时把首个分支拆开分别记。） 

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_portfolio.py -v`
Expected: PASS（5 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/portfolio.py tests/test_sr_portfolio.py
git commit -m "feat(sector-rotation): 闸门/风控/持币式同簇截断（Task 9）"
```

---

### Task 10: walkforward.py（覆盖率起点）+ permtest.py（置换 + block bootstrap 配对）

**Files:**
- Create: `tools/sector-rotation/sector_rotation/walkforward.py`、`tools/sector-rotation/sector_rotation/permtest.py`
- Test: `tests/test_sr_walkforward.py`

**Interfaces:**
- Consumes: Task 4-9。
- Produces:

```python
@dataclass
class WalkResult:
    nav: np.ndarray; nav_gross: np.ndarray; weekly: np.ndarray
    metrics: dict[str, float]; trades: list[dict]

def coverage_start(wf: WeeklyFrame, *, min_coverage: float = 0.8) -> int
    # spec §3.8 I-5：覆盖率（valid 列占比）首次 ≥80% 的行号

def run_walkforward(wf, strategy, *, cost: CostModel, start: int | None = None,
                    risk: RiskState | None = None) -> WalkResult
    # start=None → coverage_start(wf)；对照组④沪深300 由 metrics 层用 bench_300 另算

def perm_test_vs_random(wf, cost, *, k, n=1000, strategy=None, start=None) -> dict
    # 检验矩阵行 1：置换检验（H0 无选股能力），单侧 p

def paired_block_bootstrap(diff: np.ndarray, *, block: int = 4, n: int = 1000,
                           seed: int = 0) -> float
    # 检验矩阵行 2-4：配对周收益差均值>0 的 block bootstrap 单侧 p
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_walkforward.py
import numpy as np

from sector_rotation.baselines import equal_weight, momentum_topk, random_k
from sector_rotation.cost import CostModel
from sector_rotation.data import WeeklyFrame
from sector_rotation.permtest import paired_block_bootstrap, perm_test_vs_random
from sector_rotation.universe import Member, UniverseSpec
from sector_rotation.walkforward import coverage_start, run_walkforward

M2 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def _wf(T=30, seed=5, valid=None):
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.002, 0.02, (T, 2)), axis=0)
    v = np.ones((T, 2), bool) if valid is None else valid
    v[-1, :] = False
    return WeeklyFrame([f"w{i}" for i in range(T)], idx,
                       [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                       1 + rng.normal(0.001, 0.02, (T, 2)), np.ones((T, 2)),
                       np.full((T, 2), 2e8), M2, SPEC, v, np.full(T, 0.001))


def test_coverage_start_finds_first_80pct_week():
    v = np.zeros((20, 2), bool)
    v[10:, :] = True                        # 第 10 周起覆盖率 100%
    assert coverage_start(_wf(T=20, valid=v)) == 10


def test_walkforward_uses_coverage_start_and_runs():
    wf = _wf()
    res = run_walkforward(wf, momentum_topk, cost=CostModel.base())
    assert res.nav[0] == 1.0 and len(res.nav) == len(res.weekly) + 1
    assert all(set(tr["holdings"]) <= {0, 1} for tr in res.trades)


def test_paired_block_bootstrap_positive_diff():
    rng = np.random.default_rng(1)
    diff = rng.normal(0.002, 0.01, 300)     # 真正的均值 >0
    p = paired_block_bootstrap(diff, block=4, n=500)
    assert 0 <= p < 0.1


def test_perm_test_p_in_range():
    out = perm_test_vs_random(_wf(T=40), CostModel.base(), k=1, n=30,
                              strategy=equal_weight)
    assert 0 <= out["p_value"] <= 1 and out["n_random"] == 30
```

- [ ] **Step 2: 失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/walkforward.py
"""walk-forward 引擎（spec §3.8：覆盖率 ≥80% 起点，起点晚于 2019-06 功效重估）。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .cost import CostModel
from .data import WeeklyFrame
from .metrics import compute_metrics
from .portfolio import RiskState, simulate_week


@dataclass
class WalkResult:
    nav: np.ndarray
    nav_gross: np.ndarray
    weekly: np.ndarray
    metrics: dict[str, float] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)


def coverage_start(wf: WeeklyFrame, *, min_coverage: float = 0.8) -> int:
    cov = wf.valid.mean(axis=1)
    hits = np.flatnonzero(cov >= min_coverage)
    return int(hits[0]) if len(hits) else len(wf.fridays) - 1


def run_walkforward(wf: WeeklyFrame, strategy, *, cost: CostModel,
                    start: int | None = None,
                    risk: RiskState | None = None) -> WalkResult:
    risk = risk or RiskState(wf.spec)
    start = coverage_start(wf) if start is None else start
    nav, nav_g = [1.0], [1.0]
    weekly, trades = [], []
    weights_prev: dict[int, float] = {}
    last_pos_returns: dict[int, float] | None = None
    turnover_acc = cost_acc = gross_acc = 0.0
    for t in range(start, len(wf.fridays)):
        if not wf.valid[t].any():
            continue
        desired = strategy.select(wf, t)
        weights_new = risk.apply(t, wf, desired, last_pos_returns)
        net, gross_pos, detail = simulate_week(wf, t, weights_prev, weights_new, cost)
        weekly.append(net)
        nav.append(nav[-1] * (1 + net))
        nav_g.append(nav_g[-1] * (1 + detail["gross"]))
        turnover_acc += detail["turnover"]
        cost_acc += detail["costs"]
        gross_acc += detail["gross"]
        last_pos_returns = gross_pos or None
        weights_prev = weights_new
        trades.append({"friday": wf.fridays[t], "holdings": sorted(weights_new),
                       "blocked": detail["blocked"], "detail": detail})
    nav_a, weekly_a = np.array(nav), np.array(weekly)
    metrics = compute_metrics(nav_a, weekly_a, turnover=turnover_acc,
                              cost_drag=(cost_acc / gross_acc) if gross_acc > 0 else 0.0,
                              cluster_binds=risk.binds)
    return WalkResult(nav_a, np.array(nav_g), weekly_a, metrics, trades)
```

```python
# tools/sector-rotation/sector_rotation/permtest.py
"""检验矩阵实现（spec §3.8）：置换检验 + block bootstrap 配对。"""
from __future__ import annotations

import numpy as np

from .baselines import random_k
from .cost import CostModel
from .data import WeeklyFrame
from .walkforward import run_walkforward


def perm_test_vs_random(wf: WeeklyFrame, cost: CostModel, *, k: int, n: int = 1000,
                        strategy=None, start: int | None = None) -> dict:
    obs = run_walkforward(wf, strategy or (lambda w, t: random_k(w, t, k=k, seed=0)),
                          cost=cost, start=start)
    rand = np.array([
        run_walkforward(wf, lambda w, t, s=seed: random_k(w, t, k=k, seed=s),
                        cost=cost, start=start).metrics["cagr"]
        for seed in range(n)])
    p = float((1 + (rand >= obs.metrics["cagr"]).sum()) / (1 + n))
    return {"observed_cagr": obs.metrics["cagr"], "p_value": p,
            "random_cagr_mean": float(rand.mean()),
            "random_cagr_p95": float(np.percentile(rand, 95)), "n_random": n}


def paired_block_bootstrap(diff: np.ndarray, *, block: int = 4, n: int = 1000,
                           seed: int = 0) -> float:
    """H0: 配对周差均值 ≤ 0。块自助（块长 4 周）重抽均值分布，返回单侧 p。"""
    diff = np.asarray(diff, dtype=float)
    diff = diff[np.isfinite(diff)]
    if len(diff) < block:
        return float("nan")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(len(diff) / block))
    obs_mean = diff.mean()
    count = 0
    for _ in range(n):
        idx = rng.integers(0, len(diff) - block + 1, size=n_blocks)
        sample = np.concatenate([diff[i:i + block] for i in idx])[:len(diff)]
        if sample.mean() >= obs_mean:
            count += 1
    return float((1 + count) / (1 + n))
```

（执行注：若 n=1000 全程重放 >30 分钟，两处都可降 n=500 并在报告注明——spec 允许 ≥1000 为目标值，降档须披露。策略周差 = `obs.weekly − bench_weekly`，等长对齐由调用方（T11）保证。） 

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_walkforward.py -v`
Expected: PASS（4 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/walkforward.py tools/sector-rotation/sector_rotation/permtest.py tests/test_sr_walkforward.py
git commit -m "feat(sector-rotation): 覆盖率起点引擎 + 检验矩阵统计（Task 10）"
```

---

### Task 11: backtest.py CLI + 检验矩阵报告 + P1 闸门（两档）

**Files:**
- Create: `tools/sector-rotation/backtest.py`
- Test: `tests/test_sr_backtest.py`

**Interfaces:**
- Consumes: Task 1-10。
- Produces: CLI `backtest.py --level L0 --tier base|stress|both --k 3 --lookback 1`（L0 默认读**预注册配置**，非预注册组合标"探索性"）；`render_report(results, tests, *, tag, tier_notes, prereg) -> str`；报告落 `output/sector-rotation/YYYY-MM/backtest-{tag}.md`，含检验矩阵表（行=检验，列=基准档/压力档 p 值与判定）、指标表（两档成本拖累各一列）、同簇触发频率、功效注释（GC 13 逐字）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_backtest.py
import numpy as np

import backtest  # noqa: E402
from sector_rotation.walkforward import WalkResult


def _res(cagr=0.10):
    weekly = np.full(52, 0.0019)
    nav = np.concatenate([[1.0], np.cumprod(1 + weekly)])
    return WalkResult(nav, nav.copy(), weekly,
                      {"cagr": cagr, "alpha": 0.02, "sharpe": 1.1, "max_dd": -0.1,
                       "win_rate": 0.55, "turnover": 90.0, "cost_drag": 0.11,
                       "cluster_binds": 4}, [])


def test_render_report_matrix_and_power_note():
    tests = {("L0", "vs 随机", "base"): 0.03, ("L0", "vs 随机", "stress"): 0.05,
             ("L0", "vs 等权", "base"): 0.04, ("L0", "vs 等权", "stress"): 0.12,
             ("L0", "vs 沪深300", "base"): 0.03, ("L0", "vs 沪深300", "stress"): 0.06}
    text = backtest.render_report(
        {"L0": _res(), "等权持有": _res(0.05), "随机k3": _res(0.04)},
        tests, tag="L0-预注册",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="k=3 / 方向=动量 / N=1（2026-11-XX 预注册）")
    assert "检验矩阵" in text and "未检出" in text          # 功效注释在
    assert "stress" in text and "vs 等权" in text
    assert "P1 闸门" in text and "未通过" in text           # stress 档 0.12 ≥0.1 → 未过
```

- [ ] **Step 2: 失败** → **Step 3: 实现 backtest.py**

```python
# tools/sector-rotation/backtest.py
"""检验矩阵回测 CLI（spec §3.8 v1.2：预注册主配置确认性检验，其余探索性）。"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.baselines import equal_weight, momentum_topk, random_k, reversal_topk  # noqa: E402
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import build_weekly_frame  # noqa: E402
from sector_rotation.permtest import paired_block_bootstrap, perm_test_vs_random  # noqa: E402
from sector_rotation.universe import load_universe  # noqa: E402
from sector_rotation.walkforward import WalkResult, run_walkforward  # noqa: E402

TIERS = {"base": CostModel.base, "stress": CostModel.stress}
POWER_NOTE = ("功效边界：样本外约 370 周，单侧 p<0.1 稳定检出的年化 α ≈5-7%；"
              "P1 证伪结论是「未检出 ≥5-7%/年的 α」，年化 3-4% 以下弱边际可能被错杀"
              "（spec §3.8 功效注释）。")


def render_report(results: dict[str, WalkResult],
                  tests: dict[tuple[str, str, str], float], *, tag: str,
                  tier_notes: dict[str, str], prereg: str) -> str:
    lines = [f"# 板块轮动回测报告：{tag}", "",
             f"- 生成：{date.today().isoformat()} · 预注册主配置：{prereg}",
             f"- 点差档：基准 {tier_notes['base']} / 压力 {tier_notes['stress']}"
             "（佣金双边各 1bp，α 全部成本后口径）", "",
             "| 策略 | CAGR | Sharpe | MaxDD | 胜率 | 换手 | 成本拖累 | 同簇截断 |",
             "|---|---|---|---|---|---|---|---|"]
    for name, res in results.items():
        m = res.metrics
        lines.append(f"| {name} | {m['cagr']:.2%} | {m['sharpe']:.2f} | "
                     f"{m['max_dd']:.2%} | {m['win_rate']:.1%} | {m['turnover']:.1f} | "
                     f"{m['cost_drag']:.1%} | {int(m['cluster_binds'])} |")
    lines += ["", "## 检验矩阵（单侧 p<0.1 判定，两档都须过）", "",
              "| 检验 | 基准档 p | 基准档 | 压力档 p | 压力档 |", "|---|---|---|---|---|"]
    for row in ("vs 随机", "vs 等权", "vs 沪深300", "vs L0"):
        cells = [row]
        for tier in ("base", "stress"):
            p = tests.get(("L0", row, tier))
            cells += ["—" if p is None else f"{p:.3f}",
                      "—" if p is None else ("过" if p < 0.1 else "未过")]
        lines.append("| " + " | ".join(cells) + " |")
    ok = all(tests.get(("L0", r, t), 1.0) < 0.1
             for r in ("vs 随机", "vs 等权", "vs 沪深300")
             for t in ("base", "stress"))
    lines += ["", f"> P1 闸门：{'**通过，可进 P2**' if ok else '**未通过，按 spec §5 停止并写结案报告**'}",
              "", POWER_NOTE, ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", choices=["L0", "L1", "L2"], default="L0")
    ap.add_argument("--tier", choices=["base", "stress", "both"], default="both")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--lookback", type=int, default=1, choices=[1, 4])
    ap.add_argument("--exploratory", action="store_true",
                    help="跑非预注册组合（报告标探索性，不判定）")
    ap.add_argument("--universe", type=Path,
                    default=REPO_ROOT / "config/sector-rotation-universe.md")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "output/sector-rotation")
    args = ap.parse_args(argv)
    spec = load_universe(args.universe)
    wf = build_weekly_frame(REPO_ROOT / "data", spec)
    tiers = ["base", "stress"] if args.tier == "both" else [args.tier]
    tests: dict[tuple[str, str, str], float] = {}
    results: dict[str, WalkResult] = {}
    for tier in tiers:
        cost = TIERS[tier]()
        strategies = {
            f"L0-动量-lb{args.lookback}":
                (lambda w, t: momentum_topk(w, t, lookback=args.lookback, k=args.k)),
            "L0-反转": (lambda w, t: reversal_topk(w, t, lookback=args.lookback, k=args.k)),
            "等权持有": equal_weight,
            f"随机k{args.k}": (lambda w, t: random_k(w, t, k=args.k, seed=0)),
        }
        if args.level in ("L1", "L2"):
            from sector_rotation.models import make_strategy
            strategies[args.level] = make_strategy(args.level, k=args.k)
        tier_res = {n: run_walkforward(wf, s, cost=cost)
                    for n, s in strategies.items()}
        main_name = f"L0-动量-lb{args.lookback}" if args.level == "L0" else args.level
        main_res = tier_res[main_name]
        tests[(args.level, "vs 随机", tier)] = perm_test_vs_random(
            wf, cost, k=args.k, n=1000, strategy=strategies[main_name])["p_value"]
        for bench_name, row in (("等权持有", "vs 等权"), (None, "vs 沪深300")):
            bench_weekly = (tier_res[bench_name].weekly if bench_name
                            else wf.bench_300[1:1 + len(main_res.weekly)])
            tests[(args.level, row, tier)] = paired_block_bootstrap(
                main_res.weekly - bench_weekly)
        if args.level in ("L1", "L2"):
            tests[(args.level, "vs L0", tier)] = paired_block_bootstrap(
                main_res.weekly - tier_res[f"L0-动量-lb{args.lookback}"].weekly)
        if tier == "base":
            results = tier_res
        else:
            results.update({f"{n}·压力档": r for n, r in tier_res.items()})
    prereg = (f"k={args.k} / 方向=动量 / N={args.lookback}（预注册见 spec 实施记录）"
              if not args.exploratory else "探索性变体——只报告不判定")
    tag = f"{args.level}-k{args.k}-lb{args.lookback}"
    text = render_report(results, tests, tag=tag,
                         tier_notes={"base": "10bp", "stress": "20bp"}, prereg=prereg)
    out = args.out / f"{date.today():%Y-%m}" / f"backtest-{tag}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text, f"\n已写入 {out}", sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backtest.py -v`
Expected: PASS

- [ ] **Step 5: P1 闸门全量真实跑（预注册配置，两档）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 --k <预注册k> --lookback <预注册N>
```
Expected: 报告含检验矩阵两档 p 值。**读闸门**（GC 12/14）：三行 × 两档全 p<0.1 → 进 T12；任一 ≥0.1 → 停，写结案报告（含 GC 13 功效局限逐字）单独 commit。探索性变体（其他 k/方向/N）另跑标"探索性"。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backtest.py tests/test_sr_backtest.py
git commit -m "feat(sector-rotation): 检验矩阵回测 CLI + P1 闸门首跑（Task 11）"
```

（注：报告文件入不入库先 `git check-ignore -v output/sector-rotation/x.md` 确认，按 repo 现状处理。）

---

### Task 12: PyTorch 安装 + models.py L1（训练窗标准化接入）

**Files:**
- Create: `tools/sector-rotation/sector_rotation/models.py`
- Test: `tests/test_sr_models.py`

**Interfaces:**
- Consumes: Task 5 `window_blocks`/`standardize_fit_apply`/`weekly_gross_returns`、Task 4 `WeeklyFrame`。
- Produces:

```python
class LinearModel:
    def __init__(self, *, window: int = 13, epochs: int = 100, lr: float = 1e-2)
    def fit(self, blocks: np.ndarray, y: np.ndarray, r: np.ndarray) -> None
        # blocks 已是训练窗标准化后的窗口块（调用方 _prep 负责，I-4 合规）
    def select(self, wf: WeeklyFrame, t: int, *, k: int = 3) -> dict[int, float]

def make_strategy(level: str, *, k: int = 3, window: int = 13,
                  lambda_fin: float = LAMBDA_FIN, mc_dropout: bool = True,
                  roc: bool = True) -> object   # 返回带 select(wf, t) 的可调用
```

训练样本选取：`window_blocks` 的历史帧中，**只取 valid[t_i] 的帧**（label 需当周 point-in-time 可执行）；训练切片向前至多 104 周；标准化 mu/sd 只来自训练切片（`standardize_fit_apply(train_blocks, train_blocks)` + 同参数应用于当前帧）。

- [ ] **Step 1: 安装 torch**

```bash
conda run -n Quant-3.11 python -c "import torch; print(torch.__version__)" 2>/dev/null \
  || conda run -n Quant-3.11 python -m pip install "torch>=2.2"
conda run -n Quant-3.11 python -c "import torch; print(torch.__version__, torch.backends.mps.is_available())"
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_sr_models.py
import numpy as np
import pytest

pytest.importorskip("torch")

from sector_rotation.models import LinearModel, make_strategy  # noqa: E402
from sector_rotation.universe import Member, UniverseSpec  # noqa: E402

M2 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def toy_wf(T=160, seed=11):
    from sector_rotation.data import WeeklyFrame
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, 2)), axis=0)
    valid = np.ones((T, 2), bool); valid[-1] = False
    return WeeklyFrame([f"w{i}" for i in range(T)], idx,
                       [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                       1 + rng.normal(0, 0.03, (T, 2)), np.ones((T, 2)),
                       np.full((T, 2), 2e8), M2, SPEC, valid, np.full(T, 0.001))


def test_linear_model_learns_separable_signal():
    from sector_rotation.data import WeeklyFrame
    T = 160
    idx = np.zeros((T, 2))
    label_ret = np.zeros((T, 2))
    up = True
    for t in range(T):
        idx[t] = [110.0 if up else 90.0, 100.0]
        label_ret[t] = [0.05 if up else -0.05, 0.0]
        up = not up
    valid = np.ones((T, 2), bool); valid[-1] = False
    wf = WeeklyFrame([f"w{i}" for i in range(T)], idx,
                     [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                     1 + label_ret, np.ones((T, 2)), np.full((T, 2), 2e8),
                     M2, SPEC, valid, np.full(T, 0.001))
    assert 0 in make_strategy("L1", k=1).select(wf, T - 2)


def test_make_strategy_level_validation():
    with pytest.raises(ValueError, match="level"):
        make_strategy("L9")
```

- [ ] **Step 3: 失败** → **Step 4: 实现 models.py（L1，L2 占位）**

```python
# tools/sector-rotation/sector_rotation/models.py
"""L1（torch 线性）与 L2（MIMO 复刻）策略（spec §3.4）。

口径注：①训练=决策帧向前 104 周全量重训（论文为增量更新；小模型成本等价更干净）；
②标准化 mu/sd 只来自训练切片（v1.2 I-4）；③金融损失 = BCE + λ·(-(sigmoid·下周收益).mean())
——论文未给公式（spec §8-2 待验证），实现方口径，λ 消融验证；④ROC 阈值 trailing 对
（训练窗内预测 vs 当期标签，v1.2 I-4）。
"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame
from .weekly import standardize_fit_apply, weekly_gross_returns, window_blocks

TRAIN_WEEKS = 104
LAMBDA_FIN = 0.1
SEED = 20261105


def _torch():
    import torch
    torch.manual_seed(SEED)
    return torch


def _prep(wf: WeeklyFrame, t: int, *, window: int):
    """→ (X_train_std, y_train, r_train, x_now_std) | None。
    历史帧只取 valid（label point-in-time 可得）；标准化只来自训练切片。"""
    blocks, t_idx = window_blocks(wf, window=window)
    if len(t_idx) == 0 or t_idx[-1] < t or t not in set(t_idx.tolist()):
        return None
    r = weekly_gross_returns(wf)
    y = (r >= 0.01).astype(np.float32)
    r = r.astype(np.float32)
    rows = [j for j, tj in enumerate(t_idx) if tj < t and wf.valid[tj].all()]
    if len(rows) < window + 2:
        return None
    rows = rows[-TRAIN_WEEKS:]
    train = blocks[rows]
    X_train = standardize_fit_apply(train, train)
    now_row = int(np.flatnonzero(t_idx == t)[0])
    x_now = standardize_fit_apply(train, blocks[now_row:now_row + 1])[0]
    return (X_train, y[t_idx[rows]], r[t_idx[rows]], x_now)


class LinearModel:
    def __init__(self, *, window: int = 13, epochs: int = 100, lr: float = 1e-2):
        self.window, self.epochs, self.lr = window, epochs, lr

    def fit(self, blocks: np.ndarray, y: np.ndarray, r: np.ndarray) -> None:
        torch = _torch()
        Xt = torch.tensor(blocks, dtype=torch.float32)
        Yt, Rt = torch.tensor(y), torch.tensor(r)
        D, L = blocks.shape[1], y.shape[1]
        net = torch.nn.Linear(D, L)
        opt = torch.optim.Adam(net.parameters(), lr=self.lr)
        bce = torch.nn.BCEWithLogitsLoss()
        for _ in range(self.epochs):
            opt.zero_grad()
            logits = net(Xt)
            (bce(logits, Yt) - LAMBDA_FIN * (torch.sigmoid(logits) * Rt).mean()
             ).backward()
            opt.step()
        self.net = net

    def probs_now(self, x: np.ndarray) -> np.ndarray:
        torch = _torch()
        with torch.no_grad():
            z = self.net(torch.tensor(x, dtype=torch.float32)).numpy()
        return 1.0 / (1.0 + np.exp(-z))

    def select(self, wf: WeeklyFrame, t: int, *, k: int = 3) -> dict[int, float]:
        prep = _prep(wf, t, window=self.window)
        if prep is None:
            return {}
        X, y, r, x_now = prep
        self.fit(X, y, r)
        probs = self.probs_now(x_now)
        order = sorted(range(len(probs)), key=lambda i: -probs[i])
        picked = [i for i in order if wf.valid[t, i]][:k]
        return {i: 1.0 / len(picked) for i in picked} if picked else {}


def make_strategy(level: str, *, k: int = 3, window: int = 13,
                  lambda_fin: float = LAMBDA_FIN, mc_dropout: bool = True,
                  roc: bool = True) -> object:
    if level == "L1":
        strat = LinearModel(window=window)
        return lambda wf, t: strat.select(wf, t, k=k)  # type: ignore[return-value]
    if level == "L2":
        from functools import partial
        return partial(_l2_select, k=k, window=window,
                       lambda_fin=lambda_fin, mc_dropout=mc_dropout, roc=roc)
    raise ValueError(f"未知 level: {level}")


def _l2_select(wf: WeeklyFrame, t: int, *, k: int, window: int,
               lambda_fin: float, mc_dropout: bool, roc: bool) -> dict[int, float]:
    raise NotImplementedError("Task 13 实现")
```

（执行注：可分性测试若首跑未选中 0，先检查构造信号确可分再调 epochs/lr——不许放松断言凑绿。）

- [ ] **Step 5: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_models.py -v`
Expected: PASS（2 用例）

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/sector_rotation/models.py tests/test_sr_models.py
git commit -m "feat(sector-rotation): torch L1（训练窗标准化接入，Task 12）"
```

---

### Task 13: models.py L2——MIMO + MC dropout + ROC 阈值

**Files:**
- Modify: `tools/sector-rotation/sector_rotation/models.py`（替换 `_l2_select`）
- Test: `tests/test_sr_models.py`（追加）

**Interfaces:**
- Consumes: Task 12 `_prep`/`_torch`。
- Produces:

```python
class MimoModel:
    def __init__(self, n_features: int, n_assets: int, *,
                 hidden: tuple[int, ...] = (64, 64, 32, 32), dropout: float = 0.2)
    def fit(self, X, y, r, *, lambda_fin: float = LAMBDA_FIN) -> None
    def mc_dropout(self, x, *, T: int = 100) -> tuple[np.ndarray, np.ndarray]
        # confident = ≥80% 样本落在中位数 1σ 内（论文 §2.3）
    def thresholds(self, X_hist, y_hist) -> np.ndarray
        # 每资产 ROC Youden J（训练窗 trailing 对，I-4 合规）
```

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_sr_models.py 追加
def test_mc_dropout_confidence_shapes():
    from sector_rotation.models import MimoModel
    m = MimoModel(n_features=6, n_assets=2)
    rng = np.random.default_rng(1)
    m.fit(rng.normal(size=(120, 6)), rng.integers(0, 2, (120, 2)).astype(float),
          rng.normal(0, 0.02, (120, 2)), epochs=5)
    mean_probs, confident = m.mc_dropout(np.zeros(6), T=200)
    assert mean_probs.shape == (2,) and confident.dtype == bool


def test_thresholds_within_unit_interval():
    from sector_rotation.models import MimoModel
    m = MimoModel(n_features=4, n_assets=3)
    rng = np.random.default_rng(4)
    m.fit(rng.normal(size=(100, 4)), rng.integers(0, 2, (100, 3)).astype(float),
          rng.normal(0, 0.02, (100, 3)), epochs=5)
    th = m.thresholds(rng.normal(size=(100, 4)),
                      rng.integers(0, 2, (100, 3)).astype(float))
    assert th.shape == (3,) and ((th > 0) & (th < 1)).all()
```

- [ ] **Step 2: 失败** → **Step 3: 实现 L2（替换占位）**

```python
# models.py 追加
class MimoModel:
    def __init__(self, n_features: int, n_assets: int, *,
                 hidden: tuple[int, ...] = (64, 64, 32, 32), dropout: float = 0.2):
        torch = _torch()
        self.torch = torch
        layers, d = [], n_features
        for h in hidden:
            layers += [torch.nn.Linear(d, h), torch.nn.ReLU(),
                       torch.nn.Dropout(dropout)]
            d = h
        layers.append(torch.nn.Linear(d, n_assets))
        self.net = torch.nn.Sequential(*layers)

    def fit(self, X: np.ndarray, y: np.ndarray, r: np.ndarray, *,
            lambda_fin: float = LAMBDA_FIN, epochs: int = 150,
            lr: float = 1e-3) -> None:
        torch = self.torch
        Xt = torch.tensor(X, dtype=torch.float32)
        Yt, Rt = torch.tensor(y), torch.tensor(r)
        opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        bce = torch.nn.BCEWithLogitsLoss()
        self.net.train()
        for _ in range(epochs):
            opt.zero_grad()
            logits = self.net(Xt)
            loss = bce(logits, Yt)
            if lambda_fin > 0:
                loss = loss - lambda_fin * (torch.sigmoid(logits) * Rt).mean()
            loss.backward()
            opt.step()
        self.net.eval()

    @staticmethod
    def _probs(logits) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-logits.detach().numpy()))

    def mc_dropout(self, x: np.ndarray, *, T: int = 100
                   ) -> tuple[np.ndarray, np.ndarray]:
        torch = self.torch
        xt = torch.tensor(x, dtype=torch.float32)
        samples = []
        with torch.no_grad():
            for _ in range(T):                  # 推理期开 dropout（论文 MC dropout）
                self.net.train()
                samples.append(self._probs(self.net(xt)))
            self.net.eval()
        arr = np.array(samples)
        med, sd = np.median(arr, axis=0), arr.std(axis=0)
        within = np.mean(np.abs(arr - med) <= sd, axis=0)
        return arr.mean(axis=0), within >= 0.8

    def thresholds(self, X_hist: np.ndarray, y_hist: np.ndarray) -> np.ndarray:
        torch = self.torch
        probs = self._probs(self.net(torch.tensor(X_hist, dtype=torch.float32)))
        out = np.full(probs.shape[1], 0.5)
        for j in range(probs.shape[1]):
            p, yv = probs[:, j], y_hist[:, j]
            order = np.argsort(-p)
            ps, ys = p[order], yv[order]
            tp, fp = np.cumsum(ys), np.cumsum(1 - ys)
            P, N = ys.sum(), len(ys) - ys.sum()
            if P == 0 or N == 0:
                continue
            out[j] = ps[int(np.argmax(tp / P - fp / N))]   # Youden J
        return out


def _l2_select(wf: WeeklyFrame, t: int, *, k: int, window: int,
               lambda_fin: float, mc_dropout: bool, roc: bool) -> dict[int, float]:
    prep = _prep(wf, t, window=window)
    if prep is None:
        return {}
    X, y, r, x_now = prep
    model = MimoModel(X.shape[1], y.shape[1])
    model.fit(X, y, r, lambda_fin=lambda_fin)
    if mc_dropout:
        probs, confident = model.mc_dropout(x_now)
    else:
        probs, confident = model.mc_dropout(x_now, T=1), np.ones(y.shape[1], bool)
    th = model.thresholds(X, y) if roc else np.zeros(y.shape[1])
    cands = [i for i in range(len(probs))
             if confident[i] and probs[i] > th[i] and wf.valid[t, i]]
    cands.sort(key=lambda i: -probs[i])
    picked = cands[:k]
    return {i: 1.0 / len(picked) for i in picked} if picked else {}
```

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_models.py -v`
Expected: PASS（4 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/models.py tests/test_sr_models.py
git commit -m "feat(sector-rotation): L2 MIMO（MC dropout/ROC trailing/金融损失开关，Task 13）"
```

---

### Task 14: L1/L2 接入回测 + P2 闸门（检验矩阵全行两档）

**Files:**
- Modify: `tools/sector-rotation/backtest.py`（消融旗标 `--no-fin-loss/--no-mc-dropout/--no-roc` → `make_strategy` 开关；报告 tag 后缀 `ablation-*`，标探索性；`render_report` 补按自然年切 `weekly` 的探索性分年度 α 小表）
- Test: `tests/test_sr_backtest.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_sr_backtest.py 追加
def test_make_strategy_ablation_switches():
    from sector_rotation.models import make_strategy
    assert callable(make_strategy("L2", k=2, lambda_fin=0.0,
                                  mc_dropout=False, roc=False))
```

- [ ] **Step 2: 失败** → **Step 3: 实现**（旗标透传 + 分年度表：`yearly_table(weekly, fridays) -> str` 用 friday 年份分组算年化收益，探索性标注）

- [ ] **Step 4: 通过** → **Step 5: P2 闸门全量真实跑（两档）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L1 --k <预注册k>
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k <预注册k>
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k <预注册k> --no-fin-loss
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k <预注册k> --no-mc-dropout
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k <预注册k> --no-roc
```
Expected: 五份报告。**读闸门**（GC 12）：L2 检验矩阵四行（vs 随机/等权/沪深300/L0）× 两档全 p<0.1 → 进 T15；任一 ≥0.1 → 停 T15，写结案报告（含功效注释）。消融三份标探索性。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backtest.py tools/sector-rotation/sector_rotation/models.py tests/test_sr_backtest.py
git commit -m "feat(sector-rotation): L1/L2 接入 + 消融 + P2 闸门（Task 14）"
```

---

### Task 15: signal.py 周信号工具 + README + 全量回归收尾

**Files:**
- Create: `tools/sector-rotation/signal.py`、`tools/sector-rotation/README.md`
- Test: `tests/test_sr_signal.py`

**Interfaces:**
- Consumes: 全部上游；`make_strategy("L2")` 或 `--level` 指定。
- Produces: `build_signal(wf, strategy, *, k: int) -> dict`（`{friday, buy: [{etf, name, weight, index, index_name, cluster}], skipped}`）；CLI 落 `output/sector-rotation/YYYY-MM/week-YYYY-Www.md`。**P3 当日快照规则**（spec §3.1：纸面跟踪起用当日达标快照，point_in_time_pick(week_end=今天) 天然满足）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_signal.py
from sector_rotation.baselines import momentum_topk
from sector_rotation.signal import build_signal
from tests.test_sr_models import toy_wf


def test_build_signal_shapes():
    sig = build_signal(toy_wf(), momentum_topk, k=1)
    assert set(sig) >= {"friday", "buy", "skipped"}
    assert len(sig["buy"]) == 1 and {"etf", "weight"} <= set(sig["buy"][0])
```

（执行注：跨文件导入不顺则把 `toy_wf` 提为 `tests/conftest.py` fixture。）

- [ ] **Step 2: 失败** → **Step 3: 实现 signal.py**

```python
# tools/sector-rotation/signal.py
"""周信号 CLI（spec §4/P3）：周五盘后跑，出下周 ETF 交易信号（当日快照规则）。

P3 纪律：信号页落盘后追加 review-queue 一条 pending（人工复核执行可行性），
连续 8-12 周后按 spec §5 P3 出口复盘。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.data import build_weekly_frame  # noqa: E402
from sector_rotation.models import make_strategy  # noqa: E402
from sector_rotation.universe import cluster_for, load_universe  # noqa: E402


def build_signal(wf, strategy, *, k: int) -> dict:
    t = len(wf.fridays) - 1
    weights = strategy.select(wf, t)
    cmap = cluster_for(wf.spec, wf.fridays[t]) or {}
    buy = [{"etf": wf.etf_symbols[t][i], "name": wf.members[i].index_name,
            "weight": w, "index": wf.members[i].index_code,
            "index_name": wf.members[i].index_name,
            "cluster": cmap.get(wf.members[i].index_code, "—")}
           for i, w in sorted(weights.items(), key=lambda kv: -kv[1])]
    skipped = [{"etf": wf.etf_symbols[t][i], "index": wf.members[i].index_code}
               for i in range(len(wf.members))
               if i not in weights and wf.valid[t, i]]
    return {"friday": wf.fridays[t], "buy": buy, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", choices=["L0", "L1", "L2"], default="L2")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--universe", type=Path,
                    default=REPO_ROOT / "config/sector-rotation-universe.md")
    args = ap.parse_args(argv)
    spec = load_universe(args.universe)
    wf = build_weekly_frame(REPO_ROOT / "data", spec)
    sig = build_signal(wf, make_strategy(args.level, k=args.k), k=args.k)
    iso = date.today().isocalendar()
    out = (REPO_ROOT / "output/sector-rotation" / f"{date.today():%Y-%m}"
           / f"week-{iso[0]}-W{iso[1]:02d}.md")
    lines = [f"# 板块轮动周信号（决策帧 {sig['friday']}）", "",
             f"- 级别 {args.level} · k={args.k} · 生成 {date.today().isoformat()} · P3 当日快照规则",
             "- 执行纪律：周一 09:30 开盘价买入；开盘涨停弃买；周五 14:50 清仓（spec §3.5）",
             "", "| ETF | 信号指数 | 权重 | 簇 |", "|---|---|---|---|"]
    for b in sig["buy"]:
        lines.append(f"| {b['etf']} | {b['index']} {b['index_name']} | "
                     f"{b['weight']:.1%} | {b['cluster']} |")
    lines += ["", f"未入选行业 {len(sig['skipped'])} 个（弃权/信号弱/闸门拦截）。"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), f"\n已写入 {out}", sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: README**（模块图 + CLI 速查 + 两档成本表 + **已知限制**：跌停顺延简化、周频重训 vs 论文增量更新、金融损失/ROC 为实现方口径、规模 proxy 近似、退市 ETF 可得性结论、P1/P2 闸门真实 p 值摘要）

- [ ] **Step 5: 全量回归 + 真实冒烟**

```bash
conda run -n Quant-3.11 python -m pytest tests/ -q
conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py
conda run -n Quant-3.11 python tools/sector-rotation/signal.py --level L0 --k 3
```
Expected: 存量+新增全绿、ruff 零告警、周信号页落盘（L0 冒烟不依赖未过闸 L2）。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/signal.py tools/sector-rotation/README.md tests/test_sr_signal.py
git commit -m "feat(sector-rotation): 周信号工具 + README + 全量回归绿（Task 15）"
```

---

## Self-Review 记录（v1.2 对齐版）

1. **Spec v1.2 覆盖对照**：§3.1 point-in-time 映射 + 退市探测 + 逐年宇宙曲线 → T2/T3/T4（C-1）；§3.2 start 分页 + 数据现实曲线 → T2（含 spec L284 指针）；§3.3 训练窗标准化（I-4）→ T5 `standardize_fit_apply` 唯一入口 + T12 `_prep`；§3.4 阶梯与升级闸门引用检验矩阵（I-1）→ GC 12 + T11/T14；§3.5 闸门与迟滞 → T9（`limit_up`/`liquidity`/`missing`）+ T4 `etf_week_amount`；§3.6 持币截断 + 滞后簇（I-4）→ T1 `cluster_for` 簇代 + T9 `binds` 计数；§3.7 两档制（C-1）→ T6 + T11 两档渲染；§3.8 检验矩阵（I-1/I-2）+ 预注册（I-3）+ 覆盖率起点（I-5）+ 功效注释 → T10 + T11 + GC 12/13 + T3 Step 6；§5 P0-P2 出口与闸门 → T3 Step 6（P0 review-queue + 预注册）、T11 Step 5（P1）、T14 Step 5（P2）；稳健切片的 2023-07 口径漂移分段与指数深度分布 → T2 verify 报告 + T14 分年度探索表（口径漂移分段回放属分析动作，T11 后由 agent 用真实数据手工切，不单列任务）。
2. **占位符扫描**：无 TBD/TODO；"执行注"均为「以仓库真实签名/实测数据为准」的核对指令，实现代码本体完整。
3. **类型一致性**：`Member`（含 `etf_candidates` 元组）T1 定义、T3/T4/T8/T9/T12/T13/T15 一致；`UniverseSpec`+`cluster_for` T1 定义、T4/T9/T15 消费一致；`WeeklyFrame` 新字段（etf_symbols/etf_week_amount/spec/bench_300）T4 定义、T5/T8/T9/T10/T12/T13/T15 使用一致；`point_in_time_pick` T3 定义、T4 Step 3 下沉到 universe.py 后双方导入一致；`select(wf,t)` 协议与 `make_strategy` 签名（含消融三开关）在 T8/T10/T11/T12/T13/T14 一致；检验矩阵键 `("L0", row, tier)` 在 T11 定义与测试一致。
