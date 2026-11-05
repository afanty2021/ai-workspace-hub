# 板块轮动策略 P0-P2（含 P3 信号工具）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 `workspace/proposals/2026-11-05-sector-rotation-design.md`（**v1.2，独立评审 1C+9I+8M 闭环版**）的 P0（数据回补 + point-in-time 宇宙 + 预注册）、P1（两档成本回测 + L0 检验矩阵）、P2（L2 论文复刻 + 消融），并交付 P3 纸面跟踪所需的周信号工具。

**Architecture:** 双层标的（信号层 = 通达信 881 二级行业指数，执行层 = 行业 ETF，**point-in-time 映射**：每周用当时达标 ETF，杜绝幸存者/前视偏差）。数据复用持久化层（mootdx 深回补走 `market_data_io` upsert 正规通道）；回测引擎以「周五决策帧」为原子单位，策略统一 `select(wf, t)` 协议；**统计纪律三禁**（映射/点差/标准化与簇相关性一律禁全样本信息）；成本两档制（10/20bp），闸门统一引用 spec §3.8 检验矩阵，两档各过、单侧 p<0.1。P1/P2 出口闸门是**实证判定**，不满足即停并写结案报告（spec §5）。

**Tech Stack:** Python 3.11（conda Quant-3.11）、mootdx（已在环境，start 分页见持久化 spec L284）、numpy/pandas（已在环境）、PyTorch（T12 安装，CPU/MPS 轮子）、pytest、ruff。

**Spec:** `workspace/proposals/2026-11-05-sector-rotation-design.md`（**v1.2.1**，commit c10dde2 + S1-S3 补钉）。冲突以 spec 为准，本计划是它的任务化论证。本计划已对齐 v1.2 全部六处硬口径变更（point-in-time 映射 / 点差两档 / 训练窗标准化 / 滞后滚动簇 / 覆盖率起点 / 检验矩阵）；**本版 v1.1 = 独立评审全修闭环**（评审报告 `workspace/proposals/2026-11-05-sector-rotation-plan-review.md`，9C+15I+14M，结论 With fixes；用户拍板全修 2026-11-05，逐条处置见该报告末尾处置记录）。

## Global Constraints（全任务绑定）

1. **Python 一律 `conda run -n Quant-3.11 python ...`**（系统 Python 是 PEP 668 管理的 3.15）。
2. **测试**：`conda run -n Quant-3.11 python -m pytest tests/ -q` 全量必须保持全绿（评审实测 collect 465 用例）；新测试放根级 `tests/test_sr_*.py`（沿 `test_masters_*.py` 命名惯例），输出必须干净。
3. **Lint**：`conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py`（规则集 E4/E7/E9/F）零告警。
4. **提交**：中文 `type: subject`，按关注点拆 commit，**不推送**；在 `feat/sector-rotation-design` 分支续做（已含 v1/v1.1/v1.2 与本计划），不切新分支。
5. **数据纪律**：`data/` 全部是 gitignore 运行时数据，绝不 `git add`；回测报告中的每一个数字必须来自真实运行输出，禁止编造（工作区标注纪律：`[本地]`/`[网页]`/`[推测]`）。
6. **mootdx 单 socket**：所有 bars 拉取必须经 `mootdx_source._mootdx_call`（内部已 RLock 串行化）；单页 ≤ 800 根，深回补走 start 分页（mootdx 库 `k()` 已支持，见 `docs/superpowers/specs/2026-11-02-market-data-persistence-design.md:284`），按 date 去重；**写回必须持 `series_lock`（market_data_io 惯例：调用方负责持锁，评审 I14）**，断点续传——已够深标的直接跳过（评审 M13）。
7. **不新建 skill、不动 AGENTS.md 路由表**（spec §4：P3 跑通前）。
8. **统计纪律三禁（spec v1.2 C-1/I-4）**：①ETF 映射 point-in-time——回测中每周只用**当时**达标者（上市满 2 年且当时 trailing 20 日均成交额 ≥ 1 亿元，同行业多只取当时 20 日均额最大者[规模 proxy，近似已声明待验证]），无达标 ETF 的行业当周出宇宙；②历史段禁用今日实测点差；③标准化统计量只在当前训练窗内重算（推理周沿用训练窗参数），簇相关性只用滞后窗（t 时点用 t-2 至 t-1 年收益，每 2 年再聚一次）。
9. **成本两档制（spec §3.7，评审 C1 修正口径）**：**单边成本 = 佣金 1bp + 单边点差档（基准 10bp / 压力 20bp）**，即单边 11/21bp、**roundtrip 基准档 22bp / 压力档 42bp**（与 spec §7「单边 10 × 2 = 22bp/周·全换手」算术一致；spread_bps 语义 = 单边点差，不是全宽半宽）；冲击 0 参数化预留；**所有出口闸门两档都必须通过**；成本拖累占比两档各一列；α 永远只报成本后。**计费按净换手**（评审 C5）：逐资产 |新权重 − 旧权重(漂移调整后)| × 单边成本，重复入选资产持有过周末不重复付点差（spec §3.7「每笔成交计」+ §7 重叠率口径；论文的"每周全清"退化为信号语义，执行层持有等价敞口）。
10. **执行闸门与迟滞（spec §3.5/§3.1）**：周一开盘涨停（`open ≥ prev_close × (1 + limit_pct × 0.995)`）弃买；周五清仓跌停顺延下周一开盘卖（首版简化口径见 T9 注）；**入选严、周内宽**——入选 trailing 20d ≥ 1 亿（point-in-time），周内拦截线为执行周日均成交额 < 5000 万。
11. **风控参数（spec §3.6 初值）**：单行业周亏 ≥5% 移出下周清单；组合连亏 4 周停一周；年内回撤 ≥8% 降半仓至新高；单行业滚动 8 周胜率 <45% 进两周观察期；组合绝对亏损 10% 全停；同簇 ≤2 截断**持币不顺延**（截断资金不重新分配）。
12. **检验矩阵是唯一闸门口径（spec §3.8，别处只引用不另设数字）**：vs 随机 k=置换检验 ≥1000 次（单侧 p<0.1）；vs 等权 / vs 沪深300ETF / L1·L2 vs L0 = 配对周收益差 block bootstrap（块长 4 周 ≥1000 次，单侧 p<0.1，**H0 下重定心**，评审 C2）；n=1000 是下限，**禁止降档**——超时如实报告失败并停（评审 I6）。全部两档各过；预注册字段"判定点差档"语义 = **双档都过**（spec 补钉 S1）。**预注册在 T11 两段式进行**（评审 I1/C9 修正，不再在 T3）：引擎就绪后先在**样本外前窗口**跑探索性网格选配置 → 预注册行写死进 spec 实施记录并单独 commit → 样本外窗口只对该配置做一次确认性检验。**样本外边界 OOS 起点 = max(2019-06 首个决策周, point-in-time 可用行业数 ≥50 首周)**（spec 补钉 S5，2026-11-05 宇宙确认拍板：416 成员宇宙覆盖率峰值 65%，80% 百分比口径不可达，改绝对数 50——起点≈2020 年中、OOS≈335 周），选择窗与确认窗不相交（评审 C9）；OOS 实际周数写入报告与 spec 实施记录。功效重估按 spec 补钉 S3：OOS 周数 n 时可检出年化 α ≈ (5-7%)×√(370/n)，随实际周数动态生成并披露。其余变体标"探索性"只报告不判定（**不打印闸门结论行**，评审 I10）。
13. **功效边界（spec §3.8 功效注释 + 补钉 S3，写进 P1 出口一起读）**：基准样本外约 370 周，单侧 p<0.1 稳定检出年化 α ≈5-7%；**实际 OOS 周数 n 时按 √(370/n) 缩放动态生成（T11 `power_note`），起点晚于 2019-06 时该行为必填**——P1 证伪的结案报告必须写"未检出（缩放后阈值）/年的 α"，不得写成"A 股周频轮动无 α"的全称否定。
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
    walkforward.py             # 引擎（可用行业数 ≥50 起点，spec 补钉 S5）
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
# torch 仅探测不安装（评审 I15：环境问题提前到 P0 暴露；安装仍在 T12）
conda run -n Quant-3.11 python -c "import torch; print('torch', torch.__version__)" 2>/dev/null \
  || echo "torch 未装（预期内，T12 安装；此行仅留环境探测记录）"
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
    # 口径（评审 C8 修正的是测试、不是实现）：代 g 聚类窗 [g, g+1]，g+2 年起才可用
    # （spec §3.6"t 时点用 t-2 至 t-1 年收益"）。照旧测试改实现 = 引入当年收益泄漏。
    spec = _spec()
    assert cluster_for(spec, "2019-01-04") is None           # 无可用代
    assert cluster_for(spec, "2020-06-05") is None           # 2019 代 2021 年起才可用
    assert cluster_for(spec, "2022-01-07") == {"881101": "c-a", "881127": "c-b"}
    assert cluster_for(spec, "2023-01-06") == {"881101": "c-x", "881127": "c-x"}


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

from market_data_io import series_lock, upsert_series_rows  # noqa: E402
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
    stats = {"ok": 0, "empty": 0, "skip": 0}
    for symbol, is_index in targets:
        existing = verify_depth([(symbol, is_index)], data_root,
                                expect_bars=total)[0]
        if existing["rows"] >= total:          # 评审 M13：断点续传，已够深跳过
            stats["skip"] += 1
            continue
        rows = fetch_bars_paginated(symbol, index=is_index, total=total)
        if not rows:
            stats["empty"] += 1
            log(f"Warning: {symbol} 空返回（指数可能新增短史/ETF 可能退市——verify 复核）")
            continue
        path = _target_path(data_root, symbol, index=is_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        with series_lock(data_root, path.name) as acquired:   # 评审 I14：调用方持锁
            if not acquired:
                stats["skip"] += 1
                log(f"Warning: {symbol} 锁被其它进程持有，本轮跳过（重跑可续）")
                continue
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


def ex_dividend_scan(data_root: Path, symbols: list[str]) -> list[dict]:
    """疑似除息事件粗检（评审 I9）：ETF 单日 close 跌幅 < -5% 记事件。
    通达信日线不复权、除息跳空保留——open→close 周收益会漏分红，方向为系统性
    低估收益；事件清单进 P0 数据现实报告声明偏差方向，不改价格序列。"""
    import json
    events = []
    for sym in symbols:
        path = data_root / "market" / "series" / f"{sym}.jsonl"
        if not path.exists():
            continue
        rows = [json.loads(ln) for ln in
                path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        for prev, cur in zip(rows, rows[1:]):
            if prev.get("close") and cur.get("close"):
                chg = cur["close"] / prev["close"] - 1.0
                if chg < -0.05:
                    events.append({"etf": sym, "date": cur["date"], "drop": chg})
    return events


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
    etf_syms: list[str] = []
    for path in filter(None, (args.etf_candidates, cand_default, delist_default)):
        if path.exists():
            etf_syms += _read_candidates(path)
    targets += [(c, False) for c in etf_syms]
    for row in verify_depth(targets, data_root, expect_bars=TOTAL):
        print(row)
    if etf_syms:
        print("--- 疑似除息事件（评审 I9：偏差方向=周收益系统性低估，详见 P0 数据现实报告）---")
        for ev in ex_dividend_scan(data_root, sorted(set(etf_syms))):
            print(ev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backfill.py -v`
Expected: PASS（4 用例）

- [ ] **Step 5: 真实全量跑（评审 C3 修正：`indices` 是本任务核心使命，必须全量执行——初版只在 CLI 定义、无执行步骤，会静默退化到 802 根浅数据）**

```bash
mkdir -p data/sector-rotation
printf '512480.SH\n512000.SH\n' > data/sector-rotation/etf-candidates.txt
# ① ETF 冒烟：先验证 start 分页生效
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py etfs
head -1 data/market/series/512480.SH.jsonl; tail -1 data/market/series/512480.SH.jsonl
# ② 881 全集深回补——P0 的根（467 × ~4 页串行 RLock，预算 15-40 分钟；
#    幂等可重跑：已够 2600 根自动跳过、锁冲突轮跳过，中断后直接重跑续传）
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py indices
# ③ 深度验收：881 深度分布（P0 出口"881 历史深度"检查项的机器底稿）
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py verify | tail -30
```
Expected: ① 512480 深度显著 > 802（start 分页生效，若仍 ~800 如实记录为服务器限制）；② 汇总 ok ≥ 400/467（空返回=新增短史指数，逐一如实记录）；③ **验收门槛：≥2400 根的 881 指数占比 ≥ 80%——不达标必须把深度分布写进 P0 数据现实报告并触发 spec §3.8 起点降级评估，不得静默继续**。同时**联网检索近 5 年清盘/退市行业 ETF 代码清单**（交易所公告/基金公告，exa 补充），落 `data/sector-rotation/delisted-etf.txt`（每行一代码，附来源行注释）；重跑 `etfs` 后 verify 检查退市代码行数——0 行 = 通达信不留退市数据，如实写入 P0 报告（该时段行业出宇宙，压力档兜底近似）；疑似除息事件清单同步输出（偏差方向=周收益系统性低估）。

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
    r"黄金(?!股)|豆粕|有色期货|能源化工|原油|货币|债|国债|信用|转债|添益|理财")  # M4：黄金(?!股)——黄金股 ETF 属行业票要保留

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
    （规模 proxy 近似，spec §8 待验证——README 声明；上市年满 2 年按年整数差
    近似，误差 ±数日，评审 M2 注记）。"""
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
    # 评审 M5：ETF 显示名缓存（signal.py 信号表用），随候选池一起落盘
    name0 = {x["code"]: x["name"].replace("\x00", "") for x in listing}
    (data_root / "sector-rotation" / "etf-names.json").write_text(
        json.dumps({s: name0.get(s.split(".")[0], "") for s in candidates},
                   ensure_ascii=False, indent=1), encoding="utf-8")
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

- [ ] **Step 5: 真实数据全流程跑（前置（评审 C3）：T2 Step 5 的 `indices` 全量深回补必须已完成——否则 881 只有 802 根，簇代 2017-2021 全被 `<40 交易日` 跳过、覆盖曲线 2017-2022 全 0%）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/build_universe.py
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py etfs   # 新候选补拉
conda run -n Quant-3.11 python tools/sector-rotation/build_universe.py  # 带流动性重跑
```
Expected: config（draft）+ coverage-curve.md + unmatched.txt。逐年曲线是 walk-forward 起点判定（T10）的输入，数字如实记录。

- [ ] **Step 6: review-queue 提名与停等（评审 I1/I8/M9：预注册不在本任务——网格须回测引擎就绪，已重排至 T11 两段式；P0 出口过队列后才进 T4）**

向 `workspace/review-queue.md` 追加七列完整行（ID 沿 `Q-YYYYMMDD-NN` 惯例取当日次序）：

`| Q-202611XX-0N | proposal | config/sector-rotation-universe.md + data/sector-rotation/coverage-curve.md | 确认宇宙清单（draft→confirmed）+ 数据现实曲线：人工复核 ETF 候选集映射、双创 limit_pct、簇代表、逐年覆盖曲线、881 深度分布与退市可得性结论、除息事件清单；确认中的修订（补 KEYWORDS/换候选/改 limit_pct）落回本脚本后**必须重跑 Step 5** 再交确认 | build_universe.py P0 产物（T3） | 2026-11-XX | pending |`

**停等纪律（I8）**：T4 起所有任务前置 = 本条 done 且 config frontmatter `status: confirmed`；确认中任何人工修订后必须重跑本任务产物，下游不消费 draft。

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
    valid: np.ndarray             # (T, L) bool：执行期有效 = point-in-time 达标且三价齐（回测用）
    dvalid: np.ndarray            # (T, L) bool：决策期有效 = pick 存在 + 指数收盘/上周五收盘齐
                                  # （评审 C7：信号帧（执行周未发生）用 dvalid，build_signal 经
                                  #  replace(wf, valid=wf.dvalid) 切换口径）
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


def _etf_rows(first: str, last: str, row=(1.0, 1.01, 3e8)) -> list[dict]:
    """显式日期区间的逐日行（评审 C7 修复附带：初版 fixture 1500 天止于 2024-02，
    盖不到 2026-11 决策周，valid 断言必失败——改为按区间生成）。"""
    from datetime import date, timedelta
    out, d, end = [], date.fromisoformat(first), date.fromisoformat(last)
    while d <= end:
        out.append({"date": d.isoformat(), "open": row[0], "close": row[1],
                    "amount": row[2]})
        d += timedelta(days=1)
    return out


def test_point_in_time_symbol_selection(tmp_path: Path):
    _write(tmp_path / "sector/series/881101.jsonl",
           [{"date": "2026-11-06", "close": 100.0},
            {"date": "2026-11-13", "close": 101.0},
            {"date": "2026-11-20", "close": 102.0}])
    # 528030：2020 年上市且均额 3 亿（达标），日线止于 11-13；528031：2025 上市（不达标）
    _write(tmp_path / "market/series/528030.SH.jsonl",
           _etf_rows("2020-01-02", "2026-11-13"))
    _write(tmp_path / "market/series/528031.SH.jsonl",
           _etf_rows("2025-06-02", "2026-11-13", (1.0, 1.01, 5e8)))
    _write(tmp_path / "market/series/510300.SH.jsonl",
           _etf_rows("2020-01-02", "2026-11-13", (1.0, 1.02, 1e9)))
    wf = build_weekly_frame(tmp_path, SPEC)
    assert wf.etf_symbols[0][0] == "528030.SH"     # point-in-time 选中老 ETF
    assert wf.fridays == ["2026-11-06", "2026-11-13", "2026-11-20"]
    assert wf.valid[0][0]                          # 11-06 帧：执行周 11-09..13 存在
    assert not wf.valid[1][0] and not wf.valid[2][0]
    assert wf.dvalid[0][0] and wf.dvalid[1][0]     # 11-13 帧决策期有效（出信号场景）
    assert not wf.dvalid[2][0]                     # 11-20 帧 ETF 断档 → 决策期也无效
    assert wf.bench_300.shape == (len(wf.fridays),)
```

（执行注：fixture 日期区间必须显式覆盖决策周（评审 C7 附带修复——初版 1500 天止于 2024-02）；连续日历日含周末不影响 point_in_time_pick（只比日期），ISO 周分组天然正确。）

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
    dvalid: np.ndarray
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
    dvalid = np.zeros(shape, dtype=bool)
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
            if wk in last:                 # 决策期可得，独立于执行周是否存在（评审 C7）
                etf_prev[ti, li] = float(last[wk]["close"])
            dvalid[ti, li] = bool(np.isfinite(idx_close[ti, li])
                                  and np.isfinite(etf_prev[ti, li]))
            etf_symbols[ti][li] = pick     # 决策期即记录 point-in-time 选择（C7 信号帧用）
            next_wk = next((c for c in (wk + 7, wk + 14) if c in first), None)
            if next_wk is None:
                continue
            etf_open[ti, li] = float(first[next_wk].get("open", first[next_wk]["close"]))
            etf_close[ti, li] = float(last[next_wk]["close"])
            etf_amt[ti, li] = float(amt.get(next_wk, np.nan))
            valid[ti, li] = bool(dvalid[ti, li]
                                 and np.isfinite(etf_open[ti, li])
                                 and np.isfinite(etf_close[ti, li]))
    return WeeklyFrame(fridays, idx_close, etf_symbols, etf_open, etf_close,
                       etf_prev, etf_amt, members, spec, valid, dvalid, bench_ret)
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
        dvalid=np.ones((T, 1), bool), bench_300=np.full(T, 0.001))


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
    spread_bps: float = 10.0      # 单边点差档（评审 C1：不是全宽半宽！）基准 10 / 压力 20
    impact_bps: float = 0.0

    @classmethod
    def base(cls) -> "CostModel":        # 单边 11bp / roundtrip 22bp（spec §7 算术）
    @classmethod
    def stress(cls) -> "CostModel":      # 单边 21bp / roundtrip 42bp（闸门兜底档）
    def side_bps(self) -> float          # = commission + spread + impact
    def roundtrip_bps(self) -> float     # = 2 × side
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_cost.py
from sector_rotation.cost import CostModel


def test_two_tiers_spec_arithmetic():
    """对拍 spec §7：单边点差 10bp × 2 + 佣金双边 = 22bp/周·全换手（评审 C1）。"""
    assert CostModel.base().spread_bps == 10.0
    assert CostModel.stress().spread_bps == 20.0
    assert CostModel.base().side_bps() == 11.0
    assert CostModel.stress().side_bps() == 21.0
    assert CostModel.base().roundtrip_bps() == 22.0
    assert CostModel.stress().roundtrip_bps() == 42.0
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
    spread_bps: float = 10.0     # 语义 = 单边点差（评审 C1 修正）
    impact_bps: float = 0.0

    @classmethod
    def base(cls) -> "CostModel":
        return cls(spread_bps=10.0)

    @classmethod
    def stress(cls) -> "CostModel":
        return cls(spread_bps=20.0)

    def side_bps(self) -> float:
        return self.commission_bps + self.spread_bps + self.impact_bps

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
- Produces（统一 callable 协议 `strategy(wf, t) -> dict[int, float]`——评审 I11：策略一律**普通可调用对象**（函数/lambda/实现 `__call__` 的实例），引擎只 `strategy(wf, t)`，禁止 `.select` 方法协议）：

```python
class EqualWeightAnnual:    # 对照①（评审 C5：等权持有 + 年再平衡 + 宇宙时变驱动调仓，
    def __init__(self)      #   非周频再平衡——否则对照被每周收取幻影换手成本）
    def __call__(wf, t) -> dict[int, float]
def momentum_topk(wf, t, *, lookback: int = 1, k: int = 3)   # L0 动量（主检验配置之一）
def reversal_topk(wf, t, *, lookback: int = 1, k: int = 3)   # L0 反转
def random_k(wf, t, *, k: int = 3, seed: int = 0)            # 对照③：噪音
```

（对照②=L0 自身，对照④=沪深300 持有由 walkforward 层用 `wf.bench_300` 特判，不进策略协议。）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_baselines.py
import numpy as np

from sector_rotation.baselines import (EqualWeightAnnual, momentum_topk, random_k,
                                       reversal_topk)
from sector_rotation.data import WeeklyFrame
from sector_rotation.universe import Member, UniverseSpec

M2 = [Member("881101", "机械", ("E1.SH",), 0.10),
      Member("881127", "半导体", ("E2.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def _wf(index_rows, valid=None, fridays=None):
    T, L = index_rows.shape
    v = np.ones((T, L), bool) if valid is None else valid
    return WeeklyFrame(
        fridays=fridays or [f"w{i}" for i in range(T)], index_close=index_rows,
        etf_symbols=[["E1.SH", "E2.SH"]] * T,
        etf_open=np.ones((T, L)), etf_close=np.ones((T, L)),
        etf_prev_close=np.ones((T, L)), etf_week_amount=np.full((T, L), 2e8),
        members=M2, spec=SPEC, valid=v, dvalid=v.copy(),
        bench_300=np.full(T, 0.001))


def test_momentum_picks_topk_by_trailing_return():
    idx = np.array([[100.0, 100.0], [101.0, 110.0], [101.0, 120.0]])
    assert momentum_topk(_wf(idx), 2, lookback=2, k=1) == {1: 1.0}
    assert reversal_topk(_wf(idx), 2, lookback=2, k=1) == {0: 1.0}


def test_equal_weight_annual_rebalance():
    fridays = ["2020-01-03", "2020-06-05", "2021-01-08"]
    wf = _wf(np.ones((3, 2)), fridays=fridays)
    eq = EqualWeightAnnual()
    w0 = eq(wf, 0)
    assert w0 == {0: 0.5, 1: 0.5}
    assert eq(wf, 1) == w0                    # 同年同宇宙 → 持有不调（评审 C5）
    v = np.ones((3, 2), bool); v[2, 1] = False   # 次年 + 成员退出 → point-in-time 重建
    assert eq(_wf(np.ones((3, 2)), v, fridays=fridays), 2) == {0: 1.0}


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


class EqualWeightAnnual:
    """对照①（spec §3.8 + 评审 C5）：等权持有当周 valid 全体；**年再平衡 + 宇宙时变
    驱动**（成员集变化周被迫调仓），其余周返回上周权重原值——引擎按净换手计费，
    持有周成本 ≈ 0，不给对照制造幻影换手。"""

    def __init__(self) -> None:
        self.last: dict[int, float] | None = None
        self.last_year: int | None = None

    def __call__(self, wf: WeeklyFrame, t: int) -> dict[int, float]:
        cols = _valid(wf, t)
        year = int(wf.fridays[t][:4])
        if (self.last is None or year != self.last_year
                or set(self.last) != set(cols)):
            self.last = {i: 1.0 / len(cols) for i in cols} if cols else {}
            self.last_year = year
        return dict(self.last)


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
              last_week_pos_returns: dict[int, float] | None,
              *, nav: float = 1.0) -> dict[int, float]
    # nav = 引擎传入的当前净值（评审 I2：补全 §3.6 全六条——初版漏了两条）：
    #   ① 年内高点回撤 ≥8% → halved=True，全部权重 ×0.5，nav 创年内新高才恢复
    #   ② 自起始净值亏损 ≥10% → halted=True 永久停（返回 {}，人工复盘后重跑）
    # 持币式同簇截断（spec §3.6 v1.2）：簇内 >2 截断后不重新归一，空出资 = 现金；
    # 簇表用 cluster_for(spec, wf.fridays[t])，None 代 → 同簇约束跳过 + binds 不计数
    binds: int      # 同簇截断触发次数（报告披露）
    halved: bool
    halted: bool

def simulate_week(wf, t, weights_prev, weights_new, cost) -> tuple[float, dict, dict]
    # 涨停弃买 / 跌停顺延（简化口径）/ 周内流动性迟滞（etf_week_amount < 5000 万拦截）
    # 成本 = 净换手 Σ|w_new − w_prev| × side_bps（评审 C5；weights_prev 为引擎传入的
    # 漂移调整后上周权重——重复入选资产持有过周末成本 ≈ 0，等权对照不再吃幻影成本）
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
    # 默认 friday 取 ≥2021 年（评审 C8：2019 代簇 2021 年起可用，cap 测试才成立）
    T, L = open_.shape
    v = np.ones((T, L), bool) if valid is None else valid
    return WeeklyFrame(
        fridays=fridays or ["2021-06-04"] * T, index_close=np.ones((T, L)),
        etf_symbols=[["E1.SH", "E2.SH", "E3.SH", "E4.SH"]] * T,
        etf_open=open_, etf_close=close_, etf_prev_close=prev_close,
        etf_week_amount=week_amount if week_amount is not None
        else np.full((T, L), 2e8),
        members=M4, spec=SPEC, valid=v, dvalid=v.copy(),
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


def test_simulate_week_net_turnover_costs():
    """评审 C1+C5：建仓只付单边 11bp；持有过周末（同权重再入选）成本 ≈ 0。"""
    wf = _wf(np.array([[1.0]]), np.array([[1.10]]), np.array([[0.99]]))
    net, pos, detail = simulate_week(wf, 0, {}, {0: 1.0}, CostModel.base())
    assert abs(pos[0] - 0.10) < 1e-12
    assert abs(detail["costs"] - CostModel.base().side_bps() / 1e4) < 1e-12
    assert abs(net - (0.10 - CostModel.base().side_bps() / 1e4)) < 1e-9
    wf2 = _wf(np.array([[1.0]]), np.array([[1.05]]), np.array([[0.99]]))
    _, _, detail2 = simulate_week(wf2, 0, {0: 1.0}, {0: 1.0}, CostModel.base())
    assert detail2["costs"] == 0.0


def test_drawdown_halves_and_absolute_loss_halts():
    """评审 I2：§3.6 风控表六条补全——回撤 ≥8% 降半仓、绝对亏损 ≥10% 全停。"""
    rs = RiskState(SPEC)
    wf = _wf(np.full((3, 4), 1.0), np.full((3, 4), 1.01), np.full((3, 4), 1.0),
             fridays=["2021-01-08", "2021-06-04", "2021-12-31"])
    assert rs.apply(0, wf, {0: 0.5}, None, nav=1.0) == {0: 0.5}
    got = rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.91)   # 回撤 9% → 半仓
    assert got == {0: 0.25} and rs.halved
    got = rs.apply(2, wf, {0: 0.5}, {0: 0.01}, nav=0.89)   # 绝对亏损 11% → 全停
    assert got == {} and rs.halted


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
        self.halved = False                     # 评审 I2：年内回撤 ≥8% 降半仓至新高
        self.halted = False                     # 评审 I2：绝对亏损 ≥10% 全停
        self.start_nav: float | None = None
        self.ytd_high = 0.0
        self.ytd_year: int | None = None

    def apply(self, t: int, wf: WeeklyFrame, desired: dict[int, float],
              last_week_pos_returns: dict[int, float] | None,
              *, nav: float = 1.0) -> dict[int, float]:
        if not self.enabled:
            return dict(desired)
        year = int(wf.fridays[t][:4])
        if self.start_nav is None:
            self.start_nav = nav
        if self.ytd_year != year:               # 新年重置年内高点
            self.ytd_year, self.ytd_high = year, nav
        self.ytd_high = max(self.ytd_high, nav)
        if nav <= self.start_nav * 0.90:        # 组合绝对亏损 ≥10% → 永久停
            self.halted = True
        if self.halted:
            return {}
        if nav >= self.ytd_high:                # 创年内新高 → 恢复满仓
            self.halved = False
        elif nav / self.ytd_high <= 0.92:       # 年内回撤 ≥8% → 降半仓
            self.halved = True
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
        scale = 0.5 if self.halved else 1.0
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
            picked[i] = desired[i] * scale           # 截断资/半仓资 = 现金，不归一
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
    # 评审 C5：净换手计费——逐资产 |新 − 旧(漂移后)| × 单边成本；持有过周末 ≈ 0 成本
    turnover = sum(abs(executed.get(i, 0.0) - weights_prev.get(i, 0.0))
                   for i in set(executed) | set(weights_prev))
    costs = turnover * cost.side_bps() / 1e4
    detail = {"blocked": blocked, "turnover": turnover,
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
    t_rows: list[int]     # 每个周收益对应的决策帧行号（评审 C4：配对基准按此对齐）
    metrics: dict[str, float]; trades: list[dict]

def coverage_start(wf: WeeklyFrame, *, min_universe: int = 50) -> int
    # spec §3.8 I-5 + 补钉 S5：point-in-time 可用行业数（valid 列计数）首次 ≥50 的行号

def run_walkforward(wf, strategy, *, cost: CostModel, start: int | None = None,
                    end: int | None = None, oos_start: int | None = None,
                    risk: RiskState | None = None) -> WalkResult
    # start=None → coverage_start(wf)；oos_start 给定时 start = max(start, oos_start)
    # （评审 C9：样本外边界，选择窗 end=oos_start 与确认窗不相交）；
    # end 排他上界（预注册网格跑样本外前数据用）；每周 nav 传给 RiskState（I2），
    # 上周权重漂移调整后计净换手（C5）；对照④基准取 bench_300[t_rows]（C4）

def perm_test_vs_random(wf, cost, *, k, n=1000, strategy=None, start=None,
                        end=None) -> dict
    # 检验矩阵行 1：置换检验（H0 无选股能力），单侧 p；n≥1000 禁降档（I6）

def paired_block_bootstrap(diff: np.ndarray, *, block: int = 4, n: int = 1000,
                           seed: int = 0) -> float
    # 检验矩阵行 2-4：H0(均值≤0) 下**重定心** block bootstrap，单侧 p（评审 C2）
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_walkforward.py
import numpy as np

from sector_rotation.baselines import EqualWeightAnnual, momentum_topk, random_k
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
                       np.full((T, 2), 2e8), M2, SPEC, v, v.copy(), np.full(T, 0.001))


def test_coverage_start_finds_first_week_meeting_min_universe():
    v = np.zeros((20, 2), bool)
    v[10:, :] = True                        # 第 10 周起 2 行业全部可用
    assert coverage_start(_wf(T=20, valid=v), min_universe=2) == 10


def test_walkforward_uses_coverage_start_and_runs():
    wf = _wf()
    res = run_walkforward(wf, momentum_topk, cost=CostModel.base())
    assert res.nav[0] == 1.0 and len(res.nav) == len(res.weekly) + 1
    assert len(res.t_rows) == len(res.weekly)          # 评审 C4：行号账本等长
    assert all(set(tr["holdings"]) <= {0, 1} for tr in res.trades)


def test_paired_block_bootstrap_positive_and_negative():
    """评审 C2：重定心版——正效应 p<0.1、负效应 p 接近 1（未重定心版两者都 ≈0.5）。"""
    rng = np.random.default_rng(1)
    assert paired_block_bootstrap(rng.normal(0.002, 0.01, 300),
                                  block=4, n=500) < 0.1
    assert paired_block_bootstrap(rng.normal(-0.002, 0.01, 300),
                                  block=4, n=500) > 0.9


def test_perm_test_p_in_range():
    out = perm_test_vs_random(_wf(T=40), CostModel.base(), k=1, n=30,
                              strategy=EqualWeightAnnual())
    assert 0 <= out["p_value"] <= 1 and out["n_random"] == 30
```

- [ ] **Step 2: 失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/walkforward.py
"""walk-forward 引擎（spec §3.8 + 补钉 S5：可用行业数 ≥50 起点，起点晚于 2019-06 功效重估）。"""
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
    t_rows: list[int] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)


def coverage_start(wf: WeeklyFrame, *, min_universe: int = 50) -> int:
    counts = wf.valid.sum(axis=1)
    hits = np.flatnonzero(counts >= min_universe)
    return int(hits[0]) if len(hits) else len(wf.fridays) - 1


def run_walkforward(wf: WeeklyFrame, strategy, *, cost: CostModel,
                    start: int | None = None, end: int | None = None,
                    oos_start: int | None = None,
                    risk: RiskState | None = None) -> WalkResult:
    risk = risk or RiskState(wf.spec)
    start = coverage_start(wf) if start is None else start
    if oos_start is not None:
        start = max(start, oos_start)
    stop = len(wf.fridays) if end is None else end
    nav, nav_g = [1.0], [1.0]
    weekly, trades, t_rows = [], [], []
    weights_prev: dict[int, float] = {}
    last_pos_returns: dict[int, float] | None = None
    turnover_acc = cost_acc = gross_acc = 0.0
    for t in range(start, stop):
        if not wf.valid[t].any():
            continue
        desired = strategy(wf, t)                    # 评审 I11：callable 协议
        weights_new = risk.apply(t, wf, desired, last_pos_returns, nav=nav[-1])
        net, gross_pos, detail = simulate_week(wf, t, weights_prev, weights_new, cost)
        weekly.append(net)
        nav.append(nav[-1] * (1 + net))
        nav_g.append(nav_g[-1] * (1 + detail["gross"]))
        turnover_acc += detail["turnover"]
        cost_acc += detail["costs"]
        gross_acc += detail["gross"]
        last_pos_returns = gross_pos or None
        total = 1 + detail["gross"]                  # 评审 C5：上周权重漂移调整
        weights_prev = ({i: weights_new[i] * (1 + gross_pos[i]) / total
                         for i in weights_new} if total > 0 else dict(weights_new))
        t_rows.append(t)
        trades.append({"friday": wf.fridays[t], "holdings": sorted(weights_new),
                       "blocked": detail["blocked"], "detail": detail})
    nav_a, weekly_a = np.array(nav), np.array(weekly)
    metrics = compute_metrics(
        nav_a, weekly_a, turnover=turnover_acc,
        cost_drag=(cost_acc / gross_acc) if gross_acc > 0 else float("nan"),
        cluster_binds=risk.binds)                    # 评审 M7：毛收益 ≤0 时记 nan
    return WalkResult(nav_a, np.array(nav_g), weekly_a, t_rows, metrics, trades)
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
                        strategy=None, start: int | None = None,
                        end: int | None = None) -> dict:
    obs = run_walkforward(wf, strategy or (lambda w, t: random_k(w, t, k=k, seed=0)),
                          cost=cost, start=start, end=end)
    rand = np.array([
        run_walkforward(wf, lambda w, t, s=seed: random_k(w, t, k=k, seed=s),
                        cost=cost, start=start, end=end).metrics["cagr"]
        for seed in range(n)])
    p = float((1 + (rand >= obs.metrics["cagr"]).sum()) / (1 + n))
    return {"observed_cagr": obs.metrics["cagr"], "p_value": p,
            "random_cagr_mean": float(rand.mean()),
            "random_cagr_p95": float(np.percentile(rand, 95)), "n_random": n}


def paired_block_bootstrap(diff: np.ndarray, *, block: int = 4, n: int = 1000,
                           seed: int = 0) -> float:
    """H0: 配对周差均值 ≤ 0。评审 C2：必须在 H0 下**重定心**——对 diff − obs_mean
    重抽，p = P(boot_mean ≥ obs_mean)；未重定心版 p 数学收敛 ~0.5，检验矩阵第
    2-4 行全体失效（数值验证：正效应数据 plan_p≈0.5 / 重定心版 p≈0.01）。"""
    diff = np.asarray(diff, dtype=float)
    diff = diff[np.isfinite(diff)]
    if len(diff) < block:
        return float("nan")
    rng = np.random.default_rng(seed)
    centered = diff - diff.mean()
    obs_mean = diff.mean()
    n_blocks = int(np.ceil(len(diff) / block))
    count = 0
    for _ in range(n):
        idx = rng.integers(0, len(diff) - block + 1, size=n_blocks)
        sample = np.concatenate([centered[i:i + block] for i in idx])[:len(diff)]
        if sample.mean() >= obs_mean:
            count += 1
    return float((1 + count) / (1 + n))
```

（执行注：评审 I6——n=1000 是 spec §3.8 下限，**禁止降档**；若耗时不可接受，如实报告失败并停下来调实现（如向量化/缓存），不得把 n 降到 500。策略周差 = `obs.weekly − bench_weekly`，等长对齐由 T11 用 `t_rows` 保证。） 

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
- Produces: CLI `backtest.py --level L0|L1|L2 --direction momentum|reversal（评审 I12） --k 3 --lookback {1,4}（L0 排名回看，区别于特征窗 --window {8,13,26,52}，评审 I3） --tier base|stress|both --oos-start YYYY-MM-DD（默认 2019-06-01，评审 C9） --pre-oos（预注册选择窗：[首个有可用行业周, 确认窗起点)——S5 下确认窗起点=max(oos_start 行, ≥50 首周)，2026-11-05 裁定防选择窗恒空；评审 I1） --slice FROM:TO（稳健切片，评审 I7） --exploratory（只报告不判定，评审 I10）`；`render_report(results, tests, *, level, tag, tier_notes, prereg, exploratory=False, n_oos=None) -> str`（评审 C6：矩阵键用 level 参数，禁硬编码）；`power_note(n_oos) -> str`（评审 C9：功效注释按实际样本外周数动态生成）。报告落 `output/sector-rotation/YYYY-MM/backtest-{tag}.md`：检验矩阵表（行=检验，列=两档 p 与判定）、指标表（**两档成本拖累各一列**，M8）、同簇触发频率、OOS 起点与周数。**配对基准一律 `wf.bench_300[t] for t in res.t_rows`（评审 C4：禁止固定切片）。**

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_backtest.py
import numpy as np

import backtest  # noqa: E402
from sector_rotation.walkforward import WalkResult


def _res(cagr=0.10):
    weekly = np.full(52, 0.0019)
    nav = np.concatenate([[1.0], np.cumprod(1 + weekly)])
    return WalkResult(nav, nav.copy(), weekly, list(range(52)),
                      {"cagr": cagr, "alpha": 0.02, "sharpe": 1.1, "max_dd": -0.1,
                       "win_rate": 0.55, "turnover": 90.0, "cost_drag": 0.11,
                       "cluster_binds": 4}, [])


def _tests(level, p_stress_eq=0.12):
    return {(level, "vs 随机", "base"): 0.03, (level, "vs 随机", "stress"): 0.05,
            (level, "vs 等权", "base"): 0.04, (level, "vs 等权", "stress"): p_stress_eq,
            (level, "vs 沪深300", "base"): 0.03, (level, "vs 沪深300", "stress"): 0.06,
            (level, "vs L0", "base"): 0.02, (level, "vs L0", "stress"): 0.03}


def test_render_report_matrix_and_power_note():
    text = backtest.render_report(
        {"L0": _res(), "等权持有": _res(0.05), "随机k3": _res(0.04)},
        _tests("L0"), level="L0", tag="L0-预注册",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="k=3 / 方向=动量 / lookback=1（2026-11-XX 预注册）", n_oos=370)
    assert "检验矩阵" in text and "未检出" in text          # 功效注释在
    assert "370" in text                                     # C9：动态周数
    assert "L0 闸门" in text and "未通过" in text           # stress 档 0.12 ≥0.1 → 未过


def test_render_report_level_param_and_exploratory_no_gate():
    text = backtest.render_report(                          # C6：L 级键不再空转
        {"L2": _res()}, _tests("L2", p_stress_eq=0.03),
        level="L2", tag="L2-确认",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="L2 主检验", n_oos=370)
    assert "vs L0" in text and "L2 闸门" in text and "通过" in text
    text2 = backtest.render_report(                         # I10：探索性无闸门行
        {"L2-k2": _res()}, _tests("L2", 0.9),
        level="L2", tag="L2-k2",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="探索性", exploratory=True, n_oos=370)
    assert "只报告不判定" in text2 and "闸门" not in text2
```

- [ ] **Step 2: 失败** → **Step 3: 实现 backtest.py**

```python
# tools/sector-rotation/backtest.py
"""检验矩阵回测 CLI（spec §3.8 v1.2 + 评审 C4/C6/C9/I1/I3/I10/I12 修正）。

预注册两段式（I1/C9+S5 裁定）：--pre-oos 在样本外前窗口（首个有可用行业周 →
确认窗起点）跑探索性网格 → 预注册行写 spec 实施记录并单独 commit →
不带 --pre-oos 跑确认性检验（start = max(可用行业数 ≥50 首周（S5）,
oos_start 行)，选择窗与确认窗不相交）。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.baselines import (EqualWeightAnnual, momentum_topk,  # noqa: E402
                                       random_k, reversal_topk)
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import build_weekly_frame  # noqa: E402
from sector_rotation.permtest import paired_block_bootstrap, perm_test_vs_random  # noqa: E402
from sector_rotation.universe import load_universe  # noqa: E402
from sector_rotation.walkforward import WalkResult, coverage_start, run_walkforward  # noqa: E402

TIERS = {"base": CostModel.base, "stress": CostModel.stress}


def power_note(n_oos: int) -> str:
    """评审 C9 + spec 补钉 S3：按实际样本外周数动态生成（370 周基准 ≈5-7%）。"""
    scale = (370 / n_oos) ** 0.5 if n_oos > 0 else float("nan")
    lo, hi = 0.05 * scale, 0.07 * scale
    return (f"功效边界：样本外 {n_oos} 周，单侧 p<0.1 稳定检出的年化 α ≈ "
            f"{lo:.1%}-{hi:.1%}（spec §3.8 补钉 S3：随 √(370/n) 缩放，粗估）；"
            f"证伪结论是「未检出 ≥{lo:.0%}/年的 α」，弱边际可能被错杀。")


def render_report(results: dict[str, WalkResult],
                  tests: dict[tuple[str, str, str], float], *, level: str,
                  tag: str, tier_notes: dict[str, str], prereg: str,
                  exploratory: bool = False,
                  n_oos: int | None = None) -> str:
    lines = [f"# 板块轮动回测报告：{tag}", "",
             f"- 生成：{date.today().isoformat()} · 配置：{prereg}",
             f"- 点差档：基准 {tier_notes['base']} / 压力 {tier_notes['stress']}"
             "（单边口径，含佣金后单边 11/21bp；α 全部成本后）", "",
             "| 策略 | CAGR | Sharpe | MaxDD | 胜率 | 换手 | 成本拖累(基准) | 成本拖累(压力) | 同簇截断 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, res in results.items():                        # M7/M8：nan 记 —，两档各一列
        m = res.metrics
        def _drag(key):
            mm = results.get(key).metrics if key in results else m
            v = mm.get("cost_drag", float("nan"))
            return f"{v:.1%}" if isinstance(v, float) and np.isfinite(v) else "—"
        lines.append(f"| {name} | {m['cagr']:.2%} | {m['sharpe']:.2f} | "
                     f"{m['max_dd']:.2%} | {m['win_rate']:.1%} | {m['turnover']:.1f} | "
                     f"{_drag(name)} | {_drag(f'{name}·压力档')} | {int(m['cluster_binds'])} |")
    lines += ["", "## 检验矩阵（单侧 p<0.1 判定，两档都须过）", "",
              "| 检验 | 基准档 p | 基准档 | 压力档 p | 压力档 |", "|---|---|---|---|---|"]
    for row in ("vs 随机", "vs 等权", "vs 沪深300", "vs L0"):
        cells = [row]                                        # C6：键用 level 参数
        for tier in ("base", "stress"):
            p = tests.get((level, row, tier))
            cells += ["—" if p is None else f"{p:.3f}",
                      "—" if p is None else ("过" if p < 0.1 else "未过")]
        lines.append("| " + " | ".join(cells) + " |")
    if exploratory:                                          # I10：探索性不判定
        lines += ["", "> **探索性变体——只报告不判定**（spec §3.8 变体协议，不构成闸门结论）。"]
    else:
        rows = ["vs 随机", "vs 等权", "vs 沪深300"] + ([] if level == "L0" else ["vs L0"])
        ok = all(tests.get((level, r, t), 1.0) < 0.1
                 for r in rows for t in ("base", "stress"))
        lines += ["", f"> {level} 闸门："
                  f"{'**通过，可进下一级**' if ok else '**未通过，按 spec §5 停止并写结案报告**'}"]
    if n_oos:
        lines += ["", power_note(n_oos), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", choices=["L0", "L1", "L2"], default="L0")
    ap.add_argument("--direction", choices=["momentum", "reversal"],
                    default="momentum")                      # I12
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--lookback", type=int, default=1, choices=[1, 4])
    ap.add_argument("--window", type=int, default=13, choices=[8, 13, 26, 52])
    ap.add_argument("--tier", choices=["base", "stress", "both"], default="both")
    ap.add_argument("--oos-start", default="2019-06-01",    # C9
                    help="样本外起点（实际起点 = max(此值首周, 可用行业数≥50 首周（S5）)）")
    ap.add_argument("--pre-oos", action="store_true",
                    help="预注册选择窗：只跑 oos_start 之前（I1 阶段 A）")
    ap.add_argument("--slice", default=None, metavar="FROM:TO",
                    help="稳健切片，如 2024-09-01:2024-12-31（I7）")
    ap.add_argument("--exploratory", action="store_true",
                    help="探索性变体：只报告不判定（I10）")
    ap.add_argument("--universe", type=Path,
                    default=REPO_ROOT / "config/sector-rotation-universe.md")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "output/sector-rotation")
    args = ap.parse_args(argv)
    spec = load_universe(args.universe)
    wf = build_weekly_frame(REPO_ROOT / "data", spec)

    oos_row = next(t for t, f in enumerate(wf.fridays) if f >= args.oos_start)
    start = max(coverage_start(wf), oos_row)                 # C9：样本外边界
    if args.slice:                                           # I7：稳健切片
        lo, hi = args.slice.split(":")
        run_kw = {"start": next(t for t, f in enumerate(wf.fridays) if f >= lo),
                  "end": next((t for t, f in enumerate(wf.fridays) if f > hi),
                              len(wf.fridays))}
    elif args.pre_oos:  # I1+S5 裁定：选择窗=[首个有可用行业周, 确认窗起点)，防 start>end 恒空
        run_kw = {"start": int(np.flatnonzero(wf.valid.any(axis=1))[0]), "end": start}
    else:
        run_kw = {"start": start}
    tiers = ["base", "stress"] if args.tier == "both" else [args.tier]

    def _l0(w, t):
        fn = momentum_topk if args.direction == "momentum" else reversal_topk
        return fn(w, t, lookback=args.lookback, k=args.k)

    def _l0_anti(w, t):
        fn = reversal_topk if args.direction == "momentum" else momentum_topk
        return fn(w, t, lookback=args.lookback, k=args.k)

    tests: dict[tuple[str, str, str], float] = {}
    results: dict[str, WalkResult] = {}
    n_oos = 0
    for tier in tiers:
        cost = TIERS[tier]()
        strategies = {
            f"L0-{args.direction}-lb{args.lookback}": _l0,
            "L0-反向": _l0_anti,
            "等权持有": EqualWeightAnnual(),                 # C5：年再平衡
            f"随机k{args.k}": (lambda w, t: random_k(w, t, k=args.k, seed=0)),
        }
        if args.level in ("L1", "L2"):
            from sector_rotation.models import make_strategy
            strategies[args.level] = make_strategy(args.level, k=args.k,
                                                   window=args.window)
        tier_res = {n: run_walkforward(wf, s, cost=cost, **run_kw)
                    for n, s in strategies.items()}
        main_name = args.level if args.level in ("L1", "L2") \
            else f"L0-{args.direction}-lb{args.lookback}"
        main_res = tier_res[main_name]
        n_oos = len(main_res.weekly)                         # C9：实际样本外周数
        if not args.exploratory:  # 2026-11-05 裁定：探索性跳过 1001 次置换（只按净指标选配置）
            tests[(args.level, "vs 随机", tier)] = perm_test_vs_random(
                wf, cost, k=args.k, n=1000, strategy=strategies[main_name],
                start=run_kw.get("start"), end=run_kw.get("end"))["p_value"]
        eq_weekly = tier_res["等权持有"].weekly
        bench_weekly = np.array([wf.bench_300[t]              # C4：t_rows 对齐
                                 for t in main_res.t_rows])
        tests[(args.level, "vs 等权", tier)] = paired_block_bootstrap(
            main_res.weekly - eq_weekly)
        tests[(args.level, "vs 沪深300", tier)] = paired_block_bootstrap(
            main_res.weekly - bench_weekly)
        if args.level in ("L1", "L2"):
            tests[(args.level, "vs L0", tier)] = paired_block_bootstrap(
                main_res.weekly - tier_res[f"L0-{args.direction}-lb{args.lookback}"].weekly)
        if tier == "base":
            results = tier_res
        else:
            results.update({f"{n}·压力档": r for n, r in tier_res.items()})
    tag = f"{args.level}-k{args.k}-lb{args.lookback}"
    if args.slice:
        tag += f"-slice-{args.slice.replace(':', '_')}"
    if args.pre_oos:
        tag += "-preoos"
    prereg = (f"k={args.k} / 方向={args.direction} / lookback={args.lookback} / "
              f"window={args.window} / 判定档=基准+压力双档"
              if not args.exploratory else "探索性变体——只报告不判定")
    text = render_report(results, tests, level=args.level, tag=tag,
                         tier_notes={"base": "10bp", "stress": "20bp"},
                         prereg=prereg, exploratory=args.exploratory, n_oos=n_oos)
    start_row = run_kw.get("start", start)
    oos_note = (f"OOS 起点 {wf.fridays[start_row]}（oos-start={args.oos_start} 与"
                f"可用行业数 ≥50 首周取大（S5），评审 C9），样本外 {n_oos} 周")
    out = args.out / f"{date.today():%Y-%m}" / f"backtest-{tag}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n\n" + oos_note + "\n", encoding="utf-8")
    print(text, f"\n{oos_note}", f"\n已写入 {out}", sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backtest.py -v`
Expected: PASS（2 用例，覆盖：矩阵+动态功效 / C6 level 参数 / I10 探索性无闸门行）

- [ ] **Step 5: P1 闸门——两段式预注册 + 确认性检验（评审 I1/C9 修正；预注册已从 T3 重排至此）**

```bash
# 阶段 A（选择窗 = 样本外前数据 only，--pre-oos）：探索性网格 16 组
for k in 2 3 4; do for d in momentum reversal; do for lb in 1 4; do
  conda run -n Quant-3.11 python tools/sector-rotation/backtest.py \
    --level L0 --k $k --direction $d --lookback $lb --exploratory --pre-oos
done; done; done
```
- 阶段 A 产出 16 份探索性报告（选择窗内对比，不判定；选择窗覆盖薄——S5 裁定下行业数 1-49，预注册行须披露该现实）。按结果选定主配置（k/方向/lookback），**把预注册行追加进 spec 实施记录段并单独 commit**：`预注册（P1, 2026-11-XX）：k=? / 方向=? / lookback=? / window=13 / 判定档=基准+压力双档 / 选择窗=<起止周五> 行业数 1-49（S5 裁定，探索性选择噪声披露）`。
- 阶段 B（确认性：样本外窗口、只跑预注册配置、两档）：

```bash
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 \
  --k <预注册k> --direction <预注册方向> --lookback <预注册lb>
```
Expected: 确认性报告含检验矩阵两档 p + OOS 起点与实际周数；**OOS 起点晚于 2019-06 时报告自动带 √(370/n) 重估的功效注释，该行同步写进 spec 实施记录（评审 C9）**。**读闸门**（GC 12/14）：三行 × 两档全 p<0.1 → 进 T12；任一 ≥0.1 → 停，写结案报告（含动态功效局限声明）单独 commit。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backtest.py tests/test_sr_backtest.py
git commit -m "feat(sector-rotation): 检验矩阵回测 CLI + 两段式预注册 P1 闸门（Task 11）"
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
    def __init__(self, *, window: int = 13, epochs: int = 100, lr: float = 1e-2,
                 variant: str = "joint")   # I4："joint" | "independent"（每行业独立版）
    def fit(self, blocks: np.ndarray, y: np.ndarray, r: np.ndarray) -> None
        # blocks 已是训练窗标准化后的窗口块（调用方 _prep 负责，I-4 合规）
    def select(self, wf: WeeklyFrame, t: int, *, k: int = 3) -> dict[int, float]

def make_strategy(level: str, *, k: int = 3, window: int = 13,
                  lambda_fin: float = LAMBDA_FIN, mc_dropout: bool = True,
                  roc: bool = True, l1_variant: str = "joint") -> object
    # 返回**可调用对象** strategy(wf, t)（评审 I11：统一 callable 协议，禁 .select 协议）
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
                       np.full((T, 2), 2e8), M2, SPEC, valid, valid.copy(),
                       np.full(T, 0.001))


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
                     M2, SPEC, valid, valid.copy(), np.full(T, 0.001))
    assert 0 in make_strategy("L1", k=1)(wf, T - 2)      # callable 协议（I11）


def test_l1_independent_variant_runs():
    """评审 I4：spec §3.4 L1 双版——每行业独立 sigmoid+BCE 也要实现并对照。"""
    strat = make_strategy("L1", k=1, l1_variant="independent")
    assert isinstance(strat(toy_wf(T=180), 178), dict)


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
    def __init__(self, *, window: int = 13, epochs: int = 100, lr: float = 1e-2,
                 variant: str = "joint"):           # 评审 I4："joint" | "independent"
        self.window, self.epochs, self.lr, self.variant = window, epochs, lr, variant

    def fit(self, blocks: np.ndarray, y: np.ndarray, r: np.ndarray) -> None:
        torch = _torch()
        Xt = torch.tensor(blocks, dtype=torch.float32)
        Yt, Rt = torch.tensor(y), torch.tensor(r)
        D, L = blocks.shape[1], y.shape[1]
        if self.variant == "joint":                 # 联合 multi-label 版
            self.nets = [torch.nn.Linear(D, L)]
        else:                                       # I4：每行业独立 sigmoid+BCE
            self.nets = [torch.nn.Linear(D, 1) for _ in range(L)]
        opt = torch.optim.Adam([p for n in self.nets for p in n.parameters()],
                               lr=self.lr)
        bce = torch.nn.BCEWithLogitsLoss()
        for _ in range(self.epochs):
            opt.zero_grad()
            logits = torch.cat([n(Xt) for n in self.nets], dim=1)
            (bce(logits, Yt) - LAMBDA_FIN * (torch.sigmoid(logits) * Rt).mean()
             ).backward()
            opt.step()

    def probs_now(self, x: np.ndarray) -> np.ndarray:
        torch = _torch()
        with torch.no_grad():
            z = torch.cat([n(torch.tensor(x, dtype=torch.float32))
                           for n in self.nets], dim=0).numpy()
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
                  roc: bool = True, l1_variant: str = "joint") -> object:
    # window = 特征窗 N（spec §3.3 网格 {8,13,26,52}，I3）；≠ L0 的 lookback（排名回看）。
    if level == "L1":
        strat = LinearModel(window=window, variant=l1_variant)
        return lambda wf, t: strat.select(wf, t, k=k)  # type: ignore[return-value]
    if level == "L2":
        from functools import partial
        return partial(_l2_select, k=k, window=window,
                       lambda_fin=lambda_fin, mc_dropout=mc_dropout, roc=roc)
    raise ValueError(f"未知 level: {level}")


def _l2_select(wf: WeeklyFrame, t: int, *, k: int, window: int,
               lambda_fin: float, mc_dropout: bool, roc: bool) -> dict[int, float]:
    raise NotImplementedError("Task 13 实现（T13 落地为有状态 L2Strategy）")
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
    @staticmethod
    def thresholds_from_pairs(pairs: list, n_assets: int) -> np.ndarray
        # 评审 I5（spec §3.4 口径修正）：trailing **52 对「逐周实际预测-标签」**
        # 的 ROC Youden J；<26 对回退 0.5。禁用训练窗 in-sample 拟合概率充数。

class L2Strategy:                 # 有状态 callable（评审 I5 + I11）
    def __init__(self, *, k: int, window: int, lambda_fin: float,
                 mc_dropout: bool, roc: bool)
        # pairs = deque(maxlen=52) 环形缓冲；每次 __call__ 先把上周 (预测,已实现
        # 标签) 入缓冲（标签 = 当周 etf_close/etf_open 收益，决策时点 t 已知，无泄漏）
    def __call__(self, wf: WeeklyFrame, t: int) -> dict[int, float]
        # 置信 ∧ prob>阈值(trailing 对) ∧ valid → 按 prob 排序 top-k
```

（执行注：models.py 顶部补 `from collections import deque`；`make_strategy` 的 L2 分支同步改为 `return L2Strategy(k=k, window=window, lambda_fin=lambda_fin, mc_dropout=mc_dropout, roc=roc)`——walkforward 全程单实例，缓冲才能跨周累积。）

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


def test_thresholds_from_trailing_pairs():
    """评审 I5：阈值来自 trailing 52 对实际预测-标签，<26 对回退 0.5。"""
    from sector_rotation.models import MimoModel
    rng = np.random.default_rng(4)
    pairs = [(rng.random(3), rng.integers(0, 2, 3).astype(float))
             for _ in range(30)]
    th = MimoModel.thresholds_from_pairs(pairs, 3)
    assert th.shape == (3,) and ((th > 0) & (th < 1)).all()
    assert (MimoModel.thresholds_from_pairs(pairs[:5], 3) == 0.5).all()


def test_l2_strategy_records_pairs_statefully():
    """评审 I5+I11：有状态 callable，跨周缓冲 trailing 对。"""
    from sector_rotation.models import make_strategy
    strat = make_strategy("L2", k=1)
    wf = toy_wf(T=180)
    assert isinstance(strat(wf, 176), dict)
    assert isinstance(strat(wf, 178), dict)
    assert len(strat.pairs) >= 1
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

    @staticmethod
    def thresholds_from_pairs(pairs: list, n_assets: int) -> np.ndarray:
        """评审 I5（spec §3.4 口径）：trailing 52 对逐周实际预测-标签的 Youden J；
        <26 对回退 0.5（禁 in-sample 拟合概率充数）。"""
        out = np.full(n_assets, 0.5)
        if len(pairs) < 26:
            return out
        probs = np.vstack([p for p, _ in pairs])
        labels = np.vstack([lab for _, lab in pairs])
        for j in range(n_assets):
            p, yv = probs[:, j], labels[:, j]
            order = np.argsort(-p)
            ps, ys = p[order], yv[order]
            tp, fp = np.cumsum(ys), np.cumsum(1 - ys)
            P, N = ys.sum(), len(ys) - ys.sum()
            if P == 0 or N == 0:
                continue
            out[j] = ps[int(np.argmax(tp / P - fp / N))]   # Youden J
        return out


class L2Strategy:
    """评审 I5+I11：有状态 callable——trailing 52 对预测-标签环形缓冲驱动 ROC 阈值。"""

    def __init__(self, *, k: int, window: int, lambda_fin: float,
                 mc_dropout: bool, roc: bool):
        self.k, self.window = k, window
        self.lambda_fin, self.mc_dropout_on, self.roc_on = lambda_fin, mc_dropout, roc
        self.pairs: deque = deque(maxlen=52)
        self._pending: tuple[int, np.ndarray] | None = None

    def __call__(self, wf: WeeklyFrame, t: int) -> dict[int, float]:
        from .weekly import weekly_gross_returns
        r = weekly_gross_returns(wf)
        if self._pending is not None:        # 上周预测的标签此刻已知（≤t，无泄漏）
            t_prev, probs_prev = self._pending
            if np.isfinite(r[t_prev]).any():
                self.pairs.append(
                    (probs_prev, (r[t_prev] >= 0.01).astype(float)))
        prep = _prep(wf, t, window=self.window)
        if prep is None:
            return {}
        X, y, r_hist, x_now = prep
        model = MimoModel(X.shape[1], y.shape[1])
        model.fit(X, y, r_hist, lambda_fin=self.lambda_fin)
        if self.mc_dropout_on:
            probs, confident = model.mc_dropout(x_now)
        else:
            probs, confident = model.mc_dropout(x_now, T=1), np.ones(y.shape[1], bool)
        self._pending = (t, probs)
        th = (MimoModel.thresholds_from_pairs(list(self.pairs), y.shape[1])
              if self.roc_on else np.zeros(y.shape[1]))
        cands = [i for i in range(len(probs))
                 if confident[i] and probs[i] > th[i] and wf.valid[t, i]]
        cands.sort(key=lambda i: -probs[i])
        picked = cands[:self.k]
        return {i: 1.0 / len(picked) for i in picked} if picked else {}
```

- [ ] **Step 4: 通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_models.py -v`
Expected: PASS（6 用例：L1 可分性 / L1 独立版 / level 校验 / MC dropout 形状 / trailing 对阈值 / 有状态缓冲）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/models.py tests/test_sr_models.py
git commit -m "feat(sector-rotation): L2 MIMO（MC dropout/ROC trailing/金融损失开关，Task 13）"
```

---

### Task 14: L1/L2 接入回测 + P2 闸门 + 稳健切片（检验矩阵全行两档）

**Files:**
- Modify: `tools/sector-rotation/backtest.py`（消融旗标 `--no-fin-loss/--no-mc-dropout/--no-roc` → `make_strategy` 开关；`--l1-variant joint|independent` 透传（I4）；`--window` 已在 T11 接入（I3）；`render_report` 补探索性分年度 α 小表 `yearly_table(weekly, fridays) -> str`（按 friday 年份分组年化，标注"探索性，不作闸门"））
- Modify: `tools/sector-rotation/sector_rotation/models.py`（无改动则跳过——T12/T13 已含开关与变体参数）
- Test: `tests/test_sr_backtest.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_sr_backtest.py 追加
def test_make_strategy_ablation_switches_and_variants():
    from sector_rotation.models import make_strategy
    assert callable(make_strategy("L2", k=2, lambda_fin=0.0,
                                  mc_dropout=False, roc=False))
    assert callable(make_strategy("L1", k=2, l1_variant="independent"))


def test_yearly_table_marks_exploratory():
    import numpy as np
    import backtest
    weekly = np.full(104, 0.001)
    fridays = [f"{2021 + i // 52}-w{i % 52:02d}" for i in range(104)]
    text = backtest.yearly_table(weekly, fridays)
    assert "2021" in text and "2022" in text and "探索性" in text
```

- [ ] **Step 2: 失败** → **Step 3: 实现**（旗标与变体透传 + 分年度表；全部探索性产物在报告尾注"不构成闸门结论"）

- [ ] **Step 4: 通过** → **Step 5: P2 闸门与稳健切片全量真实跑（两档）**

**5a. L1 闸门先行（评审 M14 + spec 补钉 S2：L1 升级闸门时点 = P2 入口，L2 主检验前必读）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L1 \
  --k <预注册k> --direction <预注册方向> --lookback <预注册lb> --l1-variant joint
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L1 \
  --k <预注册k> --direction <预注册方向> --lookback <预注册lb> --l1-variant independent
```
**读 L1 闸门**（两版各四行 × 两档）：任一版过 → 记录并继续；两版全挂 → L2 仍跑（L1 是对照不是闸门对象，但结果写入 spec 实施记录）。

**5b. L2 主检验 + 消融 + window 网格（消融与网格标探索性，I3）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 \
  --k <预注册k> --direction <预注册方向> --lookback <预注册lb>
for w in 8 26 52; do
  conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 \
    --k <预注册k> --window $w --exploratory
done
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 \
  --k <预注册k> --no-fin-loss --exploratory
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 \
  --k <预注册k> --no-mc-dropout --exploratory
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 \
  --k <预注册k> --no-roc --exploratory
```
**读 L2 闸门**（GC 12）：主检验四行（vs 随机/等权/沪深300/L0）× 两档全 p<0.1 → 进 T15；任一 ≥0.1 → 停 T15，写结案报告（含动态功效注释）。消融/window 网格/L1 全部探索性只报告。

**5c. 稳健切片（评审 I7：显式步骤与验收，不再"手工切"）**

```bash
# ① 指数口径漂移分段（spec §3.8 v1.2 I-9）：2023-07 前后两段 L0 重跑
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 \
  --k <预注册k> --direction <预注册方向> --lookback <预注册lb> \
  --slice <回补起点>:2023-06-30 --exploratory
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 \
  --k <预注册k> --direction <预注册方向> --lookback <预注册lb> \
  --slice 2023-07-01:<末日> --exploratory
# ② 结构段小表：2019-2021 结构牛 / 2022-2024 熊转极值 / 2021-01:2021-04 动量崩溃段
#    （各一条 --slice，全部 --exploratory；命令同上格式）
# ③ 2024-09-24 脉冲段逐周回放
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 \
  --k <预注册k> --direction <预注册方向> --lookback <预注册lb> \
  --slice 2024-09-01:2024-10-31 --exploratory
```
验收（写进稳健切片汇总报告 `output/sector-rotation/YYYY-MM/robustness-slices.md`）：
- ① 两段动量/反转效应方向与显著性对比表；**两段质变（符号翻转或显著性消失）→ 升级为结案级风险，写入 spec 实施记录并追加 review-queue 一条 pending（人工裁决继续或结案）**；
- ②③ 各段 CAGR/MaxDD 小表 + 脉冲段逐周持仓明细（trades 字段已含）；
- **I13 跌停顺延敏感性**：脉冲段内跌停周（`low == prev×(1−limit) and close == low`）单列清单，对照"顺延下周一开盘卖"保守变体（该周收益取 close 与次周 open 孰低）的损益差，量化简化口径的偏差方向与幅度，写入同一报告；
- ④ **官方指数副口径探测**（spec §8-7）：联网查中证/国证官方行业指数的历史数据可得性（免费源），可得则同规则跑 L0 副口径对照（探索性），不可得则记 not-feasible 与原因。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backtest.py tools/sector-rotation/sector_rotation/models.py tests/test_sr_backtest.py
git commit -m "feat(sector-rotation): L1/L2 接入 + 消融 + window 网格 + 稳健切片 + P2 闸门（Task 14）"
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
from dataclasses import replace
from pathlib import Path

import numpy as np

from sector_rotation.baselines import momentum_topk
from sector_rotation.signal import build_signal
from tests.test_sr_models import toy_wf


def test_build_signal_uses_decision_valid(tmp_path: Path):
    """评审 C7：信号帧（valid[-1]=False 执行周未发生）用决策期口径仍出信号；
    M5：ETF 显示名来自 etf-names.json。"""
    wf = replace(toy_wf(), dvalid=np.ones_like(toy_wf().dvalid))  # 决策期数据齐
    assert not wf.valid[-1, :].any()        # 执行期无效（fixture 设定）
    sig = build_signal(wf, momentum_topk, k=1,
                       etf_names={"EA.SH": "甲ETF"})
    assert set(sig) >= {"friday", "buy", "skipped"}
    assert len(sig["buy"]) == 1
    assert {"etf", "name", "weight"} <= set(sig["buy"][0])
    assert sig["buy"][0]["name"] == "甲ETF"
```

（执行注：跨文件导入不顺则把 `toy_wf` 提为 `tests/conftest.py` fixture；`build_signal` 内部用 `replace(wf, valid=wf.dvalid)` 切决策期口径——测试里外层 replace 只是把 fixture 的 dvalid 设成"决策期数据齐"，模拟周五盘后真实状态。）

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


def build_signal(wf, strategy, *, k: int,
                 etf_names: dict[str, str] | None = None) -> dict:
    """评审 C7：信号帧用**决策期口径**——replace(wf, valid=wf.dvalid)，最后一帧
    （执行周未发生）仍可出信号；评审 I11：strategy(wf, t) callable 协议；
    评审 M5：ETF 显示名取 build_universe 落盘的 etf-names.json。"""
    from dataclasses import replace as _replace
    t = len(wf.fridays) - 1
    weights = strategy(_replace(wf, valid=wf.dvalid), t)
    cmap = cluster_for(wf.spec, wf.fridays[t]) or {}
    names = etf_names or {}
    buy = [{"etf": wf.etf_symbols[t][i], "name": names.get(wf.etf_symbols[t][i], "—"),
            "weight": w, "index": wf.members[i].index_code,
            "index_name": wf.members[i].index_name,
            "cluster": cmap.get(wf.members[i].index_code, "—")}
           for i, w in sorted(weights.items(), key=lambda kv: -kv[1])]
    skipped = [{"etf": wf.etf_symbols[t][i], "index": wf.members[i].index_code}
               for i in range(len(wf.members))
               if i not in weights and wf.dvalid[t, i]]
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
    import json
    names_path = REPO_ROOT / "data/sector-rotation/etf-names.json"
    etf_names = (json.loads(names_path.read_text(encoding="utf-8"))
                 if names_path.exists() else {})
    sig = build_signal(wf, make_strategy(args.level, k=args.k), k=args.k,
                       etf_names=etf_names)
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

- [ ] **Step 4: README**（模块图 + CLI 速查 + 两档成本表（单边 11/21bp，roundtrip 22/42bp）+ **已知限制清单**：跌停顺延简化（I13 敏感性已量化）、周频重训 vs 论文增量更新、金融损失/trailing 对阈值为实现方口径（论文未给公式）、ETF 规模用成交额 proxy、退市 ETF 可得性结论、除息事件数与偏差方向（I9）、coverage 曲线末年为部分年（M3）、`window_blocks` 要求全列齐——单一新行业缺史丢整帧（M10）、全周停牌 fallback wk+14 错位未记（M11）、`limit_pct` 为 Member 单值近似（M12）、P1/P2 闸门真实 p 值摘要）

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

## Self-Review 记录（v1.1 = 评审全修闭环版）

1. **评审逐条修复映射**（9C+15I 全修 + 一行级 Minor + M14；处置明细见评审报告末尾处置记录）：
   - **C1** 成本单边口径（22/42bp）→ GC 9 + T6 实现/测试对拍 spec §7 算术；
   - **C2** bootstrap H0 重定心 → T10 `paired_block_bootstrap`（centered 重抽）+ 正/负例双测试；
   - **C3** `backfill.py indices` 全量步骤 + 深度验收门槛（≥80% 标的 ≥2400 根）+ 跳过短史如实记录 → T2 Step 5②③；M13 断点续传并入 `run_backfill`；
   - **C4** 配对基准 `bench_300[t_rows]` → T10 `WalkResult.t_rows` + T11 main；
   - **C5** 净换手计费（逐资产 |Δw| × side，引擎漂移调整）+ 等权对照年再平衡 → GC 9 + T8 `EqualWeightAnnual` + T9 `simulate_week` + T10 漂移；
   - **C6** `render_report(level=…)` 矩阵键 → T11 + L1/L2 键路径测试；
   - **C7** 决策期/执行期双 valid（`dvalid`）→ T4 双口径 + T15 `replace(wf, valid=wf.dvalid)`；附带修复 T4 fixture 日期区间盖不到决策周的同类矛盾（评审未列、修复中发现）；
   - **C8** 簇代测试改为 g+2 口径（实现不动，避免 I-4 泄漏）→ T1 测试 + T9 默认 friday ≥2021；
   - **C9** OOS 边界 = max(2019-06 首周, coverage 起点（S5 后口径：可用行业绝对数 ≥50 首周）) + `--pre-oos` 选择窗 + 动态 `power_note(√(370/n))` + 实施记录回写 → GC 12 + T10 `oos_start/end` + T11（终审 Minor 3 修正：原文"覆盖率 80% 首周"为 S5 前陈旧口径）；
   - **I1** 预注册从 T3 挪到 T11 两段式 → T3 Step 6 只留 review-queue + 停等（I8 一并）；
   - **I2** 风控六条补全（回撤 ≥8% 半仓、绝对亏损 ≥10% 全停）→ T9 `nav` 参数 + 测试；
   - **I3** `--lookback`（排名回看）与 `--window`（特征窗 N，spec 网格 {8,13,26,52}）分离 + T14 网格探索性跑；
   - **I4** L1 双版（joint/independent）→ T12 variant + T14 双版对照；
   - **I5** ROC 阈值 trailing 52 对实际预测-标签（<26 回退 0.5）→ T13 `thresholds_from_pairs` + 有状态 `L2Strategy`；
   - **I6** n 禁降档 → GC 12 + T10 执行注；
   - **I7** 稳健切片显式步骤（2023-07 分段带结案级裁决、结构段、脉冲段、官方副口径探测、I13 顺延敏感性）→ T14 Step 5c + 验收行；
   - **I9** 除息事件扫描与偏差方向声明 → T2 `ex_dividend_scan`；**I10** 探索性无闸门行 → T11 `exploratory`；**I11** callable 协议统一 → T10/T11/T12/T15；**I12** `--direction` → T11；**I14** `series_lock` → T2；**I15** torch 探测前移 → T1 Step 1；
   - Minor：M1（465 实测数）、M2（年差近似注记）、M4（黄金(?!股)）、M5（etf-names.json）、M6（死常量删）、M7（cost_drag nan 特判）、M9（queue 七列模板）、M13（并入 C3）、M14（T14 Step 5a L1 闸门先读）已修；M3/M10/M11/M12 记入 T15 README 已知限制（M8 已随双列呈现修复）。
2. **Spec v1.2.1 覆盖对照**：§3.1 point-in-time + 退市 + 曲线 → T2/T3/T4；§3.2 start 分页 + 数据现实 → T2；§3.3 训练窗标准化 → T5 + T12 `_prep`；§3.4 阶梯/L1 双版/升级闸门引用矩阵 → GC 12 + T11/T12/T14；§3.5 闸门与迟滞 → T9 + T4 `etf_week_amount`；§3.6 全六条风控 + 持币截断 + 滞后簇 → T1/T9；§3.7 两档单边口径 + 净换手 → GC 9 + T6/T9；§3.8 检验矩阵（重定心 bootstrap）/两段式预注册/覆盖率起点+OOS 边界/动态功效（S3）/稳健切片 → T10/T11/T14；§5 各期出口 → T3 Step 6 / T11 Step 5 / T14 Step 5。
3. **占位符扫描**：无 TBD/TODO；"执行注"均为「以仓库真实签名/实测数据为准」的核对指令，实现代码本体完整。
4. **类型一致性**：`Member(etf_candidates)`/`UniverseSpec`/`cluster_for` T1 定义全局一致；`WeeklyFrame` 十一字段（含 `dvalid`）T4 定义、T5/T8/T9/T10/T12/T13/T15 构造与消费一致（全部 fixture 已补 `dvalid`）；策略协议统一 callable `strategy(wf, t)`（T8 函数/类、T12 lambda、T13 `L2Strategy.__call__`、T10/T11/T15 调用点）；`WalkResult(nav, nav_gross, weekly, t_rows, metrics, trades)` T10 定义与 T11 测试构造一致；`CostModel.side = commission + spread`（单边 11/21bp）在 T6/T9 测试对拍；`make_strategy(level, k, window, lambda_fin, mc_dropout, roc, l1_variant)` 签名在 T12 定义、T11/T13/T14 调用一致。
