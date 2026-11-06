# R20261106-02 实施计划评审报告（max 档）

**评审对象**：`docs/superpowers/plans/2026-11-06-sector-rotation-us-repro.md`（1488 行，untracked）
**评审方式**：独立评审 subagent（计划逐段 vs draft-rev1 提案/设计评审报告/spec v1.2.6/T13 设计源四文件对差 + 内嵌代码逐行对靶引擎真实代码与 6 个测试文件夹具 + 论文数字核对 + 双环境 yfinance 实测 + 测试基线实跑）→ 主会话逐条复核（C-1/C-2/C-3/I-1~I-3/M-1 由协调者独立对靶计划文本、引擎代码与环境证实，其余条目证据行号齐全）。
**结论**：**Ready to execute? No——计划基于评审前的旧版提案撰写，在两项用户已拍板的方向决策（I-2 标签 open→close、I-7 ROC trailing-pairs）上反向落地，照执行会把被否决口径经 Task 5 预注册 commit 冻结进 spec §6.3；另有一处驱动 bug 使 2012 年全年空仓。须先按 Rebase 地图改写（核心 Task 4/5/6 + Task 1 第 5 处参数化改形）再开工。** 骨架、窗口纪律、参数化默认值与全部 API/夹具引用经实核质量很高——rebase 是定点手术而非推倒重来。

---

## Strengths（经复核属实）

1. **窗口纪律与流程顺序无违规**：消费窗硬编码 2012-01-01:2022-12-31、`--limit-weeks` 只缩短、终点 assert；Task 5 预注册 commit → Task 6 真实数据冒烟的先后关系显式声明，无「先跑后注册」隐藏路径。
2. **Task 1 参数化的「A 股默认零变化」逐项属实**（对靶实核）：`_corrupt_weeks` 0.30 / `coverage_start` min_universe=50 / `WEEKLY_MIN_AMOUNT_WAN=5000.0` / pick 10000 / `window_blocks` 默认分支——五个默认值=现硬编码值；`coverage_start` 另两个调用点（backtest.py:137、grid_probe_params.py:55）不传参，行为不变；`_torch()` 带默认值签名后 L1 调用点不动。
3. **工程事实层几乎无假引用**（全部实核存在且签名吻合）：`_frame(T, valid, etf_close, seed, *, idx=)`、`toy_wf(T, seed=)`、`_write/_etf_rows/_build`、两个 `_wf` 变体、`momentum_topk`/`EqualWeightAnnual`、`CostModel.base()`、`compute_metrics` 键 `cagr/max_dd/win_rate`、`WalkResult.trades` 的 `holdings` 键、`load_universe` 对 frontmatter 注释行的兼容、`market_data_io` 签名、conftest 的 sys.path 注入。
4. **论文数字与外部事实全部正确**：PAPER 字典与 spec §1.1-1.2 逐项一致；SPY_ANCHORS 四年带与 ^GSPC 2022 带对公开数字全部容纳（SPY TR 2013 +32.3 / 2018 -6.2 / 2020 +18.4 / 2022 -18.17；^GSPC 2022 -19.44）。
5. **fit/select 在计划自身口径内无泄漏且确定**：训练行过滤 `tj+1 ≤ t_train` 正确；`_mc_stats` 每次 select 前重置种子使年内逐周推断可复现；`_confident` 语义与测试断言一致。
6. **部分设计评审修复已正确落实**：I-1（include_t 参数化 + MIMO 消费）、I-3（verdict B=非A 且 α>0 分支）、I-6（`RiskState(spec, enabled=False)` 显式传入）、Task 3 宇宙清单与 draft-rev1 §6 一致。

## Issues

### Critical（Must Fix）

**C-1. 标签口径 = close-to-close——与用户 2026-11-06 追认的 I-2（执行窗 open→close）直接相反，且会被 Task 5 预注册冻结**
- 证据：计划 L732（接口）、L899-900（docstring 明写「非执行窗 open→close」——与追认决策反着写）、L937（`nxt = ic[tj_all+1]/ic[tj_all]` = 周五收→周五收）、L1032（Task 5 将写入 spec §6.3 的预注册行）、L1182（Task 6 `PREREG_CONFIG` 同文）。权威链：draft-rev1 §4 偏差 7 + §10 预注册行（「标签=执行窗 open→close ≥1%，2026-11-06 用户追认 A」）；spec §1.1 L38「不是周五收→周五收」。
- 为何要紧：Task 5 是预注册 commit——照执行，被用户明确否决的口径将冻结进 spec §6.3，此后一切改动构成「预注册后变更」；且标签与执行 PnL（`simulate_week` 的 etf_close/etf_open）不同口径，α 与论文 Table 3 不可比。
- 改法：`MIMOModel.fit` 标签源改 `weekly_gross_returns(wf)`（引擎原生 open→close）+ per-asset `wf.valid` 掩码；Task 4 docstring、Task 5 预注册行、Task 6 `PREREG_CONFIG` 三处以 draft-rev1 §10 行为准逐字改。

**C-2. ROC 阈值源 = 计划训练行 in-sample Youden（年冻结模型下全年恒定）——与用户追认的 I-7 相反，且计划完全没有 trailing-pairs 有状态机制**
- 证据：计划 L869-882（`_roc_threshold`「训练行概率」）、L902-903/L960-963（fit 一次算定 `self.thresholds`，年内只读）、L1032/L1183（入预注册行）。权威链：draft-rev1 §4 偏差 9 + §8（「trailing 52 对逐周实际预测-标签 Youden J、<26 对回退 0.5、有状态环形缓冲，T13 口径」）；T13 `thresholds_from_pairs` 明令「禁用训练窗 in-sample 拟合概率充数」（plan-2026-11-05 L2556-2567）。
- 为何要紧：同 C-1 的冻结问题；且「周周重估」在计划实现里机制性空转，弃权→买入结构系统性偏离论文机制。**不是文本替换能修**——`MIMOModel.select` 现无状态，需引入跨周 pairs 环形缓冲（`deque(maxlen=52)`）并改 Task 6 驱动协议（年首回退期与跨年模型混用为已披露项）。
- 改法：按 T13 `thresholds_from_pairs` + 环形缓冲重写；`select` 协议改「先回填上周 (预测, 已实现标签) 对再取阈值」；测试改 trailing-pairs 语义（跨周状态、<26 回退、maxlen=52）。

**C-3. Task 6 `mimo_cell` 年模型训练集为空——2012 年无模型、全年空仓，冒烟必 FAIL**
- 证据：计划 L1286-1291 `train_ts = [t for t in range(start, stop) if fridays[t]年份 == y-1]`，而 start=2012 首周（L1196-1200）→ y=2012 找 2011 周 = 空集 → 无 2012 模型 → 全年空仓（2012 α ≈ -SPY2012 ≈ -13~-16pp 进均值；论文 2012 α=-0.75%，恰是 Table 3 关键对照年）。连带：`--limit-weeks 26` 冒烟只覆盖 2012 → 三格全空仓 → alpha 全等 → L1343-1345 「三格全等」FAIL 误诊「window 未生效」——与 Step 5 Expected 自相矛盾。
- 改法：训练集扫描改全帧 `range(0, stop)`（受 stop 约束兼容 limit-weeks），`t_train` 取 y-1 年最后一个决策周五。

### Important（Should Fix）

**I-1. C-1 修复形态偏离批准设计：`pick_min_amount_wan=None` 只关金额闸门、保留 `min_list_years=2`；draft-rev1 §7 第 5 行是 `pick_bypass_single` 单候选旁路（两闸全关）**
- 证据：计划 L67/L200-221（保留年限检查）、L91-94（测试把「上市<2年仍拦」锁死）、L1193；draft-rev1 §7 第 5 行（L96）。后果（按引擎代码推演）：美股数据 2009-01 起以数据首日代理上市日 → 2009-2010 pick=None → 成员 invalid → **在 C-1 修复后的 open→close 标签下，2012 年模型有效训练标签从 104 行掉到 ~52 行**（计划当前 close-to-close 标签不受影响——两个错误互相掩护）；fit 按位置计数不 raise，静默质量损伤。
- 改法：参数化目标改 `pick_bypass_single`；测试改旁路语义；补 draft-rev1 §7 要求的「2012-2022 全窗 `wf.valid[t].sum()==11`」用例。

**I-2. Task 6 `mimo_cell` 的 `bench_annual` 草稿 bug——`list(bench)` 传 int 列表当 fridays，运行即 TypeError，且不在「两处草稿残留」清理清单内**
- 证据：计划 L1300；`annual_group_returns` 内 `int(f[:4])`（L1206）对 int 抛 TypeError。tier1 里同位置是对的（L1267-1268）。计划 L1386-1388 清理清单只列两处——第三处未被覆盖，Self-Review 又称「其余任务代码完整」，执行 agent 照抄即崩。
- 改法：改 `[wf.fridays[t] for t in bench]`；清理清单补第三处。

**I-3. Task 4 `make_strategy("L2")` 测试必失败——partial 构造时不抛错**
- 证据：L829-834 期望构造时 raise；计划只改 `_l2_select`（被调用才抛），`make_strategy` L2 分支返回 partial 不调用（models.py:132-135 实核）。
- 改法：`make_strategy` L2 分支直接 raise（文案含 "MIMOModel" 匹配测试）。

**I-4. repro_paper 自检缺 draft-rev1 §9 钉死的两项断言：全窗 `valid==11` 与 SPY 锚点核对**
- 证据：draft-rev1 §9 自检纪律（L120）「锚点断言（SPY 2022 收盘对齐）、全窗 valid==11 断言（评审 C-1）」；计划 main 仅有 config 注入 + 三格不全等 + 终点 assert。C-1 评审的核心教训就是「缩宇宙全链路无警报」。
- 改法：`build_frame` 后加 `assert (wf.valid[t0:t1].sum(axis=1) == 11).all()`（2012-2022 消费窗）+ SPY 2022 锚点带断言（复用 Task 2 函数）。

**I-5. 判定域 B 文案回退到旧版「论文全样本调参嫌疑」预指派**
- 证据：计划 L1220；draft-rev1 §5 B 行（L69）已修为「归因待分：偏差 1/2/3 消融 vs 全样本调参嫌疑，并列记录（不预指派）」。该文案随 verdict() 进复现报告与结案归因。
- 改法：B 文案改并列归因。

**I-6. 最强格 tie-break 只有一级——draft-rev1 钉死三级链「α 均值→正年数→N 小」**
- 证据：计划 L1346 `max(mean_alpha)`；draft-rev1 §5（L72）/§10（L130）三级链。`max` 先到先得凑巧偏 N=13 但缺中间级。
- 改法：显式三级比较（或 key=(mean, pos_years, -n)）；预注册行同步。

**I-7. α 口径两处未按 I-8/M-3 落地：无日历年对照列、年归属按决策周而非执行周 ISO 年**
- 证据：计划 `annual_group_returns` 按决策周五归年（L1203-1208）；draft-rev1 §3 基准行（L49）要求「判定=同周 open→close + SPY 日历年 close-to-close 并排披露」+ §5「年归属=执行周 ISO 年」。每年约 1 个跨年周会归错年；论文 Table 3 是日历年口径，无并排列则「并排对照」名不副实。
- 改法：归年键改执行周；报告加 SPY 日历年列（复用 Task 2 `annual_close_returns`）。

**I-8. 净口径 2bp 参考行承诺未兑现——`REF2BP` 定义后从未使用**
- 证据：L1180 定义；`_run` 硬编码 `cost=ZERO`（L1254-1258）；draft-rev1 §3 成本行（L50）与计划自己的预注册行都写了「+2bp 参考行」——自相承诺未兑现。
- 改法：`_run`/`mimo_cell` 参数化 cost，三格各跑 ZERO/REF2BP（或至少最强格补净口径行）。

### Minor（Nice to Have）

- **M-1** 头部 yfinance 环境陈述与实际相反：计划 L9 称「已装于 homebrew python3.11、Quant-3.11 需验证」；实测 Quant-3.11 **已装 1.2.0**、`/opt/homebrew/bin/python3` **未装**。
- **M-2** Task 7 输出路径多一段 `/06`（L1433 vs Task 6 OUT）。
- **M-3** Self-Review 声明失实：「无缺口」「偏差 8 条」——draft-rev1 已是 9 条偏差/§7 六行；实际缺口即 C-1/C-2/I-1/I-4~I-8。Self-Review 是执行 agent 的信任锚。
- **M-4** `PREREG_CONFIG` 与 Task 5 spec 行并非「逐字同源」（L1025 声称同源，两串独立手写、内容有差）——rebase 后让 Task 6 测试断言 token 包含关系或从 spec 读回比对。
- **M-5** `test_mimo_feature_boundary` 的 `m3`/`m1b` 死变量 → ruff F841（GC3 零告警会挂）；`__import__` 绕行写法改常规 import。
- **M-6** `check_anchors` 对缺失年静默跳过（`if y in annual`）——改「锚点年缺失直接报错」。
- **M-7** 报告模板缺 draft-rev1 指定的披露句：Good Friday 周定义注记（M-5）、MC T=20 选择依据（M-6）、8%=锚定折扣非推导（M-2）——补「口径与披露」小节。

## Rebase 工作量地图

| Task | 改动量 | 段落 |
|---|---|---|
| Task 1 | 中 | 第 5 处参数化改形 `pick_min_amount_wan`→`pick_bypass_single`（签名/实现/测试/调用点说明）；补 valid==11 用例；其余 4 处已核成立不动 |
| Task 2 | 小 | 头部 yfinance 陈述（M-1）；可选 check_anchors 缺失年报错（M-6） |
| Task 3 | 无 | 与 draft-rev1 §6 一致 |
| Task 4 | **大（重写核心）** | ①标签源 ic→`weekly_gross_returns`+valid 掩码（C-1）；②ROC→trailing-pairs 有状态机制（C-2，与 Task 6 驱动协议联动）；③docstring 偏差②⑦⑨改写；④`make_strategy` L2 raise（I-3）；⑤测试重写 3 个+新增 pairs 状态测试（`test_mimo_learns_alternating_regime` 夹具在 open→close 下与 idx 交替错位需重造）；⑥F841 清理（M-5） |
| Task 5 | 小/高意义 | 预注册行整段以 draft-rev1 §10 逐字替换（C-1/C-2/I-5/I-6/I-7 一并解决）；status 替换文本保留评审溯源 |
| Task 6 | **大** | ①训练集扫描全帧（C-3）；②bench_annual bug（I-2）；③执行周归年+SPY 日历年列（I-7）；④三级 tie-break（I-6）；⑤B 文案（I-5）；⑥2bp 参考行（I-8）；⑦valid==11+SPY 锚点断言（I-4）；⑧PREREG 同源+披露句（M-4/M-7） |
| Task 7 | 小 | 路径笔误（M-2）；B 归因文案随 I-5；预引用的 Q-20261106-06 编号顺延 |
| Self-Review | 重写 | 覆盖声明与计数改对（M-3） |

## Assessment

**Ready to execute?** **No**

**Reasoning**：计划把两项用户已拍板的方向决策（I-2 标签 open→close、I-7 ROC trailing-pairs）反向内嵌进 Task 4 代码、Task 5 预注册行与 Task 6 PREREG_CONFIG，照执行会把被否决口径 commit 进 spec §6.3 冻结（C-1/C-2）；加上 2012 年无模型的驱动 bug（C-3）使复现结果无效且冒烟即撞墙。必须先按 Rebase 地图改写（核心 Task 4/5/6 + Task 1 改形）再开工；窗口纪律、默认值不变性、API/夹具事实层经实核全部成立，rebase 是定点手术。

---

# 复查轮（Rebase 后，2026-11-06）

**复查对象**：本报告上述 18 项发现 + Rebase 地图，对靶 rebased 计划（1672 行，2026-11-06 20:48，计划作者会话已按地图全量改写）。
**复查方式**：独立复查 subagent（计划全文 vs draft-rev1 提案 + 引擎 8 文件现状 + 6 测试夹具现状 + ISO 边界解释器实测 + 调用点 grep）→ 主会话对全部新发现逐条亲自复核（N1 字典推导逐行推演、N3 日历事实与泄漏链推演、N2/N4 直接对靶 data.py/universe.py 现状签名、N6 与提案 §10 逐字 diff、N5/N7/N8 对靶计划代码），并对其唯一分歧视（N3 定级）做协调者升裁。
**结论**：**Ready to execute? Yes——先修 N1/N3 两处 Important 再开工**（修复限于下表范围则免再复查）；原 18 项 **18/18 已核销**，C-1/C-2 经机制级核验为真修复非文本替换。

## 18 项核销表（证据行号为 rebased 计划）

| 原编号 | 三态 | 关键证据 |
|---|---|---|
| C-1 标签 | 已核销 | fit 标签源 `weekly_gross_returns(wf)[tj]` + per-asset `wf.valid & isfinite` 掩码（L1026-1030）；行过滤 `tj+1≤t_train` 无泄漏（执行列经 data.py:141-142 预移位到决策行，weekly.py:10-13 同行 open→close）；三载体（Task 5 L1129 / PREREG L1306 / DISCLOSURES L1327）与提案 §4 偏差⑦/§10 一致 |
| C-2 ROC | 已核销 | 真状态机制：`ROCState`（deque maxlen=52，L963-977）+ `thresholds_from_pairs`（<26 回退 0.5、docstring 明令禁 in-sample，L945-960）+ select 回填协议（先入上周 (预测,已实现标签) 再取阈值，L1077-1082）+ 驱动闭包跨年共享（L1447-1456）+ 毛/净独立实例 + 测试语义重写（L781-795/L861-877） |
| C-3 训练集 | 已核销 | `train_ts = range(0, stop)` 全帧扫 y-1（L1442-1445）；2012 有模型，冒烟路径自洽（L1583/L1672 连带验证点） |
| I-1 pick 改形 | 已核销 | `bypass_single` 两闸门前直接返回（L206-219）；旁路/多候选不旁路/帧级 valid 三层测试（L80-91/L123-141）；真实数据 valid==11 断言 L1499（括注措辞失真见 N4，不影响行为） |
| I-2 bench_annual | 已核销 | 结构性消除：两处 bench_annual 均以 exec-year 键列表派生（L1417-1419/L1463-1464），全文无 int 当日期调用 |
| I-3 make_strategy | 已核销 | 构造时 raise 含 "MIMOModel"（L1091-1093）；`_l2_select` 删除安全（grep 无外部引用，backtest.py 走 `make_strategy(args.level)` 间接） |
| I-4 自检断言 | 已核销 | L1497-1503：`valid[start:end].sum(axis=1)==11` 全窗 assert + SPY 锚点带 assert |
| I-5 B 文案 | 已核销 | 「并列记录不预指派」入 verdict（L1369-1371）+ 测试 token（L1236） |
| I-6 三级链 | 已核销 | `key=(mean_alpha, pos_years, -n)`（L1522-1523）；token 入预注册三载体 |
| I-7 归年 | 已核销 | `exec_iso_year`（`_week_key` 周一 ordinal +7，实测三边界正确）全消费点接线；SPY 日历年列 L1552-1553；边界残根见 N3 |
| I-8 净参考行 | 已核销 | REF2BP 定义并消费（L1303/L1459）；独立 ROCState 保毛/净信号逐位一致 |
| M-1..M-7 | 全核销 | yfinance 陈述 L9/L614；Task 7 路径无 `/06`（L1614）；Self-Review 重写且声明经本轮逐项核实相符（L1666-1672）；预注册三载体 token 互锁（L1159/L1213/L1653，等号偏差见 N6）；死变量/`__import__` 清零（L808-829）；锚点缺失报错（L529-538）；披露六条（L1316-1329） |

## 新发现（复查狩猎，全部经主会话逐条亲自复核属实）

### Important（开工前修，共 2 处）

**N1. Task 2 `test_annual_close_returns_compounds_year_end` 必 KeyError——夹具缺前年基准行**
- 证据：实现 `annual_close_returns` 的 `{y: by_year[y]/by_year[prev]-1 for prev,y in zip(years, years[1:])}`（L520-526）首年无键；夹具首行 2020（L387-391）→ `got[2020]` KeyError（解释器实测 `sorted(got)==[2021]`；主会话独立推演一致）。
- 为何要紧：Step 4 必红，且错误方向风险真实——执行 agent 易误判为实现错，把首年改成「年内收益」语义，连锁破坏 SPY 锚点口径（SPY_ANCHORS 2013 键必须=2012 末→2013 末年际收益）。
- 改法：夹具首行补 `{"date": "2019-12-31", "close": 100.0}`（实测修后两断言精确成立），实现不动。

**N3. `year_bounds` 决策周截窗 × 执行周归年 → 2023-W01 尾段越界 + α 字典 12 键（主会话升裁 Important；复查 agent 原定 Minor 披露级）**
- 证据：窗内最后决策周五 = 2022-12-30（实测：周五、ISO 2022-W52），其执行周 = 2023-W01（2023-01-02..06）——该周策略/基准 open→close 收益进 `mean_alpha`/`pos_years`/Sharpe/CAGR/MaxDD 全部判定统计（L1417-1419/L1460-1466）；对称侧决策 2011-12-30（执行周 2012-W01）被窗排除 → α 字典 12 键（2012..2023，2023 单周残根）、2012 缺 W01。
- 为何要紧（升裁理由）：①尾段 2023+ 是预注册声明的处女确认窗候选，GC 6 明文「不暴露任何能触及 2023+ 的开关」——判定统计实质消费 2023 第一周，预注册合规性硬伤；②判定域 A「≥7/11 年为正」是冻结判据，`pos_years` 在 12 键上计数 = 静默多一个抽头；报告模板 `"{}/11"`（L1529）硬编码分母，可打出「12/11」。
- 改法：`year_bounds` 过滤条件追加 `exec_iso_year(f) <= 2022`（弃决策 2022-12-30，最后执行周=2022-W52 止于 2022-12-30 收盘，尾段零触及）；DISCLOSURES 补一句「窗界按决策周五 ∈ 2012-01-01..2022-12-31 且执行周 ISO 年 ≤2022 过滤：2012 年不含 W01 执行周（属决策 2011-12-30，窗外）」。
- 附注：机制与毛/净内部一致性确实不受影响（复查 agent 事实成立），升裁仅因预注册纪律与判据完整性。

### Minor（同轮顺手修，6 处）

- **N2**：Task 1 Step 2「Expected: 7 个 FAIL」错——`bench_symbol` 现状已存在（data.py:63-64），`test_bench_symbol_param` 实现前即 PASS，实际 6 FAIL + 1 PASS；改文案并注明该用例为行为回归锁。
- **N4**：L69 括注「金额闸门保持硬编码不参数化」失实——universe.py:83-85 现状本就是签名参数；改「金额/年限闸门参数保持现状签名与默认值不动」。
- **N5**：`test_roc_threshold_separable_and_fallback` 4 样本命中 `_roc_threshold` 的 `len(p)<10` 早退 → Youden 主路径在纯函数层零覆盖（断言被 0.5 兜底凑巧满足）；夹具扩 ≥10 对可分样本。
- **N6**：Task 5 预注册六行「seed 20261106」vs 提案 §10「seed=20261106」差一等号（主会话逐字 diff 证实；L1125 自称「原文逐字」）；恢复等号并同步三处 token，或删「逐字」措辞。
- **N7**：Task 6 `_run` 恒传显式 `start` → `min_universe=5` 永不生效（`start = coverage_start(...) if start is None else start`）；无害冗余，Interfaces 表述易误导，注记一句即可。
- **N8**：`test_sr_us_backfill.py` 的 `json`/`Path` 导入未用 → ruff F401；计划 L418 已有「以零告警为准」预案，执行时删即可。

### 复查候选核实记录（主会话 12 项候选 vs 独立复查）

证伪 6（B valid 夹具——帧网格仅由 index series 派生、C `_frame` seed=3 带默认、D 签名矛盾——现状本就是参数、F WeeklyFrame 12 字段位置构造吻合、I corrupt 夹具——污染打在执行周、`[0][0]` 精确、L 前半——无旧口径残根）；证实 6（A=N3、E=N2、G 标签行对齐语义正确、H `_week_key` 正确、J 端点语义确认、K 杂项 API 全部成立含 conftest 导入链/`_l2_select` 无外部引用/market_data_io 签名）；L 后半=N6。两轮交叉无一假阳性冲突。

## 复查轮 Assessment

**Ready to execute?** **Yes——先修 N1/N3 两处（Important）再开工；N2/N4-N8 同轮顺手修。**

**Reasoning**：原否决的两类根因（方向决策反向落地 + 2012 驱动 bug）已彻底消除，18/18 核销且 C-1/C-2 机制级为真修复；窗口纪律、A 股默认零变化（backtest.py:134/grid_probe_params.py:53 既有调用点不传新参、`window_blocks` 默认分支逐位一致）、conftest 导入链、API/夹具事实层经两轮独立核验全部成立。新发现的 N1（单测夹具 KeyError，1 行）与 N3（执行周尾段越界，2 行 + 1 句披露）都是定点修复不伤骨架——**修复限于本清单范围则免再复查，超范围改动须回来再过一轮**。修复归属沿用用户 2026-11-06 拍板：计划作者（并行会话）自改。
