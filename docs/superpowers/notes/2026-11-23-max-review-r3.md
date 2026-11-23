# 2026-11-23 max 评审 r3：三灯/HY OAS/ERP/百济批次（3de273f..7aa99d2）

- **范围**：7 笔未推提交（8566c39 百济观察行 / c8c26b7 三灯模块 / b39fc8f HY OAS / a1d9c09 清单落盘 / c414334 ERP 通路 / 25565db ERP 日报段 / 7aa99d2 登记五处）+ gitignored 本地侧（百济报告+entity、股票池 78→79、queue、今日日报、数据序列、cron prompt）。
- **评审员**：general-purpose 子代理（遭遇一次账号 5 小时限额中断后恢复），46 次工具调用、分四遍：diff/新代码/新测试 → 本地侧数据+账本+日报对拍 → /tmp 变异 16 发+确定性 EMA 验证+真实数据全量重算 → 百济收口面+过时表述清查+联网点状复核（FRED BAMLH0A0HYM2 CSV、Damodaran ERPbymonth.xlsx 实拉、BeOne 10-K/新闻稿）。全量 926 passed+16 subtests（评审时点）与提交声明一致。
- **findings 0C / 6I / 5M，主会话逐条回源核实全属实、零误报**，当日全处置。

## Findings 与处置

| # | 级别 | finding | 核实 | 处置 |
|---|------|---------|------|------|
| I-1 | Important | object-model.md `kind` 停「十一值」漏登 `batch-damodaran-erp`（run_archive.KINDS 已 12 值）；7aa99d2 自述「登记五处」不含 object-model——11-22 评审 I-2 同族第 2 次 | 属实（grep :84 vs KINDS 12 项） | 补十二值；**同族第 2 次触发硬规则→A+B 双修根**：checklist 扩⑥+新契约测试 `test_registration_contract.py`（kind 全等+序列三文档登记，doc 侧双向变异红） |
| I-2 | Important | 工具 README 零同步：FRED 行无 BAMLH0A0HYM2、无 Damodaran 行、CLI 无双命令——违反 skill 文档同步硬规则①，11-22 I-2 同款漏法第 2 次 | 属实（grep 0 命中） | README 补 FRED 行 HY OAS+新增 Damodaran 行+CLI 双命令；与 I-1 共用 A+B 修根 |
| I-3 | Important | 灯2 `gold_state` 用 `>=`：11-20 崩盘周收盘恰=3,534.64，等值即亮——今日总览灯2 ✅ 由此而来，与清单自注「首读窗 11-27 当周」矛盾；active-context「未收复」与总览 ✅ 打架 | 属实（重算 above=True 于等值） | **改严格 `>`（等值=未收复）**+渲染 ≥/< 改 >/≤+清单 v1.0 勘误级边界注记+测试双向断言；AskUserQuestion 未答按判例「证据一边倒按推荐先行」先行，**同日用户追认「同意」Q-20261123-09 闭环（v1.1 回退路径关闭）** |
| I-4 | Important | 1a/1b streak 把当日盘中快照行当收盘：DX/^TNX 尾行 11-23 source=sina/eastmoney（官方 kline 止 11-20），实测计入后 1a N=2/1b N=35、剔除后 1/34，今日日报 1b 行「4.96%（2026-11-23）」即污染读数；且 append_record 幂等 skip 使快照行**永久占据收盘位**（DX 存量 4 个 sina 行） | 属实（尾行实况+重算对比） | `assess_three_lights` 增 today 注入，日频腿剔除 `date>=today` 行（当日行必非完成收盘）+变异红测试；管线修根（kline 覆盖快照行+存量 4+1 行清洗）影响 append_record 语义与账本锚定，**挂 Q-20261123-08 待拍板**；friction-log 记条目（「盘中值当收盘写」同族第 2 次） |
| I-5 | Important | 3c「金叉后连续 2 日收盘失守 21EMA 才回退」未实现（trend_state 无回退分支、无测试），commit c8c26b7 message 声明了未兑现的行为（overclaim 判例族） | 属实（源码无 close-vs-EMA21 回退逻辑） | 补实现：`cross_reverted`（自最近金叉扫描收盘 vs EMA21，连续 `CROSS_REVERT_DAYS=2` 日失守→回退，渲染 ⚠️ 已回退）+2 测试（双日回退红/单日回踩容差绿） |
| I-6 | Important | friction-log 未记「HY OAS 接线后未同步进 18:25 cron prompt」（CHANGELOG/queue 都承认了缺口，唯独 friction 没记）——cron 侧一致性问题本库已两次进 friction，漏记使同族计数失真 | 属实（今日仅 tagger 一条） | 补记两条：①登记/cron 滞后族（四处在案：18:25 prompt/8:00 自检五组/object-model/README，A+B 修根）②盘中快照占位族（挂 Q-08） |
| M-1 | Minor | 1c 否决→灯1 熄灭零测试锁定（变异 hy_clear 恒 True 后 25 全绿）——最关键熔断腿无覆盖 | 属实（评审员变异 M7b） | 补端到端测试：全绿夹具下 HY 381/385 两行→总览 ⬜/🚫（前置 ✅ 对照），变异 D 红 |
| M-2 | Minor | `erp_state` today 注入无测试锁定（变异恒 date.today() 后 14 全绿——fixture 日期恰近真实今天） | 属实（评审员变异 M13b） | 补钉死测试：最新行=真实今天-10 天+注入 2099 → 必须报陈旧；变异 E 红（注：主会话首轮变异 sed 缩进打偏空转，纠正后红，过程如实） |
| M-3 | Minor | active-context:28 ERP 条「改动待点名提交」与已提交 7 笔不符（断点写于提交前未更新） | 属实 | 已改「7 笔已提交未推+处置笔待点名」+追加 r3 断点 |
| M-4 | Minor | 8:00 盘前自检 prompt「batch-* 五组 open」未扩六组（batch-damodaran-erp 不在自检面）——评审员无 CronList 工具，主会话核实 | 属实（CronList 原文） | CronUpdate 五组→六组（title 不变，其余逐字保留）；明日 8:00 首跑可实证 |
| M-5 | Minor | us-hy-oas 含 5 个周末观测日（FRED 真实行），「连续 2 日否决」按日历日计数跨周末实际 3-4 自然日 | FRED 原生数据非解析错误 | 仅语义注记，不改码不改清单（预注册纪律，留 v1.1 时一并考虑） |

## 评审员自验（主会话确认采信的部分）

- **数字回源全对**：RV20 重算 35.1949、USD 末次 60 日新高 11-19=103.94、10Y 末次 20 日新高 10-05=5.3089（N=35）、EMA21 24979.52/10154.53、金周收 11-20=3534.64、HY 358 行/11-19=352.0（联网 FRED CSV 对拍 3.52 ✓）、ERP 218 行/3.79/n_lower=1/中位 5.25/2022-10=6.21（联网 Damodaran xlsx 实拉 ✓）、BRUKINSA $3,928M +49%（联网 SEC 10-K R109+新闻稿 ✓）；「RRP 341 行幂等跳过」窗口算术证实；百济核心数字跨 6 文件一致零分歧。
- **百济收口面全绿**：preflight_id/knowledge_used/wiki_pages_loaded/Wiki check 齐全；profile 序号全量 grep max=81 且六处一致；688235=百济神州四处+SEC 稿头确认；池=79 机械计数、插恒瑞后相邻、Notes 带敞口合并披露；「不入池裁决」与「同日用户拍板 WARM」各带主体时序限定无矛盾。
- **渲染字节级可复现**：两段渲染文本逐字节出现在今日日报，无占位符残留。
- **16 发变异 14 红**证实既有防御有效；2 绿（M-1/M-2）即测试缺口，已补。
- 主会话补充核实（评审员无工具的面）：CronList 18:25 档双命令属实无需动、8:00 五组坐实（→M-4）。

## 教训

1. **同族复发两连**（11-22 I-2 → 11-23 I-1/I-2/M-4）：「接线登记面」在一天内同一批工作里掉了三处——checklist 五处不含 object-model/cron prompt 是结构性缺口，A+B 修根后 kind 枚举与序列登记已有机械网，cron prompt 一致性仍靠 checklist ⑥ 人工（无可解析载体，限制已写进测试 docstring）。
2. **预注册落地要「对照读一遍文字」**：>=/>、含当日/不含当日、等值边界——三灯五处偏差（I-3/I-4/I-5）全是「代码写了个体面近似」而非「照抄清单文字」。本次 I-3 的等值情形连清单作者也没定义，靠「首读窗 11-27」的自洽性反推出严格口径——预注册文字自身的歧义要在落盘时补边界注记，不能留到代码里隐式选择。
3. **commit message 声明了未实现的行为**（I-5）与覆盖面自述漏项同族：写「金叉后连续 2 日失守才回退」时该逻辑还不存在——消息里只写已落地的事实，规划写进 queue。

## 终态

- 全量 **934 passed +16 subtests**（926+8 新用例：three_lights +5、damodaran +1、registration_contract +2）。
- 新增 8 用例全部变异验证：>回退成 >=（红）/当日行过滤失效（红）/3c 回退禁用（红）/1c 否决摘除（红）/erp today 注入失效（红）/契约测试 doc 侧双向（红×2）。
- 变异验证后逐文件 cmp 还原，工作树无残留（three_lights/update_damodaran_erp 均与处置版一致）。
- gitignored 本地侧已同步：queue（Q-08/Q-09 新增 pending）、friction-log（+2 条）、active-context（M-3 修正+r3 断点）。
- 待点名提交（git 侧）：`three_lights.py`、`generate_daily_report.py`、`tests/test_three_lights.py`、`tests/test_damodaran_erp.py`、`tests/test_registration_contract.py`（新）、`system/integrations/object-model.md`、`tools/daily-watch/README.md`、`system/skills/daily-watch.md`、`workspace/monitoring/tech-reentry-three-lights.md`、`CHANGELOG.md`（+本报告）。
- **并行会话同日活跃**（德银 Q-20261123-07、_index EXP-02、active-context 同段追加）：本会话所有编辑用紧锚点未触碰其产物；提交时按文件隔离并先 `git status` 复核。
- 两个 pending 均已闭环：**Q-20261123-08** 同晚用户拍板「修」当日执行（见下条）；**Q-20261123-09** 同日用户追认「同意」严格 `>`（v1.1 回退路径关闭）。
- **Q-20261123-08 后续（同晚用户拍板「修」当日执行，闭环细节见 CHANGELOG 同日修复条/queue Q-08 done 行）**：回源勘误真病灶=`update_ticker` 增量起点锚尾行（push2his 限流夜整批失败后尾行前移、孤儿日期永不重拉；非 append_record 幂等——upsert batch 档本就允许尾部覆盖），修根=`incremental_beg` 回撤到回看窗内最早快照源行（收盘指纹补集）+8 契约测试四变异红；DX 存量 4 行由修复后脚本自清（封禁期后台重试/次日 cron 兜底），^TNX 11-23 次日自愈=实证点。
