# 美股 11 行业 ETF 域：论文复现 + 引擎验证实施计划（P0-US）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在论文原始证据域（美股 11 行业 ETF，2012-2022）复现 SSRN 4280640 的 MIMO 周频轮动信号（毛 α 均值 12.63%），产出与论文 Table 3 的并排对照表 + 预声明判定域（A/B/C）归类——区分「我们的引擎有 bug」vs「论文数字不可复现」。

**Architecture:** 复用 A 股周频轮动引擎全套（WeeklyFrame + run_walkforward + CostModel），A 股耦合点做**最小参数化**（默认值零变化）；美股数据走独立根 `data/us-sector/` 镜像布局（yfinance 复权价，ETF 自身 = 信号指数 = 交易标的的退化情形）；新增 `MIMOModel`（L2/T13 复活：4 层 FC + MC dropout 弃权 + trailing-pairs ROC 动态阈值，年模型冻结 + 跨年共享 ROC 状态）；`repro_paper.py` 驱动 Tier-1 引擎锚（L0 动量对照/等权/手验切面）+ Tier-2 三格复现（毛主判定 + 2bp 净参考行），硬编码消费窗口 2012-2022（尾段 2023+ 处女不可达），年归属 = 执行周 ISO 年。

**Tech Stack:** Python 3.11（conda Quant-3.11）、yfinance 1.2.0（实测已装于 Quant-3.11；homebrew python3 未装——计划评审 M-1 实核）、pandas/numpy、PyTorch CPU（已装）、pytest、ruff。

**Spec:** `workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md`（R20261106-02 draft-rev1，含预检 PF-R20261106-02-6202cda2；复现配置 §10 预注册行草案、判定域 §5、偏差清单 §4 九条、§7 参数化六行）。冲突以该提案为准，本计划是它的任务化论证。上游 spec：`workspace/proposals/2026-11-05-sector-rotation-design.md`（v1.2.6 §3.8 第 8 条 = 本轮重开依据）。

> **Rebase（2026-11-06）**：本计划按计划评审报告 `workspace/proposals/2026-11-06-sector-rotation-us-repro-plan-review.md`（C-1~C-3 / I-1~I-8 / M-1~M-7 全部修复）改写——核心：标签 = 执行窗 open→close（C-1，用户已追认 I-2）、ROC = trailing-pairs 有状态机制（C-2，用户已追认 I-7）、年模型训练集全帧扫描（C-3，否则 2012 全年空仓）、`pick_bypass_single` 单候选旁路（I-1）。执行以本版为准。
>
> **复查轮（2026-11-06，同报告「复查轮」章节）**：原 18 项 **18/18 核销**（C-1/C-2 机制级核验为真修复），裁决 **Ready to execute? Yes**——新发现 N1（Task 2 夹具缺前年基准行必 KeyError）/N3（决策 2022-12-30 的执行周 = 2023-W01 尾段越界 + α 字典 12 键）两 Important 与 N2/N4-N8 六 Minor 已全部修入本版；修复限于复查清单范围（免再复查）。

## Global Constraints（全任务绑定）

1. **Python 一律 `export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python ...`**（系统 Python 是 PEP 668 的 3.15）。
2. **测试**：`conda run -n Quant-3.11 python -m pytest tests/ -q` 全量保持全绿（2026-11-06 实测 556+ 用例）；新测试进根级 `tests/test_sr_*.py`，输出干净。
3. **Lint**：`conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py` 零告警。
4. **提交**：中文 `type: subject`，按关注点拆 commit，**不推送**；分支 `feat/sector-rotation-design` 续做（HEAD 预期 593f2fa 附近，有并行会话 commit 属正常，提交前 `git log --oneline -3` 确认）。
5. **数据纪律**：`data/` 全部 gitignore，绝不 `git add`；报告数字必须来自真实运行输出，禁止编造。
6. **窗口纪律（本轮核心约束）**：消费区间硬编码 **2012-01-01:2022-12-31**；尾段 2023-01→now 处女——`repro_paper.py` 不暴露任何能触及 2023+ 的开关（`--limit-weeks` 只能缩短不能延长终点），代码内 `assert` 终点周 ≤ 2022-12-31，且消费窗按**执行周 ISO 年 ≤2022** 过滤（决策 2022-12-30 的执行周是 2023-W01，弃——复查轮 N3）。
7. **A 股路径零行为变化**：所有参数化新参默认值 = 现硬编码值；全量回归绿是每个引擎任务的验收条件。
8. **yfinance 限流史**（friction-log 2026-10-28/10-31 两次 429）：fetch 指数退避重试 5 次；仍失败则**如实停止报告**，不降级低质源、不造数。
9. **并行会话**：工作树可能有他人未提交文件（wiki/explorations/_index.md、workspace/knowledge-usage.jsonl）——绝不 add/checkout 他们；只提交本计划清单内文件。
10. **预注册纪律**：Task 5（预注册 commit）必须先于 Task 6 的任何真实复现运行（代码编写可以在 Task 6 内，但全窗运行只发生在预注册 commit 之后）。

## 文件结构（决策锁定）

```
tools/sector-rotation/
  us_backfill.py               # 新：yfinance 13 标的深回补 → data/us-sector/ 镜像布局 + verify 锚点核对
  make_us_universe.py          # 新：write_universe 生成美股宇宙清单（11 成员退化情形）
  repro_paper.py               # 新：Tier-1 引擎锚 + Tier-2 MIMO 三格（毛+2bp净）→ 对照报告
  sector_rotation/
    universe.py                # 改：point_in_time_pick bypass_single（单候选旁路，评审 I-1）
    data.py                    # 改：corrupt_threshold / pick_bypass_single 参数化
    weekly.py                  # 改：window_blocks include_t（特征窗含决策周五收盘）
    walkforward.py             # 改：min_universe / min_amount_wan 透传
    portfolio.py               # 改：simulate_week min_amount_wan 参数
    models.py                  # 改：_torch(seed)、MIMOModel + ROCState + thresholds_from_pairs、make_strategy L2 直接报错
config/sector-rotation-us-universe.md   # 新（tracked）：11 成员宇宙清单
data/us-sector/                          # 新（gitignore）：sector/series + market/series 镜像布局
output/sector-rotation/2026-11/          # 复现报告落点
tests/test_sr_us_backfill.py   # 新
tests/test_sr_repro.py         # 新
tests/test_sr_{weekly,universe,data,walkforward,portfolio,models}.py  # 各加用例
workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md     # 状态流转 + 结果段
workspace/proposals/2026-11-05-sector-rotation-design.md              # spec §6.3 预注册行 + §3.8 第 10 条草案（v1.2.7）
```

依赖方向：Task 1（引擎参数化）→ Task 2/3（数据+宇宙）→ Task 4（MIMO）→ Task 5（预注册）→ Task 6（复现运行）→ Task 7（结案）。

---

### Task 1: 引擎跨域参数化（A 股默认零变化）

**Files:**
- Modify: `tools/sector-rotation/sector_rotation/universe.py:83-101`
- Modify: `tools/sector-rotation/sector_rotation/data.py:47-60,63-64,128`
- Modify: `tools/sector-rotation/sector_rotation/weekly.py:16-32`
- Modify: `tools/sector-rotation/sector_rotation/walkforward.py:31-36,50`
- Modify: `tools/sector-rotation/sector_rotation/portfolio.py:13,133-151`
- Test: `tests/test_sr_universe.py`、`tests/test_sr_data.py`、`tests/test_sr_weekly.py`、`tests/test_sr_walkforward.py`、`tests/test_sr_portfolio.py`

**Interfaces:**
- Consumes: 现有 `WeeklyFrame`/`UniverseSpec`/`point_in_time_pick`/`simulate_week`/`run_walkforward`/`window_blocks`。
- Produces（后续任务依赖的精确签名）:
  - `point_in_time_pick(candidates, bars, week_end, *, min_list_years=2, min_amount_wan=10000.0, bypass_single: bool = False) -> str | None`（单候选集旁路两道闸门——金额/年限闸门参数保持现状签名与默认值不动，评审 I-1；复查轮 N4：两者本就是签名参数、非硬编码）
  - `build_weekly_frame(data_root, spec, *, bench_symbol="510300.SH", corrupt_threshold: float = 0.30, pick_bypass_single: bool = False) -> WeeklyFrame`（`bench_symbol` 为现状参数——data.py:63-64 已存在，对应用例是行为回归锁而非本任务新增，复查轮 N2）
  - `window_blocks(wf, *, window=13, cols=None, upto=None, include_t: bool = False) -> tuple[np.ndarray, np.ndarray]`（include_t=True 时行 t 的特征 = `mat[t-window+1 : t+1]`，t 遍历 `[window-1, stop)`）
  - `run_walkforward(wf, strategy, *, cost, start=None, end=None, oos_start=None, risk=None, min_universe: int = 50, min_amount_wan: float | None = WEEKLY_MIN_AMOUNT_WAN) -> WalkResult`
  - `simulate_week(wf, t, weights_prev, weights_new, cost, *, min_amount_wan: float | None = WEEKLY_MIN_AMOUNT_WAN)`

- [ ] **Step 1: 写失败测试（7 个新用例，分布 5 个文件）**

`tests/test_sr_universe.py` 追加（该文件已导入 `point_in_time_pick`）：

```python
def test_point_in_time_pick_bypass_single():
    """R20261106-02 §7 第 5 行（设计评审 C-1/计划评审 I-1）：美股单候选成员
    旁路 pick——上市年限/均额两闸门本为 A 股多候选择一而设；旁路后 valid
    退化为数据齐备性；多候选路径不旁路（A 股默认零变化）。"""
    short = [{"date": f"2025-{m:02d}-15", "open": 1.0, "close": 1.0, "amount": 1e9}
             for m in range(1, 13)]                   # 12 行：<20 行且上市<2 年
    assert point_in_time_pick(["XLE"], {"XLE": short}, "2026-01-01") is None
    assert point_in_time_pick(["XLE"], {"XLE": short}, "2026-01-01",
                              bypass_single=True) == "XLE"
    assert point_in_time_pick(["A", "B"], {"A": short, "B": short}, "2026-01-01",
                              bypass_single=True) is None   # 多候选不旁路
```

`tests/test_sr_data.py` 追加（复用文件内既有 `_write`/`_etf_rows`/`_build`；文件头需 `import numpy as np`）：

```python
def test_corrupt_threshold_disable(tmp_path: Path):
    # R20261106-02 §7 第 1 行：美股复权数据无拆分残留，拆分防护可参数化关闭
    # ——同一 30%+ 跳变数据，默认阈值屏蔽该周、corrupt_threshold=1e9 放行。
    split = _etf_rows("2020-01-02", "2026-11-13")
    for r in split:
        if r["date"] >= "2026-11-11":                 # 周三起 close 减半
            r["close"] = 0.505
    _build(tmp_path, split)                           # 布局落盘（帧用默认参数）
    wf_def = build_weekly_frame(tmp_path, SPEC)
    wf_off = build_weekly_frame(tmp_path, SPEC, corrupt_threshold=1e9)
    assert not wf_def.valid[0][0]                     # 默认 0.30：周二~周五生效跳变 → 屏蔽
    assert wf_off.valid[0][0]                         # 1e9：放行


def test_bench_symbol_param(tmp_path: Path):
    # R20261106-02 §7：bench_symbol 传入即用（美股 SPY），bench_300 字段名不动。
    _write(tmp_path / "sector/series/881101.jsonl",
           [{"date": "2026-11-06", "close": 100.0},
            {"date": "2026-11-13", "close": 101.0},
            {"date": "2026-11-20", "close": 102.0}])
    _write(tmp_path / "market/series/528030.SH.jsonl", _etf_rows("2020-01-02", "2026-11-13"))
    _write(tmp_path / "market/series/SPY.jsonl",
           _etf_rows("2020-01-02", "2026-11-13", (1.0, 1.05, 1e9)))
    wf = build_weekly_frame(tmp_path, SPEC, bench_symbol="SPY")
    assert np.isfinite(wf.bench_300[0]) and abs(wf.bench_300[0] - 0.05) < 1e-9


def test_pick_bypass_single_valid_from_first_data_week(tmp_path: Path):
    # R20261106-02 §7 第 5 行（计划评审 I-1）：单候选旁路后 valid 退化为数据
    # 齐备性——短史成员从首个执行周齐备周即 valid；默认路径上市<2 年
    # pick=None → valid 恒 False（不旁路则美股 2009-2010 静默缩宇宙且无警报，
    # 2012 年模型有效训练标签腰斩）。真实数据全窗 valid==11 断言在
    # repro_paper.py 自检（提案 §9）。
    spec1 = UniverseSpec([Member("881101", "工程机械", ("528030.SH",), 0.10)], {})
    _write(tmp_path / "sector/series/881101.jsonl",
           [{"date": d, "close": 100.0 + i}
            for i, d in enumerate(["2026-10-09", "2026-10-16", "2026-11-06"])])
    _write(tmp_path / "market/series/528030.SH.jsonl",
           _etf_rows("2026-10-02", "2026-11-13"))
    _write(tmp_path / "market/series/510300.SH.jsonl",
           _etf_rows("2020-01-02", "2026-11-13"))
    wf_def = build_weekly_frame(tmp_path, spec1)
    wf_byp = build_weekly_frame(tmp_path, spec1, pick_bypass_single=True)
    assert not wf_def.valid[:, 0].any()               # 默认：上市<2 年 → 恒 invalid
    assert wf_byp.valid[:, 0].all()                   # 旁路：数据齐备即 valid
```

`tests/test_sr_weekly.py` 追加（该文件若未导入 `window_blocks`/`numpy`，补 `from sector_rotation.weekly import window_blocks` 与 `import numpy as np`）：

```python
def test_window_blocks_include_t_uses_decision_close():
    """R20261106-02 §8：MIMO 特征窗含决策周五收盘（论文口径，修 I-3 滞后一档）——
    include_t=True 时行 t 的块 = mat[t-window+1 : t+1]，t 从 window-1 起。"""
    from sector_rotation.data import WeeklyFrame
    from sector_rotation.universe import Member, UniverseSpec
    spec = UniverseSpec([Member("A", "甲", ("EA.SH",), 0.10)], {})
    idx = np.array([[1.0], [2.0], [4.0], [8.0], [16.0]])
    wf = WeeklyFrame([f"w{i}" for i in range(5)], idx, [["EA.SH"]] * 5,
                     np.ones((5, 1)), np.ones((5, 1)), np.ones((5, 1)),
                     np.full((5, 1), 2e8), spec.members, spec,
                     np.ones((5, 1), bool), np.ones((5, 1), bool), np.zeros(5))
    blocks, t_idx = window_blocks(wf, window=2, upto=5, include_t=True)
    assert list(t_idx) == [1, 2, 3, 4]
    assert blocks[0] == [1.0, 2.0] and blocks[3] == [8.0, 16.0]
    b2, i2 = window_blocks(wf, window=2, upto=5)     # 默认不含 t：行为不变
    assert list(i2) == [2, 3, 4] and b2[0] == [1.0, 2.0]
```

`tests/test_sr_walkforward.py` 追加：

```python
def test_min_universe_passthrough_prevents_collapse():
    """R20261106-02 §7：11 成员宇宙下默认 min_universe=50 令 coverage_start 回退
    末行（空转）；透传 min_universe=1 后从首个有效周正常起跑。"""
    wf = _wf(T=30)                                   # 2 成员全 valid（末行除外）
    res_def = run_walkforward(wf, momentum_topk, cost=CostModel.base(),
                              min_universe=50)       # 回退 start=29 → 第 29 周无 valid → 空转
    assert len(res_def.t_rows) == 0
    res = run_walkforward(wf, momentum_topk, cost=CostModel.base(), min_universe=1)
    assert len(res.t_rows) == 29
```

`tests/test_sr_portfolio.py` 追加：

```python
def test_min_amount_none_disables_liquidity_gate():
    """R20261106-02 §7：美股 SPDR 流动性不需要 5000 万元闸门（论文无此规则）——
    min_amount_wan=None 放行低均额成员；默认值行为不变（上条用例已锁）。"""
    wf = _wf(np.array([[1.0]]), np.array([[1.02]]), np.array([[1.0]]),
             week_amount=np.array([[3e7]]))          # 3000 万 < 默认 5000 万
    _, pos, detail = simulate_week(wf, 0, {}, {0: 1.0}, CostModel.base())
    assert 0 not in pos and detail["blocked"][0] == "liquidity"
    _, pos2, detail2 = simulate_week(wf, 0, {}, {0: 1.0}, CostModel.base(),
                                     min_amount_wan=None)
    assert 0 in pos2 and detail2["blocked"] == {}
```

- [ ] **Step 2: 跑新用例确认失败**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/test_sr_universe.py::test_point_in_time_pick_bypass_single tests/test_sr_data.py::test_corrupt_threshold_disable tests/test_sr_data.py::test_bench_symbol_param tests/test_sr_data.py::test_pick_bypass_single_valid_from_first_data_week tests/test_sr_weekly.py::test_window_blocks_include_t_uses_decision_close tests/test_sr_walkforward.py::test_min_universe_passthrough_prevents_collapse tests/test_sr_portfolio.py::test_min_amount_none_disables_liquidity_gate -v
```

Expected: 6 个 FAIL（TypeError: unexpected keyword argument）+ 1 个 PASS——`test_bench_symbol_param` 是现状回归锁（`bench_symbol` 已存在于 data.py:63-64，复查轮 N2），实现前即绿。

- [ ] **Step 3: 最小实现（5 个文件）**

`universe.py` `point_in_time_pick`（L83-101，只加 `bypass_single` 参数与函数体首行旁路，金额/年限闸门逻辑不动）：

```python
def point_in_time_pick(candidates: list[str], bars: dict[str, list[dict]],
                       week_end: str, *, min_list_years: int = 2,
                       min_amount_wan: float = 10000.0,
                       bypass_single: bool = False) -> str | None:
    """当时达标者：上市满 2 年 + trailing 20 日均额 ≥ 1 亿；多只取均额最大
    （规模 proxy 近似，spec §8 待验证——README 声明；上市年满 2 年按年整数差
    近似，误差 ±数日，评审 M2 注记）。

    bypass_single（R20261106-02 §7 第 5 行，设计评审 C-1）：单候选集旁路两道
    闸门直接返回该候选——美股退化宇宙每成员仅 1 只 ETF，闸门本为 A 股多候选
    择一而设，不旁路则美元口径均额/短史被静默踢出、宇宙缩水且全链路无警报；
    旁路后 valid 退化为数据齐备性（缺数防护仍在 build_weekly_frame）。"""
    if bypass_single and len(candidates) == 1:
        return candidates[0]
    best, best_amt = None, 0.0
    # ……以下函数体与现状逐字相同，不动……
```

`data.py`：`_corrupt_weeks` 加阈值参数（L47-60）：

```python
def _corrupt_weeks(series: dict[str, dict], *, threshold: float = 0.30) -> set[int]:
    """拆分防护（T4 修正案，T3 实测 76 件 >30% 事件）：close-to-close 单日
    |涨跌| > threshold 且生效日为周二~周五的日期所在 ISO 周——该执行周 open→close
    被份额拆分/缩股污染（场内行业 ETF ±10/20% 涨跌停下不可能是真实行情）。
    周一生效良性（整执行周 post-split），不标记。返回污染周 key 集。
    threshold 参数化（R20261106-02 §7）：美股复权数据无拆分残留，调用方传大值关闭。"""
    out: set[int] = set()
    dates = sorted(series)
    for prev, d in zip(dates, dates[1:]):
        if date.fromisoformat(d).weekday() == 0:    # 周一跳空（对上周五）不标记
            continue
        c0, c1 = float(series[prev]["close"]), float(series[d]["close"])
        if c0 > 0 and abs(c1 / c0 - 1) > threshold:
            out.add(_week_key(d))
    return out
```

`build_weekly_frame` 签名与两处调用点（L63-64、L73、L128）：

```python
def build_weekly_frame(data_root: Path, spec: UniverseSpec,
                       *, bench_symbol: str = "510300.SH",
                       corrupt_threshold: float = 0.30,
                       pick_bypass_single: bool = False
                       ) -> WeeklyFrame:
```
L73：`corrupt = {s: _corrupt_weeks(etf_data[s], threshold=corrupt_threshold) for s in all_etf_syms}`
L128：`pick = point_in_time_pick(list(m.etf_candidates), bars, fridays[-1], bypass_single=pick_bypass_single)`

`weekly.py` `window_blocks`（L16-32）：

```python
def window_blocks(wf: WeeklyFrame, *, window: int = 13, cols=None, upto=None,
                  include_t: bool = False
                  ) -> tuple[np.ndarray, np.ndarray]:
    """cols：资产子集（None=全体）；upto：只取 tj < upto（None=全帧）；
    include_t：特征块含决策周 t 自身收盘（[t-window+1, t]，R20261106-02 论文
    「周五收盘后采样」口径，修 v2 评审 I-3 滞后一档）——默认 False 保持
    [t-window, t) 原口径，L1 既有行为零变化。

    v2（R20261105-02）子集口径：全市场口径在 point-in-time 覆盖增长宇宙
    （416 成员 10→416 增长、峰值 65%）下无任何一行全体齐备 → t_idx 恒空
    → L1 策略恒 {}（真实数据冒烟实测）——消费端按当周 M_t 子集调用。"""
    mat = wf.index_close if cols is None else wf.index_close[:, cols]
    ok = np.isfinite(mat).all(axis=1)
    stop = len(wf.fridays) if upto is None else upto
    first = window - 1 if include_t else window
    feats, t_index = [], []
    for t in range(first, stop):
        rows = (np.arange(t - window + 1, t + 1) if include_t
                else np.arange(t - window, t))
        if ok[rows].all():
            feats.append(mat[rows, :].reshape(-1))
            t_index.append(t)
    return np.array(feats, dtype=float), np.array(t_index, dtype=int)
```

`portfolio.py`：`simulate_week` 签名加 keyword（L133-135），流动性分支改（L149-151）：

```python
def simulate_week(wf: WeeklyFrame, t: int, weights_prev: dict[int, float],
                  weights_new: dict[int, float], cost: CostModel,
                  *, min_amount_wan: float | None = WEEKLY_MIN_AMOUNT_WAN
                  ) -> tuple[float, dict[int, float], dict[float: float] | dict]:
```
（docstring 追加一句：`min_amount_wan=None 关流动性闸门（美股域 R20261106-02 §7）。`——以文件内既有返回类型注记为准，勿改其他）
```python
        elif (min_amount_wan is not None
              and (not np.isfinite(wf.etf_week_amount[t, i])
                   or wf.etf_week_amount[t, i] < min_amount_wan * 1e4)):
            blocked[i] = "liquidity"
```

`walkforward.py`：导入行加常量，`run_walkforward` 加两参并透传（L31-36 与 L50）：

```python
from .portfolio import RiskState, WEEKLY_MIN_AMOUNT_WAN, simulate_week


def run_walkforward(wf: WeeklyFrame, strategy, *, cost: CostModel,
                    start: int | None = None, end: int | None = None,
                    oos_start: int | None = None,
                    risk: RiskState | None = None,
                    min_universe: int = 50,
                    min_amount_wan: float | None = WEEKLY_MIN_AMOUNT_WAN
                    ) -> WalkResult:
    risk = risk or RiskState(wf.spec)
    start = (coverage_start(wf, min_universe=min_universe)
             if start is None else start)
```
L50：`net, gross_pos, detail = simulate_week(wf, t, weights_prev, weights_new, cost, min_amount_wan=min_amount_wan)`

- [ ] **Step 4: 全量回归 + lint**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/ -q && conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py
```

Expected: 全绿 + 零告警（A 股默认行为零变化由既有 550+ 用例背书）。

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/{universe,data,weekly,walkforward,portfolio}.py tests/test_sr_{universe,data,weekly,walkforward,portfolio}.py
git commit -m "feat(sector-rotation): 引擎跨域参数化——拆分防护/覆盖阈值/流动性闸门/单候选旁路（A股默认不变）"
```

---

### Task 2: us_backfill.py——yfinance 深回补 + verify 锚点核对

**Files:**
- Create: `tools/sector-rotation/us_backfill.py`
- Test: `tests/test_sr_us_backfill.py`
- 产出（gitignore）：`data/us-sector/{sector,market}/series/*.jsonl`

**Interfaces:**
- Consumes: `market_data_io.series_lock/upsert_series_rows`（`sys.path` 注入 `tools/daily-watch/scripts`，同 `backfill.py` L15-16 模式）。
- Produces:
  - `US_MEMBERS = ["XLK","XLV","XLY","VOX","XLF","XLI","XLP","XLU","XLB","IYR","XLE"]`（论文顺序，spec §1.1）
  - `BENCH = ["SPY", "^GSPC"]`、`START = "2009-01-01"`、`DATA_ROOT = REPO_ROOT/"data"/"us-sector"`、`SPY_ANCHORS`（Task 6 复用）
  - `df_to_rows(sym: str, df) -> list[dict]`（row = `{date,open,high,low,close,volume,amount,source}`，amount=close×volume）
  - `annual_close_returns(rows: list[dict]) -> dict[int, float]`（按年末 close 复合；Task 6 复用做 SPY 日历年对照列）
  - `check_anchors(annual: dict[int,float], anchors: dict[int,tuple[float,float]]) -> list[str]`（锚点年**缺失即报错**，计划评审 M-6）
  - `split_residues(rows: list[dict], threshold=0.30) -> list[tuple[str,float]]`
  - CLI：`fetch` / `verify`（verify 只读本地文件，`--raw-compare` 可选二次下载）

- [ ] **Step 1: 写失败测试 `tests/test_sr_us_backfill.py`**

```python
# tests/test_sr_us_backfill.py
import numpy as np
import pandas as pd

from us_backfill import (DATA_ROOT, US_MEMBERS, annual_close_returns,
                         check_anchors, df_to_rows, split_residues)


def _df(sym: str, dates, closes, volumes=None) -> pd.DataFrame:
    cols = pd.MultiIndex.from_product([[sym], ["Open", "High", "Low", "Close", "Volume"]])
    n = len(dates)
    vols = np.ones(n) * 1e6 if volumes is None else volumes
    data = np.column_stack([np.array(closes), np.array(closes) * 1.01,
                            np.array(closes) * 0.99, np.array(closes), vols])
    return pd.DataFrame(data, index=pd.DatetimeIndex(dates), columns=cols)


def test_df_to_rows_schema_and_amount():
    df = _df("XLE", ["2020-01-02", "2020-01-03"], [10.0, 11.0])
    rows = df_to_rows("XLE", df)
    assert rows[0]["date"] == "2020-01-02"
    assert rows[0]["source"] == "yfinance"
    assert abs(rows[0]["amount"] - 10.0 * 1e6) < 1e-6      # amount = close × volume
    assert set(rows[0]) == {"date", "open", "high", "low", "close",
                            "volume", "amount", "source"}


def test_annual_close_returns_compounds_year_end():
    # 首年无前年末基准 → 不在输出字典（年际收益语义；SPY_ANCHORS 2013 键 =
    # 2012 末→2013 末）——夹具必须含前年基准行（复查轮 N1：否则 got[2020]
    # KeyError，且易诱导执行者错改实现语义毁锚点口径）。实现不动。
    rows = [{"date": "2019-12-31", "close": 100.0},
            {"date": "2020-06-01", "close": 100.0},
            {"date": "2020-12-31", "close": 110.0},
            {"date": "2021-06-01", "close": 121.0},
            {"date": "2021-12-31", "close": 99.0}]
    got = annual_close_returns(rows)
    assert abs(got[2020] - 0.10) < 1e-12 and abs(got[2021] - (99.0 / 110.0 - 1)) < 1e-12


def test_check_anchors_reports_out_of_band_and_missing():
    # 计划评审 M-6：锚点年缺失 = 数据不完整，必须硬警报，不静默跳过。
    anchors = {2022: (-0.205, -0.16)}
    assert check_anchors({2022: -0.181}, anchors) == []
    errs = check_anchors({2022: -0.05}, anchors)
    assert len(errs) == 1 and "2022" in errs[0]
    miss = check_anchors({}, anchors)
    assert len(miss) == 1 and "缺失" in miss[0]


def test_split_residues_detects_jump():
    rows = [{"date": f"2020-01-{d:02d}", "close": 100.0} for d in range(1, 11)]
    rows.append({"date": "2020-01-13", "close": 50.0})     # 周一跳变 -50%
    res = split_residues(rows)
    assert res == [("2020-01-13", -0.5)]


def test_constants_and_layout():
    assert len(US_MEMBERS) == 11 and "VOX" in US_MEMBERS and "IYR" in US_MEMBERS
    assert DATA_ROOT.name == "us-sector"
```

（复查轮 N8：原 `json`/`Path` 导入未用已删，ruff 零告警。）

- [ ] **Step 2: 跑测试确认失败（ModuleNotFoundError: us_backfill）**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/test_sr_us_backfill.py -v
```

- [ ] **Step 3: 实现 `tools/sector-rotation/us_backfill.py`**

```python
# tools/sector-rotation/us_backfill.py
"""美股 11 行业 ETF 深回补（R20261106-02 §6 U2，spec §3.8 第 8 条新宇宙路径）。

主源 yfinance 复权价（auto_adjust=True）——研究域存储，偏离 daily-watch
「不复权」铁律，理由：论文口径（Yahoo adjusted close）+ 分红必须计入 TR 基准
（SPY 2022 TR ≈ -18.1% vs 价格 -19.4%，提案 §3 基准条）。布局镜像 A 股
data/ 根：成员 ETF 复权 close 同写 sector/series（信号价）与 market/series
（执行价 OHLC+amount≈close×volume）；SPY/^GSPC 只写 market/series。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from market_data_io import series_lock, upsert_series_rows  # noqa: E402

US_MEMBERS = ["XLK", "XLV", "XLY", "VOX", "XLF", "XLI",
              "XLP", "XLU", "XLB", "IYR", "XLE"]   # 论文顺序（spec §1.1）
BENCH = ["SPY", "^GSPC"]
START = "2009-01-01"
DATA_ROOT = REPO_ROOT / "data" / "us-sector"
SOURCE = "yfinance"
# 锚点带（提案 §6 verify）：SPY 复权=TR 口径，^GSPC 价格口径；带宽 ±2pp 级
SPY_ANCHORS = {2013: (0.30, 0.34), 2018: (-0.08, -0.04),
               2020: (0.16, 0.20), 2022: (-0.205, -0.16)}
GSPC_2022 = (-0.215, -0.175)


def _download(tickers: list[str], *, start: str = START, auto_adjust: bool = True,
              attempts: int = 5):
    """批量单次调用（13 标的合一下载降 429 风险），指数退避重试；仍失败抛出。
    本机对 Yahoo 有 429 限流史（friction-log 2026-10-28/10-31）——失败如实停。"""
    import yfinance as yf
    last = None
    for k in range(attempts):
        try:
            df = yf.download(tickers, start=start, auto_adjust=auto_adjust,
                             group_by="ticker", progress=False, threads=False)
            if df is not None and not df.empty:
                return df
            last = RuntimeError("empty frame")
        except Exception as exc:                     # noqa: BLE001
            last = exc
        time.sleep(min(2 ** k * 10, 120))
    raise RuntimeError(f"yfinance 拉取失败（退避 {attempts} 次）: {tickers} —— {last}")


def df_to_rows(sym: str, df) -> list[dict]:
    sub = df[sym].dropna(subset=["Close"])
    rows = []
    for d, r in sub.iterrows():
        close, vol = float(r["Close"]), float(r.get("Volume") or 0.0)
        rows.append({"date": d.date().isoformat(), "open": float(r["Open"]),
                     "high": float(r["High"]), "low": float(r["Low"]),
                     "close": close, "volume": vol,
                     "amount": close * vol, "source": SOURCE})
    return rows


def _write_series(rel_dir: str, sym: str, rows: list[dict]) -> None:
    path = DATA_ROOT / rel_dir / f"{sym}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with series_lock(DATA_ROOT, f"us-{sym}"):
        upsert_series_rows(path, rows, "batch")


def run_fetch() -> None:
    df = _download(US_MEMBERS + BENCH)
    for sym in US_MEMBERS:
        rows = df_to_rows(sym, df)
        _write_series("sector/series", sym, rows)   # 信号价 = 执行价同源（退化情形）
        _write_series("market/series", sym, rows)
        print(f"{sym}: {len(rows)} 行 ({rows[0]['date']} → {rows[-1]['date']})")
    for sym in BENCH:
        rows = df_to_rows(sym, df)
        _write_series("market/series", sym, rows)
        print(f"{sym}: {len(rows)} 行")


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def annual_close_returns(rows: list[dict]) -> dict[int, float]:
    by_year: dict[int, float] = {}
    for r in rows:                                   # rows 已按 date 升序
        by_year[int(r["date"][:4])] = float(r["close"])
    years = sorted(by_year)
    return {y: by_year[y] / by_year[prev] - 1.0
            for prev, y in zip(years, years[1:])}


def check_anchors(annual: dict[int, float],
                  anchors: dict[int, tuple[float, float]]) -> list[str]:
    """锚点年缺失即报错（计划评审 M-6）——数据不完整必须硬警报，不静默跳过。"""
    errs = []
    for y, (lo, hi) in anchors.items():
        if y not in annual:
            errs.append(f"锚点年 {y} 缺失（数据不完整）")
        elif not (lo <= annual[y] <= hi):
            errs.append(f"{y} 年收益 {annual[y]:.4f} 超出锚点带 {lo}~{hi}")
    return errs


def split_residues(rows: list[dict],
                   threshold: float = 0.30) -> list[tuple[str, float]]:
    out = []
    for prev, cur in zip(rows, rows[1:]):
        c0, c1 = float(prev["close"]), float(cur["close"])
        if c0 > 0 and abs(c1 / c0 - 1) > threshold:
            out.append((cur["date"], c1 / c0 - 1.0))
    return out


def run_verify(*, raw_compare: bool = False) -> int:
    errors = []
    print(f"{'symbol':8} {'首行':12} {'末行':12} {'行数':>6}  拆分残留(>30%)")
    for sym in US_MEMBERS + BENCH:
        rows = _read_rows(DATA_ROOT / "market" / "series" / f"{sym}.jsonl")
        if not rows:
            errors.append(f"{sym} 无数据（先跑 fetch）")
            continue
        res = split_residues(rows)
        print(f"{sym:8} {rows[0]['date']:12} {rows[-1]['date']:12} "
              f"{len(rows):>6}  {len(res)}{res[:2] if res else ''}")
        if sym in US_MEMBERS:
            if rows[0]["date"] > "2010-06-01":
                errors.append(f"{sym} 首行 {rows[0]['date']} 过晚（2012 交易需 "
                              "≥2 年训练史，MIMOModel fit）")
            if res:
                errors.append(f"{sym} 复权后仍有 {len(res)} 处 >30% 跳变，数据可疑")
    spy = annual_close_returns(_read_rows(DATA_ROOT / "market" / "series" / "SPY.jsonl"))
    errors += check_anchors(spy, SPY_ANCHORS)
    print("SPY 复权逐年收益: " + " ".join(f"{y}:{v:+.1%}" for y, v in spy.items()))
    gspc = annual_close_returns(_read_rows(DATA_ROOT / "market" / "series" / "^GSPC.jsonl"))
    errors += check_anchors(gspc, {2022: GSPC_2022})
    if raw_compare:
        raw = _download(US_MEMBERS + BENCH, auto_adjust=False)
        spy_raw = annual_close_returns(df_to_rows("SPY", raw))
        print("SPY 未复权 vs 复权年收益差（分红贡献披露）: "
              + " ".join(f"{y}:{spy_raw.get(y, float('nan')) - spy.get(y, float('nan')):+.2%}"
                         for y in sorted(spy)))
    if errors:
        print("\n".join(f"[FAIL] {e}" for e in errors))
        return 1
    print("[OK] 深度/拆分/锚点全部通过")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["fetch"]:
        run_fetch()
        return 0
    if argv[:1] == ["verify"]:
        return run_verify(raw_compare="--raw-compare" in argv)
    print("用法: us_backfill.py fetch | verify [--raw-compare]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

（verify 的深度门槛注记从「point_in_time_pick」改为「MIMOModel fit」——Task 1 已旁路 pick，深度需求来自 104 周训练史。）

- [ ] **Step 4: 单测绿 + lint**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/test_sr_us_backfill.py -v && conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/us_backfill.py tests/test_sr_us_backfill.py
```

- [ ] **Step 5: 真实拉取 + verify（网络步骤）**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python tools/sector-rotation/us_backfill.py fetch && conda run -n Quant-3.11 python tools/sector-rotation/us_backfill.py verify
```

Expected: 13 标的全部 ≥4300 行、首行 ≤2009 年、拆分残留 0、SPY 四个锚点年 + ^GSPC 2022 全在带内，exit 0。yfinance 1.2.0 已实测装于 Quant-3.11（计划评审 M-1），无需 pip 安装；429 耗尽退避 → 如实报告停止（Global Constraint 8）。

- [ ] **Step 6: Commit（只提交代码与测试，data/ 不入库）**

```bash
git add tools/sector-rotation/us_backfill.py tests/test_sr_us_backfill.py
git commit -m "feat(sector-rotation): us_backfill——yfinance 美股行业ETF深回补与锚点核对"
```

---

### Task 3: 美股宇宙清单（论文 11 成员退化情形）

**Files:**
- Create: `tools/sector-rotation/make_us_universe.py`
- Create: `config/sector-rotation-us-universe.md`（脚本生成，tracked）
- Test: `tests/test_sr_universe.py`（追加 1 用例）

**Interfaces:**
- Consumes: `sector_rotation.universe.Member/UniverseSpec/write_universe/load_universe`。
- Produces: `config/sector-rotation-us-universe.md`——11 成员 `index_code==ETF 符号`、`etf_candidates=(符号,)`、`limit_pct=1.0`、无簇表；Task 6 以 `load_universe(Path("config/sector-rotation-us-universe.md"))` 消费。

- [ ] **Step 1: 写失败测试（`tests/test_sr_universe.py` 追加）**

```python
def test_us_universe_roundtrip(tmp_path):
    """R20261106-02 §6 U3：论文 11 成员退化宇宙——index_code==ETF 符号、
    limit_pct=1.0（涨停闸门永不触发）、无簇表。"""
    from make_us_universe import NAMES, US_MEMBERS, write_config
    out = tmp_path / "us-universe.md"
    write_config(out)
    spec = load_universe(out)
    assert [m.index_code for m in spec.members] == US_MEMBERS
    assert all(m.etf_candidates == (m.index_code,) for m in spec.members)
    assert all(m.limit_pct == 1.0 for m in spec.members)
    assert spec.clusters == {}
    assert len(NAMES) == 11
```

（`tests/` 已有把 `tools/sector-rotation` 加进 `sys.path` 的 conftest，`import make_us_universe` 直接可用；`load_universe`/`write_universe` 按该文件既有导入。）

- [ ] **Step 2: 确认失败（No module named make_us_universe）**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/test_sr_universe.py::test_us_universe_roundtrip -v
```

- [ ] **Step 3: 实现 `tools/sector-rotation/make_us_universe.py` 并生成正式清单**

```python
# tools/sector-rotation/make_us_universe.py
"""美股宇宙清单生成（R20261106-02 §6 U3）：论文 §1.1 原始 11 成员逐字——
XLK/XLV/XLY/VOX/XLF/XLI/XLP/XLU/XLB/IYR/XLE（通讯=VOX、地产=IYR，非
XLC/XLRE；11 只 2012 前全部上市，全窗成员齐备）。退化情形：index_code==
ETF 符号、候选集单元素（Task 1 pick_bypass_single 消费）、limit_pct=1.0
（涨停闸门永不触发）、无簇表。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.universe import Member, UniverseSpec, write_universe  # noqa: E402

US_MEMBERS = ["XLK", "XLV", "XLY", "VOX", "XLF", "XLI",
              "XLP", "XLU", "XLB", "IYR", "XLE"]
NAMES = {
    "XLK": "Technology Select Sector SPDR", "XLV": "Health Care Select Sector SPDR",
    "XLY": "Consumer Discretionary Select Sector SPDR", "VOX": "Communication Services Select Sector SPDR",
    "XLF": "Financial Select Sector SPDR", "XLI": "Industrial Select Sector SPDR",
    "XLP": "Consumer Staples Select Sector SPDR", "XLU": "Utilities Select Sector SPDR",
    "XLB": "Materials Select Sector SPDR", "IYR": "iShares U.S. Real Estate ETF",
    "XLE": "Energy Select Sector SPDR",
}
OUT = REPO_ROOT / "config" / "sector-rotation-us-universe.md"


def write_config(path: Path) -> None:
    spec = UniverseSpec([Member(s, NAMES[s], (s,), 1.0) for s in US_MEMBERS], {})
    write_universe(path, spec, status="confirmed")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "status: confirmed\n---",
        "status: confirmed\n"
        "# 2026-11-06 美股域重开（R20261106-02，用户指令+论文 §1.1 原始清单）：11 成员\n"
        "# 退化情形 index_code==ETF 符号；limit_pct=1.0 禁用涨停闸门；无簇表（cluster_for→None）；\n"
        "# 单候选集由 build_weekly_frame(pick_bypass_single=True) 旁路 pick（§7 第 5 行）。\n"
        "---", 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    write_config(OUT)
    print(f"written: {OUT}")
```

生成正式清单并跑测试：

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python tools/sector-rotation/make_us_universe.py && conda run -n Quant-3.11 python -m pytest tests/test_sr_universe.py -v
```

- [ ] **Step 4: 人工核对生成的 config（11 行成员表 + frontmatter 注记，limit_pct 全 1.0）**

```bash
head -25 config/sector-rotation-us-universe.md
```

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/make_us_universe.py config/sector-rotation-us-universe.md tests/test_sr_universe.py
git commit -m "feat(sector-rotation): 美股宇宙清单落盘（论文11成员退化情形）"
```

---

### Task 4: MIMOModel——L2/T13 复活（TDD）

**Files:**
- Modify: `tools/sector-rotation/sector_rotation/models.py`（顶部 `from collections import deque`、`_torch` 签名、L2 常量、`thresholds_from_pairs`、`ROCState`、`MIMOModel`、`_roc_threshold`、`_confident`、`make_strategy` L2 分支直接 raise 并删除 `_l2_select`）
- Test: `tests/test_sr_models.py`（追加 8 用例）

**Interfaces:**
- Consumes: Task 1 的 `window_blocks(..., include_t=True)`；既有 `standardize_fit_apply`、`weekly_gross_returns`（标签源——执行周 open→close，引擎原生）、`LAMBDA_FIN`。
- Produces（Task 6 依赖）:
  - `L2_SEED = 20261106`、`L2_TRAIN_WEEKS = 104`、`L2_HIDDEN = (64, 32, 16)`、`L2_DROPOUT = 0.2`、`L2_EPOCHS = 200`、`L2_LR = 1e-3`、`L2_MC_SAMPLES = 20`
  - `_roc_threshold(probs: np.ndarray, labels: np.ndarray) -> float`（纯函数：数组上的 Youden J，单类回退 0.5）
  - `thresholds_from_pairs(pairs, n_assets: int, *, min_pairs: int = 26) -> np.ndarray`（trailing 实际（预测,已实现标签）对的每资产阈值，<26 对回退 0.5——偏差⑨，T13/评审 I5 口径）
  - `_confident(samples: np.ndarray, *, mass: float = 0.80) -> np.ndarray`（(T,L)→(L,) bool）
  - `ROCState(maxlen=52)`：属性 `pairs: deque`、`last_t: int | None`、`last_pred: np.ndarray | None`——跨年共享、毛/净双跑各持独立实例
  - `MIMOModel(*, window=13, epochs=200, lr=1e-3, hidden=(64,32,16), dropout=0.2, mc_samples=20, lambda_fin=LAMBDA_FIN, roc: ROCState | None = None)`，方法：
    - `fit(wf, t_train) -> self`（训练行 = 特征块 `[tj-window+1, tj]` 齐备且标签已实现（tj ≤ t_train−1）的最近 ≤104 周；**标签 = `weekly_gross_returns(wf)[tj]` ≥ 1%（执行周 open→close，偏差⑦）**，per-asset `wf.valid & isfinite` 掩码）
    - `select(wf, t, *, roc: ROCState | None = None) -> dict[int, float]`（**先回填上周 (预测, 已实现标签) 对进 ROC 状态 → trailing 阈值 → 买 = 置信 ∧ MC 中位数 ≥ 阈值 → 等权**；`roc=None` 用实例自有状态；特征块 = `[t-window+1, t]`）
    - `_mc_stats(x_now) -> (median, confident)`

- [ ] **Step 1: 写失败测试（`tests/test_sr_models.py` 追加；文件已有 `pytest.importorskip("torch")`、`_frame`、`toy_wf`）**

```python
# ---- MIMOModel（L2 复活，R20261106-02 §3/§8）----

from sector_rotation.models import (  # noqa: E402
    MIMOModel, ROCState, _confident, _roc_threshold, thresholds_from_pairs)
from sector_rotation.weekly import (  # noqa: E402
    weekly_gross_returns, window_blocks)


def test_confident_rule_tighter_than_gaussian():
    """论文 §1.1：MC 样本 ≥80% 质量落在中位数 ±1σ 内才置信——高斯 ≈68% 不
    过，紧簇样本过（弃权机制的判定单位）。"""
    tight = np.full((20, 1), 0.5)
    tight[0, 0] = 0.9                       # 19/20 落带内 → 0.95 ≥ 0.8 → 置信
    assert _confident(tight)[0]
    wide = np.linspace(0, 1, 20)[:, None]   # ≈13/20 落带内 → 0.65 < 0.8 → 弃权
    assert not _confident(wide)[0]


def test_roc_threshold_separable_and_fallback():
    # ≥10 对可分样本才越过 len<10 早退、真实命中 Youden 主路径（复查轮 N5：
    # 4 样本会被 0.5 兜底凑巧通过断言，主路径零覆盖）。
    p = np.array([0.05, 0.1, 0.15, 0.2, 0.3, 0.7, 0.8, 0.85, 0.9, 0.95])
    y = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    thr = _roc_threshold(p, y)
    assert 0.3 < thr <= 0.75                # 完全可分：Youden J 主路径的分割点
    assert _roc_threshold(p, np.ones(10)) == 0.5   # 单类标签 → 回退 0.5


def test_thresholds_from_trailing_pairs():
    """偏差⑨（T13/评审 I5 口径，用户追认 I-7）：阈值来自 trailing 实际
    （预测,已实现标签）对——<26 对每资产回退 0.5；可分对阈值落在 (0,1)。"""
    rng = np.random.default_rng(4)
    L = 3
    pairs = []
    for _ in range(30):
        pred = rng.random(L)
        pairs.append((pred, (pred > 0.5).astype(float)))   # 完全可分
    th = thresholds_from_pairs(pairs, L)
    assert th.shape == (L,) and ((th > 0) & (th < 1)).all()
    assert (thresholds_from_pairs(pairs[:10], L) == 0.5).all()   # <26 回退
    st = ROCState()
    st.pairs.extend(pairs + pairs)                    # 60 对 → maxlen=52 截断
    assert len(st.pairs) == 52


def test_mimo_seed_deterministic():
    """可复现性：同数据两个全新实例 → 连续三周 select 输出逐位一致
    （含 ROC 状态演化的确定性）。"""
    wf = toy_wf(T=180, seed=11)
    m1 = MIMOModel(window=13).fit(wf, 170)
    m2 = MIMOModel(window=13).fit(wf, 170)
    assert ([m1.select(wf, t) for t in (171, 172, 173)]
            == [m2.select(wf, t) for t in (171, 172, 173)])


def test_mimo_feature_boundary_uses_decision_close():
    """I-3 修正的边界锁：决策 t 的特征块 = [t-window+1, t]——t 之后的数据
    翻转不影响 t 决策；翻转 t 自身收盘则特征块必变。"""
    T = 180
    rng = np.random.default_rng(9)
    idx1 = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, 2)), axis=0)
    idx1_late = idx1.copy()
    idx1_late[171:] = 1.0                            # t 之后全变垃圾
    idx3 = idx1.copy()
    idx3[170] = idx1[170] * 0.5                      # 只翻 t=170 收盘
    close = 1 + rng.normal(0, 0.03, (T, 2))
    v = np.ones((T, 2), bool)
    v[-1] = False
    wf1 = _frame(T, v, close, idx=idx1)
    wf1l = _frame(T, v, close, idx=idx1_late)
    wf3 = _frame(T, v, close, idx=idx3)
    m1 = MIMOModel(window=13).fit(wf1, 170)
    m1l = MIMOModel(window=13).fit(wf1l, 170)
    assert m1.select(wf1, 170) == m1l.select(wf1l, 170)     # 171+ 无关
    b3, t_idx3 = window_blocks(wf3, window=13, upto=171, include_t=True)
    b1, _ = window_blocks(wf1, window=13, upto=171, include_t=True)
    assert t_idx3[-1] == 170 and not np.allclose(b3[-1], b1[-1])  # x_now 含 t 收盘


def test_mimo_learns_alternating_regime():
    """可学习性冒烟（open→close 标签版，偏差⑦）：A 资产偶数周执行窗 +5%、
    奇数周 -5%，特征=交替收盘模式（偶 90/奇 110）——训练行 tj≤194 学到
    「特征末值 90 → 该行执行窗 +5%」，决策偶数周应选中 A 而非 B（B 平价
    标签恒 0）。"""
    T = 200
    idx = np.zeros((T, 2))
    lab_ret = np.zeros((T, 2))
    for t in range(T):
        idx[t] = [90.0 if t % 2 == 0 else 110.0, 100.0]
        lab_ret[t] = [0.05 if t % 2 == 0 else -0.05, 0.0]
    v = np.ones((T, 2), bool)
    v[-1] = False
    wf = _frame(T, v, 1 + lab_ret, idx=idx)   # _frame 的 etf_open=1 → 执行周收益=lab_ret
    m = MIMOModel(window=13).fit(wf, 195)
    sel = m.select(wf, 196)                   # 偶数周决策：行 196 执行窗 +5%
    assert 0 in sel and sel.get(1, 0.0) <= sel[0]


def test_mimo_fit_requires_min_history():
    wf = toy_wf(T=20)
    try:
        MIMOModel(window=13).fit(wf, 19)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_mimo_roc_backfill_stateful_and_shared():
    """偏差⑨回填协议：select(t) 先把上周 (预测, 已实现标签) 入缓冲——标签 =
    执行周 open→close（决策时点 t 已实现，无泄漏）；状态对象跨实例共享
    （年冻结模型跨年携带）。"""
    wf = toy_wf(T=180, seed=5)
    st = ROCState()
    m1 = MIMOModel(window=13).fit(wf, 170)
    m1.select(wf, 171, roc=st)
    assert len(st.pairs) == 0                 # 首周无上周可回填
    m1.select(wf, 172, roc=st)
    assert len(st.pairs) == 1                 # 回填 (171 的预测, 171 执行周标签)
    pred, lab = st.pairs[0]
    assert pred.shape == lab.shape == (2,)
    np.testing.assert_allclose(lab, (weekly_gross_returns(wf)[171] >= 0.01))
    m2 = MIMOModel(window=13).fit(wf, 170)    # 年冻结驱动模式：新实例接续同一缓冲
    m2.select(wf, 173, roc=st)
    assert len(st.pairs) == 2


def test_make_strategy_l2_protocol_error():
    """L2 不走 per-call 重训协议：年冻结模型由 repro_paper.py 驱动，
    make_strategy("L2") 构造时即报错指路（计划评审 I-3）。"""
    with pytest.raises(ValueError, match="MIMOModel"):
        make_strategy("L2")
```

- [ ] **Step 2: 跑新用例确认失败（ImportError: cannot import name 'MIMOModel'）**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/test_sr_models.py -v -k "mimo or confident or roc or thresholds or l2_protocol"
```

- [ ] **Step 3: 实现 models.py 扩展**

顶部导入加 `from collections import deque`；`_torch` 改签名（L35-38，L1 调用点不动——默认参数仍为 SEED）：

```python
def _torch(seed: int = SEED):
    import torch
    torch.manual_seed(seed)            # 每次 fit/推断前重置（v2 可复现性口径）
    return torch
```

模块常量（L30-32 之后加）：

```python
# L2 复刻常量（R20261106-02 §10 预注册；论文 N 缺失 → 网格在消费端声明）
L2_SEED = 20261106
L2_TRAIN_WEEKS = 104                  # 论文「前 2 年历史训练」→ 年模型 104 周冻结
L2_HIDDEN = (64, 32, 16)              # 3 隐层 + 线性输出 = 论文「4 层全连接」
L2_DROPOUT = 0.2
L2_EPOCHS = 200
L2_LR = 1e-3
L2_MC_SAMPLES = 20
```

`_roc_threshold` + `_confident` + `thresholds_from_pairs` + `ROCState` + `MIMOModel`（放在 `LinearModel` 之后、`make_strategy` 之前）：

```python
def _roc_threshold(probs: np.ndarray, labels: np.ndarray) -> float:
    """纯函数：数组上的 Youden J 最优分位点；单类/样本过少 → 回退 0.5。
    trailing 对口径经 thresholds_from_pairs 调用（偏差⑨）。"""
    m = np.isfinite(probs) & np.isfinite(labels)
    p, y = probs[m], labels[m]
    if len(p) < 10 or len(np.unique(y)) < 2:
        return 0.5
    best, thr = -1.0, 0.5
    for q in np.unique(np.quantile(p, np.linspace(0.05, 0.95, 19))):
        tpr = float(((p >= q) & (y == 1)).mean())
        fpr = float(((p >= q) & (y == 0)).mean())
        if tpr - fpr > best:
            best, thr = tpr - fpr, float(q)
    return thr


def _confident(samples: np.ndarray, *, mass: float = 0.80) -> np.ndarray:
    """MC dropout 置信（论文 §1.1）：某资产 (T,) 概率样本 ≥80% 落在
    中位数 ±1 样本标准差内 → 置信。高斯 ≈68% 不过——只有紧于高斯的
    预测分布才可买（论文周均仅买 2.25/11 的机制来源）。"""
    med = np.median(samples, axis=0)
    sd = samples.std(axis=0)
    return (np.abs(samples - med) <= sd).mean(axis=0) >= mass


def thresholds_from_pairs(pairs, n_assets: int, *, min_pairs: int = 26
                          ) -> np.ndarray:
    """T13/评审 I5 口径（R20261106-02 §4 偏差⑨，2026-11-06 用户追认）：
    每资产买入阈值 = trailing 实际（预测, 已实现标签）对的 Youden J；
    有效对 < min_pairs 回退 0.5（年首回退期）。禁用训练窗 in-sample
    拟合概率充数。"""
    out = np.full(n_assets, 0.5)
    if len(pairs) < min_pairs:
        return out
    P = np.stack([p for p, _ in pairs])              # (n, L) 预测（MC 中位）
    Y = np.stack([lb for _, lb in pairs])            # (n, L) 已实现标签（含 NaN）
    for j in range(n_assets):
        m = np.isfinite(P[:, j]) & np.isfinite(Y[:, j])
        if m.sum() >= min_pairs:
            out[j] = _roc_threshold(P[m, j], Y[m, j])
    return out


class ROCState:
    """L2 跨年共享 ROC 状态（R20261106-02 §4 偏差⑨）：trailing 实际
    （预测, 已实现标签）对环形缓冲（maxlen=52）+ 上周预测暂存。年冻结模型
    逐年换实例，同一状态对象跨年携带（缓冲跨年模型混用，提案 §4 已披露）；
    毛/净两次运行各持独立实例（ROC 对与成本无关，独立状态保证两跑信号
    逐位一致——repro_paper.make_strat）。

    回填协议（T13 评审 I5/I11）：select(t) 先把上周 (last_pred, 已实现标签)
    入缓冲——标签 = weekly_gross_returns[last_t]（执行周 open→close），决策
    时点 t 已实现，无泄漏。"""

    def __init__(self, maxlen: int = 52):
        self.pairs: deque = deque(maxlen=maxlen)
        self.last_t: int | None = None
        self.last_pred: np.ndarray | None = None


class MIMOModel:
    """L2 论文复刻（spec §1.1；R20261106-02 §3/§8，T13 复活）。

    与 L1 的差异：①特征块含决策周五收盘（window_blocks include_t=True，
    论文「周五收盘后采样」，修 v2 评审 I-3 滞后一档，偏差⑥）；②标签 =
    执行周 open→close ≥1%（weekly_gross_returns 引擎原生，与执行 PnL 同
    口径，偏差⑦——2026-11-06 用户追认 A）；③MIMO 联合 4 层 FC（3 隐层
    ReLU+dropout + 线性 11 输出）；④推断 MC dropout T 采样——中位数 ±1σ
    含 ≥80% 样本质量才置信；⑤买入 = 置信 ∧ 中位数 ≥ ROC 阈值，阈值 =
    trailing 52 对实际（预测,已实现标签）的 Youden J（<26 回退 0.5，偏差⑨
    ——论文「周周重估」的机制落地，2026-11-06 用户追认 A）；等权（论文
    win-rate/streak 加权公式排版损坏，偏差①）。年模型协议（偏差②）：fit
    在交易年前最后一个决策周五调用后冻结，年内 select 只换特征不换参，
    ROC 状态跨年共享（驱动见 repro_paper.py）。"""

    def __init__(self, *, window: int = 13, epochs: int = L2_EPOCHS,
                 lr: float = L2_LR, hidden: tuple[int, ...] = L2_HIDDEN,
                 dropout: float = L2_DROPOUT, mc_samples: int = L2_MC_SAMPLES,
                 lambda_fin: float = LAMBDA_FIN, roc: ROCState | None = None):
        self.window, self.epochs, self.lr = window, epochs, lr
        self.hidden, self.dropout, self.mc_samples = hidden, dropout, mc_samples
        self.lambda_fin = lambda_fin
        self.net = None
        self.roc = roc if roc is not None else ROCState()
        self._train_blocks: np.ndarray | None = None

    def _build_net(self, torch, D: int, L: int):
        layers, d = [], D
        for h in self.hidden:
            layers += [torch.nn.Linear(d, h), torch.nn.ReLU(),
                       torch.nn.Dropout(self.dropout)]
            d = h
        layers.append(torch.nn.Linear(d, L))
        return torch.nn.Sequential(*layers)

    def fit(self, wf: WeeklyFrame, t_train: int) -> "MIMOModel":
        blocks, t_idx = window_blocks(wf, window=self.window,
                                      upto=t_train + 1, include_t=True)
        lab = [k for k, tj in enumerate(t_idx) if tj + 1 <= t_train]
        if len(lab) < self.window + 2:
            raise ValueError(f"训练行不足：{len(lab)} < window+2={self.window + 2}")
        take = lab[-L2_TRAIN_WEEKS:]
        tj_all = t_idx[take]
        train = blocks[take]
        # 标签 = 执行周 open→close（偏差⑦）：weekly_gross_returns 行 tj 即
        # 决策 tj 的执行周收益；tj ≤ t_train-1 保证至决策周五收盘已实现
        rets = weekly_gross_returns(wf)
        sub_r = rets[tj_all]
        lab_ok = wf.valid[tj_all] & np.isfinite(sub_r)   # per-asset 掩码
        r = np.where(lab_ok, sub_r, np.nan).astype(np.float32)
        y = np.where(lab_ok, sub_r >= 0.01, np.nan).astype(np.float32)
        X = standardize_fit_apply(train, train)
        torch = _torch(L2_SEED)
        self.net = self._build_net(torch, X.shape[1], y.shape[1])
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr)
        bce = torch.nn.BCEWithLogitsLoss(reduction="none")
        Xt = torch.tensor(X, dtype=torch.float32)
        mask = torch.tensor(np.isfinite(y) & np.isfinite(r), dtype=torch.float32)
        Yt = torch.nan_to_num(torch.tensor(y), nan=0.0)
        Rt = torch.nan_to_num(torch.tensor(r), nan=0.0)
        denom = mask.sum().clamp(min=1.0)
        for _ in range(self.epochs):
            opt.zero_grad()
            logits = self.net(Xt)
            loss = ((bce(logits, Yt) * mask).sum() / denom
                    - self.lambda_fin * (torch.sigmoid(logits) * Rt * mask).sum() / denom)
            loss.backward()
            opt.step()
        self._train_blocks = train
        return self

    def _mc_stats(self, x_now: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        torch = _torch(L2_SEED)          # 推断前重置种子：dropout 采样可复现
        self.net.train()                 # MC dropout：推断时开 dropout
        samples = []
        with torch.no_grad():
            xt = torch.tensor(x_now[None, :], dtype=torch.float32)
            for _ in range(self.mc_samples):
                samples.append(torch.sigmoid(self.net(xt))[0].numpy())
        self.net.eval()
        s = np.stack(samples)            # (T, L)
        return np.median(s, axis=0), _confident(s)

    def select(self, wf: WeeklyFrame, t: int, *,
               roc: ROCState | None = None) -> dict[int, float]:
        if self.net is None:
            return {}
        roc = roc if roc is not None else self.roc
        blocks, t_idx = window_blocks(wf, window=self.window,
                                      upto=t + 1, include_t=True)
        if len(t_idx) == 0 or t_idx[-1] != t:
            return {}
        x_now = standardize_fit_apply(self._train_blocks, blocks[-1:])[0]
        med, conf = self._mc_stats(x_now)
        # 偏差⑨回填协议：先入上周 (预测, 已实现标签) 对再取阈值——标签 =
        # 执行周 open→close，决策时点 t 已实现无泄漏；t > last_t 即可回填
        # （跳周时上周标签同样已实现）
        if roc.last_t is not None and t > roc.last_t:
            rets = weekly_gross_returns(wf)
            lab = np.where(np.isfinite(rets[roc.last_t]),
                           rets[roc.last_t] >= 0.01, np.nan)
            roc.pairs.append((roc.last_pred, lab))
        thr = thresholds_from_pairs(roc.pairs, len(med))
        buy = [j for j in range(len(med)) if conf[j] and med[j] >= thr[j]]
        roc.last_t, roc.last_pred = t, med
        return {j: 1.0 / len(buy) for j in buy} if buy else {}
```

`make_strategy` L2 分支替换为直接 raise，并**删除 `_l2_select` 整个函数**（grep 实核无外部引用；`backtest.py` 经 `make_strategy(args.level, ...)` 调用，L2 输入将得到清晰报错而非沉默 partial——backtest.py 本身不动）：

```python
    if level == "L2":
        raise ValueError("L2=MIMOModel 年冻结协议（R20261106-02 §3），由 "
                         "repro_paper.py 驱动，不走 per-call 重训的 make_strategy")
```

- [ ] **Step 4: 全量回归 + lint**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/ -q && conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/ tests/test_sr_*.py
```

（若 `test_mimo_learns_alternating_regime` 因种子敏感性不过：只允许微调该用例的 T/固定种子，禁止改 MIMOModel 超参——超参已在 Task 5 预注册冻结。）

- [ ] **Step 5: Commit**

```bash
git add tools/sector-rotation/sector_rotation/models.py tests/test_sr_models.py
git commit -m "feat(sector-rotation): L2 MIMOModel 复刻——4层FC+MC dropout弃权+trailing-pairs ROC动态阈值"
```

---

### Task 5: 复现配置预注册（先于任何复现运行，单独 commit）

**Files:**
- Modify: `workspace/proposals/2026-11-05-sector-rotation-design.md`（§6.3 追加预注册行；版本注记 v1.2.6 不动——**不加第 10 条**，第 10 条属结案 Task 7）
- Modify: `workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md`（status → prereg-registered；§11 追加 U6 行）

**Interfaces:**
- Consumes: Task 4 的常量值与偏差口径（预注册文本必须与代码一致——标签 open→close / ROC trailing 52 为用户已追认方向决策，计划评审 C-1/C-2）。
- Produces: spec §6.3 预注册行——Task 6 报告的 config 注入断言与关键 token 以本行文本为准。

- [ ] **Step 1: spec §6.3 追加预注册行**

打开 `workspace/proposals/2026-11-05-sector-rotation-design.md`，定位 `## 6.3`（实施记录表），在 v3 双窗结构行（Q-20261106-02 行）之后按既有条目格式追加。**内容 = 提案 §10 预注册行草案六行原文逐字**（前置日期与轮次前缀；§6.3 若为单行列表项则六行以原文换行追加、断句不改写）：

```
2026-11-06：US-复现-L2 预注册（R20261106-02，引擎验证性诊断·探索性，无 p 值闸门；先于任何复现运行单独 commit）：
US-复现-L2 预注册：MIMOModel · N∈{13,26,52} 三格全披露 · 训练=前 104 周年冻结（训练行 tj≤t-1） · 标签=执行窗 open→close ≥1%（偏差⑦，采信 spec §1.1 读法）
特征=[t-N+1, t] 含决策周五（include_t/错位配对，偏差⑥） · 置信=MC dropout T=20 · 中位±1SD ≥80% 质量
ROC=trailing 52 对实际预测-标签 Youden J（<26 回退 0.5，偏差⑨） · 等权（论文加权公式损坏，偏差①）
损失=masked BCE+λ0.1 金融项（实现方口径，偏差⑤） · seed=20261106 · CPU · 零成本主判定+2bp 参考行 · RiskState 关（enabled=False，裸路径=唯一路径）
窗口=2012-01-01:2022-12-31（尾段 2023+ 处女，第 10 条草案） · 基准=SPY 复权（TR 代理）· α 判定=同周 open→close 合成、日历年口径并排 · 年归属=执行周 ISO 年
判定域=A（α≥8% 且 ≥7/11 正）/B（非 A 且 α>0）/C（α≤0）预声明，无 p 值闸门（探索性诊断定性） · 最强格=α 均值→正年数→N 小
```

- [ ] **Step 2: 提案状态流转**

`2026-11-06-sector-rotation-us-reproduction.md` frontmatter：

```
status: prereg-registered（预注册已单独 commit，先于任何复现运行；计划评审 2026-11-06-sector-rotation-us-repro-plan-review.md 的 C/I 修复已并入实施计划；评审 Q-20261106-05）
```

§11 追加：

```
- **U6（2026-11-06）**：预注册行落 spec §6.3 并单独 commit（先于 U7 任何真实复现运行）。配置与 models.py 常量逐字一致（L2_SEED/L2_HIDDEN/…），标签/ROC 口径为用户 2026-11-06 追认方向（偏差⑦⑨）。
```

- [ ] **Step 3: 验证 + Commit**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python - <<'EOF'
from pathlib import Path
spec = Path("workspace/proposals/2026-11-05-sector-rotation-design.md").read_text(encoding="utf-8")
prop = Path("workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md").read_text(encoding="utf-8")
assert "US-复现-L2 预注册" in spec
for token in ("标签=执行窗 open→close", "trailing 52", "执行周 ISO 年",
              "最强格=α 均值→正年数→N 小", "2012-01-01:2022-12-31",
              "seed=20261106", "裸路径=唯一路径"):   # 复查轮 N6：与提案 §10 逐字一致，含等号
    assert token in spec, token
assert "prereg-registered" in prop
print("prereg ok")
EOF
git add workspace/proposals/2026-11-05-sector-rotation-design.md workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md
git commit -m "docs(sector-rotation): US复现预注册——配置冻结与判定域A/B/C落档（spec §6.3）"
```

（token 断言覆盖两项用户拍板决策与择格/归年规则——Task 6 的 `PREREG_CONFIG` 与 `test_prereg_config_frozen` 用同一 token 集，三处载体不逐字复制但关键决策互锁，计划评审 M-4。）

---

### Task 6: repro_paper.py——Tier-1 引擎锚 + Tier-2 三格复现

**Files:**
- Create: `tools/sector-rotation/repro_paper.py`
- Test: `tests/test_sr_repro.py`
- 产出（gitignore）：`output/sector-rotation/2026-11/us-repro-2026-11-06.md`

**Interfaces:**
- Consumes: Task 1 新参数（`pick_bypass_single=True`/`corrupt_threshold=1e9`/`min_amount_wan=None`；`min_universe` 在显式 start 下不参与——复查轮 N7，防坍缩语义由 Task 1 测试在 start=None 路径锁定）、Task 3 `config/sector-rotation-us-universe.md`、Task 2 `data/us-sector/` + `SPY_ANCHORS`/`annual_close_returns`/`check_anchors`、Task 4 `MIMOModel`/`ROCState` + 常量。
- Produces:
  - `PREREG_CONFIG: str`（与 Task 5 spec 行关键 token 同源的配置段）
  - `YEARS = list(range(2012, 2023))`、`N_GRID = [13, 26, 52]`
  - `exec_iso_year(friday: str) -> int`（年归属 = 执行周 ISO 年）
  - `annual_group_returns(keys: list[int], weekly: np.ndarray) -> dict[int, float]`
  - `verdict(mean_alpha: float, pos_years: int) -> str`
  - `alpha_vs_paper(annual: dict[int, float], bench: dict[int, float]) -> dict[int, float]`
  - `manual_cross_check(wf, data_root: Path, weeks: list[str]) -> list[str]`
  - CLI：`python repro_paper.py [--limit-weeks N]`（N 只缩短首年长度，终点恒 2022-12-31）

- [ ] **Step 1: 写失败测试 `tests/test_sr_repro.py`**

```python
# tests/test_sr_repro.py
import numpy as np
import pytest

pytest.importorskip("torch")            # repro_paper 顶部 import models

from repro_paper import (PREREG_CONFIG, YEARS, alpha_vs_paper,  # noqa: E402
                         annual_group_returns, exec_iso_year, verdict)


def test_years_window_frozen():
    assert list(YEARS) == list(range(2012, 2023))     # 尾段 2023+ 处女，硬编码


def test_prereg_config_frozen():
    # 计划评审 M-4：预注册三处载体（spec §6.3 行 / PREREG_CONFIG / 报告注入）
    # 的关键 token 集合——含两项用户已拍板方向决策（偏差⑦⑨）与归年/择格规则。
    for token in ("N∈{13,26,52}", "seed=20261106", "2012-01-01:2022-12-31",
                  "open→close", "trailing 52", "执行周 ISO 年", "最强格",
                  "SPY", "等权"):
        assert token in PREREG_CONFIG


def test_annual_group_returns_by_exec_year():
    keys = [2012, 2012, 2013, 2013]
    weekly = np.array([0.10, 0.10, -0.5, 0.0])
    got = annual_group_returns(keys, weekly)
    assert abs(got[2012] - 0.21) < 1e-12 and abs(got[2013] - (-0.5)) < 1e-12


def test_exec_iso_year_boundaries():
    # 计划评审 I-7：年归属 = 执行周 ISO 年——跨年决策周（W52/W53）归下一 ISO 年
    assert exec_iso_year("2019-06-07") == 2019
    assert exec_iso_year("2016-12-30") == 2017     # W52 周五 → 执行周 W1-2017
    assert exec_iso_year("2020-12-31") == 2021     # W53 周四（Good Friday 型短周）


def test_verdict_domains():
    assert verdict(0.10, 8).startswith("A")
    assert verdict(0.03, 5).startswith("B")
    assert "不预指派" in verdict(0.03, 5)          # 计划评审 I-5：并列归因
    assert verdict(-0.02, 3).startswith("C")
    assert verdict(0.10, 5).startswith("B")        # 均值够但正年数不足


def test_alpha_arithmetic():
    a = alpha_vs_paper({2022: 0.1029}, {2022: -0.1811})
    assert abs(a[2022] - 0.284) < 1e-9             # 论文 2022 α=+28.4% 同口径
```

- [ ] **Step 2: 确认失败（ModuleNotFoundError: repro_paper）**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/test_sr_repro.py -v
```

- [ ] **Step 3: 实现 `tools/sector-rotation/repro_paper.py`**

```python
# tools/sector-rotation/repro_paper.py
"""SSRN 4280640 论文复现驱动（R20261106-02 §9 U7；预注册先行，spec §6.3）。

Tier-1 引擎锚：L0 动量对照（论文缺失的对照组）+ 等权年再平衡 + 3 周帧手验
切面（etf_open/close vs 原始 jsonl 逐位）——锚全绿才继续。
Tier-2 主跑：MIMOModel 三格（window∈{13,26,52}）× 2012-2022，年模型冻结 +
跨年共享 ROC 状态（偏差⑨），毛口径（0 成本）主判定 + 2bp 净参考行（同信号
双跑、独立 ROC 状态——ROC 对与成本无关，净行只差成本），vs 论文 Table 3
并排对照 + 判定域 A/B/C 归类（无 p 值闸门——探索性诊断定性）。

自检（提案 §9）：config 注入断言、三格不全等、SPY 锚点带、全窗 valid==11
（设计评审 C-1 教训——缩宇宙须硬警报，计划评审 I-4）。

窗口纪律：消费区间硬编码 2012-01-01:2022-12-31；尾段 2023+ 处女——
--limit-weeks 只缩短不改终点，代码 assert 终点周 ≤ 2022-12-31。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.baselines import EqualWeightAnnual, momentum_topk  # noqa: E402
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import _week_key, build_weekly_frame  # noqa: E402
from sector_rotation.models import MIMOModel, ROCState  # noqa: E402
from sector_rotation.portfolio import RiskState  # noqa: E402
from sector_rotation.universe import load_universe  # noqa: E402
from sector_rotation.walkforward import run_walkforward  # noqa: E402
from us_backfill import SPY_ANCHORS, annual_close_returns, check_anchors  # noqa: E402

YEARS = list(range(2012, 2023))
N_GRID = [13, 26, 52]
WIN_START, WIN_END = "2012-01-01", "2022-12-31"
US_CONFIG = REPO_ROOT / "config" / "sector-rotation-us-universe.md"
US_DATA = REPO_ROOT / "data" / "us-sector"
OUT = REPO_ROOT / "output" / "sector-rotation" / "2026-11" / "us-repro-2026-11-06.md"
CROSS_WEEKS = ["2012-01-06", "2016-11-04", "2020-03-20"]
PAPER = {"mean_alpha": 0.1263, "median_alpha": 0.0763, "alpha_2012": -0.0075,
         "alpha_2022": 0.284, "cagr_mean": 0.2661, "spx_cagr": 0.1397,
         "sharpe_mean": 1.39, "maxdd_mean": 0.10, "win_rate": 0.606,
         "avg_positions": 2.25}
ZERO = CostModel(commission_bps=0.0, spread_bps=0.0)
REF2BP = CostModel(commission_bps=0.0, spread_bps=2.0)
PREREG_CONFIG = ("US-复现-L2 预注册（与 spec §6.3 2026-11-06 行同源，R20261106-02）："
                 "MIMOModel · N∈{13,26,52} 三格全披露 · 训练=前 104 周年冻结"
                 "（训练行 tj≤t-1） · 标签=执行窗 open→close ≥1%（偏差⑦） · "
                 "特征=[t-N+1,t] 含决策周五（偏差⑥） · 置信=MC dropout T=20 · "
                 "中位±1SD ≥80% 质量 · ROC=trailing 52 对实际预测-标签 Youden J"
                 "（<26 回退 0.5，偏差⑨） · 等权（论文加权公式损坏，偏差①） · "
                 "损失=masked BCE+λ0.1 金融项（实现方口径，偏差⑤） · "
                 "seed=20261106 · CPU · 零成本主判定+2bp 参考行 · RiskState 关"
                 "（enabled=False，裸路径=唯一路径） · 窗口 2012-01-01:2022-12-31"
                 "（尾段 2023+ 处女） · 基准 SPY 复权（TR 代理） · α 判定=同周 "
                 "open→close 合成、日历年口径并排 · 年归属=执行周 ISO 年 · "
                 "判定域 A/B/C 预声明无 p 值闸门 · 最强格=α 均值→正年数→N 小")
DISCLOSURES = [
    "周定义：ISO 周内最后交易日决策、执行=次周首日 open→末日 close；Good Friday 等"
    "休市周自动退为周四决策（提案 §3 评审 M-5 注记）。",
    "MC dropout T=20：论文未给 T，较 T13 默认 100 降档（算力/方差折衷），边界敏感"
    "性提案 §3 评审 M-6 披露。",
    "A/B 边界 8% = 论文 12.63% 的锚定折扣（非推导）；7/11 正年 = 论文 10/11 正年"
    "的容差（提案 §5 评审 M-2/M-1）。",
    "ROC 阈值：年首回退期（<26 对 → 0.5）与缓冲跨年模型混用为实现方选择（偏差⑨，"
    "提案 §4，2026-11-06 用户追认）。",
    "α 双口径：判定列 = 同周 open→close 合成（引擎 bench 原生）；SPY 日历年 "
    "close-to-close 并排披露供论文对照（提案 §3 评审 I-8）。",
    "标签 = 执行窗 open→close ≥1%（偏差⑦，与执行 PnL 同口径，2026-11-06 用户"
    "追认）；净参考行基准为毛口径 SPY（指数无交易成本）。",
    "窗界过滤（复查轮 N3）：决策周五 ∈ 2012-01-01..2022-12-31 且执行周 ISO 年 "
    "≤2022——2012 年不含 W01 执行周（属窗外决策 2011-12-30）、末决策 2022-12-30 "
    "的执行周 2023-W01 已弃，尾段 2023+ 零触及。",
]


def build_frame():
    spec = load_universe(US_CONFIG)
    return build_weekly_frame(US_DATA, spec, bench_symbol="SPY",
                              corrupt_threshold=1e9, pick_bypass_single=True)


def exec_iso_year(friday: str) -> int:
    """年归属 = 执行周 ISO 年（提案 §5 评审 M-3，计划评审 I-7）：决策 ISO 周
    的下一周——其周一 = _week_key(friday)+7，取该周 ISO 年（跨年 W52/W53
    决策周归下一年）。"""
    return date.fromordinal(_week_key(friday) + 7).isocalendar()[0]


def year_bounds(wf) -> tuple[int, int]:
    """消费窗（GC 6 + 复查轮 N3）：决策周五 ∈ 2012-01-01..2022-12-31 且执行周
    ISO 年 ≤ 2022——末决策周五 2022-12-30 的执行周是 2023-W01，必须弃（尾段
    2023+ 处女零触及；α 字典保持 2012..2022 十一键，与 ≥7/11 判据对齐）。"""
    idx = [t for t, f in enumerate(wf.fridays)
           if WIN_START <= f <= WIN_END and exec_iso_year(f) <= 2022]
    assert idx, "2012-2022 无决策周——数据未回补？"
    assert wf.fridays[idx[-1]] <= WIN_END            # 窗口纪律（Global Constraint 6）
    return idx[0], idx[-1] + 1


def annual_group_returns(keys: list[int], weekly: np.ndarray) -> dict[int, float]:
    """按执行周 ISO 年复合周收益（keys 与 weekly 一一对应）。"""
    out: dict[int, float] = {}
    for y, r in zip(keys, weekly):
        out.setdefault(int(y), 1.0)
        out[int(y)] *= (1.0 + float(r))
    return {y: v - 1.0 for y, v in out.items()}


def alpha_vs_paper(annual: dict[int, float],
                   bench: dict[int, float]) -> dict[int, float]:
    return {y: annual[y] - bench[y] for y in annual if y in bench}


def verdict(mean_alpha: float, pos_years: int) -> str:
    if mean_alpha >= 0.08 and pos_years >= 7:
        return "A（域内复现成功——引擎验证通过 + 论文方向可复现）"
    if mean_alpha > 0:
        return ("B（方向复现——引擎通过、幅度/一致性未达 A；归因待分：偏差①②③"
                " 消融 vs 论文全样本调参嫌疑，并列记录不预指派）")
    return "C（复现失败——引擎/数据单元核对后再下结论）"


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def manual_cross_check(wf, data_root: Path, weeks: list[str]) -> list[str]:
    """3 周帧手验：wf.etf_open/close vs 原始 jsonl 逐位（friction-log 教训——
    真实数据冒烟是任何网格的前置闸门）。"""
    errors = []
    for wk in weeks:
        t = wf.fridays.index(wk)
        for li, m in enumerate(wf.members):
            rows = _read_rows(data_root / "market" / "series"
                              / f"{m.etf_candidates[0]}.jsonl")
            by_wk: dict[int, list[dict]] = {}
            for r in rows:
                by_wk.setdefault(_week_key(r["date"]), []).append(r)
            nxt = next((c for c in (_week_key(wk) + 7, _week_key(wk) + 14)
                        if c in by_wk), None)
            if nxt is None:
                errors.append(f"{wk} {m.index_code}: 执行周缺数据")
                continue
            first, last = by_wk[nxt][0], by_wk[nxt][-1]
            if abs(wf.etf_open[t, li] - float(first["open"])) > 1e-9 \
                    or abs(wf.etf_close[t, li] - float(last["close"])) > 1e-9:
                errors.append(f"{wk} {m.index_code}: 帧价与原始行不符")
    return errors


def _run(wf, strategy, start, end, *, cost: CostModel):
    # min_universe 不传（复查轮 N7）：恒传显式 start 时 coverage_start 不被
    # 调用、该参数是死参——防坍缩语义由 Task 1 测试在 start=None 路径锁定
    return run_walkforward(wf, strategy, cost=cost,
                           risk=RiskState(wf.spec, enabled=False),
                           start=start, end=end, min_amount_wan=None)


def tier1(wf, start, end, data_root) -> tuple[list[str], list[str]]:
    errors = manual_cross_check(wf, data_root, CROSS_WEEKS)
    lines = ["## Tier-1 引擎锚（描述性，不判定）", "",
             "| 策略 | 逐年 α vs SPY（毛口径，执行周归年） | 均值 |",
             "|---|---|---|"]
    t_rows = list(range(start, end))
    bench_annual = annual_group_returns(
        [exec_iso_year(wf.fridays[t]) for t in t_rows],
        np.array([wf.bench_300[t] for t in t_rows]))
    for name, strat in [("L0 动量 k=3/lb=1", momentum_topk),
                        ("等权年再平衡", EqualWeightAnnual())]:
        res = _run(wf, strat, start, end, cost=ZERO)
        ann = annual_group_returns(
            [exec_iso_year(wf.fridays[t]) for t in res.t_rows], res.weekly)
        al = alpha_vs_paper(ann, bench_annual)
        mean_a = float(np.mean(list(al.values())))
        lines.append(f"| {name} | " + " ".join(f"{y}:{al[y]:+.1%}" for y in sorted(al))
                     + f" | {mean_a:+.1%} |")
    lines.append("")
    lines.append("SPY（TR 代理，执行周归年）逐年: "
                 + " ".join(f"{y}:{v:+.1%}" for y, v in sorted(bench_annual.items())))
    return errors, lines


def mimo_cell(wf, window: int, start, end, limit_weeks=None) -> dict:
    stop = end if limit_weeks is None else min(end, start + limit_weeks)
    years_run = sorted({int(wf.fridays[t][:4]) for t in range(start, stop)})
    models: dict[int, MIMOModel] = {}
    for y in years_run:
        # 计划评审 C-3：训练集扫全帧（受 stop 约束兼容 --limit-weeks）——start
        # 是 2012 首周，y-1（如 2011）的训练周在 start 之前，必须向前扫
        train_ts = [t for t in range(0, stop)
                    if int(wf.fridays[t][:4]) == y - 1]
        if train_ts:
            models[y] = MIMOModel(window=window).fit(wf, train_ts[-1])

    def make_strat():
        # 计划评审 I-8：毛/净两次运行各持独立 ROCState——ROC 对 =
        # (预测, 已实现标签) 与成本无关，独立状态保证两跑信号逐位一致
        roc = ROCState()

        def strat(wf_, t):
            y = int(wf_.fridays[t][:4])
            return models[y].select(wf_, t, roc=roc) if y in models else {}

        return strat

    res = _run(wf, make_strat(), start, stop, cost=ZERO)
    res_net = _run(wf, make_strat(), start, stop, cost=REF2BP)
    years = [exec_iso_year(wf.fridays[t]) for t in res.t_rows]
    ann = annual_group_returns(years, res.weekly)
    ann_net = annual_group_returns(years, res_net.weekly)
    bench_annual = annual_group_returns(
        years, np.array([wf.bench_300[t] for t in res.t_rows]))
    al = alpha_vs_paper(ann, bench_annual)
    al_net = alpha_vs_paper(ann_net, bench_annual)
    by_year: dict[int, list[float]] = {}
    for y, r in zip(years, res.weekly):
        by_year.setdefault(y, []).append(float(r))
    sharpe_years = {y: (float(np.mean(v)) / float(np.std(v)) * np.sqrt(52)
                        if np.std(v) > 0 else float("nan"))
                    for y, v in by_year.items()}
    return {
        "annual": ann, "alpha": al,
        "mean_alpha": float(np.mean(list(al.values()))),
        "median_alpha": float(np.median(list(al.values()))),
        "pos_years": sum(1 for v in al.values() if v > 0),
        "net_alpha_mean": float(np.mean(list(al_net.values()))),
        "net_cagr": res_net.metrics["cagr"],
        "sharpe_years": sharpe_years,
        "sharpe_mean": float(np.nanmean(list(sharpe_years.values()))),
        "cagr": res.metrics["cagr"], "maxdd": res.metrics["max_dd"],
        "win_rate": res.metrics["win_rate"],
        "avg_positions": (sum(len(tr["holdings"]) for tr in res.trades)
                          / max(len(res.trades), 1)),
        "weeks_with_positions": sum(1 for tr in res.trades if tr["holdings"]),
        "n_weeks": len(res.trades),
    }


def main(argv: list[str]) -> int:
    limit = None
    if "--limit-weeks" in argv:
        limit = int(argv[argv.index("--limit-weeks") + 1])
    wf = build_frame()
    start, end = year_bounds(wf)
    # 自检（提案 §9，计划评审 I-4）：全窗 valid==11 + SPY 锚点带——缩宇宙/数据
    # 漂移必须硬警报，静默通过即重演设计评审 C-1
    assert (wf.valid[start:end].sum(axis=1) == 11).all(), "宇宙缩水：valid≠11"
    spy_annual = annual_close_returns(
        _read_rows(US_DATA / "market" / "series" / "SPY.jsonl"))
    anchor_errs = check_anchors(spy_annual, SPY_ANCHORS)
    assert not anchor_errs, anchor_errs
    report = ["# US 复现报告（SSRN 4280640 × 自研引擎）",
              "", f"预注册配置：{PREREG_CONFIG}", ""]
    errors, t1 = tier1(wf, start, end, US_DATA)
    report += t1
    if errors:
        report += ["", "## [FAIL] Tier-1 锚未过，终止", ""] + errors
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
        print("\n".join(errors))
        return 1
    cells = {n: mimo_cell(wf, n, start, end, limit) for n in N_GRID}
    # 自检：三格不全等（sweep 纪律——window 必须真实注入）
    sigs = [tuple(sorted(round(v, 6) for v in c["alpha"].values()))
            for c in cells.values()]
    if sigs[0] == sigs[1] == sigs[2]:
        print("[FAIL] 三格结果全等——window 未生效")
        return 1
    # 最强格三级链（提案 §5 评审 I-4，计划评审 I-6）：α 均值 → 正年数 → N 小
    best = max(cells, key=lambda n: (cells[n]["mean_alpha"],
                                     cells[n]["pos_years"], -n))
    report += ["", "## Tier-2 MIMO 三格（毛口径主判定 + 2bp 净参考行）", "",
               "| 指标 | 论文 | " + " | ".join(f"N={n}" for n in N_GRID) + " |",
               "|---|---|" + "---|" * len(N_GRID)]
    rows = [("α 均值", "mean_alpha", PAPER["mean_alpha"], "{:+.2%}"),
            ("α 中位", "median_alpha", PAPER["median_alpha"], "{:+.2%}"),
            ("α 正年数", "pos_years", 10, "{}/11"),
            ("Sharpe 均值", "sharpe_mean", PAPER["sharpe_mean"], "{:.2f}"),
            ("CAGR", "cagr", PAPER["cagr_mean"], "{:+.2%}"),
            ("MaxDD", "maxdd", PAPER["maxdd_mean"], "{:.2%}"),
            ("胜率", "win_rate", PAPER["win_rate"], "{:.1%}"),
            ("周均持仓数", "avg_positions", PAPER["avg_positions"], "{:.2f}"),
            ("净α均值(2bp)", "net_alpha_mean", None, "{:+.2%}")]
    for label, key, pv, fmt in rows:
        paper_cell = fmt.format(pv) if (pv is not None and "{}" in fmt) else "—"
        report.append(f"| {label} | {paper_cell} | "
                      + " | ".join(fmt.format(c[key]) for c in cells.values()) + " |")
    for n in N_GRID:
        c = cells[n]
        report.append(f"\n**N={n}** 逐年 α（执行周 ISO 年）: "
                      + " ".join(f"{y}:{v:+.1%}" for y, v in sorted(c["alpha"].items())))
        report.append(f"N={n} 净口径(2bp)：α 均值 {c['net_alpha_mean']:+.2%} · "
                      f"CAGR {c['net_cagr']:+.2%} · 有持仓周 "
                      f"{c['weeks_with_positions']}/{c['n_weeks']} · 逐年 Sharpe "
                      + " ".join(f"{y}:{c['sharpe_years'][y]:.2f}"
                                 for y in sorted(c["sharpe_years"])))
        report.append(f"N={n} 判定: {verdict(c['mean_alpha'], c['pos_years'])}")
    report += ["", "## 总判定（最强格 N={best}，三级链 α 均值→正年数→N 小，三格全披露）".format(best=best),
               "", verdict(cells[best]["mean_alpha"], cells[best]["pos_years"]),
               "", "SPY 日历年 close-to-close（论文对照口径，评审 I-8）: "
               + " ".join(f"{y}:{spy_annual[y]:+.1%}" for y in YEARS if y in spy_annual),
               "", "## 口径与披露", ""]
    report += [f"- {d}" for d in DISCLOSURES]
    report += ["", "偏差清单与边界见提案 §4/§5（R20261106-02）。"]
    # 自检：config 注入断言
    text = "\n".join(report)
    assert PREREG_CONFIG in text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    print(f"best N={best}: {verdict(cells[best]['mean_alpha'], cells[best]['pos_years'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: 单测绿 + lint + 全量回归**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python -m pytest tests/test_sr_repro.py -v && conda run -n Quant-3.11 python -m ruff check tools/sector-rotation/repro_paper.py tests/test_sr_repro.py && conda run -n Quant-3.11 python -m pytest tests/ -q
```

- [ ] **Step 5: 冒烟（预注册 commit 已在 Task 5 完成，可以跑真实数据）**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python tools/sector-rotation/repro_paper.py --limit-weeks 26
```

Expected: Tier-1 锚全绿（手验 0 错、SPY 逐年收益表打印）；2012 模型经全帧扫描训练于 2010-2011（C-3 修复后 `--limit-weeks` 下也有模型），三格 26 周内各自出数且不全等。若 MIMO 全程零持仓 → 看报告 `weeks_with_positions`，确认非数据问题后如实继续（论文弃权机制下周均仅 2.25/11，短窗零持仓不必然是 bug；全窗仍零持仓须回查 `_confident`/阈值分布再定）。

- [ ] **Step 6: 全窗复现运行**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python tools/sector-rotation/repro_paper.py
```

Expected: `output/sector-rotation/2026-11/us-repro-2026-11-06.md` 生成，含 Tier-1 锚表 + 三格全表（毛+净）+ SPY 日历年对照 + 口径披露 + 判定域归类。**把报告里的关键数字（三格 α 均值/正年数/总判定）原样带回给用户，不加工不择优。**

- [ ] **Step 7: Commit**

```bash
git add tools/sector-rotation/repro_paper.py tests/test_sr_repro.py
git commit -m "feat(sector-rotation): repro_paper——Tier-1引擎锚+Tier-2 MIMO三格对论文Table 3并排"
```

（报告文件在 `output/`，gitignore 不入库，数字进 Task 7 的提案/spec 文本。）

---

### Task 7: 结案——结果落档 + spec §3.8 第 10 条草案（v1.2.7）

**Files:**
- Modify: `workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md`（§12 结果段 + status）
- Modify: `workspace/proposals/2026-11-05-sector-rotation-design.md`（§3.8 第 10 条草案 + 版本 v1.2.7 注记 + §6.3 结案行）
- Modify: `workspace/review-queue.md`（Q-20261106-05 补执行注记；新增第 10 条追认 + EXP 沉淀候选行）
- Modify: `workspace/meta/active-context.md`（断点行）
- Modify: `/Users/berton/.zcode/cli/memories/projects/ai-workspace-hub-a8dbddb2b73685dc/memory/sector-rotation-proposal.md` + `MEMORY.md` 对应行（若指针行文本需更新）

**Interfaces:**
- Consumes: Task 6 报告的真实数字（`output/sector-rotation/2026-11/us-repro-2026-11-06.md`——计划评审 M-2：路径无 `/06` 段）。
- Produces: spec v1.2.7 §3.8 第 10 条（草案，pending 用户追认）。

- [ ] **Step 1: 提案结果段 + status**

`2026-11-06-sector-rotation-us-reproduction.md` 追加 `## 12. 结果（U8 结案）`：三格 α 均值/中位/正年数全表（毛+净口径行）、总判定域（A/B/C）、Tier-1 锚结果、SPY 日历年对照、与论文 Table 3 并排对照（引用报告数字，逐字不加工）、偏差对结果的可能影响一段。frontmatter：

```
status: closed-<A|B|C>（复现运行完毕；spec §3.8 第 10 条草案待追认，queue 编号执行时以实读为准）
```

§11 追加 U7/U8 两行（commit 哈希执行时回填）。

- [ ] **Step 2: spec §3.8 第 10 条草案 + §6.3 结案行 + 版本注记**

`2026-11-05-sector-rotation-design.md`：
- 头部版本注记追加一行：`- v1.2.7（2026-11-06）：§3.8 第 10 条草案——美股域窗口状态（R20261106-02 复现结案，待追认）`；
- §3.8 第 9 条之后追加：

```
10. **美股域窗口状态（v1.2.7 草案，待追认，R20261106-02 结案）**：美股 11 行业 ETF 域经第 8 条新宇宙路径重开——2009-01→2022-12 区间已被复现性探索诊断消费（引擎验证 + 论文复核，无确认性消费）；尾段 2023-01→now（≈200 周、逐周增长）保持处女，为美股域确认窗候选。确认性重开触发（与第 9 条同构，三者同时满足方可提请拍板）：(a) 确认窗实测 ≥100 周（现已满足）；(b) 候选信号族+超参+判据已在提请前冻结落档（防选择过程二次污染）；(c) 用户显式拍板。追认前美股域一切研究默认第 8 条纯探索。
```

- §6.3 追加结案行（列结构同表内其他行）：`2026-11-06：US-复现结案（R20261106-02）——判定 <A|B|C>：三格 α 均值 <逐字填>；详见 output/sector-rotation/2026-11/us-repro-2026-11-06.md 与提案 §12`。

- [ ] **Step 3: review-queue + active-context + memory**

- `workspace/review-queue.md`：Q-20261106-05 行尾追加执行注记（预注册 commit 与复现 commit 哈希、判定域结论）；新增两行 pending——第 10 条追认行（编号取 queue 实读的下一个空闲号，计划原文预写的 Q-20261106-06 若被并行会话占用则顺延，对象 `spec §3.8 第 10 条草案 v1.2.7`）、EXP 沉淀候选行（若结果有可沉淀发现：A=论文可复现性的正样本 / B=全样本调参嫌疑证据 / C=引擎无罪证据链——按实际判定写，对象 `wiki/explorations/（候选）us-sector-rotation-paper-repro`，状态 pending）。
- `workspace/meta/active-context.md`：「最近对话延续」段顶追加一行断点（格式同既有行：`- **2026-11-06：美股域复现执行完毕（DONE，判定 X）** -> ...锚点：第 10 条追认 + EXP 沉淀确认`）。
- memory：`sector-rotation-proposal.md` 末段追加本轮结论一句（判定域 + 窗口状态 + 尾段处女）；`MEMORY.md` 对应行 hook 若需同步（只改一行文本）。

- [ ] **Step 4: 验证文档一致性 + Commit**

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda && conda run -n Quant-3.11 python - <<'EOF'
from pathlib import Path
spec = Path("workspace/proposals/2026-11-05-sector-rotation-design.md").read_text(encoding="utf-8")
assert "10. **美股域窗口状态" in spec
assert "v1.2.7" in spec
assert "标签=执行窗 open→close" in spec and "trailing 52" in spec   # 预注册行仍在（M-4 结案侧互锁）
prop = Path("workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md").read_text(encoding="utf-8")
assert prop.count("## 12. 结果") == 1 and "closed-" in prop
print("closure docs ok")
EOF
git add workspace/proposals/2026-11-05-sector-rotation-design.md workspace/proposals/2026-11-06-sector-rotation-us-reproduction.md
git commit -m "docs(sector-rotation): US复现结案——结果对照与spec §3.8 第10条草案（v1.2.7）"
```

（`workspace/review-queue.md`/`active-context.md` 是 gitignore 实例文件，不入库；memory 在仓库外。）

---

## Self-Review 记录（Rebase 后重写，2026-11-06）

1. **Spec 覆盖（对 draft-rev1 提案逐节）**：§2 窗口纪律 → GC 6 + Task 6 `year_bounds` assert；§3 论文配置 → Task 4 常量 + Task 6 驱动（α 双口径、净参考行）；§4 **九条偏差** → ①等权（Task 4 docstring/预注册/PREREG_CONFIG）、②年冻结（Task 4 + Task 6 mimo_cell）、③风控不实现（Task 6 `RiskState(enabled=False)` 裸路径=唯一路径）、④N 网格（Task 6 N_GRID 三格全披露）、⑤损失公式（Task 4 fit）、⑥含 t 特征窗（Task 1 include_t + Task 4）、⑦标签 open→close（Task 4 fit 标签源 = `weekly_gross_returns` + valid 掩码；预注册三载体）、⑧seed（Task 4）、⑨trailing-pairs ROC（Task 4 `ROCState`/`thresholds_from_pairs` + Task 6 `make_strat`）；§5 判定域 → Task 6 `verdict` + 三级链 tie-break + `exec_iso_year` 归年；§6 U2/U3 → Task 2/3；§7 **六行参数化** → Task 1（1 corrupt_threshold / 2 min_universe / 3 min_amount / 5 pick_bypass_single / 6 include_t；第 4 行「backtest.py 不动」= 文件结构声明）；§8 → Task 4；§9 U4-U8 → Task 1-7 一一对应（含自检纪律四项：注入断言/三格不全等/SPY 锚点/valid==11）；§10 预注册 → Task 5 六行逐字。
2. **计划评审（repro-plan-review）覆盖**：C-1 标签（Task 4/5/6 三载体改 open→close）、C-2 ROC（ROCState 跨年共享 + select 回填协议 + 测试重写）、C-3 训练集全帧扫描（Task 6 mimo_cell）、I-1 `pick_bypass_single` 改形（Task 1 签名/测试/实现 + 帧级 valid 测试）、I-2 bench_annual（Task 6 以 exec-year 键派生，结构性消除）、I-3 make_strategy 直接 raise（Task 4）、I-4 valid==11 + SPY 锚点断言（Task 6 main）、I-5 B 文案并列归因（Task 6 verdict + 测试）、I-6 三级 tie-break（Task 6 + 预注册 token）、I-7 执行周归年 + SPY 日历年列（Task 6 exec_iso_year/annual_group_returns/报告）、I-8 2bp 净参考行（Task 6 双跑独立 ROCState）、M-1 yfinance 陈述（头部 + Task 2 Step 5）、M-2 路径（Task 7）、M-3 本 Self-Review 重写、M-4 预注册 token 互锁（Task 5/6/7 三处断言）、M-5 死变量/`__import__` 清理（Task 4 边界测试重写）、M-6 check_anchors 缺失年报错（Task 2）、M-7 披露句（Task 6 DISCLOSURES 六条，复查轮 N3 增至七条）。全部 18 项有落点。
3. **代码完整性**：Task 6 代码 Rebase 后**无草稿残留**——原计划的两处占位（sharpe_years 推导/半吊子断言）与评审新发现的 bench_annual bug 已在正文中修净（逐年 Sharpe 真实推导 + `n_weeks` 字段 + 干净的三格检查）；Task 2/4 代码完整可落地。
4. **类型一致性**：`min_amount_wan: float | None`（portfolio/walkforward 同名同型；universe 的金额闸门不再参数化——bypass_single 只加 bool）；`include_t: bool = False`（weekly 定义 = models/测试消费）；`MIMOModel.fit(wf, t_train)`/`select(wf, t, *, roc=None)` 与 Task 6 `make_strat` 闭包、测试调用一致；`annual_group_returns(keys, weekly)`/`exec_iso_year(friday)`/`verdict(mean, pos)` 在测试与实现同签名；`ROCState` 为唯一跨周状态载体（模型/驱动/测试共用一个定义）。
5. **已知边界**：`test_mimo_learns_alternating_regime` 夹具已按 open→close 标签重造（lab_ret 偶数周为正 + 决策偶数周），若种子敏感只调夹具不调超参（Task 4 Step 4 注记）；`--limit-weeks` 冒烟下 `years_run` 只含 2012，三格由全帧训练的不同 window 产生差异（C-3 修复的连带验证点）。
6. **复查轮修订（2026-11-06，报告「复查轮」章节）**：原 18 项 18/18 核销；新发现 8 项已全部修入，修复限于复查清单范围（裁决：免再复查）——N1 Task 2 夹具补 2019 基准行（防 KeyError 诱导错改实现语义）、N3 `year_bounds` 加 `exec_iso_year ≤2022` 过滤 + GC 6/披露句同步（2023-W01 尾段越界与 α 字典 12 键双向消除）、N2 Task 1 Step 2 期望改 6F+1P（bench_symbol 现状回归锁）、N4 括注改「保持现状签名与默认值」、N5 `_roc_threshold` 夹具扩 10 对（Youden 主路径真实命中）、N6 三处 token 统一 `seed=20261106`（与提案 §10 逐字一致）、N7 `_run` 删死参 `min_universe=5`、N8 删未用导入。
