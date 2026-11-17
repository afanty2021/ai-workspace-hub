# 2026-11-17 max 评审闭环（今日提交 + 工作树）

## 范围

- 提交区间：`ee7834e..e099842`（EXP-20261117-01 银行红利补跌七底检验落卡 + _index 一行，+125 行；单一提交）
- 工作树本地文件（约定不入库）：concept 卡 defensive-crowding-capitulation.md、queue Q-20261117-01、active-context、friction-log、output/research/2026-11-17-bank-dividend-capitulation-check/（数据+脚本固化）
- 评审方式：requesting-code-review skill 派发独立评审员（41 次工具调用），全部声称独立复做——analyze.py/analyze_v2.py 现场复跑逐格对拍、2026YTD 用 CSV 自算（上年末收盘口径）、verify_000922.py 联网重跑中证官网 API 对拍 41/41、yaml 程序化解析、rebuild-index dry-run 三索引 changed=false、tagger scan 0、/tmp 缓存与固化副本 5 CSV md5 全对、commit message 三项声称逐条核实。协调侧对评审员报的修法数字（-4.1%/-3.1% 双口径）另行独立自算核实后才执行。

## 结论

**0 Critical / 1 Important / 6 Minor，已全处置。** 核心结论三重验证全部成立：七底判定表全格子复跑逐位一致、2026YTD 切面独立复算一致（评审员并确认 v2 脚本输出的 CZ +1.16% 是 2026 首交易日口径、卡正确采用上年末口径——口径陷阱没踩）、000922 数据质量联网复验 41/41。frontmatter 七列表字段全独立、无 related（符合 11-13 停用决策）、ticker 全带后缀、_index 逐字一致、queue/concept 卡/commit message 数字四方对拍全中。

## 处置明细

### Important

- **I-1：固化脚本硬编码 /tmp 路径，「固化」保障脱钩**。`analyze.py:14`、`analyze_v2.py:12`、`verify_000922.py:8` 均 `CACHE = Path("/tmp/bank_div_bottoms/cache")`，而固化目录就放着同 md5 的 CSV——/tmp 重启即清，固化目录届时无法直接复跑，与 based_on「固化副本」的承诺相悖。→ **已修**：三处改 `CACHE = Path(__file__).resolve().parent`；复跑验证 analyze.py / analyze_v2.py 输出与修复前基线 **diff 逐位一致**、verify_000922.py 联网复跑 41/41 一致——固化目录现已自洽可复跑。friction-log 已记（固化产出脚本一律以脚本同目录为数据根）。

### Minor（全处置）

- **M-2：「距历史前高 -3.1%」限定词缺失**。卡 summary 与 commit message 写「中证银行距历史前高仅 -3.1%」；协调侧自算：全史最大收盘 **2025-07-10（8497.84）、当前距 -4.1%**，-3.1% 实为距 **2024-09 前历史高点（2007-10-31, 8412.19）**——analyze.py 的 pre-2024-09 窗口径。queue 行原本就带（2007-10-31）限定词=准确。→ **已修**：卡 summary 改双口径并列「距 2024-09 前历史高点（2007-10-31）-3.1%、距全史高点（2025-07-10）-4.1%」；commit message 同步（见下 amend）。
- **M-3：斜杠双数映射不显式（11-16 M-2 同族）**。卡 summary「银行红利末段补跌 -21.4%/-20.2%」与「红利抱团瓦解末段 -11.4%/-11.2%」先行词单数、数字双数，且判定表列头恰为「全程/末段%」斜杠格式易误读。→ **已修**：卡与 concept 卡两处改「银行/上证红利末段 -21.4%/-20.2%」「上证红利/中证红利末段 -11.4%/-11.2%」（2013-06 与 2024-09-18 两案例、两卡共四处）；queue 原文为单数数字无歧义不动。
- **M-4：RS 行 2016 格混用两版口径未标注**。卡 :81「+12.7(2016 银行，RS 峰在 2013-02)」取自 analyze_v2 的 750 日窗；v1（熊市段窗）同格输出 0.0（RS 峰 2016-01-27）。协调侧复跑两版核实属实（其余六格 v1/v2 同值，仅此格分叉）。→ **已修**：补注「750 日窗 RS 峰在 2013-02=相对强度早已回落；v1 熊市段窗同格为 0.0、RS 峰恰在 2016-01-27」。
- **M-5：analyze.py 死代码**。:24 CSI1000（000852）加载后从未使用、:23 `"015.SH" if False else` 死分支；based_on 写「四指数」而目录有 5 CSV（000852 系 fetch 顺带辅助数据、非检验输入）。→ **已修**：删两行死代码（输出 diff 零差异佐证未参与计算）；based_on「四指数」保留（指检验输入，000852 未用于检验，表述成立）。
- **M-6：concept 卡推测降级**。腿拆分条「银行腿常提前见底并领涨（3/7 底）…」在 exploration 卡 :89 明确标 [推测，2 vs 3 样本]，concept 卡使用边界段无标注。→ **已修**：补「[推测，2 vs 3 样本]」。
- **M-7：summary 含 markdown 加粗残留**。frontmatter summary 两处 `**…**` 被 _index 逐字引用带进表格，邻行均无。→ **已修**：去两处加粗，rebuild-index --apply 刷新 _index（二跑幂等 no-op），程序化对拍「index contains summary: True / bold in line: False」。

### commit message 勘误（amend）

e099842 未推送（本地 ahead 顶端），三处表述勘误走 `git commit --amend`（90a13d4 先例）：M-2 限定词、M-3 票名×2。**e099842 → 6fa085f**；queue:290 与 active-context:31 共四处 SHA 引用同步更新。memory 教训「commit 信息别引用会被改写波及的 SHA」反向适用：queue/active-context 引用了将被改写的 SHA，amend 时一并同步。

## 验证

- 修复后复跑：analyze.py/analyze_v2.py 与基线 diff 逐位一致（V1-IDENTICAL / V2-IDENTICAL）；verify_000922.py 联网 41/41。
- yaml 复验：两卡全部列表字段逐项独立（EXP 卡 based_on 3/domain 3/ticker 4/concepts 4/tags 4/recall 4/decision 3）、summary 无加粗；tagger scan 0 问题；rebuild-index --apply 幂等（二跑三索引 changed: false）；_index 行与新 summary 逐字一致。
- 评审员报的修法数字（-4.1%/8497.84/2025-07-10）由协调侧独立自算核实后才执行——「评审修法也要核实」纪律。

## 附注

- 评审时点工作树另出现 `workspace/research-profile.md` 未预期改动（11:47 并行会话写入 R20261117-01 国产算力板块观察行）——非本次评审范围，按「并行会话同分支」纪律本次提交**按文件隔离**（只含 wiki/explorations 两文件+本报告），不碰 profile。
- 评审员未验证项（风险可控，留档）：fetch*.py 未重跑（避免覆盖 /tmp 缓存破坏 md5 对拍基础，数据质量已由 verify 网络对拍覆盖）；tushare 三指数源数据未重新联网对拍（依赖当日 fetch，读数与公开常识相符）；tagging provider=current_agent 人工预填（卡内复审记录已如实注明，EXP-20261110-03 同惯例）。
