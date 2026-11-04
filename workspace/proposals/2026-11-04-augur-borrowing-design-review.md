# 评审报告：2026-11-04-augur-borrowing-design.md

> 评审日期：2026-11-04 · 规格：max（3 并行评审位：augur 源码事实 / AWH 仓库现状 / 设计内在质量，协调者逐条复核）
> 状态：**报告已出，6 Critical + 11 Important 待用户拍板处置；设计文档未改动**

**总裁决**：⚠️ 方向全部成立，开工前须先修 6 个 Critical。augur 事实基础扎实（15 条核查：9 属实、6 部分属实、无方向性错误）；AWH 现状描述可靠（14 条：8 属实、5 部分属实、零捏造，底数全对：6 份 evidence、5,572 只 gpcw）；五项拍板决策无一被推翻。run-log 三个核心机制（哈希语义、amend 协议、missing 通路）各有一处会让 P1 验收卡死的文本缺陷。

## 设计做对了什么

1. §3.1 取舍准确："append-only 的不是文件，是账本"，没把 RunBundle 搬成第二个数据层。
2. §2.2 复盘时点封顶（available_at ≤ 复盘基准日才采信）是三时点最高价值用法。
3. §4 missing 落为一等公民并强制补数命令，直击 11-02 事故教训。
4. §5.2/§5.6 移植裁剪克制；rolling-IC/学习权重 augur 默认关闭（AUGUR_FORCE_* 门控，engine.py:91-127）属实。
5. §7 L217 三真相源无重叠职责段是全文最清醒一段。
6. augur 侧核心引用逐字属实：EvidenceItem 三时间戳（schemas/evidence.py:6-9,98-116）、cycle 补齐命令（cli_commands/cycle_cmd.py:9-13）、18 persona 纯函数零 LLM 零联网、half-Kelly 公式（engine.py:308-312）、段永平 0.75/0.4（duan_yongping.py:174-179）、disagreement 模块（src/augur/disagreement.py）、industry_matrix 151 行。

## Critical（不修则对应阶段验收无法成立）

### C1 · 三时点字段格式与比较规则未定义，样板例违反自身单调性（L38 vs L49）
日期/带时区时刻/日期混搭：折算当日 00:00 则 04:00 违例，折算当日末则不可证。现有 6 份 evidence 的 observed_at YAML 类型不统一（裸 date vs 引号串），naive date 与 aware datetime 直接比较抛 TypeError。**样板例错 1 小时**：11-02 已是 EST（2026 DST 11-01 结束），16:00 ET = 北京 11-03 05:00，设计写 04:00（按 EDT 算）。
修法：§2.1 补字段规范（observed_at=何地日历日；available_at=必填带时区时刻；recorded_at 新文件升时刻；lint 按日粒度包含判定 + YAML 双类型归一）。

### C2 · verify 对 series 的哈希语义未定义（L75/L79/L96）
整文件哈希 + 追加式 jsonl = 次日必过期：纳入 verify 天天误报，不纳入则 series 不可机检——而两起真实事故恰是 series 错行。加重项：update_market_series.py（writer=batch）是不走 persist 的权威写者（market_data_io.py:177-209），合法覆盖更新会打穿哈希；persist 落盘与记账间有竞态窗口（series_lock 非阻塞拿不到即跳过，market_data_io.py:123-156）。
修法（推荐）：行锚定模型——记 `{path, trade_date, sha256(date≤trade_date 的行序列)}`，追加不触发、改写旧行才触发；amend 加 `--data-target path#date`。

### C3 · "先 amend 后改文件"与 post_sha256 自相矛盾（L79 vs L101）
post_sha256 改完才存在，记账时刻不可知；jsonl 不能回填；CLI 签名无此参数。P1 演练第一步卡死。
修法（推荐）：两步协议——`amend`（intent，post_sha256=null）→ 改 → `amend --done`（补完成行），verify 以 done 为准，天然支持崩溃中断。

### C4 · P0 验收引用 P1 工具（L205）
P0 验收"lint 零缺省告警"，lint 是 P1 交付物。修法：P0 改 grep 可判定项（6 份 frontmatter 均含 available_at + 落点文档 grep 一致），lint 全绿留 P1。

### C5 · persist 挂钩落地前提与代码不符（L74/L82；拍板 #3 的缺口非决策错误）
fetch snapshot meta 只有 `{state, missing_tickers}`（fetch_market_data.py:1457-1459），降级原因只打 stderr 不进 payload；VIX 示例反例更结构性：generate_daily_report.py:942-948 调用序是 persist hook 在 fetch_macro_data 之前，宏观缺失到不了 persist。连带三缺口：① `--no-run-log` CLI 逃生门对真实路径无效（真实路径导入调用 run_persist_hook，不走 main() 的 argparse）→ 须函数参数或 env；② run_persist_hook 吞一切异常（persist_market_data.py:147-154），账本写失败会被静默吞——与"消灭沉默的缺失"相反；③ open 行 started_at 实际只能是 persist 被调时刻（fetch 是独立子进程）。
修法（推荐）：fetch 把结构化降级清单写进 meta（+30-50 行列入 P1 预算），宏观侧同理前移；或明示 data-close 只记股票侧名单、reason 由 skill 补写。

### C6 · observed_at 正名漏盘最大 writer（升自 Important；L53-56 落点清单）
generate_daily_report.py:694 write_signal_evidence 把 observed_at 写成 = 报告日。正名后每次日报自动生成语义错误的 evidence，P1 lint 上线后天天告警。system/templates/evidence-entry.md 模板无 available_at 也不在落点清单。隐式 schema 破坏性变更应附消费方盘点表。
修法：模板进 P0 落点；generate_daily_report 修复排 P1（observed_at 用 quote 的 tradeDate、available_at 按收盘时刻规则），§7 补预算。

## Important（开工前应补进设计）

| # | 问题 | 修法 |
|---|---|---|
| I1 | verdict 4 值（L109）vs blocked-by-review 第 5 值（L134）矛盾 | 扩五值进表，或统一降级 missing（reason: 关键证据 pending review） |
| I2 | kind 枚举矛盾：L84 五值 vs L87 backfill | 扩六值；backfill 无 close 语义不参与 verify |
| I3 | 生命周期未定义：孤儿 open、同分钟重试 run_id 碰撞、masters 同日重跑同路径多 close、账本写失败静默/报错未定 | 复用 series_lock；写失败必须可感知；定义 abort 行与碰撞序号；verify 对 stale open 列清单 |
| I4 | evidence amend 义务不可机检（close 只记 ID 不记哈希）；复盘合法迁移 review_status 会被当修订；目标声明过强 | 豁免条款（状态字段迁移≠修订）；目标句收窄"close 登记产物可机检"；可选 evidence_registered 记 [{id, sha256}] |
| I5 | verdict 行格式无最小文法（字段序/—约定/补数命令含 \| : 转义） | object-model.md 给固定文法；值内禁竖线 |
| I6 | §5.3 推导链期间/口径未声明：gpcw 单报告期、TTM 需 4 期；shares=净资产/bps 有 ~5.5% 系统偏差（300476 实测 9.83 亿 vs 净利/eps 9.32 亿股——总资产−总负债含少数股东权益，bps 归母口径） | 设计文本写明净利期间口径/年化规则、TTM 是否多期（进 P3 范围）、shares 改归母净利/eps 反推 |
| I7 | vendoring 剥离清单低估：engine.compute 还嵌 sentiment/MetaModel/RiskManager/相关性惩罚/ten_x/learning 预测记录；行业加权传递依赖 import yfinance（macro_features.py:146）；BaseAgent 有 feedback 钩子（base.py:247-255）；persona 是绝对包路径 import，"原样搬运"不成立 | §5.2 补剥离裁决清单；砍 macro/regime 只留 get_agent_weights 纯函数；包结构显式拍板；预算 ~200→~300 行 |
| I8 | augur persona 不读 field_availability（全 src 检索证实），MarketContext 非 ownership 字段默认 0——适配层"如实标 missing"只填 field_availability 对打分不可见；debt_ratio 缺失=0 会被当极低负债加分（duan_yongping.py:110-111） | 适配层硬约束：missing 须经值语义或自算 coverage 体现 |
| I9 | industry_matrix 已内置 A 股路由（.SZ/.SS/.SH→"china" 键，中国大师权重 1.45/1.35/1.3…），classify 先查 ticker 后缀——申万映射会被短路 | 两条机制显式对齐：改 classify 优先级或适配层直填行业键 |
| I10 | 账本自身无完整性保护（data/ 整目录 gitignore 已核实）；P2 验收窗口 10-31→11-04 大部分早于账本诞生且无客观通过线 | 轻量三选一（尾行哈希链/checkpoint 入库/声明接受风险）；P2 改"账本启用日至今"或定义 retro:true 补录 |
| I11 | "巡检"流程从未被文档化（grep 证实），§4.2 行格式在 P0 是从零新增非修改现有段 | P0 落点加 hypothesis-tracker.md 巡检流程段，工作量如实计入 |

## Minor（事实修正 + 打磨）

| 项 | 修正 |
|---|---|
| L22 commit hash | 359bbc1 → **359bbc9** |
| §5.1 行数 | base.py 实为 **303** 行；scanner/personas/base.py 是 10 行兼容 shim 非副本，vendoring 唯一来源 = src/augur/personas/base.py |
| §5.2 行数口径 | 18 persona 合计 **4,144** 行（~4,500 误把目录总量当 persona 总量）；vendored 总量约 **4,800** 非 5,200 |
| §5.3 字段表 | 删 bps/shares（MarketContext 无此字段）；sma → sma20/sma50/sma200（base.py:114-115,171）；series 行内字段名是 date 非 as_of |
| §5.1 表述 | persona 按**数据数值**推断覆盖度、不读 field_availability；engine 另有设计未提的 half-Kelly 保底 1% 分支（engine.py:314-315） |
| §5.2 "个别 persona" | 英文 sector 关键词是普遍面：buffett/duan/引擎本体（engine.py:158-173）都有 |
| ARPS/Serenity | ARPS 是 Crypto/Gold 专属、Serenity 美股小票 Twitter 交易者——A 股常驻弃权，计入 §5.5 弃权常态 |
| augur 更严校验注记 | augur 禁止 available_at==retrieved_at（schemas/evidence.py:167-183）；设计允许旧文件缺省=recorded_at 属可辩取舍，应知情声明 |
| §7 P0 文档数 | 实为 5 个（漏计 object-model.md 自身），加模板则 6 个 |
| run-log 轮转 | 明确"不轮转不分区"（<2MB/年） |
| P4 口径 | 21 只 = 17 个股 + 4 ETF abstain（19%）；NVDA/000660.KS/指数/商品边界应明确 |
| 保守缺省×封顶 | 封顶遇缺省文件单独列告警清单，避免静默通过被当"已核实" |

## 验收可测性结论

P0"lint 零告警"依赖未定义物（C4）；P1 四条验收两条被 C2/C3/C5 卡住；P2 窗口早于账本诞生且无通过线（I10）；P3"跑通"可判定但正确性受 I6/I8 影响；P4 可判定。

## 待拍板（2026-11-04 提出，未答）

1. **amend 协议**（C2/C3）：行锚定+两步 amend（推荐）/ series 不进 verify / 先改后记
2. **missing 通路**（C5）：改 fetch 写 meta（推荐，+30-50 行）/ 只记名单 reason 手补
3. **处置方式**：全部修订落设计文档（推荐）/ 只修 Critical+事实修正 / 只出报告不动文档
4. **P3 期间口径**（I6）：单期年化+eps 反推 shares（推荐）/ P3 拉四期 TTM / 启动前再拍

---

## 处置记录（2026-11-04，用户拍板后闭环）

**拍板**：① amend 协议 = 行锚定 + 两步 amend（推荐）；② missing 通路 = 改 fetch 写 meta + 宏观调用序前移（推荐）；③ 处置方式 = 全部修订落设计文档；④ P3 期间口径 = **P3 即做 TTM**（四期滚动 + eps 反推 shares，未采用推荐项"单期年化"）。

**设计文档已改版为 v2**（`2026-11-04-augur-borrowing-design.md`），逐条处置：

| 项 | 处置 | v2 落点 |
|---|---|---|
| C1 | 修：字段规范三行表（observed_at=当地日历日 / available_at=必填带时区时刻 / recorded_at 升时刻）+ 日粒度包含判定 + YAML 双类型归一 + 样板改 05:00（EST）+ 时区正确性归人工责任 + 缺省×封顶「未核实」清单 + 与 augur 禁等值校验的知情分歧声明 | §2.1 |
| C2 | 修：行锚定三元组 `{path, anchor_date, sha256(date≤anchor 行序列)}`，追加不触发/改旧行触发；兼容 update_market_series writer=batch | §3.2 |
| C3 | 修：两步协议 amend(intent, null)→改→amend-done；verify 只认 done，intent 无 done 列"未完成修订" | §3.2/3.3 |
| C4 | 修：P0 验收改 grep 可判定项，lint 全绿留 P1 | §6 P0 行 |
| C5 | 修：fetch meta 结构化降级清单 + 宏观调用序前移（+30-50 行入 P1 预算）；逃生门改函数参数+env 双通道；账本写不吞（单独捕获 + run-log.error sentinel）；open started_at 语义如实=persist 被调时刻 | §3.3 |
| C6 | 修：模板进 P0 落点；write_signal_evidence 修复排 P1（observed_at 用 tradeDate、available_at 按收盘时刻）；消费方盘点三处入 §2.3 | §2.3/§6 |
| I1 | 修：定四值；blocked-by-review 统一降级 missing（reason 带证据 ID） | §4.1 |
| I2 | 修：kind 六值含 backfill，backfill 无 close 语义不参与 verify | §3.2 |
| I3 | 修：孤儿 open 清单 / abort 行 / -r2 碰撞序号 / 同报告多 close 取最后一条 / 账本写失败 sentinel | §3.2 |
| I4 | 修：状态字段迁移豁免条款 + 目标句收窄"close 登记产物可机检" + evidence_registered 带 {id, sha256} | §3.4 |
| I5 | 修：固定文法（字段序/—/禁竖线）进 object-model 落点 | §4.2 |
| I6 | 修（拍板 TTM）：P3 即做四期 TTM 滚动公式 + eps 反推 shares（9.32 亿，偏差声明）+ TTM 窗口入报告"数据截至" + TTM 对拍进 P3 验收 | §5.3/§6 |
| I7 | 修：剥离裁决清单（sentiment/MetaModel/RiskManager/相关性/ten_x/learning 全删；macro/regime 砍只留 get_agent_weights 纯函数；feedback 钩子删）；"原样"改"最小改动"（import 行）；预算 200→300、总量 5,200→4,800 | §5.2 |
| I8 | 修：适配层硬约束两级——persona×因子依赖表 + analyze 后处理重算 coverage_confidence，debt_ratio=0 错误加分型字段点名 | §5.3 |
| I9 | 修：适配层绕过 classify 直填行业键（china 之上细化）+ 映射表第三列英文 sector 关键词（普遍面） | §5.3 |
| I10 | 修：尾行哈希链（轻量三选一选中）；P2 验收窗口改"账本启用日至今"，历史区间 retro:true 补录演示（可选）；明确不轮转不分区 | §3.2/§6 |
| I11 | 修：hypothesis-tracker.md 新增巡检流程段进 P0，工作量如实计入（5 文档+1 模板） | §4.2/§6 |
| Minor 13 项 | 全修：359bbc9；base 303 行+shim 声明；4,144/~4,800；字段表删 bps/shares、sma 拆三、date 字段名；coverage 按数值推断+1% 保底；英文关键词普遍面；ARPS/Serenity 常驻弃权；augur 禁等值知情声明；P0 文档数 5+1；不轮转；P4 口径 17+4+界外；缺省「未核实」清单 | 各节散布 |

**接受协调者复核结论**：16 条关键事实经本侧独立核验（DST 日历推算、fetch meta/调用序/hook 吞异常、write_signal_evidence、锁非阻塞跳过、batch 覆盖、9.83 vs 9.32 亿股、field_availability 仅 base.py、china 后缀路由）全部坐实，零翻案。

---
*评审员：3 个并行 general-purpose 评审位 + 协调者复核（evidence 6 份、fetch meta 结构、write_signal_evidence、base.py 字段与默认值、china 路由、half-Kelly 公式、359bbc9、DST 换算均已协调者亲自重验）。全程只读，未改动任何仓库文件。*
