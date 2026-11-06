---
id: NOTES-20261106-V2-REVIEW
title: V2-L1 三 commit max 评审报告（torch 线性策略 + 预注册 + 负结果结案）
created: 2026-11-06
scope: c1fdd91..86f5f45（feat/sector-rotation-design）
reviewer: code-review subagent（max 强度）+ 主会话逐条对靶核实
related:
  - workspace/proposals/2026-11-05-sector-rotation-design.md（spec v1.2.4）
  - workspace/proposals/2026-11-05-sector-rotation-v2-research.md（R20261105-02 方案 A）
  - workspace/proposals/2026-11-06-sector-rotation-v2-closure.md（被核对象）
  - docs/superpowers/notes/2026-11-05-sector-rotation-s6-review.md（上一轮基线）
status: closed（4I+9M 处置完毕；负结果判定经专项证伪检验维持；修复在工作树待点名提交）
---

# V2-L1 评审报告（c1fdd91..86f5f45，3 commits，+540/-9）

评审对象：

| commit | 内容 |
|---|---|
| 92cce34 | feat：v2-L1 torch 线性策略——models.py LinearModel（joint/independent、masked-mean BCE、CPU+seed）+ window_blocks cols/upto 修根 + backtest --l1-variant + grid_l1_selection.py + 7 用例 |
| 8ecc286 | docs：spec v1.2.4——v2-L1 预注册（w8/independent）+ 消费保护第 7 条 |
| 86f5f45 | docs：v2-L1 确认性检验结案——8 格全未过，OOS 窗口关闭（负结果） |

评审验证强度：子代理逐行 diff + 上下文全文 + masked-mean BCE 手工数值对表（真实数据 104×1896，61% 标签有效 + 合成数据逐元素公式）+ joint 输出形状合成可分信号实证 + 预注册时序 mtime 与运行时长实证（单次 L1 拟合实测 ~1.0s，5 条 L1 walk×324 周 ≈27 分钟 vs 确认窗实际 28 分钟——确认性 run 不可能在预注册 commit 前完成）+ 主会话 4I 逐条对靶（I-4 以 /tmp 脚本独立复测）+ 全量测试独立复跑 + ruff。

执行披露：评审员按文档用法运行 `grid_l1_selection.py --parse-only` 时踩中 I-1 死开关，意外触发 6 格完整网格重跑并重写一份 gitignore 运行时 artifact——重写内容与 spec §6.3 六格全表逐项一致（确定性重放，无数字漂移），已核无害；该摩擦记 friction-log（2026-11-06 条）。

## 负结果真实性专项（P0：假阴性会错杀整条研究线）

按假阴性通路清单逐一尝试证伪「8 格全未过」：

| # | 通路 | 结论 |
|---|---|---|
| 1 | 掩码口径错误（BCE 把 valid 平均掉） | 排除：自动 loss 与手工逐元素公式精确相等，被掩码元素零贡献 |
| 2 | 训练/推断特征错位 | 排除：blocks 行序与 t_idx 一一对应，x_now 与训练块同构同标准化参数 |
| 3 | t_idx 对齐/off-by-one | 排除：upto=t 严格 tj<t，最晚标签 r[t-1] 决策时点已实现，w8 边界训练/推断一致 |
| 4 | 标准化泄漏 | 排除：mu/sd 只来自训练切片（models.py） |
| 5 | joint 变体形状退化（probs 恒取首成员） | 排除：合成可分信号实证两变体均正确选中目标、k=2 出 2 成员；joint 各格换手 34.6-57.1 互异反证 |
| 6 | 掩码外数据泄漏 | 排除：掩码外价格翻转 ±50%/+200% → probs 逐位不变（既有用例为真击杀） |
| 7 | 推断周 M_t 为空退化现金 | 实测仅 1 周（2026-11-05，本就被 valid 跳过） |
| 8 | 训练行坍缩压低表现 | 实测存在但限于尾部（见 I-4，方向只会垫高主策略） |
| 9 | 判据与预注册不一致 | 排除：spec 文字 / grid 代码 / 6+1 份 artifact 三方对表全一致，胜者 w8/ind 确为闸门净 CAGR 最大格 |
| 10 | second-look 未启用 | 排除：确认性报告含二看横幅、阈值 0.05、消费计数与 §3.8 第 3 条一致 |
| 11 | 预注册时序造假 | 排除：mtime 链（6 份网格报告 00:23-00:30 → 预注册 commit 00:37 → 确认性报告 01:05）+ 运行时长测算吻合 |

**结论：「8 格全未过」是真实结果，无翻转方向的通路。** 剩余风险只在解释边界——「预注册的这一版 L1 设计（特征窗滞后一档、超参化线性模型、M_t 联合齐备训练）无边际」≠「任何学习型信号在该窗口无边际」，结案 §4/§5 功效与代表性表述已画对。6 格（选择窗网格）vs 8 格（确认性 4 检验×2 档）无口径混淆。

## 优点

- **预注册纪律经实物证据验证为真**：mtime 链 + 拟合时长测算，确认性 run 不可能先于预注册完成；判据三方一致。
- **masked-mean BCE 数学正确**（手工数值对表精确相等）；掩码不泄漏用例是逐位击杀级。
- **确定性工程扎实**：每次 fit 前重置 seed，同进程两次训练 probs 逐位相等；跨进程网格重放逐项复现（意外重跑即实测）。
- **S6 教训制度化复用**：tag 含 w/variant 防互覆、配置行自检 + 全同断言、真实数据冒烟前置闸门（friction-log 在档）。
- **负结果报告纪律好**：结案数字与 artifact 逐格一致、功效边界与对照口径变化均披露、review-queue 两条 pending 齐备。

## Issues（主会话逐条核实后全部属实）

### Critical

无。

### Important（4 条，全部当场处置）

| # | 问题 | 处置（2026-11-06 当场） |
|---|---|---|
| I-1 | **grid_l1_selection.py `--parse-only` 死开关**：`main()` 未传 `sys.argv[1:]`，argv=None → parse_only 恒 False，文档宣称的只读模式不存在，静默重跑覆盖 artifact（评审已实际踩中） | ✅ 修根：`main(sys.argv[1:])` + 缺「配置：」行友好报错 + GATE_ROW 容 `+` 前缀；`--parse-only` 实测 0.02s 返回、六格表复现 |
| I-2 | **结案 §1/§4 + EXP 教训3/尾注「两个档位跑输全部对照」过度表述**：压力档 L1 -9.06% 优于 L0 -11.68%（§3 自家表格矛盾） | ✅ 四处改准：「基准档跑输全部四对照，压力档跑输三组、以 2.6pp 优于 L0」+ p 值余量；spec §6.3 结案 bullet 同病同修 |
| I-3 | **L1 特征窗 [t-window,t) 滞后决策周五收盘一档，口径注漏列**：L0 动量用 index_close[t]（baselines.py:36）、论文「周五收盘后采样」——vs L0 比较中 L1 信息集结构性少一周；训练/推断一致故非泄漏、非假阴性机制，但属未披露口径分叉（问题在 plan 边界未钉死，非实现错） | ✅ 补披露：models.py 口径注⑥ + README 引擎语义 + 结案 §6 v3 锚点④（v3 重启需重钉边界） |
| I-4 | **M_t 联合齐备约束在宇宙扩张周训练史坍缩**：新成员（881479，2026-07-03 首个有效行）入集把联合齐备起点拖到自身起点。**主会话独立复测比评审更重**：评审称尾部「3-9 行」，实测 2026-08-28→11-05 连续 **12 周训练行=0**（11 周 <window+2 门槛转持币 + 1 周 M_t 空），全窗 16 周（≈4.9%）训练 <30 行、中位 104 满额——尾部 L1 结构性强制现金（live edge 正是坍缩区）。方向上不交易无亏损暴露、vs L0 p=0.653/0.278 余量大，**负结果更稳而非更险** | ✅ 补披露：models.py 口径注⑦ + README + 结案 §3 M_t 口径披露段 + §6 v3 锚点⑤（成员最短历史门槛或 per-member 特征设计） |

### Minor（9 条处置）

- ✅ M-1 README 两处过期：M10 全列齐限制已被 cols 子集消解、「L1/L2 未实施」已不成立——改写并并入 I-3/I-4 限制行。
- ✅ M-2 预注册行未钉 λ_fin=0.1、标签阈值 r≥1%、最短训练行 window+2——spec §6.3 补录 bullet（三常量冻结于 92cce34，先于预注册与确认性 run，结论不受影响）。
- ✅ M-3 seed 测试只锁 picks（排序级）——补 probs 逐位断言（`np.array_equal`）。
- ✅ M-5 parse() 缺「配置：」行 AttributeError → 友好报错；GATE_ROW 容 `+`（随 I-1 修）。
- ✅ M-8 pre-prereg OOS 切片冒烟（2024-09→12，w8/joint，结构修根验证）结案 §2 合规表未列——补记披露（属修根验证非配置选择，网格判据独立于该切片）。
- ⏸ M-4 torch 未 pin set_num_threads/use_determinatic_algorithms：同机跨进程逐位复现已验证，跨机型未验证——v3 重启前提条目（本窗口已关闭无行为风险）。
- ⏸ M-6 np.exp 手写 sigmoid 极端 logits overflow warning（结果仍对，实际 |z| 到不了）：不动已结案代码，v3 一并处理。
- ⏸ M-7 power_note 文案在 p<0.05 档仍印 p<0.1 基准粗估值（结案 §4 已手工校正 6-9%）：引擎文案留 v3。
- ⏸ M-9 `--l1-variant` 对 `--level L0` 静默无效：无害，不加。

## Recommendations

1. v3 重启锚点追加两条实证（已落结案 §6④⑤）：特征窗边界钉死到决策周五收盘；M_t 成员历史门槛/联合齐备替代设计。
2. grid 脚本族（probe=argparse / l1=argv）两种 CLI 模式并存——新脚本统一 argparse；「网格脚本 CLI 接线」一族已两案（注入侧 2026-11-05 + 读取侧本次），第三次出现必须统一模板（friction-log 硬规则）。
3. 预注册行模板补「常量清单」字段：所有进判定的代码常量（λ、阈值、门槛）随行落档，不再依赖"冻结于 commit"的事后考证。

## 修复验证

- `pytest tests/`：**557 passed + 16 subtests**（修复前后同数字）；ruff 全净。
- `grid_l1_selection.py --parse-only`：0.02s 只读返回，六格表与 spec §6.3 逐项一致，胜者 w8/ind 复现。
- 变更文件：grid_l1_selection.py / models.py（口径注）/ README.md / test_sr_models.py / 结案报告 / EXP-20261106-01 / spec §6.3 / friction-log。**均在工作树未提交，待点名。**

## Assessment

**Ready to merge?** With fixes（已当场完成）

**Reasoning:** 负结果真实可信——预注册时序、判据一致性、数学正确性、确定性与运行时长均经实证核验，11 条假阴性通路无一成立；4 条 Important（死开关、过度表述、两条口径披露）已全部当场修复并复跑全绿，余下 Minor 均为已结案线的低风险备忘。
