# 2026-11-12 当日变更 max 评审报告 r2（d7478af..91981e1 + 工作树）

**范围**：r1（同日上一轮，见 [2026-11-12-today-changes-max-review.md](2026-11-12-today-changes-max-review.md)）未覆盖的 9 笔 commit（f1d6e7f..91981e1，其中 **7df7bf0 为当日唯一代码提交**——沪深300 指数入池接线）+ r1 修复闭环两笔（d80d3c8/195cb19）+ 工作树 2 文件未提交 diff（评审前快照）。评审员：独立 subagent（通用型，max 深度清单：数字逐位对拍全覆盖/代码逐行+变异推演/文档声明对靶代码/算术复算/测试实跑/rebuild-index 幂等）；主会话对全部 C/I 独立复核后执行修复波。

**结论**：1 Critical / 4 Important / 7 Minor。C-1 与 I-1~I-4、M-1/2/3/5/6/7 当日全修（变异五发全红验证 + 760+16 测试全绿 + 三索引 dry-run 幂等）；M-4（第 29 次 profile 行缺位）归还并行会话（91981e1 已如实标注）。不动摇本批任何知识结论；但 C-1 意味着 7df7bf0 的「751+16 全绿」只覆盖了代码逻辑，没覆盖「自家持久化钩子写出的数据」——当日 16:43 日报即实际受害。

---

## Strengths（评审员原始认定，主会话抽查复核）

1. **裸码歧义防御本身是真的**：`_cn_quote_symbol` 要求 6 位数字+后缀，裸码进不去；双备份表只在显式映射命中。评审员当日实时探针：新浪/腾讯 sh000300 快照与本地 `data/index/series/000300.jsonl` mootdx 行逐位一致。
2. **数字对拍质量极高**：约 60 组逐位核对仅 1 条漂移（I-3）。巨星农牧行 13 组全中、百达 carry 差分 5 点算术自洽、profile 27 行全命中源报告。
3. **工作树回填算术验真**：1.1850÷0.8373=1.41532≈1.4153，落估算带；0.8373∈[0.83,0.88]——代理法首样本验证句与 R20261112-09 报告完全同源。
4. **R-ID 台账干净**：R20261112-01..11 连续无撞号；第 29 次缺位如实标注而非掩盖。
5. **r1 修复零回归**：无源数字/双口径/salience 长句/related 锚全仓零残留；49.24/49.16 双口径显式化到位。
6. **工作树 research.md 声明对靶代码逐条吻合**（--research-file 不存在即 ValueError；恰好写 preflight 三键）。
7. last_reviewed_at 约定今日三笔复审行 commit 一致执行（r1 M-4 行为统一落地）。

## Issues 与修复（当日闭环）

| # | 级别 | 问题 | 修复 |
|---|---|---|---|
| C-1 | **Critical** | **persist 钩子对裸 000/399 指数码写 `market/series/` 影子文件**（append_series_from_snapshot 对 watchlist 全票 upsert、eastmoney 源豁免收盘闸门）→ 000300 入池当天 16:43:20 写出单行影子（volume 股口径，与 mootdx 手口径差 100×）→ `load_rolling_stats` 的 `path.exists()` 前置守卫被影子击败 → **当日日报 :17 实际输出 000300 5d/20d=「— —」，与 :29 口径注记（声称走 index/series 管道）同报自相矛盾**；往后每交易日影子+1 行，约 6 个交易日后 5d 列将静默改由东财影子序列计算 | ①`load_rolling_stats` 裸码路由改无条件（先于任何 exists 判断）；②persist 钩子 `_BARE_INDEX_CODE` 跳过裸码 series upsert（快照照常）；③删除影子文件；④今日日报 ：17 外科修正 -1.69/-2.93（index/series 807 行）+口径段附勘误注记。修根验证：修复后 load_rolling_stats 实读 807 行权威序列 |
| I-1 | Important | **接线五处文档零登记**（AGENTS/CLAUDE/DATA-SOURCES/两模板均无 sh000300/1.000300）——惯犯坑第 5 案风险；既有反引号锁只管「AGENTS→DATA-SOURCES」，「接线了但 AGENTS 忘写」方向无锁 | 补登五文件；探测顺带带出 **7 个同族存量缺口**（171.US10Y/100.NDX/109.LCPT/177.000660/DGS10/DINIW/hf_CAD）一并补齐；**新增反向派生锁** `test_fetch_symbol_tables_are_registered_in_agents_md`（*_SYMBOLS 全表 value 必须在 AGENTS.md 出现，变异验证红） |
| I-2 | Important | EXP-08-03:66 `勤辰资产: supporting` 违反 schema 枚举（只许 core/reference/mention），全仓唯一 | 改 `reference` |
| I-3 | Important | 「瑞程 4.7 年」无源且与源报告算术冲突（源 :78 原文「4 年多 +183.02%、年化 21.78%」；+183.02%@21.78% 互推 5.28 年，4.7 年只给 +152.5%）——**195cb19 当天修根的「跨文件数字对拍」首案漏网** | 卡 :125 改源口径+〔待验证 回源〕括注；报告「待验证问题」补第 7 条（三元组失配）；queue done 注追加补正括注；entity 林森.md 经核忠实无改 |
| I-4 | Important | 7df7bf0 三处新分支零测试锁（load_rolling_stats 回退/liquidity 降级/TENCENT+SINA_CN_INDEX 双表 payload），变异推演全不红 | 新增 6 测试（含影子文件存在时权威管道仍胜出的路由锁、裸 000001 歧义拒绝锁、置首契约锁、persist 跳过锁×2）；**五发变异全红** |
| M-1 | Minor | EXP-08-03 related 新增 [[968176]]/[[林森]]/[[勤辰资产]]、EXP-08-01 [[603477]] 正文无锚 | 各在正文首提处补 wikilink |
| M-2 | Minor | EXP-08-05/EXP-09-02 related [[000300]] 正文无锚（r1 I-4 修复的存量缺口） | 两卡 11-12 复审行补 [[000300]] 锚 |
| M-3 | Minor | EXP-08-03 based_on 缺第 3/4/5 样本报告（同批 EXP-08-01 补了，不一致） | 补 R20261112-02/pictet/qinchen 三路径 |
| M-4 | Minor | 第 29 次（巨星农牧）profile 观察行缺位 | **不修**——并行会话欠账，91981e1 已如实标注，归还该会话收口时补行 |
| M-5 | Minor | SBMQ66（支付宝内部码非 AMAC 备案号 [待验证]）进卡 frontmatter ticker 无处挂验证标记 | ticker 删 SBMQ66（SXN916 保留）；queue 补正括注；报告 :62 原标注保留 |
| M-6 | Minor | 「峰值后 ~2.5 个月」系对反推峰值的再推算、精度无源 | 改定性「落在 2025-11 反推净值峰值后约一个季度」 |
| M-7 | Minor | SOURCE_CALIBER_NOTES 无 000300 条目（东财股/mootdx 手 100× 防患） | 补条目（HSTECH M-5 同款纪律） |

## 复查（修复波独立验证）

- 变异五发全红：M1 路由守卫回退/M2 persist 跳过移除/M3 liquidity 降级分支移除/M4 视图路由回归/M5 腾讯 CN 指数 elif 移除；另对反向文档锁做 AGENTS.md 抹 token 变异（3 红：反向锁+反引号连锁+模板一致锁），均恢复后复绿。
- 全量 `pytest tests/`：**760 passed + 16 subtests**（r2 前 751+16，净增 9 锁）。
- rebuild-index 默认 dry-run：三索引全部 `changed:false`（frontmatter 修改不触索引行，幂等）。
- 残留扫描：`4.7 年` 仅剩勘误括注自引用（卡 :125 修复注 + queue :219 历史记录）；`: supporting` 全仓 0；卡内 SBMQ66 为 0。
- git：修复未提交，待用户点名。工作树另含并行会话文件（system/skills/research.md + EXP-08-03 原有回填行——r2 已验证为真，保持不动）。

## 机制层建议（已采纳，同日修根）

1. **C-1 类「读者路由 vs 写者范围」错配**：query_market._view_for 早已把裸码路由到 index_series 视图，但 persist 写者与 load_rolling_stats 读者各有自己的文件层判断——三处口径必须同源。本次修根把读者的路由改为无条件+写者停写，若未来再接裸码指数，唯一正道是让它进 update_market_series._CORE_INDICES（权威写者）+显式快照映射表。
2. **接线五处同步**：反向派生锁落地后，「只改代码不改文档」在 *_SYMBOLS 表域内已不可能静默；表外新形态（如未来 ticker 级历史源分发表）接入时须同款补锁（沿用 verify-reviewer-proposed-fixes 记忆「登记新接线形态时须同步补 regex」纪律）。
3. **跨文件数字对拍步需要算术细则**（评审员建议）：I-3 的三元组互推（任期/累计/年化）值得写进 research-closeout 对拍步示例——本次未落，留待该 skill 下次修订一并处理（避免同日二次改 skill）。

## 遗留与边界

- M-4（第 29 次 profile 行）归还 R20261112-08 会话。
- 今日 16:43 日报的修正只动了 000300 行与口径段勘误注记；运行账本（audit log）未回写——账本是 append-only 审计记录，不应事后改写。
- 并行会话 R20261112-12..15（许继/思源/恩威/润泽）在评审期间落盘新报告，不在本批范围。
