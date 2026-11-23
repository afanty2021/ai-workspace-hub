# 2026-11-23 max 评审：tagger exploration related 修根 + EXP-20261123-01 落卡

- **范围**：今日（2026-11-23）零提交，全部变更在工作树——`system/scripts/wiki_tagger.py`（merge_generated_metadata 按 type 过滤可写字段修根）+ `tests/test_wiki_tagger.py`（MergeRelatedPolicyTests 3 例）+ `wiki/explorations/_index.md`（rebuild 新行）+ 新卡 `EXP-20261123-01`（untracked）+ gitignored 本地三件（queue Q-20261123-01 done 行 / friction-log 修根条目 / active-context 断点）。另：昨日 r3 处置 77888dd 尚未推送（origin 落后 1，push 另算）。
- **评审员**：general-purpose 子代理，52 步自验。findings **0C / 3I / 2M**，主会话逐条回源核实全属实，当日全处置。

## Findings 与处置

| # | 级别 | finding | 核实 | 处置 |
|---|------|---------|------|------|
| I-1 | Important | `_schema.md:197` 自动标签契约表头写「新建 source **或 exploration** 后…按下表契约补空字段」、`:210` related 行无豁免——交互会话补空字段走契约表不经 merge 函数，与同文件 `:182` 的 6ff98c9 废弃注记自相矛盾；首轮修根注释只自述「tag/backfill 单点」漏此换位形态 | 属实（回源 :197/:210/:182 三处矛盾确认） | 契约表 related 行加 exploration 豁免句（指向 :182 注记+tagger 写侧同步）；代码注释补三通路限制声明（①交互契约路径靠表豁免堵②append_frontmatter.py/手工建卡不在机械防线内③LLM 生成侧保留统一 schema、写侧丢弃的取舍与代价）；friction-log 条目同步补全 |
| I-2 | Important | CHANGELOG Unreleased 无今日条目——`test_changelog_freshness` 规则=CHANGELOG 末次提交后不允许 tools/system 非 md 代码 feat/fix 零条目，884 绿只因今日零提交，一旦按惯例 fix( 前缀提交即被 `_lagged` 抓红 | 属实（回源测试规则+CHANGELOG 状态） | 「### 修复」段顶部补今日条目（修根+评审处置全量），与代码同笔落盘 |
| I-3 | Important | 数字回源归属错位（11-17「数字对了归属错了」同族）：卡 based_on 把美元 103.6/10Y 5.12 归给 `memory/us-ai-crash-20261120.md`，该档案 11-22 段实为 **103.9/4.93（-12bp）**；真源是 **11-16~18 日报**（`2026-11-17.md:34` 美元 103.6/`2026-11-17-premarket.md:24` ^TNX 5.12% **-3bp**/`2026-11-18.md:33` 103.76+5.12）；「大跌日仅 -3bp」的大跌日=11-16（SOX -5.28% 日）非 11-20（当日 10Y 避险 -10~-12bp），卡内叙事流「随后 11-20 IXIC -5.28%」极易误读 | 属实（档案与日报双向对拍：103.9/4.93/-12bp 在档案，103.6/5.12/-3bp 在日报） | based_on 拆为两条（日报真源行+档案行含「勿混引」警示）；「已验证事实」第 1 条补「11-16~18 读数」限定+大跌日=11-16 显式标注+11-20 当日 -10~-12bp 对照；frontmatter summary「2026-11（美元 103.6…）」补「11-16~18」；rebuild --apply 同步 _index 行（二跑幂等 changed:false） |
| M-1 | Minor | 测试 docstring 变异策略自述不实：「去掉过滤后前两个用例必红」——评审员 /tmp 副本实测仅第一例红（第二例存量非空被 fill-empty-only 语义本来就保护，与过滤无关） | 属实（评审员实测+逻辑复核一致） | docstring 照实写：去过滤仅第一例红；第二例价值=钉「未来 merge 语义改成覆盖/追加时存量仍不动」 |
| M-2 | Minor | LLM 生成侧（build_messages schema）不分 type 仍对 exploration 卡产出 related 再被写侧过滤丢弃——预览/缓存出现永不落盘的值；无正确性影响但取舍未声明 | 属实 | 并入 I-1 的限制声明③（保留统一 schema 避免 prompt 按 type 条件化引入缓存键分裂，代价=展示噪音） |

## 评审员自验（主会话确认采信的部分）

- 覆盖面独立重枚举：全库 grep `merge_generated_metadata` 仅 `wiki_tagger.py:560` 一处调用，tag/backfill 经 main()→tag_file() 汇聚，scan 只读——「两入口单点」在 tagger 范围内成立；全 wiki type 普查 36/36/25/8/112 过滤命中面精确无误伤。
- 测试复跑 884 passed（处置后主会话复跑同为 884 绿）；变异二（`if True:` 全 type）第三例红与声称一致；变异一证伪 docstring（→M-1）。
- 新卡 yaml 复验（处置后主会话重跑）：based_on 4（拆分后）/domain 3/ticker 1/concepts 6/tags 4/recall_signals 4/decision_scenarios 3，无 related。
- 过时表述清查：Q-20261123-01/EXP-20261123-01 全库 grep（含 gitignored）零「挂/待拍板」残留。
- 数字对拍：4,032→3,534.64（-12.3%）/HY OAS 352/Sahm 0/core PCE 3.2%/+3.9%/IXIC -5.28%/SOX -42.54% 全部对上档案与 queue:308；2022/2018/2020 例证正确留在「训练知识未回源」层。

## 教训

1. **覆盖面自述必须评审员独立重枚举**（11-22 I-1 判例再次生效）：本次评审员枚举出首轮修根漏掉的第三条写入通路（契约表交互路径）——修根覆盖面硬规则（a069b69）的换位形态检查在「自述」里又一次没做全，靠评审席位补获。
2. **数字对但归属错**（11-17 判例族）：103.6/5.12 每个数字单独看都能在 11 月会话里找到，但指针指向的档案不含它们——「数字回源」必须核到「该数字在该指针源内」，不能只核「该数字在某处为真」。
3. 基于事实的月份级表述（「2026-11 美元 103.6」）在与后续事件（11-20 崩盘）连写时须补读数日限定，防跨日误读——本例「大跌日 -3bp」若按 11-20 读会与当日 -10~-12bp 直接矛盾。

## 终态

- 全量测试 **884 passed, 16 subtests passed**（处置后复跑）。
- rebuild-index 二跑幂等（三索引 changed:false）。
- 待点名提交文件（git 侧 6 个）：`system/scripts/wiki_tagger.py`、`tests/test_wiki_tagger.py`、`wiki/_schema.md`、`wiki/explorations/EXP-20261123-01-*.md`、`wiki/explorations/_index.md`、`CHANGELOG.md`（+本报告）；gitignored 本地三件已同步（queue/friction-log/active-context）。
- origin 落后 1 笔（77888dd）未推送，push 待用户点名。
