# 实施计划：augur 借鉴四机制（P0-P4）

> 权威 spec：`workspace/proposals/2026-11-04-augur-borrowing-design.md`（v2，评审闭环版）。冲突以 spec 为准，本计划是它的任务化论证。
> 分支：`feat/augur-borrowing`（自 c6cbac1）。

## Global Constraints（全任务绑定）

1. **Python 一律 `conda run -n Quant-3.11 python ...`**（系统 Python 是 PEP 668 管理的 3.15）。
2. **测试**：`conda run -n Quant-3.11 python -m pytest tests/ -q`，现有 271 用例必须全绿，新功能配套新测试文件放 `tests/`。测试输出必须干净（无 stray warning）。
3. **Lint**：`ruff check`（规则集 E4/E7/E9/F）必须过，改动文件零告警。
4. **提交**：中文 `type: subject`，按关注点拆 commit；**不推送**；`hypothesis/*`、`evidence/*` 内容是 gitignore 实例数据——**绝不 `git add -f`**。
5. **run-log 哈希语义**（spec §3.2 逐字）：series 目标 = 三元组 `{path, anchor_date, sha256}`，sha256 对文件中 `date ≤ anchor_date` 的全部行（按文件序）拼接计算；追加新行不触发 verify，改写旧行才触发。报告类目标用整文件 sha256。
6. **两步 amend**：`amend` 记 intent（`post_sha256: null`）→ 改文件 → `amend --done` 补完成行；verify 只认 done。
7. **尾行哈希链**：账本每行带 `prev_sha256`（前一行整行哈希，首行为 null），verify 校验链。
8. **verdict 四值词表 + 固定文法**（spec §4）：`- YYYY-MM-DD | check: <id> | verdict: normal|warn|trigger|missing | as_of: <时点> | reading: <值或—> | evidence: <E-ID或—> | 补数: <missing 必填>`；值内禁竖线；空值用 `—`。
9. **三时点格式**（spec §2.1）：`observed_at` 当地日历日（裸日期）；`available_at` 必填 ISO 8601 带时区时刻；`recorded_at` 新文件带时区时刻；单调性按日粒度包含判定（先换算 +08:00 再取 date）。
10. **vendored 代码**（spec §5.2）：只搬 `src/augur/personas/base.py`（303 行，删 `_merge_saved_thresholds`）+ 18 个 persona（合计 4,144 行，仅改 import 行）+ 共识核心（剥离 sentiment/MetaModel/RiskManager/agent 相关性惩罚/ten_x/learning 预测记录、macro_features/regime_router，只留 `get_agent_weights` 纯函数 + `restrict_weights_to_agents` + `calibrate_confidence` + half-Kelly 含 1% 保底）；文件头注明 MIT + 来源仓库 + 锁定 commit；**不搬** rolling-IC/学习权重/EDGAR/Dashboard/MCP。
11. **大师面板边界**（spec §5.5）：输出是推测层分析产物——不写 `evidence/`、不写 hypothesis frontmatter、Kelly 只出现在报告、`portfolio/` 不自动写；ARPS/Serenity A 股常驻弃权；ETF/指数/美股/韩股 abstain。
12. **适配层硬约束**（spec §5.3）：persona 不读 `field_availability` 且非 ownership 字段默认 0——缺失必须经「persona×因子依赖表 + analyze 后重算 coverage_confidence」两级处理体现；shares = 归母净利/eps 反推（禁用净资产/bps 法，+5.5% 偏差）；TTM 四期滚动公式 `TTM(t) = FY(t-1) + 累计(t) − 累计(t同期上年)`。
13. 不引第三方依赖（P0-P2 全标准库；vendored 引擎只用 stdlib；适配层读本地 jsonl，mootdx 已在环境内）。

---

## Task 1: P0 约定落地（6 处文档/模板 + 6 份 evidence 补齐）

**改动文件**（spec §2.4 / §3.2 / §4.2 落点）：

1. `system/integrations/object-model.md`：
   - 「证据最小字段」段升级为三时点规范：字段表（observed_at/available_at/recorded_at 格式与语义，逐字按 Global Constraint 9）+ 单调性日粒度包含判定 + 旧文件缺省口径（缺 available_at 视为 = recorded_at，lint 单列「未核实」清单）+ 与 augur 禁等值校验的知情分歧声明一句；
   - 新增「运行账本」段：`data/.state/run-log.jsonl` 的行类型（open/data-close/close/amend/amend-done/abort）、行锚定哈希语义（逐字按 Global Constraint 5）、两步 amend、尾行哈希链、kind 六值（watch/inspect/research/screen/masters/backfill）、孤儿 open/`-r2` 碰撞/同报告多 close 取末条、不轮转不分区；
   - 新增「巡检判定词表」段：verdict 四值语义表 + 行文法（逐字按 Global Constraint 8）。
2. `evidence/README.md`：约定段加三时点一行口径。
3. `system/templates/evidence-entry.md`：frontmatter 加 `available_at:`（带时区时刻示例）；`observed_at` 注释改「业务时点（当地日历日）」；`recorded_at` 改时刻格式示例。
4. `system/integrations/hypothesis-tracker.md`：新增「巡检流程」段（此前从未文档化，从零新增）：巡检=按假设 frontmatter `next_review_at`/温度计设定对检查点逐项判定，判定行用 verdict 文法记入假设正文「巡检记录」区，missing 必带补数命令；引用 object-model 词表。
5. `system/skills/daily-watch.md`：证据登记步骤加「登记前判业务时点与可得时点，跨时区按当期实际偏移填 available_at」；新增「运行账本」小节：报告落盘后一步 `python3 system/scripts/run_archive.py close --run-id … --report …`；修订纪律（先 amend intent → 改 → amend --done）。
6. `system/skills/hypothesis-review.md`：复盘弃权规则两条（available_at 晚于基准日的证据弃权单列；关键证据 pending → 判定降级 missing 带 reason）。

**6 份 evidence 一次性补齐**（文件在 `evidence/2026-10/`、`evidence/2026-11/`，gitignore 实例数据，改完不 git add）：

| 文件 | observed_at（业务时点） | available_at（核定依据） |
|---|---|---|
| E-20261031-earnings-300476sz-H1 | 三季报披露日（读正文来源定 10-30 或 10-31） | 披露当日盘后时刻（如 2026-10-30T16:00:00+08:00，按正文实际披露时点核定） |
| E-20261031-mover-300476-sz-h1 | 2026-10-31 | 2026-10-31T15:00:00+08:00（A 股收盘） |
| E-20261102-mover-000660ks-h1 | 2026-11-02 | 2026-11-02T15:30:00+09:00（KOSPI 收盘，KST） |
| E-20261102-mover-300476sz-h1 | 2026-11-02 | 2026-11-02T15:00:00+08:00 |
| E-20261103-mover-300476-sz-h1 | 2026-11-03 | 2026-11-03T15:00:00+08:00 |
| E-20261103-sox-break-ai-financing-h1 | **2026-11-02**（正名，现错写 11-03） | **2026-11-03T05:00:00+08:00**（美东 11-02 16:00 EST 收盘） |

`recorded_at` 保持原值（登记日）；YAML 引号串格式统一（全部引号串，避免裸 date 混型）。

**验收（grep 可判定）**：6 份 frontmatter 均含 `available_at:` 且带 `+08:00`/`+09:00` 时区偏移；object-model.md grep 到 `行锚定`/`amend-done`/`prev_sha256`/`verdict`；模板 grep 到 `available_at`。

**提交**：文档/模板改动一个 docs commit；evidence 改动不提交（gitignore）。

## Task 2: run_archive.py（账本核心）

新文件 `system/scripts/run_archive.py` + `tests/test_run_archive.py`。全标准库（json/hashlib/argparse/datetime/pathlib）。既是 CLI 也是被 T4 导入的库（公开函数 + CLI 薄壳）。

**数据模型**（逐字按 Global Constraints 5-7；行类型与字段见 spec §3.2 代码块）：
- 账本路径默认 `data/.state/run-log.jsonl`（相对仓库根解析；`--data-root` 可覆盖，测试用 tmp 目录）。
- `run_id` = `RUN-YYYYMMDD-HHMM-<kind>`；同 run_id 已存在且状态未终结时新开 run 追加 `-r2`/`-r3` 序号。
- 每行写入时算 `prev_sha256`（前一整行含换行的 sha256，首行 null）。

**CLI 子命令**：
- `open --kind K --trade-date D`：写 open 行（started_at=当前时刻、git_head=`git rev-parse --short HEAD`，失败 null）；打印 run_id。kind 六值校验。
- `data-close --run-id R --data-target path[:#anchor]... --sources s1,s2 --missing-json '...'`：series 目标算行锚定哈希；path 是 md 文件算整文件哈希（按扩展名 .jsonl 判定）。missing 数组透传。
- `close --run-id R --report P --evidence E-ID[:sha256]...`：报告整文件 sha256 + evidence_registered [{id, sha256}]。
- `amend --run-id R --target P --reason TXT [--data-target path#date]...`：写 intent 行（post_sha256=null）。
- `amend --done --run-id R --target P`：写 amend-done 行（改后哈希）。
- `abort --run-id R --reason TXT`。
- `verify [--json]`：四张清单——①未申报修订（报告/masters 报告整文件哈希 vs 最后一条 close/amend-done；series 行锚定哈希重算比对）②未完成修订（intent 无 done）③孤儿 open（>24h 无 data-close/close/abort）④sentinel（存在 `data/.state/run-log.error` 即列出）；外加哈希链校验（断链行号）。退出码：全部干净 0，任一非空 1。
- `ledger`：Task 5 实现，本任务留 argparse 占位（`parser error: not implemented`）。

**库 API**（T4 导入用）：`append_open(data_root, kind, trade_date) -> run_id`、`append_data_close(data_root, run_id, data_targets, sources_used, missing)`、`append_amend(data_root, run_id, target, reason, data_targets=None, done=False)`、`row_anchor_hash(path, anchor_date)`、`verify_ledger(data_root) -> dict`。所有 append 函数失败**抛异常**（不吞——调用方 T4 决定怎么处理）。

**测试**（`tests/test_run_archive.py`，tmp_path 账本，不发网络不碰真实 data/）：
1. open→data-close→close 全链 + prev_sha256 链正确（逐行重算验证）；
2. 行锚定：写 3 行 series jsonl，data-close 锚 date=第 2 行；追加第 4 行 → verify 干净；改第 1 行内容 → verify 报未申报；
3. 两步 amend：amend 后 verify 列未完成；amend --done 后干净；
4. 同分钟碰撞 → -r2；
5. 孤儿 open：open 后伪造 25h 前时间戳（monkeypatch 或直接改行）→ verify 列出；
6. abort 后 verify 不追其 close；
7. 哈希链篡改（删中间行）→ verify 报断链；
8. kind 非法值被拒。

## Task 3: evidence_lint.py

新文件 `system/scripts/evidence_lint.py` + `tests/test_evidence_lint.py`。全标准库。

**规则**（spec §2.1 逐字）：
- 扫 `evidence/YYYY-MM/*.md`（`--evidence-root` 可覆盖），解析 frontmatter（简易 YAML：仅取顶层标量键，够用；不引 pyyaml——检查环境无 pyyaml 时保持零依赖，有则可用但不强制）。
- 双类型归一：observed_at/recorded_at 接受裸 date 或引号串；available_at 必须可解析为带时区 datetime（无时区 → 违规）。
- 单调性（日粒度包含）：`date(observed) ≤ date(available→+08:00) ≤ date(recorded→+08:00)`；违规 = error。
- 缺 available_at → 「未核实」清单（单独输出，不算 pass 不算 fail）。
- 输出：errors 清单（文件+字段+原因）、unverified 清单、`--json` 模式；退出码 errors>0 → 1，仅 unverified → 0。

**测试**：合法文件、observed>available 违规、available 无时区违规、缺 available 入 unverified、双类型（裸 date vs 引号串）等价、空目录。

## Task 4: 管线接线（persist 挂钩 + fetch meta + 宏观前移 + writer 三时点修复）

**4a `tools/daily-watch/scripts/persist_market_data.py`**：
- 导入 `system/scripts/run_archive.py`（sys.path 处理参考仓库现有跨目录导入先例，查 `tests/conftest.py` 或 scripts 内既有做法）。
- `run_persist_hook(market_data, data_root=None, run_log=True)`：run_log=True 时——进入即 `append_open(kind="watch", trade_date=今日)`（注意 spec：started_at=persist 被调时刻，如实）；成功路径在 snapshot+series 落盘后 `append_data_close`（data_targets=本轮写入的 series 文件行锚定三元组 + sources_used 从行内 source 字段汇总 + missing 从 meta 降级清单透传）。
- **账本子步骤单独 try/except**：失败时 `print(..., file=sys.stderr)` + 写 sentinel `data/.state/run-log.error`（内容：时间+异常），**不抛**（日报不阻塞，spec §3 不破）；持久化本身的吞异常逻辑不变。
- 逃生门双通道：函数参数 `run_log=False` 或 env `RUN_LOG_DISABLE=1`。
- 现有测试全部保持绿；新增：挂钩写 open+data-close（mock fetch payload，断言账本行）、RUN_LOG_DISABLE 跳过、账本失败产生 sentinel 且不抛（monkeypatch append_open 抛）。

**4b `tools/daily-watch/scripts/fetch_market_data.py`**：meta 升级——`quotes.degradations: [{ticker, source_tried, reason, fallback}]`（+30-50 行预算）：现有降级重试链处（先读懂现有 fallback 结构）把「打 stderr 的降级原因」结构化收集进 payload。不改变行为，只增信息。

**4c `tools/daily-watch/scripts/generate_daily_report.py`**：
- 调用序前移：`fetch_macro_data` 移到 `_persist_market_data_hook` **之前**（宏观降级清单也能进 data-close 的 missing；宏观 payload 若有 meta 同理透传）。注意 macro_data 现有消费位置不变，只挪 fetch 调用点。
- `write_signal_evidence` 修复：`observed_at` 改用 quote 的 `tradeDate`（读现有 quote dict 结构确认字段名；无 tradeDate 回退报告日并在正文注明）；`available_at` 按 Global Constraint 9 规则生成（A 股 15:00+08:00；若信号涉美股指数按 spec §2.1 样板 05:00 EST 逻辑——从 signal 数据可得的市场判定，判定不了就 A 股口径+注明）；`recorded_at` 用带时区时刻。
- 新增/更新测试：write_signal_evidence 三时点断言（observed=tradeDate≠报告日的场景）、宏观前移后 hook 调用序断言。

**验收**：271+新增全绿；手动冒烟（mock payload 走 run_persist_hook）账本出现 open+data-close 两行且 missing 与降级清单一致。

## Task 5: run_archive.py ledger 子命令

`ledger --from YYYY-MM-DD --to YYYY-MM-DD [--hypothesis H1] [--json]`：
- 读账本：区间内 close/amend-done/abort 行 → 运行清单 + 修订历史；
- 读 evidence（`evidence/**/*.md` frontmatter）：`recorded_at` 落区间（或 linked_hypotheses 命中）→ 证据增量（ID+direction+review_status）；
- 读 hypothesis 文件正文巡检行（按 Task 1 文法解析）：区间内 verdict 行 → 变化清单；**解析失败显式报错降级**（打印无法解析的行，不静默跳过）；
- 输出 markdown 三段：运行与修订 / 证据增量 / 判定变化。
- 测试：构造 tmp 账本+tmp evidence/假设正文，断言三段内容；文法坏行走降级路径。

## Task 6: vendored augur_core 引擎移植

新目录 `tools/masters/augur_core/`（含 `__init__.py`、`personas/`、`consensus/`）。**来源：`/Users/berton/Github/Invest/augur/src/augur/`**（只读参考仓）。先 `git -C /Users/berton/Github/Invest/augur rev-parse HEAD` 记录锁定 commit 写进每个文件头。

- `personas/base.py`：拷贝 303 行版本，删 `_merge_saved_thresholds` 方法及 `__init__` 中的调用（Global Constraint 10），头注 4 行（MIT / 来源 repo / 锁定 commit / 本地改动说明）。
- `personas/` 18 个 persona 文件：逐字节拷贝，仅 import 行 `from augur.personas.base import` → `from augur_core.personas.base import`。
- `consensus/`：新写 `engine.py`（从 augur engine.compute 摘取主干：信号计数、行业加权 `get_agent_weights`、置信度 `calibrate_confidence`、加权评分、half-Kelly 含 1% 保底与 20% 上限、`restrict_weights_to_agents`）；`industry_matrix.py` 拷贝（151 行，保留 china 键与中国大师权重、`get_agent_weights`、`detect_industry` 一并保留供适配层选择）；`calibration.py`（12 行 calibrate_confidence）+ `weighting.py` 的 `restrict_weights_to_agents`。**剥离**：sentiment/MetaModel/RiskManager/agent 相关性惩罚/ten_x/learning 预测记录/rolling-IC/feedback 文件加载/macro_features/regime_router 的全部调用点。
- `registry.py`（新，~30 行）： persona 实例化清单 + `analyze_all(context) -> dict[str, AgentResponse]`。

**测试** `tests/test_masters_engine.py`：**importlib 对拍**（仓库有先例）——用 importlib.util 从 augur 原仓直接加载原版 persona 模块，与 vendored 版对同一 MarketContext 输入断言 AgentResponse 逐字段一致（18 位全测；需构造含中英文 sector、缺省 0 字段的 context 样本）；vendored consensus engine 对固定 18 个 response 输出共识分/Kelly 与手工计算一致（含 1% 保底触发场景、20% 上限截断场景）。

**提交**：vendored 拷贝与 consensus 重构分两个 commit。

## Task 7: 适配层 adapter.py + 单票 CLI

新文件 `tools/masters/adapter.py`、`tools/masters/industry_map.json`、`tools/masters/persona_deps.json`、`tools/masters/run_masters.py`（CLI）+ `tests/test_masters_adapter.py`。

- **TTM 合成**：`ttm_financials(code) -> dict`——优先读本地 `data/finance/gpcw-*.jsonl`（按 report_date 降序取可用期），不足 4 期时经 mootdx Affair 补拉（复用 `tools/daily-watch/scripts/` 现有财务拉取实现，先读懂 `update_finance_snapshots.py`；补拉按现有规范落盘）；公式 `TTM(t) = FY(t-1) + 累计(t) − 累计(t同期上年)`（Q1/H1/Q3/FY 节奏），注释可复核；返回 TTM 营收/归母净利/eps + 窗口标注。
- **shares = 归母净利(TTM)/eps(TTM)** 反推（禁用净资产/bps 法）。
- **build_context(code) -> MarketContext**：series（`data/market/series/<code>.jsonl`）取最新收盘价/change_pct/52 周高低/sma20/sma50/sma200；gpcw 直值 roe/revenue_yoy/net_profit_yoy/deducted_yoy；TTM 值填 revenue/profit_margins/eps/market_cap/pe/pb/ps；debt_ratio=total_liabilities/total_assets；`field_availability` 逐字段标注；`as_of_date` 填 series 末日 + gpcw report_date。缺失字段（gross_margins/operating_margins/fcf/current_ratio/quick_ratio/两个 ownership）保持 vendored 默认并标 missing。
- **industry_map.json**：A 股代码 → {industry_key: augur industry_matrix 键（"china" 或其上细化键）, sector_en: 英文关键词}；初版覆盖 watchlist 21 只（读 `config/daily-watchlist-watchlist.md` 拿代码清单）+ 常见申万一级行业示例 10 条；缺失回落 {industry_key: "china", sector_en: "China"}。**不走 detect_industry(ticker)**（防 .SZ 后缀短路——直接把 industry_key 传 get_agent_weights，sector_en 填 context.sector）。
- **persona_deps.json + coverage 后处理**：从 18 个 persona 源码人工核对产出 `persona×因子→依赖字段` 映射（重点覆盖「缺省 0 引来加分」型：debt_ratio/current_ratio/quick_ratio 的 `< 阈值加分` 路径，如 duan_yongping durability 的 debt_ratio<0.40 +1.5）；`apply_coverage(responses, context) -> responses`：命中缺失关键字段 → coverage_confidence 降档（×0.6）+ metadata 加 `degraded_factors` 清单。
- **abstain**：ETF（watchlist 内 51/56/58 开头 .SH/.SZ ETF 代码段或现有 watchlist 配置的 type 字段）/指数/^ 前缀/非 A 股代码 → `analyze_all` 前过滤，输出 `abstain: 不是公司标的或数据面不支持`，不进共识。
- **run_masters.py CLI**：`python tools/masters/run_masters.py 300476.SZ [--data-root ...] [--out output/masters/]` → 跑 18 位（ARPS/Serenity 常驻弃权标注）→ 共识 → 报告 md 落 `output/masters/YYYY-MM/<code>-<date>.md`（结构按 spec §5.4：各位大师/共识/分歧清单/half-Kelly 明示公式假设/数据截至 TTM 窗口/missing 清单/页眉免责声明）→ 调 run_archive `append_open(kind="masters")` + `close`（报告整文件哈希）。
- **测试**：TTM 对拍（300476 手工公式构造期望值断言）；shares 与市值/PE 自洽断言（pe×eps≈price）；coverage 后处理（缺 debt_ratio 时 duan_yongping coverage 降档且 metadata 有 degraded_factors）；ETF abstain；行业映射回落；报告生成冒烟（tmp data-root，mock gpcw/series 文件）。

## Task 8: P4 集成（watchlist 批量 + skill 文档 + 分歧→研究问题）

- `system/skills/masters.md`（新）：场景路由（单票/批量/何时用）、边界纪律五条逐字入文（spec §5.5）、run-log 接线说明、输出目录约定。
- `run_masters.py` 加 `--watchlist` 批量模式：读 `config/daily-watchlist-watchlist.md`，21 只 = 17 A 股个股逐票跑 + 4 ETF 全员 abstain 记一行；输出汇总对比表 `output/masters/YYYY-MM/watchlist-<date>.md`（ticker/score/signal/参与大师数/弃权数/半 Kelly/关键分歧一列）。
- 报告尾部「分歧 → 研究问题」段：分歧清单每条给一句可验证的研究问题候选措辞 + 指引「确认后进 workspace/review-queue.md」（**不自动写队列**）。
- `system/skills/screen.md`：加一节「大师共识作辅助列（可选）」——说明 screen 报告可引用最近一次 masters 汇总表的 score 列，不改 screen 工具代码（YAGNI ruling 已记台账）。
- 测试：批量模式对 mock watchlist 配置产出 17+4 结构汇总表；abstain 行数断言。
