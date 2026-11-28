# Daily Watch（日报监控）

> 获取股票行情、检测异动、搜索新闻、生成每日结构化报告，把新信号登记为独立证据并链接到假设。
> 代码位于 `tools/daily-watch/`，原始项目 [daily-watchlist](https://github.com/Benboerba620/daily-watchlist)。

## 触发词

"今日日报" / "daily watchlist" / "盯盘日报" / "dw-today" / "生成日报"

## 前置条件

1. 安装依赖：`python3 -m pip install -r tools/daily-watch/requirements.txt`
   - A 股主源 mootdx 另装：`python3 -m pip install -r tools/daily-watch/requirements-mootdx.txt`（无 Key，TCP 7709 直连通达信；不装则 A 股直接走 tushare/东财降级链）
   - 使用 tushare 时另装：`python3 -m pip install -r tools/daily-watch/requirements-tushare.txt`
   - 需要 Python 3.10+。先运行 `python3 --version`；如果低于 3.10，改用 `python3.10` / `python3.11` / `python3.12`，或引导用户安装新版 Python
   - 如果环境只有 `python` 且版本 ≥3.10，把命令里的 `python3` 替换成 `python`
2. 配置文件（首次使用时从 `tools/daily-watch/config-examples/` 复制到 `config/`）：
   - `daily-watchlist.yaml` — 主配置
   - `daily-watchlist.env` — API key
   - `daily-watchlist-watchlist.md` — 股票池
   - `hypothesis-tracker.yaml` — 假设追踪配置
   - `hypothesis-tracker.rules.md` — 投资纪律
3. 如需 API 数据，在 `config/daily-watchlist.env` 填入对应数据源 key；没有 Key 也可以生成骨架并尝试无 Key 降级源

Agent 首次使用时检查上述条件，缺什么补什么。
免费与低成本数据源的选择、安装命令和授权边界统一读取 `DATA-SOURCES.md`，不要凭旧印象承诺额度。

> **文档同步硬规则**：改动 `tools/daily-watch/` 的代码、数据源顺序或依赖时，必须同步六处，一次不落——
> ① `tools/daily-watch/README.md`（工具自带说明：数据源表、Fallback 顺序、零 Key 矩阵、环境变量）；
> ② `DATA-SOURCES.md`；③ 本 skill 的「数据源优先级」；④ `AGENTS.md` + `CLAUDE.md` 数据源表（含 `system/templates/` 同名模板）；
> ⑤ `CHANGELOG.md` Unreleased 增量条目（2026-11-22 Q-20261122-02① 修根新增——11-16 判例后仍七笔零条目；契约测试 `tests/test_changelog_freshness.py` 机械兜底，纯文档改动用 docs( 前缀免检）；
> ⑥ `system/integrations/object-model.md` 的 `kind` 白名单与 `system/scripts/run_archive.py` `KINDS` 同步 + cron prompt 一致性（新增 batch kind / 新脚本命令 / 新序列时，核**三份 prompt——18:10 批量、8:35 盘前、18:25 美元流动性档**——命令清单与 8:35 盘前自检的 batch-* 组清单；**计数词禁用、一律列 kind 名**——2026-11-28 评审 I-4/I-5 修根，「六组/七组/十一值」型计数词三轮都没跟；2026-11-23 评审 I-1/I-2/M-4 修根新增——object-model 停计数词、README 零同步、自检组数未扩系 11-22 I-2 同族第 2 次；契约测试 `tests/test_registration_contract.py` 机械兜底 kind 枚举全等+新序列三文档登记）。
> 已两次因只改入口文档漏掉其余处返工（2026-10-31 模板、2026-11-02 工具 README），此处即 checklist。

## 核心流程（dw-today）

1. 读取 `config/daily-watchlist.yaml` + `config/daily-watchlist-watchlist.md`
2. 运行数据脚本：
   ```bash
   python3 tools/daily-watch/scripts/generate_daily_report.py
   ```
3. 持久化钩子自动落 data/（失败不阻塞日报）；引用外链文章时 agent 顺手 `save_news_snapshot.py --input <临时md>` 存原文
4. 脚本输出报告骨架到 `output/daily-watch/YYYY-MM/YYYY-MM-DD.md`
5. Agent 用 websearch 补充新闻：异动原因、财报反应、行业动态
6. Agent 扫描 `hypothesis/H*.md`。可确认的行情/财报信号先写入 `evidence/YYYY-MM/`，再把证据 ID 引用到相关假设；主题匹配仍只提示，不自动造证据。登记前判业务时点与可得时点，跨时区按当期实际偏移填 `available_at`（三时点口径见 `system/integrations/object-model.md`）。**异动票若无 entity 档案或档案 >90 天未更新，除登记证据外在报告尾注提示「开一次轻量 screen」——价格信号先行的反向通道（Q-20261109-03）**
7. 最终报告写入，更新 `workspace/meta/active-context.md`
8. 报告落盘后补运行账本 close 行（一步命令，含 `--evidence`，见「运行账本」）

日报默认只处理上一份日报之后的新证据，使用 `dedup_key` 避免重复堆积；这仍是现有 `daily-watch`，不是新的日报类型。日报不自动改变假设确定性或状态。命中证伪条件、关键催化剂、财报或连续多条同方向证据时，追加待确认复盘项，并提示按 `system/skills/hypothesis-review.md` 启动复盘。

## 数据源优先级

| 优先级 | 数据源 | 市场 | env key | 费用 | 获取 |
|--------|--------|------|---------|------|------|
| 1 | mootdx | A 股 + ETF (.SH/.SZ) + 板块指数（880/881 段 `.TDX`） | 无（`DISABLE_MOOTDX=1` 停用） | 免费，TCP 7709 直连通达信，实时快照（板块指数走 index_bars 日线） | [项目](https://github.com/mootdx/mootdx) |
| 2 | tushare | A 股 (.SH/.SZ) + HK；场外基金净值（fund_nav，`.OF` 主源，120 积分实测可调） | `TUSHARE_TOKEN` | 120 积分非复权日线当前 0 元（EOD）；其他看权限 | [注册](https://tushare.pro/register) |
| 3 | FMP | 免费 Basic 以美股 EOD/profile 测试为主；扩展市场看套餐 | `FMP_API_KEY` | 免费 250 次/日 / 付费 | [Pricing](https://site.financialmodelingprep.com/developer/docs/pricing) |
| 4+ | Nasdaq / Finnhub / EODHD / 东财 / 腾讯 / 新浪 / 腾讯环球 hf_ / CNBC / yfinance / 东财 push2his / Nasdaq 官方 historical / 新浪全球日线 / 东财 datacenter+MOFCOM | 各自覆盖（^TNX 断连三级实时备用 CNBC→新浪 `globalbd_usg10y`→FRED、NQ00Y 新浪 `hf_NQ` 备份（腾讯无此合约映射）、WTI/布油新浪+腾讯 hf_ 备份 2026-11-26 接线；含跨资产历史日线回补——^SOX 历史主源 Nasdaq 官方，与国内 Shibor/社融时序，2026-11-09 接线） | 无 Key 或各自 key | 自动 fallback / 盘后批量脚本 | `DATA-SOURCES.md` |

mootdx 未命中或缺装 → A 股在降级链里先试 tushare（首备用），再东财/腾讯/新浪。mootdx 服务器全网不可用时记 5 分钟负缓存快速失败，不影响整份日报生成。

无任何 key 且未装 mootdx → 美股基础行情先尝试 Nasdaq（腾讯 us 前缀为其后的 keyless 备份），其余缺口在报告骨架中标 `[待补充]`，agent 用 websearch 补充。

Longbridge Skill/CLI 是独立 Agent 扩展，不是 `tools/daily-watch/` 的内置数据源。需要时可用于 Agent 的临时查询，但不要把它写成日报脚本已接入。

## 输出路径

| 输出 | 路径 |
|------|------|
| 日报 | `output/daily-watch/YYYY-MM/YYYY-MM-DD.md` |
| 盘前日报 | `output/daily-watch/YYYY-MM/YYYY-MM-DD-premarket.md`（8:35 cron 自动生成：隔夜美股/商品快照+A 股要闻+池内公告；**不写 series、不建证据卡、不写 active-context、不 git 提交**，账本走 run_archive --kind watch，**严禁占用收盘日报路径**；2026-11-11 用户批准新建、11-12 首跑） |
| 独立证据 | `evidence/YYYY-MM/E-*.md` |
| 假设证据 | `hypothesis/H*.md`（只追加证据引用） |
| 长期结论 | `wiki/explorations/`（可选沉淀） |

## 盘前档第零步自检（盘前档内置，现为每交易日 8:35；手工补跑同走）

盘前日报生成前先跑只读自检（不写任何文件；canonical 定义在 8:35 automation prompt【第零步】，此处为同步副本）：

1. **收盘轮完整性（Q-20261116-04）**：run-log 上一自然日 batch-* open 逐组核对齐全——组清单（列 kind 名，计数词禁用，2026-11-28 评审 I-4 修根）：batch-series / batch-finance / batch-crossasset / batch-liquidity / batch-us-liquidity / batch-damodaran-erp / batch-money-etf（缺失=收盘轮整轮未触发；仅缺个别组=点名缺失组按单链失败处理，连续 2 日同组缺失才升级 friction-log）；A 股 series 尾行日期 D==昨天 → 当日收盘日报文件应存在（D<昨天=非交易日跳过属正常）。
2. **盘前档自身完整性（Q-20261124-01；参照日 2026-11-25 起=上一交易日，Q-20261125-07 cron+副本同日 CronUpdate 对齐）**：参照日 P=上文第 1 项的 series 尾行日期 D（=上一交易日：周一 P=上周五、长假后首个交易日 P=节前最后一个交易日——不再以「昨天=交易日」为前提，节前最后一天的盘前档失败同样隔日检出，原口径在长假后首日与周一都直接不检查）：kind=watch open 行 trade_date=P ≥2 笔（08:3x 盘前 + 18:2x 收盘各一）且「P 日期-premarket.md」存在、mtime 日期=P（mtime>P=今天属补跑，注记即可）；缺失 → 红色警告「P 日盘前档失败/缺失待确认」。设计边界：盘前档自身 turn failed 当晨不可自见（同档位自检同样不执行），由下一交易日盘前档检出——首案 2026-11-24（08:00:13 派发 OK→08:00:19 turn failed，报告账本双零，11:00 补跑闭环）。
3. 命中警告 → 盘前简报首行红色警告+口径说明注记；**不自动补跑、不写 data/**（补跑归用户指令或当晚 18:10 轮）。

## 运行账本

每次运行在 `data/.state/run-log.jsonl` 记存在证明与修订痕迹（schema 见 `system/integrations/object-model.md`「运行账本」）。`open` / `data-close` 由持久化钩子自动写入；**18:10 盘后批量（原 16:30，2026-11-16 改）四个 batch kind 五脚本（update_market_series / update_finance_snapshots / update_cross_asset_history / update_cn_liquidity，第 4 条链内另跑 update_money_etf_premium）同样自动记账**——open（kind=batch-*）→ data-close 两行制，无 close 行（孤儿判定接受 data-close 为下文），接线见 `tools/daily-watch/scripts/batch_ledger.py`（2026-11-09 三漂移修根，批量改动 series 不再成为 verify 未申报修订）；18:25 美元流动性档 `update_us_liquidity.py`（kind=batch-us-liquidity，双序列=ON RRP+HY OAS，2026-11-22 接线独立 cron automation-2b56f6a0；11-23 Q-20261123-04 扩 HY OAS，HY 失败只告警+missing 不置非零）同两行制，同档另跑 `update_damodaran_erp.py`（kind=batch-damodaran-erp，达摩达兰隐含 ERP 月度，Q-20261123-05）；18:10 批量第 4 条链内另有 `update_money_etf_premium.py`（kind=batch-money-etf，货币ETF折溢价双序列 cn-money-etf-prem-511880/511990，Q-20261127-01，**主锚 511880 失败=退出码 1，第二腿 511990 失败只告警不置非零**（语义同社融降级，次日自愈）；连续 3 天失败才 friction-log——跨日数法=run-log 各日 data-close 的 missing 含 cn-money-etf-prem-511880 的自然日连续计数；12 月末除权窗可能输出「静默：触发但末 2 日含除权修复行 → 除权窗静默」=设计内剔除非故障，按正常态带过；毒行弃用（|溢价|>±200bp 口径断裂）进 data-close missing+日报段「近期弃行」提示，2026-11-28 评审 C1 修根后不静默）；另有手工档 `update_crack_spread.py`（kind=batch-crack-spread，美国 3-2-1 裂解价差派生序列 us-321-crack，三腿 yfinance RB=F/HO=F/CL=F 同源 ET 日切，2026-11-28 Q-20261128-04 接线；**不进任何 cron**——12-09 FOMC 三分支复盘观察清单数据源，复盘窗前手工跑，同两行制记账；**禁止与本地 CL=F.jsonl 跨源拼腿**（新浪北京日切错位一天，11-28 探针同日差 83.08 vs 85.817）；缺腿/毒行进 data-close missing 不静默，0 行可算=退出码 1）；报告落盘后 skill 一步补全 close 行：

```bash
python3 system/scripts/run_archive.py close --run-id RUN-YYYYMMDD-HHMM-watch \
    --report output/daily-watch/YYYY-MM/YYYY-MM-DD.md \
    --evidence E-20261103-mover-300476-sz-h1
```

`--evidence` 可多次传（本次 run 产出的每个独立证据文件一个 E-ID）。缺 `E-ID:sha256` 时自动按归一化口径现算注册（I4 豁免：review_status/direction/confidence 三个状态字段的合法生命周期迁移不误报，只有正文改动才算修订）。

修订纪律：任何对已 close 运行产物的修改（报告正文、series 行、evidence 文件），**先 `run_archive.py amend` 记 intent，改完 `amend --done`** 补哈希，两步都不可省，漏记会被 verify 抓出。**易漏场景点名：review-queue 收账/复盘确认时给证据正文补巡检注记也是正文改动**——I4 豁免只豁免 frontmatter 状态字段迁移，不豁免正文；E-20261105 与 2026-11-09 三份 E-20261109 证据两案皆栽在此（第 2 次出现，已按 friction-log 硬规则修根进本段）。报告里的「数据修正披露」散文段保留（给人看），amend 行是其机器可读镜像。

## 股票池格式

`config/daily-watchlist-watchlist.md` 是 markdown 表格：

```markdown
| Ticker | Name | Market | Market Cap | Category | Tier | Hypothesis | Notes |
|--------|------|--------|------------|----------|------|------------|-------|
| NVDA | NVIDIA | US | Mega | Semiconductor | HOT | H1 | AI GPU leader |
```

必需列：Ticker, Name, Market, Market Cap, Category
可选列：Tier, Hypothesis, Notes

A 股个股/ETF 用交易所后缀（`.SH`/`.SZ`）；通达信 880/881 段板块指数用 `.TDX` 后缀（如 `881075.TDX` 贵金属，Market 列填 CN，volume 为板块成分合计口径）。 场外开放式基金用 `.OF` 后缀（如 `021179.OF`，2026-11-08 接线）：走 tushare fund_nav → 腾讯 jj 专用短链返回 **T-1 官方净值**，不进证券行情链（TDX 对场外码静默返回错票，段位白名单已挡）。

## 异动阈值（可在 yaml 配置）

- 大盘股：±3%
- 小盘股：±7%

## 降级策略

| 缺少 | 行为 |
|------|------|
| 所有数据源 key | 生成骨架报告，行情数据标 `[待补充]` |
| FMP key（earnings） | A 股财报日历不受影响（东财 datacenter 预约披露无 Key）；美股 earnings 跳过 |
| websearch | 只输出数据表格，跳过新闻分析 |
| 假设文件 | 跳过假设关联段 |

## 冒烟测试

```bash
python3 tools/daily-watch/scripts/check_setup.py --init
```

每日 18:10 ZCode 定时批量（automation-1e7fca91；2026-11-16 用户拍板由 16:30 改 18:10）跑六环节（幂等，非交易日自动零增量，**六环节严格串行**——1-5 同拉 mootdx/pytdx，禁止并行）：update_market_series + update_finance_snapshots + update_cross_asset_history（跨资产历史增量回补，^SOX 走 Nasdaq 官方 historical、XAUUSD=X 走新浪全球日线、其余东财 push2his 节流内置；整轮限流时不补跑次日自愈）+ update_cn_liquidity（国内 Shibor/中国 10Y 国债/社融，社融失败降级只告警、Shibor/中国 10Y 失败=非零）+ update_money_etf_premium（货币ETF折溢价温度计，与 cn_liquidity 同为第 4 条链、链内第二命令；主锚 511880 失败=非零、第二腿 511990 失败只告警，Q-20261127-01）+ weak_scan（gate70 弱票反转扫描，**2026-11-11 用户批准由原 16:10 独立 cron 合并进来**，月初首个交易日加 weak_eval 读数）+ **当日日报生成（dw-today，同日用户批准并入；cron 版按本 skill 核心流程执行，无人值守边界=证据卡只建官方硬事实且 direction/confidence 留 pending、不改假设状态、不写 active-context、18:10 版新闻面以已发布收评为准并注记晚间公告缺口）**——**cron prompt 已并入（2026-11-09 用户批准，Q-20261109-04；11-11 扩六环节）**。日报骨架自 Q-20261123-04（2026-11-23）含**三灯读数段 `{THREE_LIGHTS_SECTION}`**：`three_lights.py` 自动渲染灯1/2/3 机械读数（阈值与判定预注册见 `workspace/monitoring/tech-reentry-three-lights.md`，计算失败降级为提示行不炸报告），两处人工槽位补读程序——**FedWatch**：CME FedWatch 页面快照 12-09 会议加息概率，<50% 记灯1.5 亮；**BTC 周读**：周一读上周周线收盘，只记佐证读数不作灯。Q-20261123-05 再加**达摩达兰隐含 ERP 段 `{ERP_SECTION}`**（最新月读数+2008-09 起历史分位+陈旧 45 天标注，零网络只读本地序列，失败降级同行）。Q-20261127-01（2026-11-27）再加**货币ETF折溢价段 `{MONEY_ETF_SECTION}`**（A股资金面温度计：`update_money_etf_premium.py` 挂 18:10 批量第 4 条链内，写 `data/custom/cn-money-etf-prem-511880`（净值漂移型，pingzhongdata→lsjz 净值链，除权修复=净值回落日用前一日净值对价——F10 除权标签比价格除权提前一交易日，三年假溢价 +174/155/115bp 实锤）+ `cn-money-etf-prem-511990`（固定净值型 100 锚，**lsjz/fundmobapi 对固定净值型货基 DWJZ=万份收益非单位净值**）；触发线=连续 2 日 <-5bp 且双基金同向（基线 P5=-0.8bp/P95=+2.8bp 样本内未出现），触发时联动上证/Shibor 标注 risk-on/risk-off/方向不明（嫌疑级不裁决）；读数截至上一交易日，失败降级同行）。另有**每日 18:25 美元流动性档**（automation-2b56f6a0，2026-11-22 接线）：跑 `update_us_liquidity.py`（双序列：ON RRP 每日用量，主源 NY Fed markets API、备份 FRED RRPONTSYD，写 `data/custom/us-rrp-daily`；**HY OAS 主源 FRED BAMLH0A0HYM2，Q-20261123-04 扩接，写 `data/custom/us-hy-oas`，失败降级只告警+missing 不置非零**；另跑 `update_damodaran_erp.py`（Q-20261123-05：达摩达兰标普500隐含 ERP 月度序列，`Damodaran 官方 ERPbymonth.xlsx` 固定文件名整本全量、每日幂等拉=他本人月初更新后数日内自动捕获，写 `data/custom/us-erp-monthly`，ERP(T12m) 主值存 %、上下文进 note；失败非零但只警告、不影响流动性主档判读，连续 7 天失败才 friction-log）；不碰 mootdx 与 18:10 批量六环节，独立档因 18:10 prompt 超长不并档）；盘前自检的 batch-* open 检查随接线逐次扩组（最新组清单=「盘前档第零步自检」第 1 项的 kind 名列表；计数词禁用，2026-11-28 评审 I-4 修根——同族「六组/七组」第 3 次没跟）。以及**每交易日 8:35 盘前日报 cron**（2026-11-25 用户手改日程，原 8:00）（automation-c2895bd5，2026-11-11 用户批准新建、11-12 首跑）：隔夜美股/商品快照（8:35=ET 前夜收盘后，可信收盘口径但只进报告不写 series）+ A 股要闻 + 池内公告，落 `*-premarket.md`，无人值守边界比收盘版更紧（不建证据卡，重大事件只写「今日关注」提示；**开头带上日收盘轮完整性自检——2026-11-16 用户拍板采纳 Q-20261116-04**：查 run-log 上一自然日 batch-* open 行（非交易日也记 open）+series 尾行判交易日查收盘日报文件，缺失只红色警告+建议会话补跑、不自动补跑，18:10 轮整轮丢失盲窗 24h→~14h）。2026-11-11 曾发生 dispatch 有记录但会话未建立的空转首案（friction-log 已记），18:10（原 16:30）cron prompt 已内置「当日数据新鲜度自检」，第 2 次出现按硬规则修根进本 skill 首步。
