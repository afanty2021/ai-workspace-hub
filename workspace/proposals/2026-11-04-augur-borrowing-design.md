# 设计方案：借鉴 augur 四机制（证据三时点 · 运行账本 · 显式弃权 · 大师面板）

> 起草：2026-11-04 · v2（max 评审 6C+11I+Minor 全修闭环，评审报告：`2026-11-04-augur-borrowing-design-review.md`）
> 状态：**P0-P2 已拍板待实施；大师面板（P3/P4）设计定稿**。评审四项拍板（2026-11-04）：行锚定+两步 amend / fetch 写 meta+宏观前移 / 全部修订落本文档 / **P3 即做 TTM**。
> 来源：augur（BruceLanLan，v13.0.0，MIT，本地克隆 `~/Github/Invest/augur`）的 EvidenceItem 三时间戳、不可变 RunBundle、abstain 机制、18 大师共识引擎。
> 本文区分「事实」（来自本仓库文件 / git 历史 / augur 源码）与「推测」（预期收益，待运行验证）。

## 0. 一页总览

| augur 概念 | AWH 对应机制 | 落点 | 阶段 |
|---|---|---|---|
| EvidenceItem 三时间戳（业务 / 可得 / 获取） | evidence frontmatter 三时点字段（格式与比较规则见 §2.1）+ 单调性 lint | `system/integrations/object-model.md`、`evidence/README.md`、`system/templates/evidence-entry.md`、daily-watch skill | P0 约定 + P1 lint |
| 不可变 RunBundle | 运行账本 `data/.state/run-log.jsonl`（追加式 + 行锚定哈希 + 两步 amend + 尾行哈希链） | 新脚本 `system/scripts/run_archive.py`（persist 挂钩自动写 open/data-close）、daily-watch / research skill | P1 |
| abstain（缺数据则弃权并说明） | 判定词表 `verdict: normal / warn / trigger / missing`（四值，见 §4.1）+ 缺数条目必须带补数命令 | hypothesis 巡检记录行格式（含文法）、daily-watch 报告模板、hypothesis-review skill、hypothesis-tracker.md 巡检流程段 | P0 约定 + P2 delta |
| 18 大师 + 共识 + half-Kelly | 大师面板：vendored 引擎（剥离清单见 §5.2）+ A 股 TTM 数据适配层 | `tools/masters/` + `system/skills/masters.md` + `output/masters/` | P3 引擎移植 + P4 集成 |

一句话目标（P0-P2）：**消灭"沉默的缺失"和"未申报的修订"**——每个应该有读数的检查点，要么有值，要么有一条带原因和补数命令的 missing 记录；每次运行要么有 manifest，要么修订必须留 amendment 痕迹。

一句话目标（P3-P4）：**给 A 股标的一套规则化、可复核、缺数据就明说弃权的多视角评分面板**——观点是推测层，不冒充证据，仓位是建议不是指令。

## 1. 背景事实：两起真实事故已经踩在这三个洞上

1. **11-02 盘前快照错行**（git 140b935 根修数据层 + 359bbc9 扩四源）：^SOX 盘前快照的周五价被回填成 11-02 当日收盘行（10,687.62 vs 官方收盘 10,328.33），险些漏判 H1 破 10,450 预警线。数据层已有美股收盘闸门，但**研究记账层（evidence、判定）没有对应闸门**。
2. **`observed_at` 语义混用**（事实）：`evidence/2026-11/E-20261103-sox-break-ai-financing-h1.md` 的 `observed_at: '2026-11-03'`，但它描述的 SOX 收盘业务时点是 **11-02**；object-model.md 模板示例两字段同为一天。当前 `observed_at` 实际是"登记日"，业务时点埋在正文散文里。**且最大 writer 就是错的**：`generate_daily_report.py` 的 `write_signal_evidence` 把 observed_at 写成 = 报告日（C6，P1 修，见 §6）。
3. **修订靠散文披露**（事实）：11-02 错行修正是在日报开头手写「数据修正披露」段落 + series 行原地改写，无结构化修订记录。且 series 的合法权威写者不止 persist 一条路（`update_market_series.py` writer=batch 覆盖更新），记账模型必须兼容（C2，见 §3.2）。

数据层闸门管 series 落盘；本方案补**记账层**的同源防线。

## 2. 设计一：证据三时点

### 2.1 字段规范（C1 修：格式与比较规则逐项定义）

| 字段 | 格式 | 语义 |
|---|---|---|
| `observed_at` | `YYYY-MM-DD`（裸日期） | **业务时点 = 事实发生地的当地日历日**。美股收盘按美东日历日，A 股按北京日历日；跨市场事件（如"SOX 破线传导 KOSPI"）主事实在哪发生就填哪 |
| `available_at` | **必填，ISO 8601 带时区时刻**（如 `2026-11-03T05:00:00+08:00`） | 该事实最早可被知晓的时刻。跨时区市场按"交易所当地收盘/公布时刻 + 当期实际时区偏移"换算填写 |
| `recorded_at` | 新文件用带时区时刻；旧文件裸日期按当日 00:00+08:00 归一 | 证据文件写入时刻 |

**单调性判定（lint 实现）**：不做 naive/aware 直接比较（会抛 TypeError），统一**按日粒度包含判定**——`date(observed_at) ≤ date(available_at 换算+08:00) ≤ date(recorded_at 换算+08:00)`，等号允许（同日可得同日记录合法）。YAML 双类型归一：裸 date 与引号字符串先统一解析为字符串再走规则；现有 6 份证据两类混用，lint 必须兼容。

**时区正确性是人工责任**：lint 不做时区数学（DST 换算无法从字段本身证明），skill 提示词写明"填表按当期实际时区偏移"。样板（已修正）：`E-20261103-sox-break` 补为 `observed_at: 2026-11-02`（美东日历日）、`available_at: 2026-11-03T05:00:00+08:00`（美东 11-02 16:00 **EST** 收盘 = 北京 11-03 05:00；11-01 已出 DST，v1 写 04:00 是按 EDT 算错了 1 小时）、`recorded_at: 2026-11-03`。

**与 augur 校验的知情分歧**：augur 禁止 `available_at == retrieved_at`（schemas/evidence.py:167-183）；AWH 保守缺省（旧文件缺 available_at 视为 = recorded_at）是**有意放宽**——语义是"无法证明更早可得"。防静默通过：lint 对缺省文件单独列「未核实」清单，不算通过也不算失败，禁止被当作"已核实"（Minor：保守缺省×封顶）。

### 2.2 关键纪律：复盘的时点封顶

**复盘 / 回看只能采信 `available_at ≤ 复盘基准日` 的证据。**11-30 做 H1 月度回看时，11-03 20:00 才发布的韩国全月出口若被 `available_at: 2026-11-03T20:00+08:00` 标注，就能机器判定它对更早的决策点是否构成后视镜偏差。

### 2.3 兼容与迁移

- **现有 6 份 evidence 一次性补齐**（拍板 2026-11-04）：P0 落地时逐份核定业务时点与可得时点后手工补 `available_at`、修正 `observed_at` 语义。属字段补齐不属修订，不走 amend；6 个 ID 列进实施记录。
- **消费方盘点（C6）**：observed_at 正名是隐式 schema 变更，消费方共三处——`write_signal_evidence`（generate_daily_report.py，P1 修：observed_at 改用 quote 的 tradeDate、available_at 按收盘时刻规则生成）、`system/templates/evidence-entry.md`（P0 加 available_at 字段）、object-model.md 模板（P0）。P1 lint 上线前修复 writer，否则日报天天产生语义错误证据。

### 2.4 落点改动

- `system/integrations/object-model.md`：三时点字段 + 格式规范 + 单调性日粒度规则 + 缺省口径与「未核实」清单。
- `evidence/README.md` + `system/templates/evidence-entry.md`：三时点口径与字段。
- `system/skills/daily-watch.md`：证据登记步骤加"判业务时点与可得时点，跨时区按当期实际偏移填"。
- P1 `system/scripts/evidence_lint.py`：单调性 + available_at 缺省「未核实」清单。

## 3. 设计二：运行账本（RunBundle 的 AWH 最小版）

### 3.1 定位与取舍

不复制快照，要"存在证明 + 修订痕迹"：对产物记哈希，改可以改但必须先记账——**append-only 的不是文件，是账本**。

### 3.2 账本格式：`data/.state/run-log.jsonl`（拍板 2026-11-04）

实例数据，随 `.state/` gitignore，schema 写进 object-model.md。**不轮转不分区**（估算 <2MB/年）。写入分两级：数据侧全自动、报告侧一步命令。

```jsonc
// open：persist_market_data 挂钩自动写。started_at 语义如实 = persist 被调时刻（fetch 是独立子进程，真实抓取开始更早）
{"type":"open","run_id":"RUN-20261103-1630-watch","kind":"daily-watch","trade_date":"2026-11-03","started_at":"2026-11-03T16:30:00+08:00","git_head":"c1656a9","prev_sha256":"…"}
// data-close：persist 挂钩自动写。series 目标用行锚定三元组（见下），missing 来自 fetch meta 结构化降级清单
{"type":"data-close","run_id":"RUN-20261103-1630-watch","at":"...","data_targets":[{"path":"data/market/series/300476.SZ.jsonl","anchor_date":"2026-11-03","sha256":"…"}],"sources_used":["mootdx","nasdaq","eod"],"missing":[{"item":"VIX","reason":"FMP key 未配置"}]}
// close：报告落盘后 skill 一步命令补全（报告哈希与证据登记只有 agent 知道）；evidence_registered 带哈希（I4）
{"type":"close","run_id":"RUN-20261103-1630-watch","finished_at":"...","report":"output/daily-watch/2026-11/2026-11-03.md","report_sha256":"…","evidence_registered":[{"id":"E-20261103-sox-break-ai-financing-h1","sha256":"…"}]}
// amend 两步协议（C3）：步骤1 intent（此刻 post 哈希不存在，记 null）
{"type":"amend","run_id":"RUN-20261103-1630-watch","at":"2026-11-04T08:00:00+08:00","target":"output/daily-watch/2026-11/2026-11-03.md","data_targets":["data/market/series/^SOX.jsonl#2026-11-02"],"reason":"盘前快照错行，按官方收盘修正","post_sha256":null}
// amend 步骤2 --done：改完文件后补完成行
{"type":"amend-done","run_id":"RUN-20261103-1630-watch","at":"2026-11-04T08:05:00+08:00","target":"output/daily-watch/2026-11/2026-11-03.md","post_sha256":"…"}
// abort：运行中止显式记账（I3）
{"type":"abort","run_id":"RUN-20261103-1630-watch","at":"...","reason":"fetch 半途失败"}
```

**行锚定哈希模型（C2 修，拍板：行锚定+两步 amend）**：series 是追加式 jsonl，整文件哈希次日必过期。data-close 的 series 目标记三元组 `{path, anchor_date, sha256}`，其中 sha256 = **对文件中 `date ≤ anchor_date` 的全部行（按文件序）拼接的哈希**。效果：追加新行（date > anchor）不触发 verify；改写旧行（date ≤ anchor 的行内容变化）才触发。报告类目标（md）用整文件哈希。amend 的 `--data-target path#date` 同口径。该模型同时兼容 `update_market_series.py`（writer=batch 权威覆盖，不走 persist）——它的合法覆盖更新若发生在 anchor 之后不影响验证，改 anchor 内旧行则须先 amend。

**账本自身完整性（I10，选尾行哈希链）**：每行带 `prev_sha256`（前一行整行哈希），verify 顺带校验链——整行删除或篡改会断链可见。成本一行一字段。

- `run_id`：`RUN-YYYYMMDD-HHMM-<kind>`，同分钟重试加序号 `-r2`（I3）；kind ∈ `watch / inspect / research / screen / masters / backfill`（I2，六值；backfill 无 close 语义不参与 verify）。
- **生命周期（I3）**：孤儿 open（>24h 无后续）由 verify 列 stale 清单；同报告被多次 close（masters 同日重跑同路径）合法，verify 以**最后一条** close/amend-done 为准；账本写失败必须可感知——hook 内账本子步骤单独捕获，stderr 打印 + 写 `data/.state/run-log.error` sentinel，verify/lint 上报为未决事项（日报本身仍不阻塞，spec §3 不破）。
- research 报告已有的 `preflight_id / knowledge_used / wiki_pages_loaded` 不动，作为 close 行补充字段。

### 3.3 写入者与工具（拍板 #3：persist 挂钩自动；C5 修）

| 子命令/入口 | 作用 |
|---|---|
| `open` / `data-close` | persist_market_data **导入式自动调用**（不走 shell）。逃生门 = 函数参数 `run_log=False` + env `RUN_LOG_DISABLE=1` 双通道（CLI flag 只对 main() 有效，真实路径是 generate_daily_report 导入调用 run_persist_hook——这是 C5 核实的事实） |
| `close --run-id … --report …` | 算 sha256 写 close 行（skill 固定步骤） |
| `amend …` → 改文件 → `amend --done` | 两步协议（拍板 #1）：intent 行 post_sha256=null → 修改 → done 行补哈希。verify 只认 done；有 intent 无 done 列入"未完成修订"清单（崩溃中断可见，天然支持恢复） |
| `verify` | 报告类目标比最新哈希；series 目标比行锚定哈希；校验哈希链；输出未申报修订 / 未完成修订 / 孤儿 open / sentinel 四张清单 |
| `ledger --from D1 --to D2 [--hypothesis H1]` | P2：两次运行之间"变了什么"——evidence 时间线增量 + verdict 变化 + amendment 列表 |

**missing 通路（拍板 #2：改 fetch 写 meta）**：现状 fetch meta 只有 `{state, missing_tickers}`，降级原因只打 stderr 不进 payload；宏观更结构性——`generate_daily_report.py` 调用序是 persist hook **之后**才跑 fetch_macro_data，宏观缺失根本到不了 persist。修法（列入 P1 预算，+30-50 行）：① fetch_market_data 把结构化降级清单写进 meta（`quotes.degradations = [{ticker, source_tried, reason, fallback}]`）；② 宏观调用序前移到 persist hook 之前，fetch_macro_data 同理输出降级清单；③ run_persist_hook 把 meta 降级清单透传成 data-close 的 missing 数组。`run_persist_hook` 现状吞一切异常（persist_market_data.py:147-154，spec §3"永不阻塞日报"）——持久化吞照旧，**账本写不吞**（单独捕获 + sentinel，见 §3.2）。

### 3.4 修订纪律（写进 skill 步骤）

> 任何对已 close 运行产物的修改（报告正文、series 行、evidence 文件），**先 `run_archive.py amend` 记 intent，改完 `amend --done`**；两步都不可省。漏记会被 verify 抓出。「数据修正披露」散文段保留（给人看），amend 行是其机器可读镜像。

**豁免条款（I4）**：evidence frontmatter 的**状态字段合法迁移**（`review_status: pending→confirmed`、`direction: pending→strengthen` 等生命周期动作）**不属修订**，不触发 amend 义务；正文/观察段/来源段的改动才是。目标句相应收窄：**"close 时登记的产物（报告 + evidence 文件 + series 行锚定区间）可机检"**——close 之后的 evidence 正文改动若未 amend，verify 能抓（evidence_registered 带哈希）；复盘推动的状态迁移不误报。

## 4. 设计三：显式缺数与弃权（abstain）

### 4.1 判定词表（I1 修：定四值，blocked 情形降级）

| verdict | 含义 | 记账要求 |
|---|---|---|
| `normal` | 查了，未触发 | 记 as_of 与关键读数 |
| `warn` | 接近预警线 / 一级压力 | 同上 + 距离 |
| `trigger` | 触发（压力升级 / 证伪证据） | 同上 + 关联 evidence ID |
| `missing` | 该查没查成（源挂、停市、key 缺、口径断裂、**关键证据 pending review**） | 必须写 `reason` + **补数命令** |

复盘时关键证据 `review_status: pending` 的情形**统一降级为 missing**（reason: `关键证据 pending review [E-ID]`）——语义差异在 reason 表达，词表不膨胀到五值。

### 4.2 行格式与文法（I5：最小文法进 object-model.md）

```
- YYYY-MM-DD | check: <检查项id> | verdict: <四值之一> | as_of: <读数时点> | reading: <值或—> | evidence: <E-ID或—> | 补数: <仅missing时必填，可执行命令> | reason: <仅 missing 必填，禁竖线>
```

文法固定：字段序不可变（八槽，`reason` 为第八槽——missing 判行必填原因，与 object-model.md 已落地口径一致）；空值统一 `—`；**值内禁竖线**（`|` 是分隔符）；补数命令为自由文本但同样禁 `|`。ledger 脚本按此文法解析，解析失败显式报错降级为"人工读取"，不静默跳过。

**落点补 I11**：巡检流程此前从未被文档化（grep 证实，H1 的巡检记录是单假设正文里的实践）——P0 在 `hypothesis-tracker.md` 新增「巡检流程」段（从零新增，非修改现有段，工作量如实计入 P0）。

### 4.3 复盘弃权规则（写进 hypothesis-review skill）

- 复盘基准日之后才 `available_at` 的证据 → 弃权：不计入当期判定，单独列出（"后视镜证据，留待下期"）。
- 关键证据 pending review → 判定降级 missing（§4.1），不允许 silently 当 confirmed 用。

### 4.4 daily-watch 报告侧

「市场概览」N/A 行保留散文形式；新增要求：**假设联动段每个检查点带 verdict 标签**，与巡检行同词表同文法。

## 5. 大师面板（拍板：引入 18 大师 + 共识 + Kelly；P3/P4）

### 5.1 augur 源码事实（2026-11-04 读源码 + 评审复核）

- **引擎与数据层解耦**：`src/augur/personas/base.py`（**303** 行；scanner/personas/base.py 是 10 行 shim，vendoring 唯一来源是 src 下这份）定义 `MarketContext`（纯数据类，含 `field_availability` 与 `as_of_date`）、`AgentResponse`、`BaseAgent`；18 个 persona（合计 **4,144** 行）各自是纯函数 `analyze(MarketContext) -> AgentResponse`——规则阈值打分，零 LLM 零联网。
- **abstain 语义的真实位置（I8 事实）**：18 个 persona **无一读 `field_availability`**（全 src 检索：仅 base.py 定义处引用）；它们按**数据数值**推断覆盖度（如段永平 0.75/0.4 档），且 `MarketContext` 非 ownership 字段默认 `0`——缺失字段的值语义是"0"不是"缺"，见 §5.3 硬约束。
- **共识核心**：`engine.compute` 主干 = 信号计数 + 行业加权 + 置信度校准（12 行）+ half-Kelly（`pct = min(20, edge×conf×0.5×100)`，含 score≥阈值且 conf≥0.5 时 1% 保底分支）+ 权重收敛（~25 行）。但 compute 内还嵌 sentiment 调用、MetaModel、RiskManager、agent 相关性惩罚、ten_x、learning 预测记录（I7），剥离清单见 §5.2。rolling-IC / 学习权重默认关闭（`AUGUR_FORCE_*` 门控）——**不搬**。
- **行业路由已内置 A 股（I9 事实）**：`industry_matrix.classify` 先查 ticker 后缀（`.SZ/.SS/.SH/.HK` → `"china"` 键，中国大师权重 duan 1.45 / zhang_lei 1.35 / li_lu 1.3 / dan_bin 1.22 / dayu 1.18 / munger 1.05）。**申万 sector 映射会被 ticker 后缀短路**——适配层必须直填行业键，见 §5.3。
- **英文 sector 关键词是普遍面（Minor 修正）**：buffett、duan_yongping 及引擎本体（engine.py:158-173）都有英文 sector 匹配，不是"个别 persona"——适配层填 sector 字段时须给英文关键词。
- ARPS 是 Crypto/Gold 专属、Serenity 是美股小票 Twitter 交易者画像——**A 股常驻弃权**，计入 §5.5 弃权常态。

### 5.2 移植面与不移植面

**移植**（vendored 到 `tools/masters/augur_core/`，文件头注明 MIT + 来源仓库 + 锁定 commit，不追 HEAD；总量约 **4,800** 行 = base 303 + personas 4,144 + consensus 核心 ~300）：

| 模块 | 行数（约） | 改动 |
|---|---|---|
| `personas/base.py` | 303 | 删 `_merge_saved_thresholds` feedback 钩子（base.py:247-255，AWH 无 feedback 数据），其余原样 |
| 18 个 persona 文件 | 4,144 | **最小改动搬运**：`from augur.personas.base import …` 绝对导入统一改 vendored 包路径（一行/文件），其余逐字节 |
| 共识核心 | ~300（预算自 ~200 上调，I7） | engine.compute 主干摘取；**剥离裁决清单**：删 sentiment 调用、MetaModel、RiskManager、agent 相关性惩罚、ten_x、learning 预测记录（无 feedback 数据时本来走空路径，直接删调用点）；行业加权砍 macro_features（传递依赖 import yfinance）与 regime_router，**只留 `get_agent_weights(industry)` 纯函数** + `restrict_weights_to_agents`；保留 calibrate_confidence + half-Kelly（含 1% 保底） |

**不移植**：rolling-IC / 学习权重 / oos_harness（augur 未过样本外验证的实验）；EDGAR 五件套（美股数据层）；Dashboard / MCP / bots / CLI / 回测评估；RunBundle 导出（§3 已替代）。

### 5.3 A 股数据适配层（AWH 自建，`tools/masters/adapter.py`，预算 ~400 行）

适配层做两件事：把 AWH 数据填进 MarketContext（TTM 口径，拍板 #4）；让"缺失"对打分**可见**。

**期间口径（拍板 2026-11-04：P3 即做 TTM，未采用单期年化）**：

- gpcw 按 code 拉最近 4 期（mootdx Affair，148 期可用），TTM 营收/归母净利按 A 股披露节奏滚动公式合成（`TTM(t) = FY(t-1) + 累计(t) − 累计(t同期上年)`，Q1/H1/Q3/FY 节奏，公式写在适配层注释可复核）；缺期自动补拉并按现有规范落 `data/finance/gpcw-{period}.jsonl`。
- `MarketContext.revenue / profit_margins` 等期间字段一律 TTM；报告"数据截至"注明 TTM 窗口（如 2025Q4-2026Q3）与 gpcw report_date。
- 增长字段（revenue_yoy / net_profit_yoy / deducted_yoy）用 gpcw 交易所口径直值，不自算。
- **shares = 归母净利 / eps 反推**（I6 实测：净资产/bps 法 300476 得 9.83 亿股 vs eps 法 9.32 亿股，+5.5% 系统偏差——总资产−总负债含少数股东权益而 bps 是归母口径；eps 法与市值/PE 自洽）。推导链注释可复核。
- `field_availability` + `as_of_date` 照填（供报告与后续消费者），但对打分的作用见下。

**缺失可见性硬约束（I8）**：persona 不读 field_availability，只填该字典对打分**不可见**；且缺省 0 会引来错误加分（实例：debt_ratio 缺失=0 被 duan_yongping 当"极低负债"+1.5，duan_yongping.py:110-111）。适配层两级处理：

1. **依赖表**（P3 交付物）：从 18 个 persona 源码逐个核对"因子 → 依赖字段"，产出 `persona×因子→字段` 映射表，重点覆盖"缺省值引来加分"的字段（debt_ratio / current_ratio 等 `< 阈值加分` 型）。
2. **后处理**：`analyze` 返回后按依赖表重算 `coverage_confidence`（缺失关键字段 → 降档），报告该大师条目标注"因子 X 基于缺省值，已降权"。coverage_confidence 参与共识权重（augur 原生），降权自动传导进共识。

**行业路由对齐（I9）**：适配层**不走 `classify(ticker)`**——A股行业映射表直接产出 industry_matrix 的行业键（`.SZ/.SS` 后缀本来就会短路进 `"china"`，映射表负责在 china 之上细化，如科技/消费键），调 `get_agent_weights(industry_key)`；同时映射表第三列给英文 sector 关键词填 `MarketContext.sector`，让 persona 与引擎的英文匹配吃到。映射表初版只覆盖 watchlist 21 只 + 常见申万一级；缺失回落 `"china"`+general。

**字段映射表**（Minor 修正后）：

| MarketContext 字段 | AWH 来源 | 状态 |
|---|---|---|
| roe / revenue（TTM）/ revenue_growth / earnings_growth / eps（TTM） | gpcw 四期合成 + 直值 | 直接 |
| debt_ratio / profit_margins（TTM） | gpcw 推导 | 直接 |
| shares（内部推导）→ market_cap / pe / pb / ps | shares=归母净利/eps；× series 收盘价 | 推导链注释可复核（MarketContext 无 bps/shares 字段，此为适配层中间量） |
| price / change_pct / price_vs_52w_high/low / sma20 / sma50 / sma200 / rsi / atr 等技术指标 | `data/market/series/*.jsonl`（行内字段名 `date`，非 as_of） | 直接计算 |
| sector / industry | 行业映射表（申万一级 → augur 行业键 + 英文关键词） | 新增映射表 |
| gross_margins / operating_margins / fcf / current_ratio / quick_ratio / insider_ownership / institutional_ownership | gpcw 无 | **missing** → 依赖表+后处理降权，报告明说"半盲"；P4 可选接东财 F10 补毛利率/流动比率 |
| ETF / 指数 / 美股 / 韩股标的 | 不适用或数据层不支持 | **abstain**（见 §5.5 边界） |

### 5.4 集成点与输出

- 新 skill：`system/skills/masters.md`；工具与 vendored 引擎：`tools/masters/`；输出：`output/masters/YYYY-MM/<ticker>-<date>.md`。
- 报告结构：各位大师 signal/score/关键发现/风险/盲区说明 → 共识（加权分、置信度、信号）→ **分歧清单**（谁在哪个因子上对立、各自理由）→ half-Kelly 建议仓位（明示公式、1% 保底与 20% 上限假设）→ 数据截至（TTM 窗口）与 missing 清单。
- run-log：kind `masters` 的 open/close 自动入账，同日重跑同报告路径按 §3.2 多 close 规则处理。
- 分歧 → 研究问题：报告尾部分歧清单可整理为研究问题候选进 review-queue。
- 日报/巡检联动（P4 可选）：daily-watch 重点异动票附一行"大师面板快照"链接。

### 5.5 边界纪律

1. **大师输出 = 规则化模拟观点 = 推测层**：不是 evidence，不进 `evidence/`，不写 hypothesis frontmatter。报告页眉固定声明：模拟观点基于公开投资理念的规则化实现，不代表本人立场，不构成投资建议。
2. **Kelly 是建议数字不是指令**：只出现在报告；`portfolio/` 写入照旧只走 review-queue。
3. **缺数据不编造 + 弃权是常态**：A 股个股 18 位中常态 **16 位参与**（ARPS/Serenity 常驻弃权，报告注明）；ETF 全员 abstain；缺毛利率/FCF 的半盲大师降权并说明——宁可 16 位发言里再有几个半盲，不出全勤假象。P4 批量口径：watchlist 21 只 = **17 只 A 股个股跑 + 4 只 ETF abstain（19%）**；NVDA / 000660.KS / ^SOX / 商品属界外（美股/韩股/指数无 gpcw 财务面），面板声明边界，留待数据源扩展。
4. **大师意见一致性可作辅助观察**（P4 之后）：作为假设的辅助观察项，自身不构成任何触发。

### 5.6 其余明确不引入的部分

| augur 机制 | 不引入原因 |
|---|---|
| RunBundle 多格式导出 / evidence-pack | AWH 产物即纯 markdown，指针 + 哈希够用 |
| MCP server / Dashboard / bots | 已有 ZCode 工作流，不重建入口 |
| rolling-IC / 学习权重 / oos_harness | augur 自己默认关闭且未过样本外验证 |
| EDGAR 数据五件套 | 美股数据层；AWH 用 gpcw/series/映射表 |

## 6. 实施阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0 纯约定**（改 5 个文档 + 1 个模板，零代码） | object-model.md（三时点规范 + run-log schema + verdict 词表与文法）；evidence/README + **evidence-entry.md 模板**（C6）；hypothesis-tracker.md（**新增巡检流程段**，I11）；daily-watch、hypothesis-review skill 同步；**6 份 evidence 一次性补齐** | **grep 可判定（C4 修）**：6 份 frontmatter 均含 available_at 且格式合规（带时区时刻）；落点文档 grep 得到三时点规范与 verdict 文法。lint 全绿留 P1 |
| **P1 两个脚本一起做 + 三处管线修复** | `evidence_lint.py`（日粒度单调性 + 双类型归一 + 缺省「未核实」清单）；`run_archive.py`（行锚定哈希、两步 amend、尾行哈希链、孤儿 open/abort/碰撞序号、verify 四清单）；persist 挂钩（open/data-close 自动，函数参数+env 逃生门，账本写失败 sentinel）；**fetch meta 结构化降级清单 + 宏观调用序前移**（拍板 #2，+30-50 行）；**write_signal_evidence 修复**（observed_at 用 tradeDate、available_at 按收盘时刻规则，C6） | lint 对 6 份证据全绿；verify 演练四项：①追加新行不触发、改 anchor 内旧行触发（C2）；②amend 两步走通、中途 kill 留 intent 无 done 被 verify 列出（C3）；③人为篡改报告被抓；④data-close 的 missing 与真实降级链一致（C5） |
| **P2 ledger/delta** | `run_archive.py ledger`：给定假设 + 日期区间，输出证据增量、verdict 变化、修订历史 | 验收窗口 = **账本启用日至今**（I10 修；10-31→11-04 等历史区间以 `retro:true` 人工补录演示，可选） |
| **P3 大师引擎移植**（可与 P1/P2 并行，无依赖） | vendored `augur_core/`（锁 commit，剥离清单 §5.2）+ `adapter.py`（**TTM 四期合成 + eps 反推 shares**（拍板 #4）+ 行业键直填 + 英文 sector 关键词 + 依赖表与 coverage 后处理）+ 单票 CLI | 300476.SZ 跑通：16 位参与/2 位常驻弃权、缺字段大师降权并说明、共识 + half-Kelly、报告落 `output/masters/`、run-log 有 close 行；**TTM 正确性抽验**：TTM 净利与手工滚动公式对拍一致、shares 与市值/PE 自洽 |
| **P4 大师集成** | watchlist 批量（17 股 + 4 ETF abstain + 界外声明）、screen 集成、分歧→review-queue、（可选）东财 F10 补毛利率/流动比率 | 17 只批量跑完产出对比表；至少一条分歧转成研究问题进队列 |

依赖：P0-P2 全标准库；P3 vendored 引擎核心只用 stdlib，适配层读本地 jsonl + mootdx 拉四期；python 走 conda Quant-3.11。

## 7. 风险与防臃肿自查

- **摩擦风险**：amend 两步依赖 agent 自觉 → verify 四清单兜底 + friction-log 硬规则（第 2 次出现即修根）。
- **格式漂移**：verdict 文法进 object-model.md；ledger 解析失败显式降级"人工读取"，不静默跳过。
- **三真相源无重叠**：verdict 是历史事件（正文区），run-log 是存在证明（账本），evidence frontmatter 是状态唯一来源；大师面板输出是推测层分析产物，不新增状态真相源。
- **规模（评审后如实）**：P0 改 5 文档 + 1 模板 + 补 6 份 evidence；P1 两脚本 ~400-500 行 + persist/fetch/报告侧管线改动 ~80-100 行；P2 一个子命令；P3 vendored ~4,800 行（90% 逐字节/最小改动搬运）+ 适配层 ~400 行（含 TTM 与依赖表）；P4 集成 ~200 行。不引第三方依赖。
- **大师面板特有风险**：① gpcw 缺毛利率/FCF → 半盲降权是常态不是缺陷（诚实半盲优于全勤假象；P4 可选补源）；② vendored 与上游分叉 → 锁 commit 不追 HEAD，升级手动 re-vendor；③ 行业映射表新维护面 → 保持小，缺失回落 china/general；④ half-Kelly 参数沿用 augur 默认（20% 上限、半 Kelly、1% 保底）→ 报告明示，跑几轮有体感再调（评审开放问题 3 的既定答案）；⑤ TTM 四期拉取引入数据面依赖 → 拉取失败按 missing 降级走 §4 词表，不阻塞面板其余字段。

## 8. 决策记录与开放问题

**用户拍板（2026-11-04，五项）**：

| # | 议题 | 决策 |
|---|---|---|
| 1 | run-log 位置 | `data/.state/run-log.jsonl` |
| 2 | P1 范围 | lint + run_archive 一起做 |
| 3 | close 写入者 | persist 挂钩自动（open/data-close 全自动；close 报告侧 skill 一步补全） |
| 4 | 现有 6 份 evidence | P0 一次性补齐 available_at |
| 5 | 18 大师 / Kelly | 引入（P3 移植 + P4 集成） |

**评审拍板（2026-11-04，四项）**：

| # | 议题 | 决策 |
|---|---|---|
| 1 | amend 协议（C2/C3） | **行锚定 + 两步 amend**（推荐项） |
| 2 | missing 通路（C5） | **改 fetch 写 meta + 宏观调用序前移**（推荐项，+30-50 行入 P1 预算） |
| 3 | 处置方式 | **全部修订落设计文档**（推荐项；本 v2 即处置结果，6C/11I/Minor 全修） |
| 4 | P3 期间口径（I6） | **P3 即做 TTM**（四期滚动 + eps 反推 shares；未采用推荐项"单期年化"，评审开放问题"启动前再拍"提前锁定为 TTM） |

**开放问题（剩余，不阻塞开工）**：

1. P3 与 P1/P2 并行还是串行？（技术无依赖，可并行；串行则记账层先稳）
2. 行业映射表初版范围：仅 watchlist 21 只 vs 申万一级全集？
3. ~~half-Kelly 参数~~ 已定：首版照搬 augur 默认（20% 上限、半 Kelly、1% 保底）+ 报告明示，跑几轮有体感再调。
