---
review_of: docs/superpowers/plans/2026-11-05-sector-rotation-p0-p2.md
review_target_version: 82017af（初稿 be9ca7c + 对齐 spec v1.2 重写）
review_range: c10dde2..82017af
date: 2026-11-05
result: with-fixes
disposition: fixes-applied（2026-11-05 用户拍板「全修」：9C + 15I + spec S1-S4 补钉 + 一行级 Minor M1/M2/M4-M7/M9/M13 + M14；深层 Minor M3/M10-M12 记入计划 README 已知限制；处置明细见文末处置记录）
spot_checked: C1/C2/C3/C6/C8 五条 Critical 已由主会话逐行复核属实
---

# 评审报告：《板块轮动 P0-P2 实施计划》（effort=max）

评审方式：spec v1.2（268 行）与计划 HEAD 全文（2580 行，T1-T15 逐任务逐行）各完整通读一遍；diff（be9ca7c→82017af，+1070/−906）用于确认 v1 口径清理情况；D 层事实全部在本仓库实测；两个统计/算术判断做了只读数值验证。主会话另对 5 条最承重 Critical（C1/C2/C3/C6/C8）逐行抽查复核，全部属实。

---

## Strengths

- **仓库事实引用准确率非常高（D 层实测 14 项中 13 项吻合）**：`mootdx_source._mootdx_call(method, **kwargs)`（mootdx_source.py:270）与 `log`（:41）签名一致；`upsert_series_rows(path, incoming, writer)`（market_data_io.py:177）调用方式正确；`data/sector/sector-list.json` 实测 1037 条、其中 `category=="二级行业"` 恰好 467 条（与 spec §3.1 逐字一致）；`data/sector/series/` 裸码命名 + `data/market/series/` 带后缀命名、amount 单位为元（9.2 亿量级实测）与计划的 1 亿/5000 万阈值算术一致；持久化 spec L284"800 上限 + start 分页（`k()` 已有实现）"引用行号精确；`tests/conftest.py → _test_paths.py` 目前只注入 daily-watch/podcast 路径，T1 L148 的预判和补法正确；分支名、根级 tests 命名惯例、review-queue 表格式、`data/`与`output/*` gitignore——全部与仓库现状吻合。
- **v1.2 重写干净**：diff 确认初稿的"L1 联合 softmax 版"等 v1 口径已删（82017af 中无 softmax/今日点差回填/全样本标准化残留）；"统计纪律三禁"（GC 8）在代码结构上有真实落点（`point_in_time_pick` / `standardize_fit_apply` 唯一标准化入口 / 簇代滞后窗），不是口号。
- **TDD 结构总体规范**：每任务失败测试先行且多为行为断言（T5 标准化手工数字对拍、T9 成本/截断手工可算、T12 可分性信号测试不许放松断言的执行注）；网络边界处理得当——T2 全 mock 单测 + 一次性真实冒烟分离，避免了 flaky。
- **预注册产物落点正确**：T3 Step 6 把预注册行写进 **spec 文档「实施记录」段**而非只留在计划里，且单独 commit，符合 spec §3.8 与 §5"每期结束追加实施记录"惯例。
- **对齐意识好的细节**：`bench_300` 用 open→close 与策略敞口窗口（周一开→周五收）一致，配对比较口径想对了；功效注释逐字进报告（GC 13 + POWER_NOTE）；闸门失败即停（GC 14）与 spec §5 一致；P3 定位与 spec 一致——T15 只交付工具并注明跟踪期纪律，不声称执行 8-12 周跟踪，无 scope creep。

## Issues

### Critical (Must Fix)

**C1. 点差两档口径错一半：基准档 roundtrip 12bp ≠ spec 的 22bp，spec 压力档（42bp）从未被测试**（T6，实现 L1171-1229、测试 L1193-1198；GC 9 文本 L23 与自身代码矛盾）
计划把 `spread_bps=10` 定义为"全宽点差，每边计半宽"（side=1+5=6bp，roundtrip=12bp）。但 spec §3.7 L161 明写"**单边点差**取基准档 10bp / 压力档 20bp"，§7 L238 给出算术"点差基准档**单边 10bp × 2** = **22bp**/周·全换手"。数值实测：计划 base roundtrip=12bp（= spec 基准档的 55%），计划 stress roundtrip=22bp（**恰好等于 spec 的基准档**）。后果：所有闸门 p 值建立在被削弱的成本上，"成本后存活"这一项目核心命题的判定经济学错误；计划自己的 GC 9 文本（"单边点差基准档 10bp"）与 cost.py 互相矛盾。附带内部矛盾：T9 L1540-1544 roundtrip 测试期望收 12bp、实现只收 6bp（见 C5 的计费结构），该"确认通过"步骤必失败。**修法**：`CostModel` 语义改为 side_bps = commission + spread_bps（10/20 即单边成本），测试用 spec §7 的 22bp/42bp 对拍。

**C2. block bootstrap 未在 H0 下重定心，p 值恒 ≈0.5，检验矩阵第 2-4 行全体失效**（T10 L1844-1861；自带测试 L1739-1744）
算法直接数"重抽均值 ≥ 观测均值"的比例，而重抽分布中心就是观测均值，p 数学上收敛到 ~0.5。数值验证（本机复现计划算法）：真均值 +0.2%/周的数据 plan_p=0.455/0.501/0.545（正确重定心版为 0.018/0.010/0.002）；负均值数据 plan_p=0.443（正确定心版 1.000）。计划自带测试 `assert p < 0.1` 必然失败——执行者若"改测试凑绿"，vs 等权 / vs 沪深300 / vs L0 三行闸门全部形同虚设。**修法**：对 `diff - mean` 重抽、p = P(boot_mean ≥ obs_mean)，并补"均值<0 → p>0.1"的负例测试。

**C3. `backfill.py indices`（881 全集 × 10 年深回补，T2 的核心使命）在 15 个任务的命令清单里从未出现，会静默降级到 2023-07 起的 802 根浅数据**（T2 Step 5 L488-497 只跑 `etfs`；T3 Step 5 L782-789 只跑 build_universe + `etfs`；CLI 定义在 L452/L461 但无执行步骤）
后果链：簇代 2017-2021 因 `<40 交易日` 全部被跳过（同簇约束全程失效且 binds=0）、coverage 曲线 2017-2022 全为 0%、T11 闸门在 ~2.4 年数据上跑、spec §8-5"881 历史深度首查项"与 P0 出口的"881 历史深度"检查实际不会发生——且**没有任何验收步骤会报错**（POWER_NOTE 硬编码"约 370 周"，晚于 2019-06 的功效重估无步骤，见 C9）。**修法**：T2 Step 5 增加 `backfill.py indices` 全量跑（含时长预算：467 × ~4 页串行 RLock、失败重跑语义）+ verify 深度直方图验收门槛；T3 前置依赖显式写明。

**C4. vs 沪深300 行的基准周收益错位数年**（T11 L2016-2018：`wf.bench_300[1:1 + len(main_res.weekly)]`）
`weekly[j]` 对应决策帧行 t_j ≥ coverage_start（还可能跳过无效周），而 bench 切片固定从行 1 开始。coverage start 在 point-in-time 口径下几乎必然在第 100+ 周（行业 ETF 供给 2019 后才起量）——基准周序列与策略周序列错开两三年，配对 block bootstrap 的输入整体错位，该闸门行结论无效。**修法**：`run_walkforward` 返回每周对应的 t（或 fridays），配对用 `bench_300[t_j]`。

**C5. simulate_week 每周按 (卖出总额+买入总额)×side 计费，无重叠豁免；等权对照被每周收取 ~12bp 幻影成本，且未按 spec 年再平衡**（T9 L1643-1645；T8 L1411-1413；spec §3.8 L168 对照①"**年再平衡**、随宇宙时变"；spec §7 L238 明确按重叠率口径"周换手率 ~80-90%"）
持仓完全不变的等权组合每周也被收 2×side ≈ 12bp（计划口径）≈ 6%/年拖累——vs 等权闸门行系统性偏向策略；同时 L0 持仓重叠周也被多收成本，违背 spec §3.7"每笔成交计"的逐笔语义和 §7 的重叠率精算口径（该口径 spec 明说"P1 精算"）。**修法**：成本按净换手计（逐资产 |w_new − w_prev| 的单边和）；等权对照实现为年再平衡（每年首周调到目标权重、其余周持有）。

**C6. render_report 硬编码 `("L0", row, tier)` 键，L1/L2 报告检验矩阵全空、闸门恒"未通过"**（T11 L1968 与 L1972-1974 写死 `"L0"`；main() 却以 `tests[(args.level, ...)]` 写入 L2014/2019/2022）
T14 Step 5（L2442-2446）真实跑 L1/L2 时，矩阵单元格全为"—"、`ok` 因缺键恒 False → 每份 L1/L2 报告都打印"**未通过，按 spec §5 停止**"。T11 单测只构造 L0 键路径，测不出来；若执行者照读闸门，P2 会被错误终止。**修法**：`render_report` 增加 level 参数；补 L1 键路径单测。

**C7. T15 周信号工具在真实场景必然输出空集，且自带测试与 fixture 自相矛盾**（L2509-2521；`toy_wf` 的 `valid[-1]=False` 在 L2119/L2136，测试却断言 `len(sig["buy"])==1` L2478-2482）
`WeeklyFrame.valid` 要求执行周（下周一开、下周五收）三价齐；周五盘后出信号时执行周尚未发生 → 最后一个决策帧（正是信号帧）valid 全 False → `momentum_topk`/L1/L2 的 `_valid(wf,t)` 为空 → buy 恒空。P3 工具的核心用例（当周出下周信号）不可用；其单测按当前 fixture 也必失败。**修法**：拆"决策期 valid"（point-in-time pick 存在 + 指数收盘齐）与"执行期 valid"（三价齐）两个口径，`build_signal` 用决策期口径；fixture 同步修正。

**C8. T1/T9 簇代测试与实现互相矛盾，且"让测试过"的自然修法会引入 v1.2 明令禁止的当年收益泄漏**（T1 测试 L134-138 vs 实现 L235-238；T9 L1514-1520 默认 friday "2020-01-03"）
实现 `cluster_for` 按 `g+2 ≤ 年`（= spec"t 时点用 t-2 至 t-1 年收益"）是**正确**的；测试却假设 g+1 年可用（2020-06-05 期望 2019 代、2022-01-07 期望 2021 代；按实现分别得 None 和 2019 代）——两个任务的"确认通过"步骤必失败。危险在于：照测试改实现（改成 `g+1 ≤ 年`）= 在 t 年使用含 t-1 当年收益的簇，**正是 spec I-4 明令禁止、本计划 GC 8 第三禁承诺的泄漏口径**。**修法**：修测试不修实现（2022-01-07 应期望 2019 代 c-a/c-b；T9 cap 测试的 friday 改用 ≥2021 年日期）。

**C9. 确认性检验的"样本外边界"机制缺失：闸门周集合 = 从 coverage_start 起的全部周，预注册选择窗可能被计入检验；spec 的"起点晚于 2019-06 → 功效重估并记入实施记录"无任何落点**（T10 L1784-1814 无 OOS 参数；T11 main 无 --oos-start；POWER_NOTE L1944 硬编码"约 370 周"；GC 12 L26 承诺"样本外只对预注册配置做一次确认性检验"但引擎无法兑现）
若 coverage_start ≤ 2019：预注册网格选择所用的 2017-2019 周同时进入闸门检验（选择偏差泄漏进确认性检验）。若 coverage_start > 2019-06（按行业 ETF 供给史更可能）：整窗即样本外、污染有限，但 spec 强制的功效重估（样本外年数缩短、370 周注释失效）没有任何步骤执行，结案报告会带着错误的功效声明。两个分支都伤闸门有效性。**修法**：walkforward/backtest 增加 OOS 起点参数（= max(2019-06 首周, coverage_start)，实际起点写进报告与 spec 实施记录）；POWER_NOTE 按实际周数动态生成。

### Important (Should Fix)

**I1. T3 Step 6 预注册网格无法机械执行**（L791-794）：选主配置要"结合 L0 训练/验证段网格 {k}×{方向}×{N} 只看样本外前数据"，但回测引擎 T10/T11 此时还不存在——T3 时点要么无据拍脑袋、要么推迟，二者都违反预注册时序协议。**修法**：预注册挪到 T11 内两段式（先 `--exploratory` 跑样本外前窗口选配置 → 单独 commit 预注册行 → 再跑确认性），或 T3 附带最小 L0 网格脚本。

**I2. §3.6 风控参数表 6 条只实现 4 条**（T9 L1575-1623；GC 11 L25 承诺全部）：缺"组合自年内高点回撤 ≥8% 降半仓至新高"与"组合绝对亏损 10% 全停"。风控缺失直接改变被检验策略的收益路径。**修法**：RiskState 增加 nav/回撤状态（由 walkforward 层传入或回传）。

**I3. N 口径混淆 + spec N 网格 {8,13,26,52} 消融缺失**：T3 L793 的 `{N∈1,4}` 与 T11 L1986 `--lookback choices=[1,4]` 是计划自创的 L0 动量排名回看期，与 spec §3.3 L114 的特征窗 N 网格 {8,13,26,52} 是两个参数；L1/L2 固定 `window=13`，15 个任务没有任何一步跑 spec 要求的 N 超参网格消融（"超参网格……消融报告"）。**修法**：参数改名区分（lookback vs window）；T12/T14 加 window 网格（标探索性）。

**I4. L1 只实现联合 multi-label 版，漏 spec §3.4 L123 的"①每行业独立 sigmoid+BCE"**（T12 L2078-2087）。**修法**：`make_strategy` 增加独立版变体（两者都跑、都标对照）。

**I5. ROC 动态阈值口径偏差**（T13 L2287-2289/L2371-2384/L2399）：spec §3.4 L130 要求"trailing **预测-标签对**、窗口滚动 **52 周**、每周重估"；计划用 104 周训练切片上的 **in-sample 拟合概率** 对训练标签求 Youden J。无未来泄漏（全部 ≤t），但窗口长度（104≠52）与预测来源（拟合值≠逐周实际预测对）双双偏离，而这是 v1.2 刚钉死的 I-4 口径。**修法**：维护 52 对逐周预测-标签环形缓冲，`thresholds` 从缓冲取。

**I6. n=1000 允许降 500 与 spec 冲突**（L1863 执行注 vs spec §3.8"置换 ≥1000 次 / bootstrap ≥1000 次"）。**修法**：删掉降档出口，改为只允许上调或如实报告失败。

**I7. 稳健切片整体降级为"手工分析动作"，无任务落点与验收**（Self-Review L2578 自认）：spec §3.8 的 2019-2021 结构牛 / 2022-2024 熊转极值 / 2024-09-24 脉冲段单独回放 / 动量崩溃段独立小表、**2023-07 口径漂移分段重跑 L0**（带"两段质变升级结案级风险"的裁决语义）、官方指数副口径探测（§8-7）全部没有步骤承接。裁决级分析不能靠"agent 手工切"。**修法**：T14 增加显式分析步骤（命令 + 报告模板 + 验收行）。

**I8. P0 review-queue 确认无停等与回灌回路**（T3 Step 6 L794 → T4 L805 起直接开工）：spec §5 P0 出口 = 宇宙清单与数据现实曲线**过** review-queue；T3 自己标注确认时要"人工补 KEYWORDS、校正双创 limit_pct、过目簇代表"，但确认后的修改没有任何"重跑 T3 Step 5 / 失效下游产物"步骤。**修法**：T3 末尾加停等，或 T11 前加"以 confirmed 配置重跑 build_universe"检查点。

**I9. 复权口径检查缺失**（spec §5 P0 出口明列"复权口径"；持久化 spec 也警告"不复权价、除权跳空保留"）：ETF 日线不含分红，除息落在周内的 open→close 收益会漏掉分红，40-60 只 × 9 年是系统性偏差；T2 verify（L422-434）只查行数/首末日期。**修法**：verify 增加除息检测（ETF 与指数同周跳变对拍）或至少在数据现实报告中量化除息事件数并声明偏差方向。

**I10. 探索性运行仍打印 P1 闸门判定**（T11 L1975 无 exploratory 分支；`--exploratory` 只改 prereg 字符串 L2028-2029）：探索性报告会出现"P1 闸门：**未通过，按 spec §5 停止**"字样，违反 spec"其余变体只报告不判定"，易被误读为确认性结论。**修法**：exploratory 时省略闸门行。

**I11. 策略协议自相矛盾：`strategy.select(wf, t)` vs 全体策略是普通函数/lambda**（T10 L1797；T8 普通函数、T11 L2001-2005 lambda 包装）：运行时 AttributeError，T10/T11 的"确认通过"步骤必失败。方向明确、修复一行，但说明计划代码没做过假执行。**修法**：统一 `strategy(wf, t)` 调用。

**I12. CLI 无 `--direction`，预注册字符串硬编码"方向=动量"**（T11 L1980-1992 参数表；L2028 硬编码；主策略固定 `L0-动量` L2012）：若预注册方向=反转，确认性检验无法按预注册执行。**修法**：加 `--direction {momentum,reversal}`，main_name 随之选择。

**I13. 跌停顺延简化偏离 spec §3.5 机制**（T9 执行注 L1651）：spec 要求"跌停顺延至下周一开盘卖，损益照记"；计划简化为周五一律按 close 结算。跌停周 close 被砸低、实际顺延卖价往往更低——恰好低估 spec 指定单独回放的 2024-09 式极端段损失。已披露为已知限制，但建议至少在压力档做顺延敏感性对照。

**I14. upsert 未持锁，违反持久化层"调用方负责持锁"惯例**（T2 L414-416 直接调 `upsert_series_rows`；仓库惯例是 `with series_lock(data_root, path.name)`，market_data_io.py:124 + update_market_series.py:118）：16:30 cron 并发写时可能交错。**修法**：run_backfill 内加 series_lock。

**I15. torch 安装时点后置**（spec §5 P0 内容含"PyTorch 环境探测与安装"；计划放 T12 Step 1 L2091-2097）：环境不可用要到 P2 才发现。**修法**：T1/T3 加探测步骤（import 试探即可，不必安装）。

### Minor (Nice to Have)

- M1. GC 2 "当前 465+16 用例"：实测 collect 465 ✓，"+16"来源无法验证。
- M2. `point_in_time_pick` 上市满 2 年用年份差近似（L654-655），差数日口径；建议注释声明。
- M3. coverage 曲线末年（2026）用 `12-31` 未来日期当"年末快照"（L748-751），实为部分年。
- M4. `EXCLUDE` 含"黄金"会误杀"黄金股 ETF"，而 KEYWORDS 有色行业明确想要"黄金股"（L601 vs L610 自相矛盾）。
- M5. T15 信号表 `name` 字段填的是指数名而非 ETF 名称（L2513）。
- M6. `TWO_YEARS_DAYS = 730` 死常量（L905）。
- M7. `cost_drag = cost_acc/gross_acc` 在毛收益为负时符号失真（L1812），spec 要求"占总毛收益比例"需特判。
- M8. 两档成本拖累以"·压力档"另起行呈现而非 spec §3.7"两档各一列"（T11 L2024-2027）——语义可达、形式偏差。
- M9. review-queue 追加未给 ID/七列格式细节（T3 Step 6），执行者需自行对照表头。
- M10. `window_blocks` 要求全体成员指数齐（L1130-1131）、`_prep` 要求 `valid[tj].all()`（L2187）：单一新行业缺史丢整帧，L1/L2 训练样本无谓减少。
- M11. ETF 全周停牌时 `etf_open` 取 wk+14 周一（L994/L1007），标签周错位未记录。
- M12. `limit_pct` 是 Member 单值，但候选集可同时含 10%/20% 涨跌幅 ETF（L723-724 粗判已声明人工复核）。
- M13. T2 无断点续传：重跑从 start=0 全量重拉（不跳过已够深的标的）；建议 fetch 前查现有深度。
- M14. L1 的升级闸门（四行两档）在 T14 跑了但没人"读"，升级纪律未显式化（部分源于 spec 自身分期含糊，见 S2）。

### 源于 spec v1.2 自身、不计入计划的问题

- S1. spec L181"判定点差档**各一个值**"与同节 L180"两档都须通过"内部歧义——计划记"判定档=基准+压力双档"是与后者一致的选择，但预注册字段语义 spec 就没钉死。
- S2. spec §5 P1 内容含 L1，但 P1 出口只闸 L0，L1 的升级闸门时点无归属——计划把 L1 后置到 T12-T14 源于此。
- S3. spec"起点降级→功效重估"没给重估方法（如何从 370 周的 5-7% 重算），计划 POWER_NOTE 硬编码部分源于此（但缺步骤本身是计划的 C9）。

## Spec 对齐矩阵（10 项 v1.2 机制 × 落点 × 状态）

| # | v1.2 机制 | 落点任务 | 状态 |
|---|---|---|---|
| 1 | §3.1 point-in-time ETF 映射 + 退市探测 + 逐年宇宙曲线 | T3 `point_in_time_pick` / T4 WeeklyFrame / T2 退市探测 / T3 coverage-curve | ✓（规模 proxy 已声明待验证） |
| 2 | §3.7 点差两档（10/20bp，闸门两档都过） | T6 CostModel + T11 两档渲染 + GC 9 | **偏差**：半宽 vs 单边口径，基准档成本被减半、spec 压力档从未测试（C1） |
| 3 | §3.8 检验矩阵（置换 ≥1000 / 配对 block bootstrap 块长 4 / 单侧 p<0.1 / L0 三行 L1·L2 四行） | T10 permtest + T11 渲染 | **部分**：结构/次数/块长 ✓；bootstrap 未重定心（C2）、bench 错位（C4）、L1/L2 键错位（C6）、n 可降 500（I6） |
| 4 | §3.8 变体预注册（P0 末写死、样本外一次确认性、其余探索性） | T3 Step 6 写入 spec 实施记录段 | **部分**：落点正确；但网格无引擎可跑（I1）、确认窗含选择窗（C9）、探索性仍打印闸门（I10）、无 --direction（I12） |
| 5 | §3.8 起点降级（覆盖率 ≥80% 首周；晚于 2019-06 重估功效） | T10 `coverage_start` | **部分**：起点规则 ✓；"晚于 2019-06 功效重估记实施记录"零落点（C9） |
| 6 | §3.8 指数口径漂移切片（2023-07 分段 / 官方副口径 / 同簇触发频率入指标） | 同簇频率 T7/T9 ✓；其余降级"手工动作"（L2578） | **缺失**（I7）：分段重跑与副口径探测无任务、无验收 |
| 7 | §3.3/§3.4/§3.6 三处泄漏口径 | T5 标准化 ✓；T1/T3 簇滞后 ✓（实现对、测试错 C8）；ROC trailing 52 周 | **偏差**：ROC 用 104 周训练切片 in-sample 对（I5） |
| 8 | §3.4 L1 双版无 softmax / 金融损失 detach | T12（BCEWithLogits+常数 R，detach 语义 ✓） | **部分**：只实现联合版，漏"①每行业独立 sigmoid"（I4）；增量更新改全量重训已披露 |
| 9 | §5 P0 出口数据现实曲线；P3 三条硬检查 | T2 verify + T3 曲线 ✓；P3 定位与 spec 一致 | ✓（P0 出口的缺行率/复权口径两项检查缺失 → I9、C3 附带） |
| 10 | §4 集成约定（目录 / conda / 可选依赖 / 不动 AGENTS.md） | 全局 + T1/T15 | ✓（torch 探测安装时点后置到 T12，I15，小偏差） |

A3 补充：§3.5 执行闸门进 T9 ✓（跌停顺延简化 I13）；§3.6 风控表进 T9 但缺 2 条（I2）；scope creep 基本没有（L0 lookback {1,4} 网格是唯一自创参数，I3）。

## 事实核对结果（D 层）

| 计划声称 | 实测 | 吻合 |
|---|---|---|
| `_mootdx_call(method, **kwargs)` 存在且 RLock 串行 | mootdx_source.py:270，`with _MOOTDX_LOCK` | ✓ |
| `log` 可从 mootdx_source 导入 | mootdx_source.py:41 `def log(message)` | ✓ |
| `upsert_series_rows(path, rows, writer="batch")` 签名 | market_data_io.py:177 `(path, incoming, writer)` | ✓（但缺 series_lock，I14） |
| sector-list.json 有 `category=="二级行业"` 467 条 | 实测 Counter：二级行业 467 / 行业概念 570，共 1037 | ✓ |
| `data/sector/series/` 裸码命名、字段结构 | 881001.jsonl 实测一致，amount 单位元 | ✓ |
| `data/market/series/` 带后缀命名 | 510300.SH.jsonl 存在，字段无 up_count | ✓ |
| 持久化 spec L284 = 800 上限 + start 分页 | 逐字吻合；frequency=9=日线一致 | ✓ |
| `index_bars`/`bars`/`stocks` 用法 | update_market_series.py 同款调用 | ✓ |
| tests/conftest.py 需补 tools/sector-rotation 路径 | conftest → _test_paths 只注入 daily-watch/podcast | ✓（计划已预判） |
| "当前 465+16 用例" | pytest --collect-only 实测 465 | 部分（"+16"未验证） |
| 分支 feat/sector-rotation-design | 一致 | ✓ |
| data/ 与 output/ gitignore | .gitignore:45-46，check-ignore 命中 | ✓ |
| review-queue 追加惯例 | 表格式相容 | ✓ |
| ruff 规则集 E4/E7/E9/F | 无配置文件 → 默认即此集 | ✓ |
| conda Quant-3.11 可用 | 沙箱无执行权限，未验 | 未验 |

主会话五条抽查（C1 CostModel 半宽注释+测试断言 / C2 未重定心算法逐行 / C3 indices 零调用 grep / C6 硬编码 "L0" / C8 测试 g+1 vs 实现 g+2）——全部属实。

## Recommendations

1. **执行顺序**：先修 C1+C5（成本与换手语义，牵动 T6/T8/T9/T11 的测试数字，越晚改返工越大）→ C2（统计正确性）→ C3（补 `backfill.py indices` 步骤与验收，这是 P0 的根）→ C4/C6（T11 对齐与渲染）→ C7（T15 valid 拆分）→ C8（只修测试）→ C9（OOS 边界 + 功效重估步骤）。Important 项可在对应任务执行时顺手处理，但 I1/I2/I7 建议随 Critical 一并改计划文本。
2. **预注册时序重排**（I1+C9 联动）：把"预注册"从 T3 Step 6 挪为 T11 内的两段式步骤——引擎就绪后先在样本外前窗口跑探索性网格、commit 预注册行、再跑一次确认性检验；这也让"样本外边界"必须先实现。
3. **写作流程改进**：本次发现 5 处"计划自带代码与自带测试互相矛盾"（C2、C7、C8、T9 roundtrip、I11），全部会在"Expected: PASS"步骤翻车——说明计划代码没做过假执行。建议 writing-plans 流程加一道"每个任务的实现代码与测试在本地做一次不落盘的逻辑自检（语法 + 测试断言 vs 实现行为推演）"。
4. P0 出口检查表显式化：spec 列的"缺行率、对齐、复权口径、881 深度、退市可得性"五项在 T2 verify 落成一张 checklist 报告（当前只有后两项）。
5. S1-S3 需在 spec v1.2 补钉（预注册判定档语义=两档都过、L1 闸门时点归属 P2 入口、功效重估的最小方法如"按周数线性缩放检出阈值并披露"），修计划时一并落。

## Assessment

**Ready to execute?** With fixes

**Reasoning:** 计划的仓库事实功底、TDD 骨架和 v1.2 对齐意图都是高水准，但 9 条 Critical 中 C1（成本档减半）、C2（bootstrap 统计错误）、C4/C5（基准错位与幻影成本）、C9（确认窗含选择窗）直接决定 P1/P2 闸门结论的有效性，C3 会让 P0 的核心深回补静默不发生——照计划原样执行会产出看起来完整但经济学与统计双错的闸门结论。先清 Critical（多数是局部修改，不动 15 任务骨架），本计划即可进入执行。

**处置状态**：~~pending~~ → **fixes-applied（2026-11-05 全修闭环）**。

## 处置记录（2026-11-05，全修）

修复落点 = 计划 v1.1（Self-Review 第 1 条含同一映射）；spec 补钉落 v1.2.1 §6.2。逐条：

| 项 | 处置 | 落点 |
|---|---|---|
| C1 | 已修：`CostModel` 改单边口径（side=佣金+点差 10/20 → roundtrip 22/42bp），测试对拍 spec §7 算术；GC 9 同步 | GC 9 / T6 |
| C2 | 已修：`paired_block_bootstrap` 对 `diff − obs_mean` 重抽（H0 重定心）+ 正/负例双测试 | T10 |
| C3 | 已修：T2 Step 5 补 `backfill.py indices` 全量跑（时长预算/幂等/验收门槛 ≥80% 标的 ≥2400 根）+ T3 前置显式化 | T2/T3 |
| C4 | 已修：`WalkResult.t_rows` 行号账本，配对一律 `bench_300[t_rows]` | T10/T11 |
| C5 | 已修：净换手计费（逐资产 \|Δw\| × side，引擎漂移调整）+ `EqualWeightAnnual` 年再平衡对照 + 持有过周末零成本测试 | GC 9 / T8 / T9 / T10 |
| C6 | 已修：`render_report(level=…)`，L1/L2 键路径入测试 | T11 |
| C7 | 已修：`dvalid` 决策期口径 + `build_signal` 经 `replace(wf, valid=dvalid)`；**附带修复** T4 fixture 日期区间盖不到决策周的同类矛盾（评审未列，修复中发现） | T4 / T15 |
| C8 | 已修：只改测试（g+2 口径三断言）+ T9 默认 friday ≥2021；实现未动 | T1 / T9 |
| C9 | 已修：`--oos-start`（默认 2019-06-01，与覆盖率 80% 首周取大）+ `--pre-oos` 选择窗 + `power_note(√(370/n))` 动态功效 + OOS 周数写报告与实施记录 | GC 12 / T10 / T11 |
| I1 | 已修：预注册挪 T11 两段式（阶段 A `--pre-oos` 网格 → 预注册行单独 commit → 阶段 B 确认性）；spec 补钉 S4 同步 | T3 Step 6 / T11 Step 5 / spec §3.8·§5 |
| I2 | 已修：`RiskState` 补年内回撤 ≥8% 降半仓（×0.5 持币式）与绝对亏损 ≥10% 全停，`nav` 由引擎传入 + 测试 | T9 / T10 |
| I3 | 已修：`--lookback`（排名回看）与 `--window`（特征窗 N 网格 {8,13,26,52}）分离；T14 网格探索性跑 | T11 / T12 / T14 |
| I4 | 已修：`LinearModel(variant="independent")` 每行业独立 sigmoid+BCE，T14 双版对照 | T12 / T14 |
| I5 | 已修：`thresholds_from_pairs`（trailing 52 对实际预测-标签，<26 回退 0.5）+ 有状态 `L2Strategy` 环形缓冲 | T13 |
| I6 | 已修：删降档出口，n=1000 为下限、超时报告失败并停 | GC 12 / T10 执行注 |
| I7 | 已修：T14 Step 5c 显式步骤——2023-07 分段（两段质变升级结案级风险 + review-queue 裁决）、结构段小表、脉冲段逐周回放、I13 顺延敏感性量化、官方副口径探测 | T14 |
| I8 | 已修：T3 Step 6 停等纪律（T4 前置 = confirmed + 修订后重跑） | T3 |
| I9 | 已修：`ex_dividend_scan`（单日跌 >5% 事件清单 + 偏差方向声明）入 verify | T2 |
| I10 | 已修：`exploratory` 分支省略闸门行，测试断言无闸门字样 | T11 |
| I11 | 已修：统一 callable 协议 `strategy(wf, t)`（含 T10/T15 调用点与全部策略实现） | T8/T10/T11/T12/T13/T15 |
| I12 | 已修：`--direction {momentum,reversal}`，main_name 与预注册串随动 | T11 |
| I13 | 部分修：README 已知限制 + T14 Step 5c 脉冲段顺延敏感性对照（保守变体损益差量化）；完整顺延实现仍留简化口径（已披露） | T9 执行注 / T14 / T15 |
| I14 | 已修：`run_backfill` 内 `with series_lock(...)`，锁冲突跳过可续传 | T2 |
| I15 | 已修：T1 Step 1 torch import 探测（装仍 T12） | T1 |
| M1/M2/M4/M5/M6/M7/M9/M13 | 已修：465 实测数 / 年差近似注记 / 黄金(?!股) / etf-names.json / 删死常量 / cost_drag nan 特判 / queue 七列模板 / 断点续传（并入 C3） | 对应任务 |
| M3/M8/M10/M11/M12 | 不修，记入 T15 README 已知限制（M8 已随两档双列呈现顺手修复） | T15 Step 4 |
| M14 | 已修：T14 Step 5a「L1 闸门先行」显式读取步骤；spec 补钉 S2 钉死时点 | T14 / spec §3.4 |
| S1/S2/S3/S4 | 已落 spec v1.2.1 §6.2（S4 = 预注册时点重排，源自本评审 I1/C9，超出原 S1-S3 清单） | 设计文档 §3.4/§3.8/§5/§6.2 |

主会话修复后自查：五类「实现-测试矛盾」残留清零（`strategy.select`/`bench_300[1:`/`spread_bps / 2`/`equal_weight(`/死常量 grep 全 0）；T10 测试 `equal_weight` 引用漏网一处已随改名收口。
