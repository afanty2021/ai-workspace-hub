---
id: NOTES-20261105-S6-REVIEW
title: S6 四 commit max 评审报告（风控-锚点互斥消解 A+C）
created: 2026-11-05
scope: 949989a..9e9ad86（feat/sector-rotation-design）
reviewer: code-review subagent（max 强度）+ 主会话逐条对靶核实
related:
  - workspace/proposals/2026-11-05-sector-rotation-design.md（spec v1.2.3）
  - workspace/proposals/2026-11-05-sector-rotation-s6-draft.md
  - workspace/proposals/2026-11-05-sector-rotation-p1-closure.md（§6.1 问题源）
status: closed（5I+Minor 当场修复；I-1 挂 Q-20261105-05 待拍板）
---

# S6 评审报告（949989a..9e9ad86，4 commits，+294/-12）

评审对象：

| commit | 内容 |
|---|---|
| 4a54449 | docs：spec v1.2.3 补钉 S6（§3.6/§3.8/§6.2 + S6 草案落档） |
| 4ef2c2c | feat S6-A：RiskState 全停改滞回态（N/f/M 参数化 + halt 日志 + 3 用例） |
| 7247962 | feat S6-A 参数冻结：选择窗网格选出 N=13/f=0.5/M=4（默认值同步 + §6.3） |
| 9e9ad86 | feat S6-C：报告裸信号诊断行（只诊断不判定） |

评审验证强度：两测试文件实跑 13 passed；状态机合成数据逐周推演 40 周；5 组变异测试（M1-M3 被既有用例击杀；M4 删探针敞口优先级、M5 判据 `>=`→`>` 存活）。主会话对 6 条 Important 逐条对靶核实（I-1 用 /tmp 脚本实测复现；I-2/I-3/I-5 源码核实；I-4/I-6 测试代码核实 + M4 修法实测）。

## 优点

- **状态机主干逐周语义正确**（portfolio.py:60-80）：触发当周 wait=1、13 周现金、探针 M=4 周、判据周 `nav(M+1) ≥ probe_nav0` ⇔ 探针期累计收益 ≥0——判据分母与收益窗口算术严格对齐 spec §3.6。
- **否决周 `wait_weeks=1` 与触发周同口径**（portfolio.py:76），被变异 M3 精确击杀——「变异必须落进精确输入区间」教训执行到位。
- 探针敞口与回撤减半的级联正确：探针周 probing 优先，确认周 halved 自然接手。
- 对照同口径成立：stress 档主策略与等权/反向/随机对照全走 `run_walkforward` 默认 `RiskState(wf.spec)`，默认值已同步冻结值。
- `enabled=False` 早退路径干净，裸路径不受新字段影响。
- §6.3 自曝网格脚本首版漏参、连带披露 v1 阶段 A 压力档被冻结污染——预注册文化的正确姿势。

## Issues（核实后全部属实）

### Critical
无。

### Important（6 条，处置见下表）

| # | 问题 | 处置（2026-11-05 当场） |
|---|---|---|
| I-1 | **确认后仍低于锚点线 → 次周立即再停机**（level 触发）：与 §6.2 拍板功效依据（活跃≈215 周，按持续恢复估算）系统性不符；3 用例无一覆盖此分支 | **待拍板** → Q-20261105-05（选项：A 边沿触发 / B level 触发落 spec+重算功效；拍板后补用例） |
| I-2 | v2 协议第 3 条 p<0.1→p<0.05 未落引擎（backtest.py 四处硬编码 0.1） | ✅ 已修：`--second-look` 旋钮（阈值动态化 + 「同窗口第二次消费」标注 + power_note 阈值同步），变异击杀验证 |
| I-3 | spec v1.2.3 内部矛盾：§3.8 第 1 条/§6.2 S6 行仍写 N=8，§3.6 已 N=13 | ✅ 已修：三处统一 N=13 并标注冻结值出处；§3.8 第 5 条补步骤 0 完成时态 |
| I-4 | 参数冻结可复现性缺口：网格脚本未入库、6 组合数字未落档、defaults 无断言 | ✅ 已修：`tools/sector-rotation/grid_probe_params.py` 入库（带 sweep 自检），**重跑逐位复现冻结值**（N13/f0.5 +2.86%/0.20…六组合全表落 §6.3）；`test_probe_defaults_frozen` 锁默认值 |
| I-5 | halt 统计只披露基准档且未标注档位（v1 实测两档活跃 77 vs 33 周） | ✅ 已修：base/stress 两档各自自持 RiskState，报告分档披露 |
| I-6 | 变异 M4/M5 存活：探针周断言与 halved 的 0.5×0.5 数值碰撞；无 `nav == probe_nav0` 边界用例 | ✅ 已修：`test_probe_frac_distinct_from_halved_scale`（f=0.25→0.125，M4 击杀）+ `test_probe_confirm_boundary_exact_zero`（M5 击杀）——重做变异验证双红 |

### Minor（处置）

- ✅ s6-draft frontmatter `status: draft` 未更新 → 改 decided（已拍板 A+C，折叠进 v1.2.3）+ parent 指针 v1.2.2→v1.2.3 + 尾注同步。
- ✅ 裸诊断行未标成本档 → 报告补「（基准档成本）」。
- ✅ `main_strat` 循环外先验赋值死代码 → 删（循环内赋值，diag 用）。
- ✅ 停机期跨年 ytd_high 重置无测试 → `test_ytd_high_resets_across_year_during_halt`。
- ⏸ 停机期 cooldown 不递减/陈旧 ban 带进恢复首周 → 挂 Q-20261105-05 附带项（确认周顺手清 vs 记 spec 已知限制）。
- ⏸ 探针周撞「连亏 4 周持币」以现金度过 → 极边缘，随 I-1 拍板时一并记 spec 已知限制。

## 修复后回归

- `tests/test_sr_portfolio.py + tests/test_sr_backtest.py`：19 passed（原 13 + 新 6）。
- 全量 `pytest tests/`：**548 passed, 16 subtests passed**。
- 变异对靶：M4（删探针优先级）、M5（`>=`→`>`）、I-2（阈值回退 0.1）三变异在新增用例下全红（恢复后全绿）。

## 评审结论（原报告）

**Ready to merge? With fixes**（状态机语义、判据算术、对照同口径、隔离性全部验证正确；「确认后线下即再停机」是与 spec 文字和拍板功效依据相悖的未拍板语义分叉 + p<0.05 未落引擎 + spec 内 N 矛盾构成「协议已写、执行层未闭合」）。至本次修复后：I-2/I-3/I-4/I-5/I-6 已闭合，**唯 I-1（Q-20261105-05）拍板前不应作为 v2 确认性检验的执行依据**。

## 过程教训（已记 friction-log）

- 变异测试恢复误用 `git checkout --` 撤销未提交修复（一次性，操作纪律：恢复只用备份回写）。
