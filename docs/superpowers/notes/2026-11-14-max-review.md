# 2026-11-14 max 评审报告（今日三笔提交 + 工作树未提交三文件）

- **范围**：`6ff98c9..13720fb` 三笔（60920d6 序号账本防线 / 638a5cb 16 票落卡 / 13720fb tagger 八进制修根）+ 工作树未提交（research-closeout.md「Alpha 兑现条件」增问 / liquidity-dashboard.md 主题注意力温度段 / theme-exposure-matrix.md 新文件，Q-20261114-09 ②④①落地）。
- **结论**：0 Critical / 6 Important / 6 Minor。6I 逐条核实**全部属实**；其中 I-5/I-6（矩阵内容级）当日已修，I-1~I-4（commit message 数字声明）处置方式待用户拍板（见文末遗留）。评审员独立复现了「三发变异各自红」并对拍了 dashboard 全部外部数据（两融/份额逐位一致）。

## 逐条核实与处置

### Important

| # | 内容 | 核实证据 | 处置 |
|---|---|---|---|
| I-1 | 60920d6 message「新增 46-53 八行观察」低报：profile 实际新增 19 行（41/42/45 补录+46-**61** 两批各八行），第二批 8 行未入账面声明 | `git show 60920d6 -- workspace/research-profile.md` 提取序号序列 41,42,45,46…61 | message 勘误待拍板；行内容本身经对拍无误 |
| I-2 | 638a5cb message「复审记录第六/七次」错：卡内新增两条标**第五/六次**，queue Q-08（第五次复审）/Q-02（第六次）与卡一致，仅 message 按物理行数错数（根源=历史两条均标「第二次」，见 M-1） | EXP-08-01 复审记录段 :200-210 逐行编号序列 | message 勘误待拍板；不改卡（改卡会连带 queue dated 记录失同步） |
| I-3 | 638a5cb message「config 入池 6+1 票」错：今日实增 **11 行**（Q-01 六行 65→71 + Q-07 四行 71→75 + 富联追记 75→76，queue 自记 + config 11 个 2026-11-14 行实测） | queue Q-01/Q-07 done 单元 + config 逐行 | message 勘误待拍板 |
| I-4 | 60920d6 / 638a5cb message「806 用例全绿」在各自时点不成立：791（11-13 终态）+8（ledger）=**799**，+7（tagger）=806 @13720fb——三笔 11:29-11:30 同批打出统一盖了终态数 | 评审员 `-k "not WikiTaggerTickerIdentityTests"` 实测 799+7；791 基线与 11-13 各 message 互证 | message 勘误待拍板（13720fb 的 806 准确不动） |
| I-5 | theme-exposure-matrix 表头「16 组」vs 组表实为 **17 组**（T1-T16+T18），T17 跳号无说明；queue Q-09 同错 | 组表逐行计数；`grep -rn T17` 全库零解释 | ✅ 已修：表头 17 组 + T18 行后弃用注记 + queue Q-09 追加【评审勘误】 |
| I-6 | 矩阵把 certainty 值誊进假设阈值位：云铝「H11 派息底线 60」（H11 实为 40% 派息坐实，60=certainty）、宏桥「H9 末期息 55」（H9 实为 ≥2.3 港元且派息率 ≥60%，55=certainty） | hypothesis/H9.md、H11.md frontmatter+标题 | ✅ 已修：云铝行改「H11 派息坐实线 40%，前瞻 DV ~7%」、宏桥行改「H9 末期息 ≥2.3 港元·派息率 ≥60%」 |

### Minor

| # | 内容 | 处置 |
|---|---|---|
| M-1 | EXP-08-01 复审记录历史编号脏数据：11-12 盛科与 11-13 牧原两条均标「第二次」、中芯条无编号（I-2 的根源） | 挂 **Q-20261114-10** pending（两法拍板：就地重排连带 queue 注记 vs 段头加注不重排，建议后者） |
| M-2 | EXP-08-01:161「已验证事实（四样本坐标）」段头过时（现含各形态样本） | ✅ 已修：改「各形态样本坐标」（:7/:133/:137/:189 的「四样本」系历史表述准确，不动） |
| M-3 | ledger 三个 latent 边界：①`N~M` M<N 静默漏检 ②报告元讨论语境引用别票序号可能误计（preflight 豁免只覆盖回执目录）③异常大跨度展开污染输出 | 记档（均无现实案例；往 output/research 加新目录类型或报告体例变化时想起②） |
| M-4 | EXP-20261111-02 ticker 存量裸 int（968176/968075，无前导 0 值无损坏） | ✅ 已修：加引号 str 化（非 entity 卡不被 scan 覆盖，顺手治理） |
| M-5 | 陕煤息差双口径未互注：矩阵/profile 用 TTM +1.98pp、config 用前瞻 +3.2pp | ✅ 已修：矩阵陕煤行补「TTM 口径，config 前瞻口径 +3.2pp」 |
| M-6 | 矩阵「T1 溢价 ≤2%」与主题组 T1 撞名（实为 513880 研究触发器 T1）；:131 中英混排「unrelated」 | ✅ 已修：改「溢价线 ≤2%」+触发器编号澄清注记；「unrelated」改中文表述 |

## 实测记录

| 命令 | 结果 |
|---|---|
| `pytest tests/ -q` | **806 passed** + 16 subtests（修复后复跑一致） |
| `pytest -k "not WikiTaggerTickerIdentityTests"` | 799 passed / 7 deselected（I-4 时点口径实证） |
| 三发变异（/tmp 沙箱） | 去回执豁免→1 failed；去漏记→1 failed；去撞号→2 failed；还原后全绿（评审员独立复现） |
| `workspace_status.py` | 「四模块序号账本：OK（报告声明 18 序号 / profile 53 行）」与声明逐字一致（修复后复跑一致） |
| `wiki_tagger.py scan` | 0 问题 / 96 张 entity 卡（非空转） |
| 模板↔实例 diff（60920d6:profile） | IDENTICAL（cp 同步声明属实） |
| 东财 RPTA_RZRQ_LSHJ 实拉 | 2026-11-12：RZRQYE 23,028.6 亿 / RZYE 22,738.3 亿 / RZJME +6.94 亿 / 5 日 -46.9 亿，与 dashboard 逐位一致 |
| 腾讯快照 f73 | 159399 f73=3,903,194,835 份=39.03 亿份=基线值；562800 须 sh 前缀注记正确 |
| config↔矩阵逐票对拍 | 个股 46/46、ETF 10、场外 3、锚 17 零差异 |
| based_on 存在性 | 新增 12 条引用全部存在 |
| 入库声明 check-ignore | wiki/concepts/*、config、hypothesis/、output/* 均命中=不入库声明属实 |
| yaml 修复后复验 | EXP-08-01 18/18/16/10、EXP-11-01 6/7、EXP-11-02 4/6/8（ticker 全 str）、新卡无 related ✅ |

## 修复提交内容（本次闭环）

- `workspace/monitoring/theme-exposure-matrix.md`：I-5/I-6/M-5/M-6 共 8 处（表头 17 组+T17 注记+H11/H9 阈值+陕煤口径+溢价线两处+中文化）
- `wiki/explorations/EXP-20261108-01-…md`：M-2 段头
- `wiki/explorations/EXP-20261111-02-…md`：M-4 ticker 加引号 ×2
- `workspace/review-queue.md`：Q-09 追加【评审勘误】+ 新增 Q-20261114-10（M-1 挂账 pending）
- 本报告

## 遗留（拍板与处置记录）

1. **I-1~I-4 commit message 勘误**：用户拍板选项 A——filter-branch 改写序号账本笔/落卡笔两笔 message 的四处数字为时点口径（「46-53 八行」→「46-61 十六行两批各八行」、「第六/七次」→「第五/六次」、「入池 6+1 票」→「11 行 65→76」、「806 全绿」→「时点 799·本批终态 806」），各加尾注勘误标记指向本报告；tagger 笔的 806 准确不动。改写 SHA 随之变更，改写后以 `git diff refs/original/… main` 树 diff=0 验证；旧→新 SHA 对照见本报告文末「改写记录」（评审时点引用的旧 SHA 60920d6/638a5cb/13720fb 以本报告为勘误锚，不再进任何新 message）。
2. **Q-20261114-10**（M-1 复审记录编号）按 queue 待拍板。
3. **M-3** ledger latent 边界三处记档于本报告，无现实案例不动作。

## 改写记录（filter-branch，2026-11-14 执行）

SHA 锚定 msg-filter 只动两笔目标 message，`git diff refs/original/refs/heads/main main` 树 diff=0 验证通过（本段补录后该 diff 含本报告增量，属预期）。SHA 对照：

| 旧 SHA（本报告上文评审时点引用） | 新 SHA | message 变更 |
|---|---|---|
| 60920d6（序号账本笔） | 0fa6922 | 四处数字改时点口径+尾注勘误 |
| 638a5cb（落卡笔） | 901b96b | 三处数字改时点口径+尾注勘误 |
| 13720fb（tagger 笔） | 571db9e | 未动（806 在该笔准确） |
| 6cb2e60（Q-09 落地笔） | 59db58c | 未动（仅父链变更） |
| c5555ac（评审修复笔） | 改写记录所在提交 | 未动（仅父链变更） |

旧备份链（11-13 c14c42f 改写前快照）移至 `refs/backup/20261113-pre-c14c42f-rewrite` 保留；本次改写备份在 `refs/original/refs/heads/main`。
