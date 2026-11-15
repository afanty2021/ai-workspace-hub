# 2026-11-15 下午 max 评审（r2）：遗留项落地五笔复查（5309903..499f77d）

评审对象：上午 max 评审（`docs/superpowers/notes/2026-11-15-max-review.md`）遗留三项 Q-20261115-06①②③ + 追加 Q-20261115-07 的落地五笔——855adcb（ticker 后缀统一全量迁移）/ 42dbe78（字母码市场后缀）/ 432d667（模板观察段清空）/ c16697b（exchange 字段退役）/ 499f77d（观察行触发器对账机械化）。

评审员独立复跑域：全库测试、tagger scan、workspace_status 双账本、三迁移脚本 dry-run 幂等、message↔diff 逐笔 hunk 级诚实（含「红 54 项→0」用 5309903 时点旧 profile 完整复现）、YAML 全库解析、对账器五案人工对拍、模板断言变异复验。

## 结论：0C / 2I / 5M，全处置（I 两笔当笔修复、M-1/M-2 顺手修、M-3/M-4/M-5 留观），With fixes → 已修，Ready to push

### 亮点（评审员独立坐实）

- 「红 54 项→0」非修辞：旧版 profile + 真实报告目录复跑 issues=54 精确复现，迁移确由对账器 issue 驱动。
- 数字复核几乎全部命中：模板 112→51 行、tracked 10 张/7 文件/16 卡备份、EXP-08-03 的 4574→010736.OF 还原、000807 去重、826→836 算术自洽。
- 四层闸门防线（读侧丢弃/写侧丢弃/format violations 点名/scan 硬失败）分层清晰，丢弃不静默。
- 8 个对账用例全部真行为测试（真实报告结构，无 mock 表演）；模板占位断言变异恰 1 failed 精确区分。
- 序号账本零扰动实锤：52 个序号声明序列完全相同。

### Issues 与处置

**I-1（已修）build_messages LLM schema 示例仍是裸码 NVDA，与新闸门自相矛盾**
- wiki_tagger.py:349-356（ticker/entity_salience 两处 + related 示例）+ instructions 规则 3 无形态指引。
- 后果：LLM 按示例输出裸码被闸门丢弃——entity 路径 require_identity 报误导性错误、sources 路径静默丢 ticker；855adcb 前裸码合法，属本批引入的行为回归。
- 修复：schema 示例 NVDA→NVDA.US（related 例外：名称非代码）+ 规则 3 补「代码必须带交易所/市场后缀，entity_salience 键同此规则」；新增 test_build_messages_schema_examples_pass_ticker_gate（从渲染指令中提取 schema JSON、逐值过 _ticker_list 闸门断言零丢弃——示例改任何裸码都会红）。

**I-2（已修）对账器通道②文件名 glob 子串碰撞误配（评审员 /tmp 实测坐实）**
- workspace_status.py 通道② `rglob(f"*{key}*.md")` 子串匹配：4 位 HK 头注码（0700）会命中文件名含 5 位官方码（00700）的报告，产出「行缺 T3…T9」假异常；968↔968176 数字相邻同理。当前真实库 0 误报（无并存文件名对），但 ticker 统一后同码再研究是可预见路径。
- 修复：改边界匹配 `(?<!\d)key(?!\d)` 且直接迭代已加载的 trigger_by_path（等价于 rglob 过滤、免重复遍历）；新增 test_trigger_filename_key_digit_boundary_no_collision 回归（旧子串 glob 变异即红）。

**M-1（已修）retired_field_violations 未接 tag_file 读侧**——scan 侧已接、读侧漏接，tag_file 重写落盘可成退役字段延续源，违背本批「防线退化为仅 scan 可见=违背响亮失败」标准。修复：读侧拦截链追加 retired_field_violations，错误信息泛化为「存量元数据不合规（ticker 形态/文件名一致性/退役字段）」；新增 test_exchange_residue_rejected_before_llm_call（LLM 调用前拒绝+文件零改写）。

**M-2（已修）ticker_filename_violations 裸码无关检查成死分支**——闸门丢弃数字裸码后 `continue` 恒真；防御性保留（防未来调用方绕过闸门直传裸码），加注释标明现状，不删防。

**M-3（留观，无行动）「无 4 位 HK」声明验证域措辞差**——实际验证域=ticker 字段与 salience 键；title/正文/互链豁免区仍有 4 位写法（2319.md title、EXP-20261111-01 正文、600887.md:15 `[[9858.HK]]` 悬链）。互链不动是既定决策。**附注（同日用户点名处置+勘误）：600887 卡 9858.HK 悬链已修——勘误=「疑蒙牛误码」猜测不成立，9858.HK 系优然牧业合法代码（伊利联营 36.07%，报告 R20261115-01:58 有源），实际缺陷仅悬链（entities 无 9858 卡）+格式不一致（entity 互链惯例无后缀：[[600600]]/[[2319]]）；处置=related 内 `[[9858.HK]]`→`[[2319]]`（消悬链+格式归一+补齐蒙牛对照双向互链——2319 卡已有反向 `[[600887]]`，concepts「双寡头减值错位对照（蒙牛）」本就该挂），优然牧业关系由 related 首位报告链接承载零损失；复验=yaml 解析+双向对称+related 全可解析（entity 精确 stem/EXP 短链=38 卡同款 ID 前缀惯例/报告相对路径）+scan exit 0。**

**M-4（留观）对账器节域提取的格式假设**——非标准节名报告会漏吸收（当前 102 份报告全标准）；T05 写法被当 T5 吸收。已知假设，非缺陷。

**M-5（留观）find_field_block 两份近似实现**——两个一次性迁移脚本各自留档可接受；第三个字段级迁移出现时应抽公共模块。

**Rec：conda stdin 修根后复发未记 friction**——已按评审建议补 friction-log 短记录（11-06 首记/11-07 修根/11-15 复发）；若再复发升格 AGENTS.md 工作方式段（待用户拍板）。

## 修复验证终态

- 全库测试 **839 passed + 16 subtests**（836+3 新增）；三处新测试变异验证全过（旧子串 glob→红 / 裸码 schema→红 / 读侧去 retired→红，还原后全绿，工作树仅余预期 4 文件改动）。
- tagger scan 0 问题 exit 0；workspace_status 双账本逐字 OK（四模块序号账本 20 序号/58 行；观察行触发器对账 58 观察/对账 46/异常 0）。
- 三迁移 dry-run 幂等复证：ticker_suffix_migration 变更文件 0 个、remove_exchange_field 0 卡、rebuild-index 三索引 changed=false。

## 判定

**Ready to push**（本地 15 笔待推送：上午 8 笔已上午评审 + 本 r2 范围 5 笔 + 修复 2 笔）。
