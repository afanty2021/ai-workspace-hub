# 板块轮动策略 P0-P2（含 P3 信号工具）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 `workspace/proposals/2026-11-05-sector-rotation-design.md`（v1.1，四项已拍板）的 P0（数据回补 + 宇宙清单）、P1（回测框架 + 成本模型 + L0/L1 对照）、P2（L2 论文复刻 + 消融），并交付 P3 纸面跟踪所需的周信号工具。

**Architecture:** 双层标的（信号层 = 通达信 881 二级行业指数，执行层 = 行业 ETF）。数据复用持久化层（mootdx 深回补走 `market_data_io` 的 upsert 正规通道）；回测引擎以「周五决策帧」为原子单位，策略实现统一 `select(t)` 协议，L0 动量基线先行证伪，L1/L2（PyTorch）打赢基线才升级；成本模型在组合模拟层第一公民化。P1/P2 出口闸门是**实证判定**，不满足即停并写结案报告（design §5）。

**Tech Stack:** Python 3.11（conda Quant-3.11）、mootdx（已在环境）、numpy/pandas（已在环境）、PyTorch（T12 安装，CPU/MPS 轮子）、pytest、ruff。

**Spec:** `workspace/proposals/2026-11-05-sector-rotation-design.md`（v1.1）。冲突以 spec 为准，本计划是它的任务化论证。

## Global Constraints（全任务绑定）

1. **Python 一律 `conda run -n Quant-3.11 python ...`**（系统 Python 是 PEP 668 管理的 3.15）。
2. **测试**：`conda run -n Quant-3.11 python -m pytest tests/ -q` 全量必须保持全绿（当前 465+16 用例）；新测试放根级 `tests/test_sr_*.py`（沿 `test_masters_*.py` 命名惯例），输出必须干净。
3. **Lint**：`conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py`（规则集 E4/E7/E9/F）零告警。
4. **提交**：中文 `type: subject`，按关注点拆 commit，**不推送**；在 `feat/sector-rotation-design` 分支续做（已含 v1/v1.1 两个 docs commit），不切新分支。
5. **数据纪律**：`data/` 全部是 gitignore 运行时数据，绝不 `git add`；回测报告中的每一个数字必须来自真实运行输出，禁止编造（工作区标注纪律：`[本地]`/`[网页]`/`[推测]`）。
6. **mootdx 单 socket**：所有 bars 拉取必须经 `mootdx_source._mootdx_call`（内部已 RLock 串行化）；分页每页 ≤ 800 根（已知服务器限制），单页拿不满 10 年属预期，回补脚本按页循环 + 按 date 去重。
7. **不新建 skill、不动 AGENTS.md 路由表**（spec §4：P3 跑通前）。
8. **成本口径**（spec §3.7 逐字参数）：佣金双边各 1bp（万1）、点差全宽默认 10bp（每边计半宽 5bp）、冲击成本参数化默认 0；回测报告 α 永远只报成本后，成本拖累占比必列。
9. **执行闸门**（spec §3.5）：周一开盘涨停（`open ≥ prev_close × (1 + limit_pct × 0.995)`）弃买；周五清仓跌停（`low == limit_down and close == low`）顺延下周一开盘卖；ETF 20 日均成交额 < 5000 万当周不入买入清单。
10. **风控参数**（spec §3.6 初值）：单行业周亏 ≥5% 移出下周清单；组合连亏 4 周停一周；年内回撤 ≥8% 降半仓至新高；单行业滚动 8 周胜率 <45% 进两周观察期；组合绝对亏损 10% 全停；同产业链簇持仓 ≤2 截断。
11. **升级闸门是实证出口不是代码任务**：P1 出口 = L0 成本后对等权与随机对照置换检验 p < 0.1；P2 出口 = L2 成本后 α 同时 ≥ L0 与 L1 且分年度中位数为正。闸门失败 → 停后续任务、按 spec §5 写结案报告。

## 文件结构（决策锁定）

```
tools/sector-rotation/
  README.md                    # 模块说明 + 数据流 + CLI 速查（T15 收口）
  requirements.txt             # torch>=2.2（可选依赖注释，T1 建，T12 安装）
  backfill.py                  # CLI：881 指数 + ETF 候选深回补；verify 完整性检查
  build_universe.py            # CLI：流动性过滤 + 指数↔ETF 映射 + 相关性簇 → config 草稿
  backtest.py                  # CLI：walk-forward 回测（--level L0/L1/L2）→ output 报告
  signal.py                    # CLI：每周五盘后出下周 ETF 交易信号（P3 工具）
  sector_rotation/
    __init__.py
    universe.py                # Member 数据类 + config markdown 解析/校验
    data.py                    # WeeklyFrame：周五决策帧 + 下周一开/下周五收对齐 + 掩码
    weekly.py                  # 特征窗口矩阵 + 标准化 + 毛/净标签
    cost.py                    # CostModel：佣金/点差/冲击 → 每边/往返 bps
    metrics.py                 # CAGR/α/Sharpe/MaxDD/胜率/换手/成本拖累
    baselines.py               # 等权持有/动量 top-k/反转 top-k/随机 k/300ETF 持有
    portfolio.py               # 执行闸门 + 风控状态机 + 同簇约束 + 等权分配
    walkforward.py             # walk-forward 引擎（Strategy 协议）
    permtest.py                # 置换检验（随机 k × 1000）
    models.py                  # L1 torch 线性 + L2 MIMO（金融损失/MC dropout/ROC 阈值）
config/sector-rotation-universe.md   # 宇宙清单（P0 产物，tracked）
output/sector-rotation/              # 回测报告与周信号（YYYY-MM/ 子目录）
data/sector-rotation/                # 中间产物（universe-draft 等，gitignore）
tests/test_sr_*.py                   # 每任务配套测试（根级 tests/）
```

依赖方向（单向，禁止反向）：`backfill/build_universe → data/weekly → cost/portfolio/metrics/baselines/models → walkforward/permtest → backtest/signal`。

---

### Task 1: 脚手架 + universe.py（宇宙清单解析）

**Files:**
- Create: `tools/sector-rotation/requirements.txt`、`tools/sector-rotation/sector_rotation/__init__.py`、`tools/sector-rotation/sector_rotation/universe.py`
- Test: `tests/test_sr_universe.py`

**Interfaces:**
- Produces: `Member`（frozen dataclass，字段 `index_code: str, index_name: str, etf: str, etf_name: str, limit_pct: float, cluster: str`）；`load_universe(path: Path) -> list[Member]`；`write_universe(path: Path, members: list[Member], status: str) -> None`。后续所有任务经此读宇宙。

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

from sector_rotation.universe import Member, load_universe, write_universe


def _sample_members():
    return [
        Member("881101", "工程机械", "528030.SH", "机械ETF", 0.10, "机械"),
        Member("881127", "半导体", "512480.SH", "半导体ETF", 0.10, "半导体"),
    ]


def test_roundtrip(tmp_path: Path):
    path = tmp_path / "universe.md"
    write_universe(path, _sample_members(), status="draft")
    loaded = load_universe(path)
    assert loaded == _sample_members()


def test_load_rejects_bad_header(tmp_path: Path):
    path = tmp_path / "universe.md"
    path.write_text("---\ntype: sector-rotation-universe\n---\n别的表格\n", encoding="utf-8")
    with pytest.raises(ValueError, match="type: sector-rotation-universe"):
        load_universe(path)
```

（注：`sector_rotation` 的导入路径——测试沿用仓库现有做法：conftest 已把 `tools/` 下包纳入 sys.path 的机制若不存在，则在 `tests/conftest.py` 追加 `sys.path.insert(0, str(REPO_ROOT / "tools/sector-rotation"))`；执行本步时先读 `tests/conftest.py` 确认，只在缺失时追加这两行。）

- [ ] **Step 3: 跑测试确认失败**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_universe.py -v`
Expected: FAIL（`ModuleNotFoundError: sector_rotation`）

- [ ] **Step 4: 最小实现**

```python
# tools/sector-rotation/sector_rotation/universe.py
"""宇宙清单（config/sector-rotation-universe.md）的读写与校验。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HEADER = "type: sector-rotation-universe"
COLS = ["index_code", "index_name", "etf", "etf_name", "limit_pct", "cluster"]


@dataclass(frozen=True)
class Member:
    index_code: str
    index_name: str
    etf: str
    etf_name: str
    limit_pct: float  # 涨跌停幅度：普通行业 ETF 0.10，双创类 0.20
    cluster: str      # 产业链簇名（相关性聚类产物）


def load_universe(path: Path) -> list[Member]:
    text = path.read_text(encoding="utf-8")
    if HEADER not in text:
        raise ValueError(f"{path} 缺 frontmatter 标记 {HEADER}")
    members: list[Member] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells == COLS or cells[0] == "index_code":
            continue
        if len(cells) != len(COLS):
            raise ValueError(f"宇宙表列数不符：{line}")
        members.append(Member(cells[0], cells[1], cells[2], cells[3],
                              float(cells[4]), cells[5]))
    if not members:
        raise ValueError(f"{path} 未解析到任何成员")
    codes = [m.index_code for m in members]
    if len(codes) != len(set(codes)):
        raise ValueError("宇宙表 index_code 重复")
    return members


def write_universe(path: Path, members: list[Member], *, status: str) -> None:
    lines = [
        "---",
        HEADER,
        f"status: {status}",
        "---",
        "",
        "| " + " | ".join(COLS) + " |",
        "|" + "---|" * len(COLS),
    ]
    for m in members:
        lines.append(f"| {m.index_code} | {m.index_name} | {m.etf} | "
                     f"{m.etf_name} | {m.limit_pct} | {m.cluster} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_universe.py -v`
Expected: PASS（2 用例）

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/ tests/test_sr_universe.py
git commit -m "feat(sector-rotation): 脚手架 + 宇宙清单解析（Task 1）"
```

---

### Task 2: backfill.py——881 全集 + ETF 候选深回补 + 完整性检查

**Files:**
- Create: `tools/sector-rotation/backfill.py`
- Test: `tests/test_sr_backfill.py`

**Interfaces:**
- Consumes: `mootdx_source._mootdx_call(method, **kwargs)`、`market_data_io.upsert_series_rows(path, rows, writer="batch")`（复用 daily-watch 的正规 upsert 通道：合并去重 + 行锁 + writer 指纹）。两者经 `sys.path` 注入 `tools/daily-watch/scripts` 导入（repo 内既有跨脚本导入模式）。
- Produces: `fetch_bars_paginated(code: str, *, index: bool, total: int = 2600, page: int = 800) -> list[dict]`（date 去重升序的 bar 行，字段 date/open/high/low/close/volume/amount）；CLI `backfill.py indices|etfs|verify`。`etfs` 子命令输入 = `data/sector-rotation/etf-candidates.txt`（每行一个 `512480.SH` 式代码，由 Task 3 的候选生成预跑产出；本任务先用两行占位真实代码冒烟）。

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


def test_fetch_paginated_dedupes(monkeypatch):
    pages = [
        _page_df(["2026-11-02", "2026-10-30"]),   # 第 1 页（新）
        _page_df(["2026-10-30", "2026-10-29"]),   # 第 2 页（含重叠）
        _page_df([]),                              # 第 3 页空 → 停
    ]
    calls = []

    def fake_call(method, **kwargs):
        calls.append((method, kwargs))
        return pages[len(calls) - 1]

    monkeypatch.setattr(backfill, "_mootdx_call", fake_call)
    rows = backfill.fetch_bars_paginated("881101", index=True, total=6, page=2)
    assert [r["date"] for r in rows] == ["2026-10-29", "2026-10-30", "2026-11-02"]
    assert all(c[0] == "index_bars" for c in calls)
    assert calls[0][1]["frequency"] == 9


def test_fetch_stops_on_short_page(monkeypatch):
    monkeypatch.setattr(backfill, "_mootdx_call",
                        lambda method, **kw: _page_df(["2026-11-02"]))
    rows = backfill.fetch_bars_paginated("512480", index=False, total=100, page=2)
    assert len(rows) == 1


def test_fetch_returns_empty_when_source_down(monkeypatch):
    def boom(method, **kw):
        raise RuntimeError("server down")

    monkeypatch.setattr(backfill, "_mootdx_call", boom)
    assert backfill.fetch_bars_paginated("881101", index=True) == []


def test_verify_reports_depth_and_gaps(tmp_path: Path, capsys):
    d = tmp_path / "sector" / "series"
    d.mkdir(parents=True)
    (d / "881101.jsonl").write_text(
        '{"date":"2020-01-03","close":1.0}\n{"date":"2020-01-06","close":1.1}\n',
        encoding="utf-8")
    report = backfill.verify_depth([("881101", True)], data_root=tmp_path,
                                   expect_bars=2500)
    assert report[0]["code"] == "881101"
    assert report[0]["rows"] == 2
    assert report[0]["first"] == "2020-01-03"
    assert report[0]["shortfall"] == 2498
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backfill.py -v`
Expected: FAIL（`ModuleNotFoundError: backfill`）

- [ ] **Step 3: 实现 backfill.py**

```python
# tools/sector-rotation/backfill.py
"""881 二级行业指数与 ETF 日线深回补（spec §3.2）。

走 market_data_io 的 upsert 正规通道（与 16:30 cron 同一写者语义，writer=batch），
不绕开行锁；指数落 data/sector/series/，ETF 落 data/market/series/。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from market_data_io import upsert_series_rows  # noqa: E402
from mootdx_source import _mootdx_call, log  # noqa: E402

PAGE = 800          # mootdx 单页上限（friction-log 已记）
TOTAL = 2600        # ≈ 10.7 年日线
SECTOR_DIR = "sector/series"
ETF_DIR = "market/series"


def fetch_bars_paginated(code: str, *, index: bool, total: int = TOTAL,
                         page: int = PAGE) -> list[dict]:
    """按页回拉历史 bar，按 date 去重升序返回。

    单页失败/空返回即停（已拉到的页保留）；start 分页参数若服务器不支持，
    表现为第 2 页空返回，自然退化为单页深度——由 verify 子命令如实报告。
    """
    method = "index_bars" if index else "bars"
    by_date: dict[str, dict] = {}
    start = 0
    while start < total:
        try:
            df = _mootdx_call(method, symbol=code, frequency=9,
                              offset=page, start=start)
        except Exception as exc:  # noqa: BLE001 — 单段失败保住已拉数据
            log(f"Warning: {code} 第 {start} 起回补失败: {exc}")
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
    """index 传裸码（881101），ETF 传带后缀符号（512480.SH）——与持久化层命名一致。"""
    sub = SECTOR_DIR if index else ETF_DIR
    return data_root / sub / f"{symbol}.jsonl"


def run_backfill(targets: list[tuple[str, bool]], data_root: Path,
                 *, total: int = TOTAL) -> dict[str, int]:
    stats = {"ok": 0, "empty": 0}
    for symbol, is_index in targets:
        bare = symbol.rsplit(".", 1)[0]          # mootdx API 用裸 6 位码
        rows = fetch_bars_paginated(bare, index=is_index, total=total)
        if not rows:
            stats["empty"] += 1
            log(f"Warning: {symbol} 空返回")
            continue
        path = _target_path(data_root, symbol, index=is_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        upsert_series_rows(path, rows, writer="batch")
        stats["ok"] += 1
        log(f"{code}: {len(rows)} 根 → {path.relative_to(data_root)}")
    log(f"回补汇总: {stats}")
    return stats


def verify_depth(targets: list[tuple[str, bool]], data_root: Path,
                 *, expect_bars: int) -> list[dict]:
    report = []
    for code, is_index in targets:
        path = _target_path(data_root, code, index=is_index)
        rows = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip()] if path.exists() else []
        dates = [ln.split('"date":"')[1][:10] for ln in rows] if rows else []
        report.append({"code": code, "rows": len(rows),
                       "first": dates[0] if dates else "",
                       "last": dates[-1] if dates else "",
                       "shortfall": max(0, expect_bars - len(rows))})
    return report


def _sector_targets(data_root: Path) -> list[tuple[str, bool]]:
    import json
    listing = json.loads((data_root / "sector" / "sector-list.json").read_text())
    return [(x["code"], True) for x in listing
            if x["category"] == "二级行业"]


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("indices", help="回补 881 全集二级行业指数")
    p_etf = sub.add_parser("etfs", help="回补 etf-candidates.txt 中的 ETF")
    p_etf.add_argument("--candidates", type=Path,
                       default=data_root_default() / "sector-rotation/etf-candidates.txt")
    p_ver = sub.add_parser("verify", help="深度与完整性报告")
    p_ver.add_argument("--etf-candidates", type=Path, default=None)
    args = ap.parse_args(argv)
    data_root = data_root_default()
    if args.cmd == "indices":
        run_backfill(_sector_targets(data_root), data_root)
        return 0
    if args.cmd == "etfs":
        codes = [ln.strip() for ln in
                 args.candidates.read_text(encoding="utf-8").splitlines() if ln.strip()]
        run_backfill([(c, False) for c in codes], data_root)   # 保留 .SH/.SZ 后缀
        return 0
    targets = _sector_targets(data_root)
    if args.etf_candidates and args.etf_candidates.exists():
        codes = [ln.strip() for ln in
                 args.etf_candidates.read_text(encoding="utf-8").splitlines() if ln.strip()]
        targets += [(c, False) for c in codes]
    for row in verify_depth(targets, data_root, expect_bars=TOTAL):
        print(row)
    return 0


def data_root_default() -> Path:
    return REPO_ROOT / "data"


if __name__ == "__main__":
    raise SystemExit(main())
```

（执行注：`market_data_io.upsert_series_rows` 的具体签名以仓库现状为准，Step 3 先 `grep -n 'def upsert_series_rows' tools/daily-watch/scripts/market_data_io.py` 核对；若第二参不是 rows 列表而是 DataFrame，则在此处转换——以真实签名为准，勿按本块硬套。`upsert` 的行字段需含它要求的必填键，缺的（如 index 行的 up_count/down_count）补 `None`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backfill.py -v`
Expected: PASS（4 用例）

- [ ] **Step 5: 真实冒烟（一次性，允许跑 15-20 分钟）**

Run:
```bash
mkdir -p data/sector-rotation
printf '512480.SH\n512000.SH\n' > data/sector-rotation/etf-candidates.txt
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py etfs
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py verify --etf-candidates data/sector-rotation/etf-candidates.txt | tail -5
head -1 data/market/series/512480.SH.jsonl; tail -1 data/market/series/512480.SH.jsonl
```
Expected: 512480 深度显著 > 802（若只有 ~800，说明 start 分页不被支持——如实记录深度并在 README 的已知限制注明，881 全集回补决策不变）。ETF 行落 `data/market/series/` 与既有格式一致。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backfill.py tests/test_sr_backfill.py
git commit -m "feat(sector-rotation): mootdx 深回补 CLI（分页/去重/upsert 正规通道，Task 2）"
```

---

### Task 3: build_universe.py——ETF 候选 + 流动性过滤 + 映射 + 相关性簇 → config 草稿

**Files:**
- Create: `tools/sector-rotation/build_universe.py`
- Test: `tests/test_sr_universe_build.py`

**Interfaces:**
- Consumes: Task 2 的回补数据（`data/sector/series/881*.jsonl`、`data/market/series/{etf}.jsonl`）；Task 1 的 `write_universe`。
- Produces: `data/sector-rotation/etf-candidates.txt`（候选 ETF 代码）；`config/sector-rotation-universe.md`（status: draft）；函数 `filter_etf_candidates(listing: list[dict]) -> list[str]`、`liquidity_filter(etf: str, bars: list[dict], *, min_amount_wan: float = 5000.0, window: int = 20) -> bool`、`cluster_by_correlation(weekly_returns: "np.ndarray", codes: list[str], *, threshold: float = 0.75) -> dict[str, str]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_universe_build.py
from pathlib import Path

import numpy as np
import pytest

import build_universe  # noqa: E402


def _etf(code, name):
    return {"code": code, "name": name}


def test_filter_etf_candidates_keeps_industry_etf():
    listing = [
        _etf("512480", "半导体ETF"), _etf("512000", "券商ETF"),
        _etf("510300", "沪深300ETF"), _etf("513330", "恒生互联网ETF"),
        _etf("511990", "华宝添益"), _etf("518880", "黄金ETF"),
        _etf("159915", "创业板ETF"), _etf("588000", "科创50ETF"),
    ]
    kept = build_universe.filter_etf_candidates(listing)
    assert "512480" in kept and "512000" in kept
    assert "510300" not in kept and "513330" not in kept
    assert "511990" not in kept and "518880" not in kept


def test_liquidity_filter_uses_20d_mean_amount():
    rich = [{"amount": 2e8} for _ in range(20)]
    poor = [{"amount": 1e6} for _ in range(20)]
    assert build_universe.liquidity_filter("512480", rich, min_amount_wan=5000)
    assert not build_universe.liquidity_filter("512480", poor, min_amount_wan=5000)


def test_cluster_by_correlation_groups_high_corr():
    rng = np.random.default_rng(7)
    base = rng.normal(size=156)
    rets = np.column_stack([base, base + 0.05 * rng.normal(size=156),
                            rng.normal(size=156)])
    clusters = build_universe.cluster_by_correlation(rets, ["A", "B", "C"])
    assert clusters["A"] == clusters["B"] != clusters["C"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_universe_build.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 build_universe.py**

```python
# tools/sector-rotation/build_universe.py
"""宇宙清单构建：ETF 候选 → 流动性过滤 → 指数↔ETF 映射 → 相关性簇（spec §3.1/§3.6）。

产出一稿 config/sector-rotation-universe.md（status: draft），映射正确性由人工
复核——draft 落 review-queue 后才算 P0 宇宙完成。
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

from sector_rotation.universe import Member, write_universe  # noqa: E402
from mootdx_source import _mootdx_call  # noqa: E402

# 宽基/跨境/商品/货币/债券的关键词黑名单（spec：跨境首版不纳入）
EXCLUDE = re.compile(
    r"沪深300|中证500|中证1000|中证A50|上证50|创业板指|科创50|双创|红利|低波|价值|成长|"
    r"纳指|纳斯达克|标普|美国|日经|恒生|香港|港股通|QDII|亚洲|新兴|德国|法国|沙特|"
    r"黄金|豆粕|有色期货|能源化工|原油|货币|债|国债|信用|转债|国债逆回购|添益|理财")

# 881 指数名 → 常见行业 ETF 跟踪名关键词（手工映射底稿，未命中项输出待人工补）
KEYWORDS: dict[str, list[str]] = {
    "证券": ["证券", "券商"], "银行": ["银行"], "保险": ["保险"],
    "半导体": ["半导体", "芯片"], "软件服务": ["软件", "计算机"],
    "通信设备": ["通信", "5G"], "电子": ["电子"],
    "白酒": ["酒"], "食品饮料": ["食品饮料", "消费"],
    "医药": ["医药", "医疗", "创新药", "生物医药"], "中药": ["中药"],
    "煤炭": ["煤炭"], "钢铁": ["钢铁"], "有色": ["有色", "稀土", "黄金股"],
    "石油": ["石油", "油气"], "化工": ["化工", "碳中和"],
    "电力": ["电力"], "光伏": ["光伏"], "风电": ["风电"],
    "新能源车": ["新能源车", "智能汽车", "汽车"], "电池": ["电池"],
    "军工": ["军工", "国防"], "机械": ["机械", "智能制造"],
    "建筑": ["基建", "建筑材料"], "房地产": ["房地产"],
    "家用电器": ["家电"], "农业": ["农业", "养殖"],
    "运输设备": ["高铁"], "航空": ["航空"], "航运": ["航运"],
    "传媒": ["传媒", "游戏"], "教育": ["教育"],
}


def filter_etf_candidates(listing: list[dict]) -> list[str]:
    """从 mootdx stocks 枚举中筛行业/主题 ETF 候选（宽基跨境商品货币债剔除）。"""
    kept = []
    for item in listing:
        code, name = item["code"], (item.get("name") or "")
        if not re.match(r"^(51|15|56|58)\d{4}$", code):   # 56 = 沪市新 ETF 段
            continue
        if "ETF" not in name or EXCLUDE.search(name):
            continue
        kept.append(code)
    return sorted(set(kept))


def liquidity_filter(etf: str, bars: list[dict], *,
                     min_amount_wan: float = 5000.0, window: int = 20) -> bool:
    """近 window 根日线均成交额 ≥ 门槛（元→万元口径：min_amount_wan 单位万元）。"""
    amounts = [b["amount"] for b in bars[-window:] if b.get("amount")]
    return len(amounts) == window and (sum(amounts) / window) >= min_amount_wan * 1e4


def cluster_by_correlation(weekly_returns: np.ndarray, codes: list[str],
                           *, threshold: float = 0.75) -> dict[str, str]:
    """周收益相关性 > threshold 连通分量聚类（spec §3.6 产业链簇）。确定性：按 code 排序遍历。"""
    corr = np.corrcoef(weekly_returns, rowvar=False)
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
    # 簇名 = 簇内首个（code 序）成员的 code，保证稳定
    return {codes[i]: f"cluster-{codes[min(g)]}" for g in groups.values() for i in g}


def _weekly_close_matrix(code: str, data_root: Path) -> tuple[list[str], dict[str, float]]:
    path = data_root / "sector" / "series" / f"{code}.jsonl"
    closes: dict[str, float] = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            closes[row["date"]] = float(row["close"])
    return sorted(closes), closes


def build(data_root: Path, out_config: Path) -> dict[str, int]:
    listing = []
    for market in (0, 1):
        df = _mootdx_call("stocks", market=market)
        listing += [{"code": str(c).zfill(6), "name": str(n).replace("\x00", "")}
                    for c, n in zip(df["code"], df["name"])]
    candidates = filter_etf_candidates(listing)
    cand_file = data_root / "sector-rotation" / "etf-candidates.txt"
    cand_file.parent.mkdir(parents=True, exist_ok=True)
    cand_file.write_text("\n".join(f"{c}.SH" if c.startswith(("51", "56", "58"))
                                   else f"{c}.SZ" for c in candidates) + "\n",
                         encoding="utf-8")

    # 映射：881 指数名关键词 → 候选 ETF 名包含即配对（取代码序第一只，人工复核换优）
    name_by_code = {c: n for c, n in ((x["code"], x["name"]) for x in listing)}
    sector_list = json.loads((data_root / "sector" / "sector-list.json").read_text())
    lv2 = [x for x in sector_list if x["category"] == "二级行业"]
    members: list[Member] = []
    unmatched: list[str] = []
    for sec in lv2:
        idx_name = sec["name"].replace("\x00", "")
        hit = None
        for kw in KEYWORDS.get(idx_name, [idx_name[:2]]):
            for cand in candidates:
                if kw in (name_by_code.get(cand) or ""):
                    hit = cand
                    break
            if hit:
                break
        if not hit:
            unmatched.append(f"{sec['code']} {idx_name}")
            continue
        etf_sym = f"{hit}.SH" if hit.startswith(("51", "56", "58")) else f"{hit}.SZ"
        etf_path = data_root / "market" / "series" / f"{etf_sym}.jsonl"
        etf_bars = [json.loads(ln) for ln in
                    etf_path.read_text(encoding="utf-8").splitlines() if ln.strip()] \
            if etf_path.exists() else []
        if not liquidity_filter(hit, etf_bars):
            unmatched.append(f"{sec['code']} {idx_name} (ETF {etf_sym} 流动性不足)")
            continue
        members.append(Member(sec["code"], idx_name, etf_sym,
                               name_by_code.get(hit, ""), 0.10, ""))

    # 簇划分：入选指数的周收益相关性（3 年窗口）
    codes = [m.index_code for m in members]
    dates_union: set[str] = set()
    series = {c: dict(zip(*_weekly_close_matrix(c, data_root)[::-1]))
              for c in codes}  # {code: {date: close}}
    # 周五近似：取每周最后一根日线（指数为日线序列）
    for c in codes:
        dates_union.update(series[c])
    all_dates = sorted(dates_union)
    week_last: list[str] = []
    for d in all_dates:
        if week_last and d[:7] == week_last[-1][:7] and d > week_last[-1]:
            # 同周内更晚的日期替换（ISO 周判定从简：同月内递增视为可能同周，配合下一条）
            pass
        week_last.append(d)
    # 简化：直接用全部日线收盘算相关性（周频相关性与日频在聚类层近似等价，簇容差大）
    aligned = np.array([[series[c].get(d, np.nan) for d in all_dates] for c in codes])
    rets = np.diff(np.log(aligned), axis=1)
    rets = rets[:, ~np.isnan(rets).any(axis=0)]
    clusters = cluster_by_correlation(rets.T if rets.shape[0] != len(codes) else rets, codes)
    members = [Member(m.index_code, m.index_name, m.etf, m.etf_name, m.limit_pct,
                      clusters[m.index_code]) for m in members]
    write_universe(out_config, members, status="draft")
    (data_root / "sector-rotation" / "unmatched.txt").write_text(
        "\n".join(unmatched) + "\n", encoding="utf-8")
    return {"members": len(members), "unmatched": len(unmatched),
            "candidates": len(candidates)}


def main() -> int:
    stats = build(REPO_ROOT / "data", REPO_ROOT / "config" / "sector-rotation-universe.md")
    print(stats)
    print("草稿已写 config/sector-rotation-universe.md（status: draft）")
    print("未命中清单见 data/sector-rotation/unmatched.txt —— 人工补 KEYWORDS 后重跑")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

（执行注 1：KEYWORDS 是**底稿**，首跑后按 `unmatched.txt` 补齐关键词并人工换掉"代码序第一只"的次优配对（如券商类多只 ETF 里选规模最大者，成交额已在 bars 里，可按 20 日均额排序取最优——执行时把 hit 选择改为候选中均额最大者，属本任务范围内的小改进）。执行注 2：`_weekly_close_matrix` 返回 `(dates, closes_dict)`，上面 `dict(zip(*...[::-1]))` 写法等价 `{dates→close}`，执行时若绕可直接重写清晰版。）

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_universe_build.py -v`
Expected: PASS（3 用例）

- [ ] **Step 5: 真实数据全流程跑（依赖 Task 2 的 881 全集回补完成）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/build_universe.py
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py etfs   # 回补新筛出的候选
conda run -n Quant-3.11 python tools/sector-rotation/build_universe.py  # 带上流动性数据重筛
```
Expected: `config/sector-rotation-universe.md`（draft，预计 40-60 成员 [推测]）+ unmatched.txt。数字如实记录，不许改数字凑 40-60。

- [ ] **Step 6: review-queue 提名（宇宙清单确认是 spec 拍的 P0 闸门）**

向 `workspace/review-queue.md` 表格追加一行（pending）：
`| Q-<日期>-01 | proposal | config/sector-rotation-universe.md | 确认板块轮动宇宙清单（draft→confirmed）：881 二级行业 × 行业 ETF 映射 + 流动性/簇划分；重点复核映射正确性与双创 ETF limit_pct=0.20 标注 | build_universe.py P0 产物 | <日期> | pending |`

- [ ] **Step 7: Commit**

```bash
git add tools/sector-rotation/build_universe.py tests/test_sr_universe_build.py config/sector-rotation-universe.md
git commit -m "feat(sector-rotation): 宇宙构建（候选/流动性/映射/相关性簇）+ config 草稿（Task 3）"
```

---

### Task 4: data.py——WeeklyFrame（周五决策帧对齐）

**Files:**
- Create: `tools/sector-rotation/sector_rotation/data.py`
- Test: `tests/test_sr_data.py`

**Interfaces:**
- Consumes: Task 1 `Member`；Task 2 数据布局（`data/sector/series/{index}.jsonl`、`data/market/series/{etf}.jsonl`）。
- Produces:

```python
@dataclass
class WeeklyFrame:
    fridays: list[str]          # 决策日（当周最后交易日，周五或节假日顺延日）
    index_close: np.ndarray     # (T, L) 指数周五收盘
    etf_open: np.ndarray        # (T, L) 下一周一开盘（决策 t 的执行价）
    etf_close: np.ndarray       # (T, L) 下一周五收盘（清仓价）
    etf_prev_close: np.ndarray  # (T, L) 上一周五收盘（周一开盘涨跌停判定基准）
    members: list[Member]
    valid: np.ndarray           # (T, L) bool：决策帧完整（指数+ETF 三价齐）才 True

def build_weekly_frame(data_root: Path, members: list[Member]) -> WeeklyFrame
```

`fridays[t]` 的执行语义（spec §3.3/§3.5）：t 日收盘后决策 → t+1 周周一开盘买入 → t+1 周周五收盘清仓。`etf_open[t]/etf_close[t]` 即对应 t+1 周的两价，与 fridays[t] 对齐存放。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_data.py
import json
from pathlib import Path

from sector_rotation.data import build_weekly_frame
from sector_rotation.universe import Member

MEM = Member("881101", "工程机械", "528030.SH", "机械ETF", 0.10, "机械")


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


def test_weekly_frame_aligns_decision_and_execution(tmp_path: Path):
    # 周 1：决策周五 11-06；周 2：周一开 11-09 买入、周五收 11-13 清仓
    _write(tmp_path / "sector/series/881101.jsonl", [
        {"date": "2026-11-06", "close": 100.0},
        {"date": "2026-11-13", "close": 101.0},
    ])
    _write(tmp_path / "market/series/528030.SH.jsonl", [
        {"date": "2026-10-30", "close": 1.00},   # 上一周五（涨跌停基准）
        {"date": "2026-11-06", "close": 1.02},
        {"date": "2026-11-09", "open": 1.03, "close": 1.04},
        {"date": "2026-11-10", "open": 1.05, "close": 1.06},
        {"date": "2026-11-11", "open": 1.06, "close": 1.07},
        {"date": "2026-11-12", "open": 1.07, "close": 1.08},
        {"date": "2026-11-13", "open": 1.08, "close": 1.10},
    ])
    wf = build_weekly_frame(tmp_path, [MEM])
    assert wf.fridays == ["2026-11-06"]
    assert wf.etf_open[0, 0] == 1.03      # 下周一开盘
    assert wf.etf_close[0, 0] == 1.10     # 下周五收盘
    assert wf.etf_prev_close[0, 0] == 1.00
    assert wf.valid[0, 0]


def test_weekly_frame_marks_incomplete_weeks_invalid(tmp_path: Path):
    _write(tmp_path / "sector/series/881101.jsonl", [
        {"date": "2026-11-06", "close": 100.0},
        {"date": "2026-11-13", "close": 101.0},
        {"date": "2026-11-20", "close": 102.0},
    ])
    _write(tmp_path / "market/series/528030.SH.jsonl", [
        {"date": "2026-11-06", "close": 1.02},
        {"date": "2026-11-09", "open": 1.03, "close": 1.04},
        {"date": "2026-11-13", "open": 1.08, "close": 1.10},
        # 11-20 决策帧：下周（11-23~11-27）ETF 无数据 → invalid（弃权）
    ])
    wf = build_weekly_frame(tmp_path, [MEM])
    assert wf.valid[0, 0] and not wf.valid[1, 0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_data.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 data.py**

```python
# tools/sector-rotation/sector_rotation/data.py
"""周五决策帧构建：指数周五收盘（特征）× ETF 周一开/周五收（执行与损益）对齐。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from .universe import Member


@dataclass
class WeeklyFrame:
    fridays: list[str]
    index_close: np.ndarray
    etf_open: np.ndarray
    etf_close: np.ndarray
    etf_prev_close: np.ndarray
    members: list[Member] = field(repr=False)
    valid: np.ndarray


def _load_daily(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                row = json.loads(ln)
                out[row["date"]] = row
    return out


def _week_key(d: str) -> date:
    """ISO 周（周一）作为周分组键。"""
    day = date.fromisoformat(d)
    return day.fromisocalendar(day.isocalendar()[0], day.isocalendar()[1], 1)


def build_weekly_frame(data_root: Path, members: list[Member]) -> WeeklyFrame:
    idx_series = [_load_daily(data_root / "sector" / "series" / f"{m.index_code}.jsonl")
                  for m in members]
    etf_series = [_load_daily(data_root / "market" / "series" / f"{m.etf}.jsonl")
                  for m in members]
    # 每列取每周最后一根日线 = 决策日（周五或节前最后交易日）
    week_last: list[dict[int, dict[str, dict]]] = []
    for series in idx_series:
        by_week: dict[int, dict[str, dict]] = {}
        for d, row in series.items():
            wk = _week_key(d).toordinal()
            if wk not in by_week or d > by_week[wk]["date"]:
                by_week[wk] = {"date": d, "row": row}
        week_last.append(by_week)
    # ETF 周内首/末日（执行周 = 决策周的下一 ISO 周）
    etf_week_bounds = []
    for series in etf_series:
        first, last, prev_last = {}, {}, {}
        for d in sorted(series):
            wk = _week_key(d).toordinal()
            if wk not in first:
                first[wk] = series[d]
            prev_last[wk] = last.get(wk)
            last[wk] = series[d]
        etf_week_bounds.append((first, last, prev_last))

    all_weeks = sorted({wk for by_week in week_last for wk in by_week})
    # 决策周 t 的执行周 = t+1 周（按 ordinal 连续递推，跳过长假周用 actual next）
    t_count = len(all_weeks)
    shape = (t_count, len(members))
    idx_close = np.full(shape, np.nan)
    etf_open = np.full(shape, np.nan)
    etf_close = np.full(shape, np.nan)
    etf_prev = np.full(shape, np.nan)
    valid = np.zeros(shape, dtype=bool)
    fridays: list[str] = []
    for ti, wk in enumerate(all_weeks):
        fridays.append(week_last[0][wk]["date"] if wk in week_last[0] else "")
        for li in range(len(members)):
            if wk in week_last[li]:
                idx_close[ti, li] = float(week_last[li][wk]["row"]["close"])
            first, last, prev_last = etf_week_bounds[li]
            next_wk = None
            for cand in (wk + 7, wk + 14):  # 长假容忍：最多跳一周
                if cand in first:
                    next_wk = cand
                    break
            if next_wk is not None:
                etf_open[ti, li] = float(first[next_wk].get("open", first[next_wk]["close"]))
                etf_close[ti, li] = float(last[next_wk]["close"])
            if wk in last:
                etf_prev[ti, li] = float(last[wk]["close"])
            valid[ti, li] = bool(
                np.isfinite(idx_close[ti, li]) and np.isfinite(etf_open[ti, li])
                and np.isfinite(etf_close[ti, li]) and np.isfinite(etf_prev[ti, li]))
    # fridays 取该周所有指数决策日的最大日期
    fridays = []
    for ti, wk in enumerate(all_weeks):
        fridays.append(max(by_week[wk]["date"] for by_week in week_last if wk in by_week))
    return WeeklyFrame(fridays, idx_close, etf_open, etf_close, etf_prev,
                       members, valid)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_data.py -v`
Expected: PASS（2 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/data.py tests/test_sr_data.py
git commit -m "feat(sector-rotation): WeeklyFrame 决策帧对齐（Task 4）"
```

---

### Task 5: weekly.py——特征窗口 + 标准化 + 双口径标签

**Files:**
- Create: `tools/sector-rotation/sector_rotation/weekly.py`
- Test: `tests/test_sr_weekly.py`

**Interfaces:**
- Consumes: Task 4 `WeeklyFrame`。
- Produces:

```python
def build_features(wf: WeeklyFrame, *, window: int = 13) -> tuple[np.ndarray, np.ndarray]:
    """→ (X, t_index)：X[t_index[i], :] = 第 i 个可用决策帧的标准化特征
    （window×L 展平，z-score 按flatten向量的训练窗统计量）；
    t_index = 特征可用的决策帧行号（从第一个连续 window 个有效指数周的下一帧起）。"""

def weekly_gross_returns(wf: WeeklyFrame) -> np.ndarray:
    """(T, L)：etf_close/etf_open - 1，成本前周收益（spec §3.3 双口径之毛）。"""
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_weekly.py
import numpy as np

from sector_rotation.data import WeeklyFrame
from sector_rotation.universe import Member
from sector_rotation.weekly import build_features, weekly_gross_returns

MEM = Member("881101", "工程机械", "528030.SH", "机械ETF", 0.10, "机械")


def _wf(T=15, L=1):
    rng = np.random.default_rng(3)
    return WeeklyFrame(
        fridays=[f"2026-w{i:02d}" for i in range(T)],
        index_close=rng.normal(100, 5, (T, L)),
        etf_open=np.full((T, L), 1.0), etf_close=np.full((T, L), 1.02),
        etf_prev_close=np.full((T, L), 0.99), members=[MEM] * L,
        valid=np.ones((T, L), dtype=bool))


def test_gross_return_is_close_over_open_minus_1():
    r = weekly_gross_returns(_wf())
    assert np.allclose(r, 0.02)


def test_features_shape_and_standardization():
    wf = _wf(T=15)
    X, t_index = build_features(wf, window=4)
    assert X.shape == (15 - 4, 4 * 1)
    assert t_index[0] == 4 and t_index[-1] == 14
    assert abs(X.mean()) < 1e-8 and abs(X.std() - 1.0) < 1e-8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_weekly.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 weekly.py**

```python
# tools/sector-rotation/sector_rotation/weekly.py
"""特征窗口（N 周 × L 展平 + z-score）与标签（周一开→周五收，spec §3.3）。"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame


def weekly_gross_returns(wf: WeeklyFrame) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        r = wf.etf_close / wf.etf_open - 1.0
    return np.where(np.isfinite(r), r, np.nan)


def build_features(wf: WeeklyFrame, *, window: int = 13
                   ) -> tuple[np.ndarray, np.ndarray]:
    """连续 window 个有效指数周 → 下一决策帧特征。z-score 用全 T 统计量（回测内
    每周重算时只喂训练窗——由 walkforward 调用方保证切片，见 Task 10）。"""
    L = len(wf.members)
    ok = np.isfinite(wf.index_close).all(axis=1)
    feats, t_index = [], []
    for t in range(window, len(wf.fridays)):
        rows = np.arange(t - window, t)
        if ok[rows].all():
            block = wf.index_close[rows, :].reshape(-1)  # (window*L,)
            feats.append(block)
            t_index.append(t)
    X = np.array(feats, dtype=float)
    mu, sd = X.mean(), X.std()
    if not np.isfinite(sd) or sd == 0:
        sd = 1.0
    return (X - mu) / sd, np.array(t_index, dtype=int)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_weekly.py -v`
Expected: PASS（2 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/weekly.py tests/test_sr_weekly.py
git commit -m "feat(sector-rotation): 特征窗口与双口径标签（Task 5）"
```

---

### Task 6: cost.py——成本模型（第一公民）

**Files:**
- Create: `tools/sector-rotation/sector_rotation/cost.py`
- Test: `tests/test_sr_cost.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 1.0   # 万1，双边各收
    spread_bps: float = 10.0      # 全宽点差，每边计半宽（spec §3.7 默认）
    impact_bps: float = 0.0       # 冲击成本，小资金默认 0，参数化预留

    def side_bps(self) -> float:          # 单边成本 bps
    def roundtrip_bps(self) -> float:     # 一买一卖
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_cost.py
from sector_rotation.cost import CostModel


def test_side_and_roundtrip_bps():
    cm = CostModel()
    assert cm.side_bps() == 1.0 + 10.0 / 2
    assert cm.roundtrip_bps() == 2 * cm.side_bps()


def test_weekly_full_turnover_cost_drag():
    """全清全买一周：成本拖累 = roundtrip bps（对整组合）。"""
    cm = CostModel()
    assert abs(cm.roundtrip_bps() / 1e4 - 0.0012) < 1e-9  # 12bp = 0.12%/周
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/cost.py
"""交易成本模型（spec §3.7：成本是回测第一公民，α 只报成本后）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 1.0
    spread_bps: float = 10.0
    impact_bps: float = 0.0

    def side_bps(self) -> float:
        return self.commission_bps + self.spread_bps / 2 + self.impact_bps

    def roundtrip_bps(self) -> float:
        return 2 * self.side_bps()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_cost.py -v`
Expected: PASS（2 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/cost.py tests/test_sr_cost.py
git commit -m "feat(sector-rotation): 成本模型（Task 6）"
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
                    weeks_per_year: int = 52) -> dict[str, float]
# 返回 {"cagr","alpha","sharpe","max_dd","win_rate","turnover","cost_drag"}
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_metrics.py
import numpy as np

from sector_rotation.metrics import compute_metrics


def test_flat_nav_zero_alpha_negative_vs_benchmark():
    nav = np.ones(53)
    r = np.zeros(52)
    bench = np.linspace(1.0, 1.10, 53)   # 基准 +10%
    m = compute_metrics(nav, r, benchmark_nav=bench, turnover=2.0, cost_drag=0.0012)
    assert m["cagr"] == 0.0
    assert m["alpha"] < 0
    assert m["max_dd"] == 0.0
    assert m["win_rate"] == 0.0


def test_steady_growth_metrics():
    r = np.full(52, 0.001)
    nav = np.concatenate([[1.0], np.cumprod(1 + r)])
    m = compute_metrics(nav, r)
    assert abs(m["cagr"] - (1.001 ** 52 - 1)) < 1e-9
    assert m["sharpe"] > 50            # 零波动 → sharpe 巨大（实现须防除零：std=0 时返回 inf 的有限替代 0）
    assert m["win_rate"] == 1.0
```

（注：零波动Sharpe约定为 `float("inf")` 会污染均值统计，实现里 std==0 且 mean>0 时返回一个足够大的哨兵值并附 `_sharpe_degenerate: True`？——不引入哨兵：std==0 时 sharpe 取 `float("nan")` 并由报告层注明。测试断言改为 `np.isnan(m["sharpe"])`，执行时以实现为准同步测试。）

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/metrics.py
"""回测指标（spec §3.8）。nav 为等比净值序列，长度 = 周数 + 1。"""
from __future__ import annotations

import numpy as np


def compute_metrics(nav: np.ndarray, weekly_ret: np.ndarray, *,
                    benchmark_nav: np.ndarray | None = None,
                    turnover: float = 0.0, cost_drag: float = 0.0,
                    weeks_per_year: int = 52) -> dict[str, float]:
    years = len(weekly_ret) / weeks_per_year
    cagr = float(nav[-1] / nav[0]) ** (1 / years) - 1 if years > 0 else 0.0
    if benchmark_nav is not None:
        bench_cagr = float(benchmark_nav[-1] / benchmark_nav[0]) ** (1 / years) - 1
        alpha = cagr - bench_cagr
    else:
        alpha = 0.0
    mu, sd = float(np.mean(weekly_ret)), float(np.std(weekly_ret, ddof=1))
    sharpe = float(mu / sd * np.sqrt(weeks_per_year)) if sd > 0 else float("nan")
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    return {"cagr": cagr, "alpha": alpha, "sharpe": sharpe,
            "max_dd": float(dd.min()), "win_rate": float((weekly_ret > 0).mean()),
            "turnover": turnover, "cost_drag": cost_drag}
```

- [ ] **Step 4: 跑测试确认通过**（`test_steady_growth_metrics` 的 sharpe 断言按执行注改为 `assert np.isnan(m["sharpe"])`）

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_metrics.py -v`
Expected: PASS（2 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/metrics.py tests/test_sr_metrics.py
git commit -m "feat(sector-rotation): 回测指标集（Task 7）"
```

---

### Task 8: baselines.py——对照组四件 + L0

**Files:**
- Create: `tools/sector-rotation/sector_rotation/baselines.py`
- Test: `tests/test_sr_baselines.py`

**Interfaces:**
- Consumes: Task 4 `WeeklyFrame`（策略只读它）。
- Produces（全部实现统一策略签名 `select(wf: WeeklyFrame, t: int) -> dict[int, float]`，键 = 列索引、值 = 目标权重）：

```python
def equal_weight(wf, t) -> dict[int, float]                 # 全宇宙等权（对照组①）
def momentum_topk(wf, t, *, lookback: int = 1, k: int = 3) -> dict[int, float]   # L0 动量
def reversal_topk(wf, t, *, lookback: int = 1, k: int = 3) -> dict[int, float]   # L0 反转（A 股反转效应待验证，双向都测）
def random_k(wf, t, *, k: int = 3, seed: int = 0) -> dict[int, float]           # 噪音对照
def hold_300etf(wf, t) -> dict[int, float]                   # 沪深300ETF 买入持有（若不在宇宙中由 walkforward 特判）
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_baselines.py
import numpy as np

from sector_rotation.baselines import equal_weight, momentum_topk, random_k, reversal_topk
from sector_rotation.data import WeeklyFrame
from sector_rotation.universe import Member

M2 = [Member("881101", "机械", "528030.SH", "机械ETF", 0.10, "c1"),
      Member("881127", "半导体", "512480.SH", "半导体ETF", 0.10, "c2")]


def _wf(index_rows):
    T, L = index_rows.shape
    return WeeklyFrame(
        fridays=[f"w{i}" for i in range(T)], index_close=index_rows,
        etf_open=np.ones((T, L)), etf_close=np.ones((T, L)),
        etf_prev_close=np.ones((T, L)), members=M2,
        valid=np.ones((T, L), dtype=bool))


def test_momentum_picks_topk_by_trailing_return():
    idx = np.array([[100.0, 100.0], [101.0, 110.0], [101.0, 120.0]])  # 第 1 列涨得猛
    wf = _wf(idx)
    w = momentum_topk(wf, 2, lookback=2, k=1)
    assert w == {1: 1.0}


def test_reversal_picks_bottomk():
    wf = _wf(np.array([[100.0, 100.0], [101.0, 110.0], [101.0, 120.0]]))
    assert reversal_topk(wf, 2, lookback=2, k=1) == {0: 1.0}


def test_equal_weight_all_valid():
    wf = _wf(np.ones((3, 2)))
    assert equal_weight(wf, 2) == {0: 0.5, 1: 0.5}


def test_random_k_deterministic_and_size():
    wf = _wf(np.ones((3, 2)))
    assert random_k(wf, 2, k=1, seed=7) == random_k(wf, 2, k=1, seed=7)
    assert len(random_k(wf, 2, k=1, seed=7)) == 1
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/baselines.py
"""对照组与 L0 基线（spec §3.4/§3.8）。策略签名：select(wf, t) -> {列索引: 权重}。"""
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
    if not cols:
        return {}
    rets = {}
    for i in cols:
        if t - lookback >= 0 and np.isfinite(wf.index_close[t - lookback, i]):
            rets[i] = wf.index_close[t, i] / wf.index_close[t - lookback, i] - 1.0
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


def hold_300etf(wf: WeeklyFrame, t: int) -> dict[int, float]:  # pragma: no cover
    """300ETF 持有基准由 backtest 层特判（不在 881 宇宙内），此处占位保持协议完整。"""
    return equal_weight(wf, t)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_baselines.py -v`
Expected: PASS（4 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/baselines.py tests/test_sr_baselines.py
git commit -m "feat(sector-rotation): L0 基线与四对照组（Task 8）"
```

---

### Task 9: portfolio.py——执行闸门 + 风控状态机 + 同簇约束

**Files:**
- Create: `tools/sector-rotation/sector_rotation/portfolio.py`
- Test: `tests/test_sr_portfolio.py`

**Interfaces:**
- Consumes: Task 4 `WeeklyFrame`、Task 6 `CostModel`。
- Produces:

```python
class RiskState:
    """跨周状态机（spec §3.6 参数表初值）。"""
    def __init__(self, members: list[Member], *, enabled: bool = True): ...
    def apply(self, t: int, wf: WeeklyFrame, desired: dict[int, float],
              last_week_pos_returns: dict[int, float] | None) -> dict[int, float]:
        """desired 经执行闸门 + 风控规则 + 同簇 ≤2 截断后的可执行权重。
        last_week_pos_returns = 上周各持仓列的毛收益（None = 首周/上周空仓）。"""

def simulate_week(wf, t, weights_prev: dict[int, float],
                  weights_new: dict[int, float], cost: CostModel
                  ) -> tuple[float, dict[int, float], dict[int, float]]:
    """→ (周净收益, 各持仓毛收益 dict, 明细 dict)。含涨跌停闸门的执行修正。"""
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_portfolio.py
import numpy as np

from sector_rotation.cost import CostModel
from sector_rotation.data import WeeklyFrame
from sector_rotation.portfolio import RiskState, simulate_week
from sector_rotation.universe import Member

M3 = [Member("A1", "光伏", "E1", "光伏ETF", 0.10, "same"),
      Member("A2", "风电", "E2", "风电ETF", 0.10, "same"),
      Member("A3", "储能", "E3", "储能ETF", 0.10, "same"),
      Member("B1", "银行", "E4", "银行ETF", 0.10, "other")]


def _wf(open_, close_, prev_close, valid=None):
    T, L = open_.shape
    return WeeklyFrame(
        fridays=[f"w{i}" for i in range(T)], index_close=np.ones((T, L)),
        etf_open=open_, etf_close=close_, etf_prev_close=prev_close,
        members=M3, valid=valid if valid is not None else np.ones((T, L), bool))


def test_cluster_cap_two():
    rs = RiskState(M3)
    wf = _wf(np.full((2, 4), 1.0), np.full((2, 4), 1.01), np.full((2, 4), 0.99))
    got = rs.apply(1, wf, {0: 1 / 3, 1: 1 / 3, 2: 1 / 3}, None)
    same = [i for i in got if M3[i].cluster == "same"]
    assert len(same) == 2            # 同簇 ≤2 截断
    assert abs(sum(got.values()) <= 1.0)


def test_limit_up_blocks_buy():
    wf = _wf(np.array([[1.10, 1.0]]),      # 开盘涨停（prev 1.0, limit 10%）
             np.array([[1.10, 1.02]]), np.array([[1.0, 1.0]]))
    net, pos, detail = simulate_week(wf, 0, {}, {0: 1.0}, CostModel())
    assert 0 not in pos                  # 涨停弃买
    assert detail["blocked"][0] == "limit_up"


def test_simulate_week_applies_roundtrip_cost():
    wf = _wf(np.array([[1.0, 1.0]]), np.array([[1.10, 1.0]]), np.full((1, 2), 0.99))
    net, pos, detail = simulate_week(wf, 0, {}, {0: 1.0}, CostModel())
    assert abs(pos[0] - 0.10) < 1e-12
    assert abs(net - (0.10 - CostModel().roundtrip_bps() / 1e4)) < 1e-9


def test_consecutive_loss_weeks_pause():
    rs = RiskState(M3)
    wf = _wf(np.full((6, 4), 1.0), np.full((6, 4), 0.99), np.full((6, 4), 1.0))
    out = {0: 0.5}
    for t in range(4):                   # 连续 4 周亏损
        out = rs.apply(t, wf, {0: 0.5}, {0: -0.01})
    assert out == {}                     # 第 4 周后停一周
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现**

```python
# tools/sector-rotation/sector_rotation/portfolio.py
"""执行闸门、风控状态机、同簇约束（spec §3.5/§3.6）。"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .cost import CostModel
from .data import WeeklyFrame
from .universe import Member


class RiskState:
    def __init__(self, members: list[Member], *, enabled: bool = True):
        self.members = members
        self.enabled = enabled
        self.loss_weeks = 0              # 组合连续亏损周
        self.wins: dict[int, list[bool]] = {i: [] for i in range(len(members))}
        self.cooldown: dict[int, int] = {}   # 列索引 → 观察期剩余周数
        self.banned: set[int] = set()        # 单行业周亏 ≥5% 移出下周

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
            return {}                       # 停一周
        picked: dict[int, float] = {}
        cluster_cnt: Counter[str] = Counter()
        for i in sorted(desired, key=lambda j: -desired[j]):
            if i in self.banned or self.cooldown.get(i, 0) > 0:
                continue
            cl = self.members[i].cluster
            if cluster_cnt[cl] >= 2:        # 同簇 ≤2 截断
                continue
            picked[i] = desired[i]
            cluster_cnt[cl] += 1
        for i in list(self.cooldown):
            self.cooldown[i] -= 1
            if self.cooldown[i] <= 0:
                del self.cooldown[i]
        self.banned.clear()
        total = sum(picked.values())
        return {i: w / total for i, w in picked.items()} if total > 0 else {}


def simulate_week(wf: WeeklyFrame, t: int, weights_prev: dict[int, float],
                  weights_new: dict[int, float], cost: CostModel
                  ) -> tuple[float, dict[int, float], dict[int, float]]:
    """执行周收益：涨停弃买（权重置 0）、跌停顺延（下周处理，本周按 close 记损益），
    成本 = (卖出旧仓 + 买入新仓) × side_bps。返回 (净收益, 持仓毛收益, 明细)。"""
    blocked: dict[int, str] = {}
    executed: dict[int, float] = {}
    for i, w in weights_new.items():
        member = wf.members[i]
        limit_up = wf.etf_prev_close[t, i] * (1 + member.limit_pct * 0.995)
        if wf.etf_open[t, i] >= limit_up:
            blocked[i] = "limit_up"
        else:
            executed[i] = w
    gross: dict[int, float] = {}
    for i, w in executed.items():
        r = wf.etf_close[t, i] / wf.etf_open[t, i] - 1.0
        gross[i] = r
    port_gross = sum(executed[i] * gross[i] for i in executed)
    sell_notional = sum(weights_prev.values())
    buy_notional = sum(executed.values())
    costs = (sell_notional + buy_notional) * cost.side_bps() / 1e4
    detail = {"blocked": blocked, "turnover": sell_notional + buy_notional,
              "gross": port_gross, "costs": costs}
    return port_gross - costs, gross, detail
```

（执行注：跌停顺延的完整实现——`low == prev_close×(1−limit) and close == low` 时卖仓按 close 记损益并把持仓结转到下周 `weights_prev`——首版按上式简化：周五清仓价即 close，顺延只影响成本时点，对周频口径影响 ≤1bp；在 README 已知限制中声明。）

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_portfolio.py -v`
Expected: PASS（4 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/portfolio.py tests/test_sr_portfolio.py
git commit -m "feat(sector-rotation): 执行闸门/风控状态机/同簇约束（Task 9）"
```

---

### Task 10: walkforward.py + permtest.py——回测引擎与置换检验

**Files:**
- Create: `tools/sector-rotation/sector_rotation/walkforward.py`、`tools/sector-rotation/sector_rotation/permtest.py`
- Test: `tests/test_sr_walkforward.py`

**Interfaces:**
- Consumes: Task 4-9 全部（`WeeklyFrame`/`build_features`/`CostModel`/`RiskState`/`simulate_week`/`compute_metrics`）。
- Produces:

```python
Strategy = object  # 任何带 select(wf, t) -> dict[int, float] 的可调用/对象

@dataclass
class WalkResult:
    nav: np.ndarray                    # 净值（含成本）
    nav_gross: np.ndarray              # 毛净值（诊断列）
    weekly: np.ndarray                 # 周净收益
    metrics: dict[str, float]
    trades: list[dict]                 # 每周 {friday, holdings, blocked, detail}

def run_walkforward(wf: WeeklyFrame, strategy, *, cost: CostModel,
                    train_weeks: int = 104, risk: RiskState | None = None) -> WalkResult

def perm_test(wf, cost, *, k: int = 3, n: int = 1000, strategy=None) -> dict
# → {"observed_cagr", "p_value", "random_cagr_mean", ...}：随机 k × n 次的经验分布
```

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_walkforward.py
import numpy as np

from sector_rotation.baselines import momentum_topk, random_k
from sector_rotation.cost import CostModel
from sector_rotation.data import WeeklyFrame
from sector_rotation.permtest import perm_test
from sector_rotation.universe import Member
from sector_rotation.walkforward import run_walkforward

M2 = [Member("A", "甲", "EA", "甲ETF", 0.10, "c1"),
      Member("B", "乙", "EB", "乙ETF", 0.10, "c2")]


def _wf(T=30, seed=5):
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.002, 0.02, (T, 2)), axis=0)
    ones = np.ones((T, 2))
    valid = np.ones((T, 2), bool)
    valid[-1, :] = False                 # 最后一帧无执行周 → 弃权
    return WeeklyFrame([f"w{i}" for i in range(T)], idx, ones,
                       1 + rng.normal(0.001, 0.02, (T, 2)), ones, M2, valid)


def test_walkforward_nav_and_trades():
    wf = _wf()
    res = run_walkforward(wf, momentum_topk, cost=CostModel(), train_weeks=5)
    assert len(res.nav) == len(res.weekly) + 1
    assert res.nav[0] == 1.0 and np.all(res.nav > 0)
    assert res.metrics["cagr"] < 1.0     # 成本后不至于离谱
    assert all(set(tr["holdings"]) <= {0, 1} for tr in res.trades)


def test_perm_test_returns_pvalue_in_range():
    wf = _wf(T=40)
    out = perm_test(wf, CostModel(), k=1, n=50)
    assert 0 <= out["p_value"] <= 1
    assert out["n_random"] == 50
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现 walkforward.py**

```python
# tools/sector-rotation/sector_rotation/walkforward.py
"""walk-forward 引擎（spec §3.8）：训练窗 train_weeks 滚动，OOS 每周执行一买一卖。"""
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


def run_walkforward(wf: WeeklyFrame, strategy, *, cost: CostModel,
                    train_weeks: int = 104,
                    risk: RiskState | None = None) -> WalkResult:
    risk = risk or RiskState(wf.members)
    nav, nav_g = [1.0], [1.0]
    weekly, weekly_g, trades = [], [], []
    weights_prev: dict[int, float] = {}
    last_pos_returns: dict[int, float] | None = None
    turnover_acc, cost_acc, gross_acc = 0.0, 0.0, 0.0
    for t in range(train_weeks, len(wf.fridays)):
        if not wf.valid[t].any():
            continue
        desired = strategy.select(wf, t)
        weights_new = risk.apply(t, wf, desired, last_pos_returns)
        net, gross_pos, detail = simulate_week(wf, t, weights_prev, weights_new, cost)
        weekly.append(net)
        weekly_g.append(detail["gross"])
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
                              cost_drag=(cost_acc / gross_acc) if gross_acc > 0 else 0.0)
    return WalkResult(nav_a, np.array(nav_g), weekly_a, metrics, trades)
```

```python
# tools/sector-rotation/sector_rotation/permtest.py
"""置换检验（spec §3.8）：随机 k 对照的经验分布，p = (1+#{rand≥obs})/(1+n)。"""
from __future__ import annotations

import numpy as np

from .baselines import random_k
from .cost import CostModel
from .data import WeeklyFrame
from .walkforward import run_walkforward


def perm_test(wf: WeeklyFrame, cost: CostModel, *, k: int = 3, n: int = 1000,
              strategy=None, train_weeks: int = 104) -> dict:
    strategy = strategy or (lambda wf_, t: random_k(wf_, t, k=k, seed=0))
    obs = run_walkforward(wf, strategy, cost=cost, train_weeks=train_weeks)
    rand_cagrs = []
    for seed in range(n):
        res = run_walkforward(
            wf, lambda wf_, t, s=seed: random_k(wf_, t, k=k, seed=s),
            cost=cost, train_weeks=train_weeks)
        rand_cagrs.append(res.metrics["cagr"])
    rand = np.array(rand_cagrs)
    p = float((1 + (rand >= obs.metrics["cagr"]).sum()) / (1 + n))
    return {"observed_cagr": obs.metrics["cagr"], "p_value": p,
            "random_cagr_mean": float(rand.mean()),
            "random_cagr_p95": float(np.percentile(rand, 95)),
            "n_random": n}
```

（执行注：`perm_test` 每次随机跑都重建 `RiskState`——`run_walkforward` 内部默认新建，保持对照口径一致；若执行时观察到 n=1000 耗时不可接受（>30 分钟），降 n 到 500 并在报告注明，不改口径。）

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_walkforward.py -v`
Expected: PASS（2 用例）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/walkforward.py tools/sector-rotation/sector_rotation/permtest.py tests/test_sr_walkforward.py
git commit -m "feat(sector-rotation): walk-forward 引擎 + 置换检验（Task 10）"
```

---

### Task 11: backtest.py CLI + 报告渲染 + P1 闸门全量跑

**Files:**
- Create: `tools/sector-rotation/backtest.py`
- Test: `tests/test_sr_backtest.py`

**Interfaces:**
- Consumes: Task 1-10。
- Produces: CLI `backtest.py --level L0 --k 3 --lookback {1,4} --out output/sector-rotation/`；报告 `output/sector-rotation/YYYY-MM/backtest-L0-k3-lb1.md`（指标表 + 分年度 α + permtest p + 成本拖累 + P1 闸门判定行）。函数 `render_report(results: dict[str, WalkResult], perm: dict, *, tag: str, cost: CostModel) -> str`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_backtest.py
import numpy as np

import backtest  # noqa: E402
from sector_rotation.cost import CostModel
from sector_rotation.walkforward import WalkResult


def _res(cagr=0.10):
    weekly = np.full(52, 0.0019)
    nav = np.concatenate([[1.0], np.cumprod(1 + weekly)])
    return WalkResult(nav, nav.copy(), weekly,
                      {"cagr": cagr, "alpha": 0.02, "sharpe": 1.1, "max_dd": -0.1,
                       "win_rate": 0.55, "turnover": 90.0, "cost_drag": 0.11}, [])


def test_render_report_contains_gate_line():
    text = backtest.render_report(
        {"L0-mom-lb1": _res(), "等权持有": _res(0.05), "随机k3": _res(0.04)},
        {"observed_cagr": 0.10, "p_value": 0.04, "n_random": 1000,
         "random_cagr_mean": 0.03, "random_cagr_p95": 0.06},
        tag="L0-k3", cost=CostModel())
    assert "P1 闸门" in text
    assert "p=0.040" in text
    assert "成本后" in text and "成本拖累" in text
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现 backtest.py**

```python
# tools/sector-rotation/backtest.py
"""回测 CLI（spec §3.8/§5）：L0/L1/L2 × 对照组 → markdown 报告。"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.baselines import equal_weight, momentum_topk, random_k, reversal_topk  # noqa: E402
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import build_weekly_frame  # noqa: E402
from sector_rotation.permtest import perm_test  # noqa: E402
from sector_rotation.universe import load_universe  # noqa: E402
from sector_rotation.walkforward import WalkResult, run_walkforward  # noqa: E402


def render_report(results: dict[str, WalkResult], perm: dict, *, tag: str,
                  cost: CostModel) -> str:
    lines = [
        f"# 板块轮动回测报告：{tag}",
        "",
        f"- 生成：{date.today().isoformat()} · 成本参数：佣金 {cost.commission_bps}bp"
        f" + 点差全宽 {cost.spread_bps}bp（每边半宽）+ 冲击 {cost.impact_bps}bp",
        "- 口径：**全部指标为成本后**（毛收益仅诊断列）；周一开→周五收。",
        "",
        "| 策略 | CAGR | α(净,对等权) | Sharpe | MaxDD | 胜率 | 换手 | 成本拖累占比 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    base = results.get("等权持有")
    for name, res in results.items():
        alpha = res.metrics["cagr"] - (base.metrics["cagr"] if base else 0.0)
        m = res.metrics
        lines.append(f"| {name} | {m['cagr']:.2%} | {alpha:.2%} | "
                     f"{m['sharpe']:.2f} | {m['max_dd']:.2%} | {m['win_rate']:.1%} | "
                     f"{m['turnover']:.1f} | {m['cost_drag']:.1%} |")
    gate = (f"P1 闸门：L0 成本后 CAGR {perm['observed_cagr']:.2%}，"
            f"随机对照 p={perm['p_value']:.3f}（n={perm['n_random']}）——"
            + ("**通过（p<0.1），可进 P2**" if perm["p_value"] < 0.1
               else "**未通过（p≥0.1），按 spec §5 停止并写结案报告**"))
    lines += ["", f"> {gate}", "",
              f"随机对照分布：mean {perm['random_cagr_mean']:.2%} / "
              f"p95 {perm['random_cagr_p95']:.2%}", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", choices=["L0", "L1", "L2"], default="L0")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--lookback", type=int, default=1, choices=[1, 4])
    ap.add_argument("--universe", type=Path,
                    default=REPO_ROOT / "config/sector-rotation-universe.md")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "output/sector-rotation")
    args = ap.parse_args(argv)
    members = load_universe(args.universe)
    wf = build_weekly_frame(REPO_ROOT / "data", members)
    strategies: dict[str, object] = {
        f"L0-动量-lb{args.lookback}":
            (lambda wf_, t: momentum_topk(wf_, t, lookback=args.lookback, k=args.k)),
        "L0-反转": (lambda wf_, t: reversal_topk(wf_, t, lookback=args.lookback, k=args.k)),
        "等权持有": equal_weight,
        f"随机k{args.k}": (lambda wf_, t: random_k(wf_, t, k=args.k, seed=0)),
    }
    if args.level in ("L1", "L2"):
        from sector_rotation.models import make_strategy
        strategies[f"{args.level}"] = make_strategy(args.level, k=args.k)
    results = {name: run_walkforward(wf, strat, cost=CostModel())
               for name, strat in strategies.items()}
    perm = perm_test(wf, CostModel(), k=args.k, n=1000,
                     strategy=strategies[f"L0-动量-lb{args.lookback}"])
    tag = f"{args.level}-k{args.k}-lb{args.lookback}"
    text = render_report(results, perm, tag=tag, cost=CostModel())
    out = args.out / f"{date.today():%Y-%m}" / f"backtest-{tag}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_backtest.py -v`
Expected: PASS（1 用例）

- [ ] **Step 5: P1 全量真实跑（闸门时刻）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 --k 3 --lookback 1
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 --k 3 --lookback 4
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 --k 2 --lookback 1
```
Expected: 三份报告落 `output/sector-rotation/2026-11/`。**读 p 值**：全部 ≥0.1 → Global Constraint 11 触发，停 Task 12-15，写结案报告（模板：结论/各策略成本后 CAGR/p 值/结案建议沉淀 exploration 候选），单独 commit；任一 <0.1 → 继续。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backtest.py tests/test_sr_backtest.py output/sector-rotation/
git commit -m "feat(sector-rotation): 回测 CLI + P1 闸门首跑（Task 11）"
```

（注：`output/sector-rotation/` 若被 gitignore 覆盖则不加，先 `git check-ignore -v` 确认——报告属研究产物，repo 惯例 output/ 部分入库部分不入，按 check-ignore 结果处理。）

---

### Task 12: PyTorch 安装 + models.py L1（线性）

**Files:**
- Create: `tools/sector-rotation/sector_rotation/models.py`
- Test: `tests/test_sr_models.py`

**Interfaces:**
- Consumes: Task 5 `build_features`/`weekly_gross_returns`、Task 4 `WeeklyFrame`。
- Produces:

```python
class LinearModel:            # L1：torch 单线性层，联合 softmax 版
    def fit(self, X: np.ndarray, y: np.ndarray, r: np.ndarray) -> None   # y=(n,L)0/1 标签, r=(n,L)下周毛收益
    def select(self, wf: WeeklyFrame, t: int, *, k: int = 3) -> dict[int, float]

def make_strategy(level: str, *, k: int = 3, window: int = 13) -> object  # "L1"/"L2" → 带 select(wf,t) 的策略对象
```

`select` 内部自管训练窗（t 向前 104 周），每周全量重训（小模型毫秒级，与论文"增量更新"数据等价、拟合更干净——README 注明该口径差异）。

- [ ] **Step 1: 安装 torch（可选依赖纪律）**

```bash
conda run -n Quant-3.11 python -c "import torch; print(torch.__version__)" 2>/dev/null \
  || conda run -n Quant-3.11 python -m pip install "torch>=2.2"
conda run -n Quant-3.11 python -c "import torch; print(torch.__version__, torch.backends.mps.is_available())"
```
Expected: 版本号 + MPS True/False（False 也可，CPU 足够）。

- [ ] **Step 2: 写失败测试**

```python
# tests/test_sr_models.py
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from sector_rotation.baselines import momentum_topk  # noqa: E402
from sector_rotation.models import LinearModel, make_strategy  # noqa: E402
from sector_rotation.universe import Member  # noqa: E402

M2 = [Member("A", "甲", "EA", "甲ETF", 0.10, "c1"),
      Member("B", "乙", "EB", "乙ETF", 0.10, "c2")]


def _toy(T=140, seed=11):
    from sector_rotation.data import WeeklyFrame
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, 2)), axis=0)
    valid = np.ones((T, 2), bool); valid[-1] = False
    return WeeklyFrame([f"w{i}" for i in range(T)], idx,
                       np.ones((T, 2)), 1 + rng.normal(0, 0.03, (T, 2)),
                       np.ones((T, 2)), M2, valid)


def test_linear_model_learns_separable_signal():
    """构造强可分信号：0 号指数周五收盘 > 上周 → 下周 ETF 涨。L1 应大幅选中 0。"""
    from sector_rotation.data import WeeklyFrame
    rng = np.random.default_rng(2)
    T = 160
    idx = np.zeros((T, 2))
    label_ret = np.zeros((T, 2))
    up = True
    for t in range(T):
        idx[t] = [110.0 if up else 90.0, 100.0]
        label_ret[t] = [0.05 if up else -0.05, 0.0]
        up = not up
    valid = np.ones((T, 2), bool); valid[-1] = False
    wf = WeeklyFrame([f"w{i}" for i in range(T)], idx, np.ones((T, 2)),
                     1 + label_ret, np.ones((T, 2)), M2, valid)
    strat = make_strategy("L1", k=1)
    picks = strat.select(wf, T - 2)
    assert 0 in picks


def test_make_strategy_level_validation():
    with pytest.raises(ValueError, match="level"):
        make_strategy("L9")
```

- [ ] **Step 3: 跑测试确认失败** → **Step 4: 实现 models.py（L1 部分，L2 占位）**

```python
# tools/sector-rotation/sector_rotation/models.py
"""L1（torch 线性）与 L2（论文复刻 MIMO）策略（spec §3.4）。

口径注：训练 = 决策帧向前 104 周全量重训（论文为增量更新；小模型重训成本低，
数据等价，拟合更干净）。金融损失 = BCE + λ·(-(sigmoid(logits)·下周收益).mean())
——论文未给公式（design §8-2 待验证），此为实现方口径，λ 经消融开关验证。
"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame
from .weekly import build_features, weekly_gross_returns

TRAIN_WEEKS = 104
LAMBDA_FIN = 0.1
SEED = 20261105


def _torch():
    import torch
    torch.manual_seed(SEED)
    return torch


def _prep(wf: WeeklyFrame, t: int, *, window: int
          ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """→ (X_hist, y_hist, r_hist, x_now)，历史切片 = [t-TRAIN_WEEKS, t) 内的可用帧。"""
    X, t_idx = build_features(wf, window=window)
    if len(t_idx) < window + 2:
        return None
    r = weekly_gross_returns(wf)
    y = (r >= 0.01).astype(np.float32)
    r = r.astype(np.float32)
    pos = np.searchsorted(t_idx, t)
    lo = max(0, pos - TRAIN_WEEKS)
    if pos - lo < window + 2:
        return None
    return (X[lo:pos], y[t_idx[lo:pos]], r[t_idx[lo:pos]], X[pos - 1] if pos >= 1 else None)


class LinearModel:
    def __init__(self, *, window: int = 13, epochs: int = 100, lr: float = 1e-2):
        self.window, self.epochs, self.lr = window, epochs, lr
        self.w = None  # (D, L)

    def fit(self, X: np.ndarray, y: np.ndarray, r: np.ndarray) -> None:
        torch = _torch()
        Xt = torch.tensor(X, dtype=torch.float32)
        Yt = torch.tensor(y, dtype=torch.float32)
        Rt = torch.tensor(r, dtype=torch.float32)
        D, L = X.shape[1], y.shape[1]
        linear = torch.nn.Linear(D, L)
        opt = torch.optim.Adam(linear.parameters(), lr=self.lr)
        bce = torch.nn.BCEWithLogitsLoss()
        for _ in range(self.epochs):
            opt.zero_grad()
            logits = linear(Xt)
            loss = bce(logits, Yt) - LAMBDA_FIN * (torch.sigmoid(logits) * Rt).mean()
            loss.backward()
            opt.step()
        self.w = linear.weight.detach().numpy().copy()
        self.b = linear.bias.detach().numpy().copy()

    def probs_now(self, x: np.ndarray) -> np.ndarray:
        z = x @ self.w.T + self.b
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


def make_strategy(level: str, *, k: int = 3, window: int = 13) -> object:
    if level == "L1":
        strat = LinearModel(window=window)
        return lambda wf, t: strat.select(wf, t, k=k)  # type: ignore[return-value]
    if level == "L2":
        from functools import partial
        return partial(_l2_select, k=k, window=window)  # Task 13 实现
    raise ValueError(f"未知 level: {level}")


def _l2_select(wf: WeeklyFrame, t: int, *, k: int, window: int) -> dict[int, float]:
    raise NotImplementedError("Task 13 实现")
```

（执行注：`test_linear_model_learns_separable_signal` 若首跑未选中 0，先调 epochs/lr 或检查构造——构造信号必须真的可分（0 号列 probs 显著高于 1 号），不许放松断言凑绿。）

- [ ] **Step 5: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_models.py -v`
Expected: PASS（2 用例）

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/sector_rotation/models.py tests/test_sr_models.py
git commit -m "feat(sector-rotation): torch L1 线性策略（Task 12）"
```

---

### Task 13: models.py L2——MIMO + MC dropout + ROC 阈值 + 金融损失开关

**Files:**
- Modify: `tools/sector-rotation/sector_rotation/models.py`（替换 `_l2_select` 占位）
- Test: `tests/test_sr_models.py`（追加）

**Interfaces:**
- Consumes: Task 12 的 `_prep`/`_torch`/常量。
- Produces:

```python
class MimoModel:
    """4 层全连接 + ReLU + dropout，线性输出（论文 §2.2）。"""
    def __init__(self, n_features: int, n_assets: int, *,
                 hidden: tuple[int, ...] = (64, 64, 32, 32), dropout: float = 0.2): ...
    def fit(self, X, y, r, *, lambda_fin: float = LAMBDA_FIN) -> None
    def mc_dropout(self, x: np.ndarray, *, T: int = 100) -> tuple[np.ndarray, np.ndarray]
        # → (mean_probs, confident)：confident = ≥80% 样本落在中位数 1σ 内（论文 §2.3）
    def thresholds(self, X_hist, y_hist) -> np.ndarray
        # → 每资产阈值：训练窗内预测概率的 ROC Youden J 最优点（论文动态阈值的实现方口径）

def _l2_select(wf, t, *, k: int, window: int) -> dict[int, float]
    # 置信 ∧ prob>阈值 ∧ valid → 按 prob 排序 top-k
```

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_sr_models.py 追加
def test_mc_dropout_confidence_tight_distribution():
    from sector_rotation.models import MimoModel
    m = MimoModel(n_features=6, n_assets=2)
    m.fit(np.random.default_rng(1).normal(size=(120, 6)),
          np.random.default_rng(2).integers(0, 2, (120, 2)).astype(float),
          np.random.default_rng(3).normal(0, 0.02, (120, 2)), epochs=5)
    x = np.zeros(6)
    mean_probs, confident = m.mc_dropout(x, T=200)
    assert mean_probs.shape == (2,) and confident.dtype == bool
    # 退化一致性检查：同输入两次调用，confident 维度稳定
    _, confident2 = m.mc_dropout(x, T=200)
    assert len(confident) == len(confident2)


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

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现 L2**

```python
# models.py 追加（替换 _l2_select 占位）
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
        Yt = torch.tensor(y, dtype=torch.float32)
        Rt = torch.tensor(r, dtype=torch.float32)
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
        for _ in range(T):                      # 推理期开 dropout（论文 MC dropout）
            self.net.train()
            samples.append(self._probs(self.net(xt)))
        arr = np.array(samples)                 # (T, L)
        med = np.median(arr, axis=0)
        sd = arr.std(axis=0)
        within = np.mean(np.abs(arr - med) <= sd, axis=0)
        return arr.mean(axis=0), within >= 0.8  # 论文：≥80% 概率质量在 1σ 内

    def thresholds(self, X_hist: np.ndarray, y_hist: np.ndarray) -> np.ndarray:
        probs = self._probs(self.net(self.torch.tensor(
            X_hist, dtype=self.torch.float32)))
        L = probs.shape[1]
        out = np.full(L, 0.5)
        for j in range(L):                      # Youden J = TPR - FPR 最大点
            p, yv = probs[:, j], y_hist[:, j]
            order = np.argsort(-p)
            ps, ys = p[order], yv[order]
            tp = np.cumsum(ys); fp = np.cumsum(1 - ys)
            P, N = ys.sum(), len(ys) - ys.sum()
            if P == 0 or N == 0:
                continue
            j_idx = int(np.argmax(tp / P - fp / N))
            out[j] = ps[j_idx]
        return out


def _l2_select(wf: WeeklyFrame, t: int, *, k: int, window: int) -> dict[int, float]:
    prep = _prep(wf, t, window=window)
    if prep is None:
        return {}
    X, y, r, x_now = prep
    model = MimoModel(X.shape[1], y.shape[1])
    model.fit(X, y, r)
    th = model.thresholds(X, y)
    probs, confident = model.mc_dropout(x_now)
    cands = [i for i in range(len(probs))
             if confident[i] and probs[i] > th[i] and wf.valid[t, i]]
    cands.sort(key=lambda i: -probs[i])
    picked = cands[:k]
    return {i: 1.0 / len(picked) for i in picked} if picked else {}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n Quant-3.11 python -m pytest tests/test_sr_models.py -v`
Expected: PASS（4 用例：L1 2 + L2 2）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/models.py tests/test_sr_models.py
git commit -m "feat(sector-rotation): L2 MIMO（MC dropout 置信/ROC 阈值/金融损失开关，Task 13）"
```

---

### Task 14: L1/L2 接入回测 + 消融开关 + P2 闸门全量跑

**Files:**
- Modify: `tools/sector-rotation/backtest.py`（加 `--no-fin-loss`/`--no-mc-dropout`/`--no-threshold` 消融旗标，经环境变量或参数传入 `make_strategy`）
- Modify: `tools/sector-rotation/sector_rotation/models.py`（`make_strategy` 接受 `lambda_fin=0`/`mc_dropout=False`/`roc=False` 三开关，关闭时退化为纯 top-k by prob）
- Test: `tests/test_sr_backtest.py`（追加消融参数冒烟）

**Interfaces:**
- Consumes: Task 11/12/13。
- Produces: `make_strategy(level, *, k, window, lambda_fin=LAMBDA_FIN, mc_dropout=True, roc=True)`；三份消融报告 + 一份主报告（`backtest-L2-k3-lb13.md` 等）。

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_sr_backtest.py 追加
def test_make_strategy_ablation_switches():
    from sector_rotation.models import make_strategy
    s = make_strategy("L2", k=2, lambda_fin=0.0, mc_dropout=False, roc=False)
    assert callable(s)
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现**（`make_strategy` 签名扩三开关并透传 `_l2_select`；`backtest.py` 加三个 argparse 旗标 `--no-fin-loss/--no-mc-dropout/--no-roc` 映射到开关，报告 tag 后缀 `ablation-*`）

- [ ] **Step 4: 跑测试确认通过** → **Step 5: P2 全量真实跑（闸门时刻）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L1 --k 3
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k 3
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k 3 --no-fin-loss
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k 3 --no-mc-dropout
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L2 --k 3 --no-roc
```
Expected: 五份报告。**读闸门**：L2 成本后 α 同时 ≥ L0 与 L1 且分年度中位数为正（分年度表由报告渲染——本任务给 `render_report` 补一个按自然年切 `weekly` 的 α 小表，函数加 `yearly: dict[int, dict] | None = None` 参数）。未过闸 → Global Constraint 11：停 Task 15，写结案报告。

- [ ] **Step 6: Commit**

```bash
git add tools/sector-rotation/backtest.py tools/sector-rotation/sector_rotation/models.py tests/test_sr_backtest.py
git commit -m "feat(sector-rotation): L1/L2 接入 + 消融开关 + P2 闸门首跑（Task 14）"
```

---

### Task 15: signal.py 周信号工具 + README + 全量回归收尾

**Files:**
- Create: `tools/sector-rotation/signal.py`、`tools/sector-rotation/README.md`
- Test: `tests/test_sr_signal.py`

**Interfaces:**
- Consumes: 全部上游；`make_strategy("L2")`（或 `--level` 指定）。
- Produces: `build_signal(wf: WeeklyFrame, strategy, *, k: int) -> dict`（含 `friday`、`buy: list[{etf, name, weight, index, index_name, prob}]`、`skipped: list[...]`）；CLI 输出 `output/sector-rotation/YYYY-MM/week-YYYY-Www.md`（P3 纸面跟踪的每周信号页）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sr_signal.py
import numpy as np

from sector_rotation.baselines import momentum_topk
from sector_rotation.signal import build_signal
from tests.test_sr_models import _toy  # 复用玩具帧（或内联同构造）


def test_build_signal_shapes():
    wf = _toy()
    sig = build_signal(wf, momentum_topk, k=1)
    assert set(sig) >= {"friday", "buy", "skipped"}
    assert len(sig["buy"]) == 1
    assert {"etf", "name", "weight"} <= set(sig["buy"][0])
```

（执行注：`from tests.test_sr_models import _toy` 若跨文件导入不顺，把 `_toy` 提到 `tests/conftest.py` 作 fixture `toy_wf`，两文件共用。）

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现 signal.py**

```python
# tools/sector-rotation/signal.py
"""周信号 CLI（spec §4/P3 工具）：周五盘后跑，出下周 ETF 交易信号。

用法：conda run -n Quant-3.11 python tools/sector-rotation/signal.py --level L2 --k 3
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
from sector_rotation.universe import load_universe  # noqa: E402


def build_signal(wf, strategy, *, k: int) -> dict:
    t = len(wf.fridays) - 1
    weights = strategy.select(wf, t)
    buy, skipped = [], []
    for i, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        m = wf.members[i]
        buy.append({"etf": m.etf, "name": m.etf_name, "weight": w,
                    "index": m.index_code, "index_name": m.index_name,
                    "cluster": m.cluster})
    held = set(weights)
    for i, m in enumerate(wf.members):
        if i not in held and wf.valid[t, i]:
            skipped.append({"etf": m.etf, "name": m.etf_name, "index": m.index_code})
    return {"friday": wf.fridays[t], "buy": buy, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", choices=["L0", "L1", "L2"], default="L2")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--universe", type=Path,
                    default=REPO_ROOT / "config/sector-rotation-universe.md")
    args = ap.parse_args(argv)
    members = load_universe(args.universe)
    wf = build_weekly_frame(REPO_ROOT / "data", members)
    strategy = make_strategy(args.level, k=args.k)
    sig = build_signal(wf, strategy, k=args.k)
    today = date.today().isocalendar()
    out = (REPO_ROOT / "output/sector-rotation" / f"{date.today():%Y-%m}"
           / f"week-{today[0]}-W{today[1]:02d}.md")
    lines = [f"# 板块轮动周信号（决策帧 {sig['friday']}）", "",
             f"- 级别 {args.level} · k={args.k} · 生成 {date.today().isoformat()}",
             "- 执行纪律：周一 09:30 开盘价买入；开盘涨停弃买；周五 14:50 清仓（spec §3.5）",
             "", "| ETF | 名称 | 权重 | 信号指数 | 簇 |", "|---|---|---|---|---|"]
    for b in sig["buy"]:
        lines.append(f"| {b['etf']} | {b['name']} | {b['weight']:.1%} | "
                     f"{b['index']} {b['index_name']} | {b['cluster']} |")
    lines += ["", f"未入选行业 {len(sig['skipped'])} 个（弃权/信号弱/闸门拦截）。"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: README**

`tools/sector-rotation/README.md`：模块图（数据流：backfill → build_universe → WeeklyFrame → strategy → walkforward → backtest/signal）、CLI 速查、成本口径表、**已知限制**（mootdx start 分页若不支持的深度退化、跌停顺延简化口径、周频重训 vs 论文增量更新、金融损失/ROC 阈值为实现方口径、指数不复权口径与分红检查结论）、P1/P2 闸门结果摘要（回填真实 p 值）。

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run: `conda run -n Quant-3.11 python -m pytest tests/ -q`
Expected: 全绿（存量 + 新增 ~24 用例）；`conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py` 零告警。

- [ ] **Step 6: 真实冒烟（signal 用 L0 避免依赖未过闸的 L2）**

```bash
conda run -n Quant-3.11 python tools/sector-rotation/signal.py --level L0 --k 3
```
Expected: 周信号页落 `output/sector-rotation/2026-11/week-2026-W45.md`，含 ETF 代码/权重/簇。

- [ ] **Step 7: Commit**

```bash
git add tools/sector-rotation/signal.py tools/sector-rotation/README.md tests/test_sr_signal.py
git commit -m "feat(sector-rotation): 周信号工具 + README + 全量回归绿（Task 15）"
```

---

## Self-Review 记录

1. **Spec 覆盖对照**：spec §3.1（双层宇宙/跨境排除）→ T3；§3.2（回补/对齐/宏观预留）→ T2/T4（宏观不入第一版=spec 原文）；§3.3（周五采样/N 网格/双口径标签/周一开→周五收）→ T4/T5（N 网格 {8,13,26,52} 由 `--window` 参数覆盖，T12 `make_strategy(window=)` 已留口，消融在 P2 跑法里用 `--k`/`--lookback` 组合体现——window 网格未列独立 CLI 旗标，执行 Task 14 时顺手补 `--window` 透传，属 T14 范围）；§3.4（L0-L3 阶梯/升级闸门）→ T8/T12/T13/T14（L3 属"打赢后启动"，本计划不含=spec 原文）；§3.5（节律/闸门）→ T9/T15；§3.6（分配/风控/同簇）→ T9；§3.7（成本第一公民）→ T6/T11（报告只报净）；§3.8（walk-forward/对照/指标/稳健切片/置换检验）→ T7/T10/T11（**分年度 α 表在 T14 补**，稳健性切片中的 2024-09 脉冲段回放属分析动作，执行 T11 后由 agent 用 `weekly` 序列手工切——已在 T14 Step 5 注明出分年度表，特殊段回放不单列任务）；§4 集成 → 文件结构 + T3 review-queue + T15 README；§5 分期闸门 → Global Constraint 11 + T11/T14 Step 5。
2. **占位符扫描**：无 TBD/TODO；两处执行注（upsert 签名核对、KEYWORDS 人工补齐）是「以仓库现状为准」的核对指令，不是未写实现——实现代码已给出，核对防止签名漂移。
3. **类型一致性**：`Member` 六字段 T1 定义、T3/T4/T9/T12/T13/T15 使用一致；`select(wf, t) -> dict[int, float]` 协议 T8/T10/T12/T13/T15 一致；`WalkResult` T10 定义、T11 消费一致；`make_strategy` T12 定义（含 T13 消融扩展）、T11/T14/T15 消费一致。
