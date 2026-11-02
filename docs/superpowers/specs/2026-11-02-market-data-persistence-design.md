# 市场数据持久化层设计

- 日期：2026-11-02
- 状态：**已批准**（2026-11-02 用户批准 v0.2；v0.3 为实施计划复查引出的闸门语义修正；实施计划 `docs/superpowers/plans/2026-11-02-market-data-persistence.md`）
- 修订：v0.3 —— 2026-11-02 实施计划复查（N1/N2）：交易日闸门完成判据由「本地全体 tail 最大值」改为 `data/.state/` per-scope 完成标记（canary 板块文件会被 `--scope sectors` 单独执行写脏、market 文件混有钩子行，数据文件当标志会误判整轮已更）；§11.7/11.8 验收口径随之同步
- 修订：v0.2 —— 2026-11-02 双轨评审（设计健全性 + 事实核查，关键数值已离线复算）后修订：写者权威规则、命名契约、原子写、列名统计修正（403+256+9）、§4.3 示例改累计口径、cron 共存预案
- 范围：daily-watch 工具族的本地数据持久化——行情时序、新闻原文快照、财务快照、板块指数时序、自定义数值序列
- 技术底座：文件型 JSONL + DuckDB 直查，**零服务、零守护进程、零新增运行依赖**（duckdb 仅为查询层可选依赖）

---

## 1. 背景与目标

当前 daily-watch 每日抓取的行情只在日报 markdown 里留下一张表，原始 payload 用完即弃；财务、板块、巡检数字散落在 hypothesis 正文里，不可查询、不可回算。本设计补一层本地持久化：

1. **全沪深市场日线时序**（不止 watchlist，~6000 只股票+ETF），3 年回补、每日盘后增量；
2. **日报原始快照**（当日 fetch payload 全量落盘）；
3. **新闻原文快照**（日报引用的文章全文，防链接失效）；
4. **财务快照**（通达信 gpcw 全市场文件，按报告期，深至 1988 年可回补）；
5. **板块指数时序**（通达信 880/881 系列行业+概念+二级行业，~1037 个，自带板块涨跌家数）;
6. **自定义数值序列**（韩台出口、台积电月营收、调研观测等 API 覆盖不了的数据，人与 agent 共用入口）。

非目标：实时行情库、分钟线、复权因子库、海外票历史回补、海外财务、Web 服务。

## 2. 已拍板决策

| # | 决策 | 拍板 |
|---|---|---|
| D1 | 时序范围 = 全沪深市场（含 ETF，不含北交所、债券、B股） | AskUserQuestion 2026-11-02 |
| D2 | 新闻 = agent 抓原文 + 脚本落盘 | 同上 |
| D3 | 更新节奏 = 全市场每日盘后批量（幂等，非交易日自动零增量） | 同上 |
| D4 | 格式 = 逐票 JSONL + DuckDB 直查（否决 Docker PostgreSQL） | 同上 |
| D5 | 追加财务数据 + 板块指数 | 用户 2026-11-02 |
| D6 | 追加自定义数据层 | 用户 2026-11-02 |

**探测证据（2026-11-02 真连，脚本 /tmp/awh-probe/）**：

- 板块：SH 证券列表枚举 88 前缀 1120 个；`index_bars` 对 880301/880324/881270 返回连续真实日线（当日已更新），含 `up_count/down_count`；888880（新标准券）为占位垃圾数据。
- 财务：`Affair.files()` 列表自带 filename/hash/filesize 三元组（hash 可零下载比对），148 期至 1988-12-31；默认 bestip 不通时可用行情服务器 bestip 兜底（探测走的就是兜底路径）；列表头部含未来期 164 字节占位文件（须按 filesize 过滤）；gpcw20260930.zip 5.2MB，解析 5571 行 × 659 列（含北交所 353 行）；列名实测 **403 个中文 + 256 个无名 colNN + 9 组重名**（归母净利/扣非净利/ROE 等各 ×2）——「按列位置取数」比预想更必要；300476 抽查（存货 92.49 亿、营收 184.6 亿 +30.77%、扣非同比 +13.74%）与公告口径吻合，zip md5 与 §4.3 示例 `file_hash` 一致。

## 3. 架构与数据流

```
                       ┌─ 日报流程（交易日，agent 发起）
fetch_market_data.py ──► generate_daily_report.py ──► persist_market_data.py（hook，import 调用）
   （mootdx 主源）              │                        ├─ save_daily_snapshot：data/market/daily/
                                │                        └─ append_series：data/market/series/（watchlist 全部票）
                                └─ agent 抓新闻原文 ──► save_news_snapshot.py ──► data/news/

                       ┌─ 盘后批量（ZCode 定时，每日 16:30，幂等）
update_market_series.py --scope all ──► data/market/series/（全市场）+ data/sector/series/（板块指数）
update_finance_snapshots.py ─────────► data/finance/（hash 变化才动作）

                       ┌─ 人工 / 巡检 agent
save_custom_data.py append ──────────► data/custom/

query_market.py（DuckDB read_json_auto）◄── 读以上全部目录
```

关键约束：

- **持久化失败永不阻塞日报**：generate_daily_report 里的 hook 用 try/except 包裹，异常只 log warning。
- **mootdx 连接复用**：update/query 类脚本一律 import `mootdx_source` 的单例客户端与 `_mootdx_call`（RLock 串行），**禁止自建第二条 pytdx/tdxpy 连接**（单 socket 非线程安全，friction-log 已有教训）。
- 海外票与 A 股票同库同 schema：海外行由日报钩子从快照追加（无免费历史源，自今日起累积），缺字段置 null。
- **原子写与跨进程互斥**：series/finance 落盘一律「读全文件 → 合并 → 按日期排序 → 写临时文件 → rename 原子替换」，禁止半行 JSON 落盘；跨进程用 `data/.locks/` 目录锁互斥（16:30 批量与人工发起的 /dw-today 重跑可能同窗），拿不到锁即跳过该票并告警，不等待。

## 4. 目录结构与数据 schema

```
data/                                   # 整目录 gitignore，不入库
├── market/
│   ├── daily/YYYY-MM-DD.json           # 日报原始快照
│   └── series/{TICKER}.jsonl           # 逐票日线（全市场股票/ETF + watchlist 海外票）
├── sector/
│   ├── sector-list.json                # 板块清单（枚举生成，含名称与类别）
│   └── series/{CODE}.jsonl             # 板块指数日线
├── finance/
│   ├── _meta.json                      # 各期 gpcw 文件 hash 台账
│   └── gpcw-YYYY-MM-DD.jsonl           # 按报告期全市场财务快照
├── custom/
│   ├── registry.json                   # 自定义序列注册表
│   └── {slug}.jsonl                    # 自定义数值序列
└── news/
    └── YYYY/MM/DD-{slug}.md            # 新闻原文快照
```

### 4.1 日报快照 `data/market/daily/YYYY-MM-DD.json`

当日 fetch_market_data 的完整 payload（quotes/movers/earnings/meta 四键）**原样嵌套**落盘 + 包装字段：`{"schema_version": 1, "fetched_at": "<ISO>", "payload": {...原始 payload 原样...}}`。**同日重跑覆盖重写**（与日报本身的重跑语义一致）。fetch 现状只写 stdout：日报钩子拿到的是 generate_daily_report 内已解析的 dict（直接传入）；`--snapshot-file` 供手工补跑，文件由 `fetch_market_data.py > x.json` 重定向生成。

### 4.2 行情时序 `data/market/series/{TICKER}.jsonl` 与板块 `data/sector/series/{CODE}.jsonl`

每行一个交易日，按日期升序追加：

```json
{"date": "2026-11-02", "open": 71.0, "high": 73.2, "low": 70.5, "close": 71.54,
 "volume": 123456, "amount": 88900000.0, "source": "mootdx"}
```

- **命名契约（文件名即主键）**：TICKER 统一为 watchlist 标称记法——A 股 `{6位}.SH/.SZ`（全市场枚举与 `--tickers` 入参必须经同一 normalize 函数：market=1→`.SH`、market=0→`.SZ`，禁止裸 6 位落盘产生 `600276.jsonl` 与 `600276.SH.jsonl` 分身）、海外票原样（`^SOX`、`NVDA`、`000660.KS`）；板块 CODE 为裸 6 位（`880301`），住独立目录不与个股混。
- **不复权原始价**（除权跳空原样保留，README 注明；复权计算留给查询层按需做）。
- 量纲原样不换算：A 股 volume=手（mootdx 口径）、amount=元；**amount 仅批量 bars 路径有值**（日报钩子的 quote 无此字段，靠 null 合并兜底），README 注明；海外票 volume 以各源口径为准；板块行额外两字段 `"up_count": 16, "down_count": 15`。
- 字段可空：海外票快照行缺 open/high/low/volume 时置 null，**null 永不覆盖已有非空值**（见 5.2 upsert 合并规则）。
- schema_version 政策：daily 快照与 finance 行带 `schema_version`；series 与 custom 逐行**有意不带**——追加层每行多付 20+ 字节不值，「只加字段不改语义」+ README 字段字典已保证兼容。README 写明这是有意的不一致。

### 4.3 财务快照 `data/finance/gpcw-YYYY-MM-DD.jsonl`

按报告期一文件（披露季内同文件被通达信反复更新，hash 变化即整期重写）。每行一只票：

```json
{"code": "300476", "market": "SZ", "report_date": "2026-09-30",
 "eps_basic": 3.63, "eps_deducted": 3.759, "bps": 38.98, "roe": 8.832,
 "revenue": 18460532736.0, "net_profit_parent": 3383763712.0, "net_profit_deducted": 3694268928.0,
 "inventory": 9249440768.0, "monetary_funds": 10276478976.0, "total_assets": 71296745472.0, "total_liabilities": 32984334336.0,
 "revenue_yoy": 30.77, "net_profit_yoy": 4.28, "deducted_yoy": 13.74,
 "forecast_min": null, "forecast_max": null,
 "file_hash": "0e8202ef964fff52c3f196ed511cbfc7", "schema_version": 1}
```

示例数值全部为累计口径（离线复算核对：归母累计 33.84 亿 / 扣非累计 36.94 亿；货币资金、负债合计实有值）。curated 字段映射表（gpcw 列名 → JSON 键；**659 列 = 403 个中文名 + 256 个无名 colNN + 9 组重名（各 ×2），约半数列连名都没有——映射必须按列位置+出现序号钉死，禁止按列名取数**）：

| JSON 键 | gpcw 列名 | 备注 |
|---|---|---|
| eps_basic | 基本每股收益 | |
| eps_deducted | 扣除非经常性损益每股收益 | |
| bps | 每股净资产 | |
| roe | 净资产收益率 | **重名 ×2**（每股指标段 / 衍生指标段；300476 两处同值 8.832，仍按位置钉死取每股指标段那次） |
| revenue | 其中：营业收入 | 与后段「营业收入」是**不同列名易混**（非 pandas 重名）：前者累计 184.6 亿与公告吻合，后者 68.3 亿口径不同——按位置取「其中：营业收入」 |
| net_profit_parent | 归属于母公司所有者的净利润 | **重名 ×2**（第 1 次累计 / 第 2 次单季；300476 实测 33.84 亿 / 5.27 亿），取第 1 次（累计） |
| net_profit_deducted | 扣除非经常性损益后的净利润 | **重名 ×2**（300476 实测 36.94 亿 / 12.76 亿），取第 1 次（累计） |
| inventory / monetary_funds / total_assets / total_liabilities | 存货 / 货币资金 / 资产总计 / 负债合计 | 资产负债表段 |
| revenue_yoy / net_profit_yoy / deducted_yoy | 营业收入增长率(%) / 净利润增长率(%) / 扣非净利润同比(%) | 衍生指标段 |
| forecast_min / forecast_max | 业绩预告-本期净利润同比增幅下限% / 上限% | 0 视为无预告写 null |

实现期校验要求：用 300476（胜宏）、600519（茅台）、601398（工行，金融类非金融指标为空）三只票对照最新公告数值人工核对一次映射，校验记录写进 PR 描述。字段集合允许实现期增删（表为准），但「按位置取数 + 三票校验」的规则不可省。

`data/finance/_meta.json`：`{"gpcw20260930.zip": {"hash": "...", "fetched_at": "...", "rows": 5571}, ...}`——hash 台账，判断是否跳过。

### 4.4 自定义序列 `data/custom/{slug}.jsonl` + `registry.json`

```json
{"date": "2026-11-01", "period": "2026-10", "value": 275.0, "unit": "亿美元",
 "source": "韩国关税厅 1-20 日初步", "note": "半导体出口 YoY +222.5%", "recorded_at": "2026-11-01T20:05:00+08:00"}
```

- `date` 永远是真实日期（记录日/发布日），`period` 是数据所属期（`YYYY-MM` / `YYYY-Qn`，可选）——月度数据不硬编假日期。
- `registry.json`：`{"korea-semi-export": {"name": "韩国半导体出口", "unit": "亿美元", "category": "H1 参照指标", "description": "...", "created_at": "..."}}`，首次 append 自动注册。
- slug 全局唯一、kebab-case；数值层不校验值域（垃圾进垃圾出，只保 schema 合法）。

### 4.5 新闻快照 `data/news/YYYY/MM/DD-{slug}.md`

markdown 文件 = frontmatter + 原文全文。frontmatter：`url / title / fetched_at / dedup（URL 规范化后的 md5）/ partial（是否不完整抓取）`。dedup 命中已有文件则跳过并报告路径；同日同 slug 撞名（不同 URL）时文件名自动追加 md5 前 6 位后缀保唯一。

## 5. 组件设计（全部在 `tools/daily-watch/scripts/`）

**写者身份表**（多写者一致性的根规则，各组件实现必须遵守；同日冲突详见 5.2 三档合并规则）：

| 目录 | 权威写者 | 快照级写者 | 冲突规则 |
|---|---|---|---|
| market/series | update_market_series（批量 bars） | 日报钩子（快照 quote） | 批量对同日行按字段覆盖；钩子只补 null 空位，绝不覆盖非空值 |
| market/daily、news、custom | 各自唯一写者 | — | 同日/同 (series,date) 覆盖需显式语义（daily 同日覆盖、custom 默认拒绝） |
| sector/series、finance | 各自唯一批量写者 | — | tail/hash 未变即跳过；变了整文件原子重写 |

### 5.1 `persist_market_data.py`（存储库 + CLI，日报钩子）

- `save_daily_snapshot(snapshot: dict) -> Path`：写 `data/market/daily/`，同日覆盖。
- `append_series_from_snapshot(snapshot: dict) -> int`：把 watchlist 全部票（含 A 股，幂等可重入）从当日快照 upsert 进各自 series 文件；返回写入行数。**行日期取归一化后的 tradeDate**（mootdx 抖动时空串、FMP 是 epoch 整数、Nasdaq 是英文长戳——解析失败或为空的 quote 只进 daily 快照、跳过 series 并 log warning，禁止把 `""` 或 `November 2, 2026` 之类写进 date 主键）。
- CLI：`python persist_market_data.py --snapshot-file <fetch 输出.json>`（手工补跑用；文件由 `fetch_market_data.py > x.json` 重定向生成）。
- generate_daily_report.py 在拿到 market_data 后（现状为 subprocess stdout 已解析成 dict 的 `run_json_script` 处）import 调用，try/except 包裹，失败 log warning 不中断。

### 5.2 `update_market_series.py`（全市场 + 板块盘后批量）

- `--scope stocks|sectors|all`（默认 all）、`--backfill`（默认增量 30 bars；`--backfill 800` 回补 ~3.3 年，800 为服务器单次上限）、`--tickers`（子集，调试用，入参经同一 normalize）。
- **交易日闸门（先于一切逐票调用）**：先取一只 canary（如某 880 段指数）最新 bar 的日期作为服务器最新交易日；该日期 ≤ `data/.state/last_{scope}_round` **完成标记** → 该 scope 整轮短路零调用（stocks/sectors 各自独立标记）。标记是批量写者独占的旁路状态，与数据文件解耦——数据文件由钩子与批量共同写、行内容无法区分写者；canary 板块文件本身也会被 `--scope sectors` 单独执行写脏，拿任一数据文件当完成标志，局部执行就会被误判成「整轮已更」（全市场初始化静默短路的病根）。标记只在**全量枚举 + fail==0 + 服务器日期已知**的干净轮写入：tickers 抽查轮不写（否则挡住后续全量初始化），fail>0 轮不写（否则失败后的同日补跑被自己挡住）。非交易日「成本近零」靠这个成立——逐票判断 tail 做不到，那仍是 ~7000 次往返。
- stocks：`get_security_list(market=0/1)` 枚举 → **前缀白名单过滤**（SH：60/68 股票、51/56/58 ETF；SZ：00/30 股票、15/16 ETF；显式排除 88/89 段、1x/20x 债券回购、4/8/9 段北交所与 B 股。LOF 口径两市场**有意不对称**：SH 50 段排除、SZ 16 段保留，README 注明取舍）→ 枚举结果 normalize（market=1→`.SH`、0→`.SZ`，见 4.2 命名契约）→ 逐票 `bars(frequency=9, offset=N)` 增量 upsert。实际数量以过滤日志为准（预期 ~6000±500）。
- sectors：清单文件缺失时先枚举 `market=1` 的 88 前缀 → **段位白名单 880300 ≤ code ≤ 881999**（排除风格统计段与 888880 占位）**并显式 sort**（服务器返回未按代码排序，888880 会排在 880301 之前）生成 `sector-list.json`（code/name/category；category 按 8803xx-8809xx≈行业+概念、881xxx≈二级行业粗分）→ 逐个 `index_bars` upsert（含 up_count/down_count）。清单里消失的代码文件冻结，新出现的自动补录。
- 幂等与断点：**逐票处理即逐票落盘**（process-and-flush），中途失败重跑从断点继续；tail 日期 == 服务器最新交易日 → 跳过该票。A 股日线行 `source: "mootdx"`，板块行 `source: "mootdx-index"`。
- **upsert 合并规则（三档，配合开头写者身份表）**：① 新日期 → 「读全文件→合并→**按日期排序**→临时文件→rename」插入（回补早于 tail 的日期不破坏升序，不是纯 append）；② 同日行已存在、本次来自**批量路径**（权威写者）→ 按字段覆盖（含覆盖钩子先写的盘中价；`source` 字段记录最后写者可追溯）；③ 同日行已存在、本次来自**钩子路径**（快照级写者）→ 只补 null 空位，**绝不覆盖任何非空值**——既防降级源晚间重跑冲掉 mootdx 权威收盘，也防 close-only 海外行冲掉完整 OHLCV。
- 失败语义：单票失败计数不中断，结束打印 `ok/skip/fail` 汇总，fail>0 退出码 1。

### 5.3 `update_finance_snapshots.py`（财务盘后检查）

- `Affair.files()` 列表（一次轻调用；**列表自带 hash**，与 `_meta.json` 记录直接比对即零下载变化探测，无须下载）→ **过滤 filesize ≤ 1MB 的占位文件** → hash 变化者下载（5-6MB）+ `Affair.parse` + 按映射表（4.3）转 JSONL 整期重写（临时文件→rename）+ 更新 meta。无变化零下载。
- `--backfill N`（默认 0=只盯最新期；`--backfill 12` 补 3 年；`--backfill all` 全历史——探测见 148 期，实现期以列表日志为准，早期文件字段口径不全属已知取舍）。
- 复用 mootdx_source 客户端约束不适用（Affair 走独立 bestip 通道），但同样串行执行。**已知坑**：默认 bestip 可能连不通，须保留「改用行情服务器 bestip」的兜底路径（探测脚本 /tmp/awh-probe/probe_affair.py 已验证可行）。

### 5.4 `save_custom_data.py`（自定义层存储库 + CLI）

- `append --series {slug} --name "显示名" --date YYYY-MM-DD [--period YYYY-MM|YYYY-Qn] --value V --unit U --source S [--note N]`：首次自动写 registry；**同 (series, date) 已存在 → 默认报错拒绝**，`--overwrite` 显式覆盖（人工数据不可静默重写，与行情层语义相反，理由：机器产物可重取、人工录入错了不可恢复）。
- `list` / `show --series X [--tail 20]` / `csv-import --series X --file data.csv`（列名 date/period/value/unit/source/note 映射，其余列忽略；遇已存在 (series,date) 默认**跳过并在汇总计数**，`--overwrite` 才覆盖——与 append 的拒绝语义一致，不静默、不中断整批）。

### 5.5 `save_news_snapshot.py`

- `--url URL --title T --date YYYY-MM-DD --slug S --input file.md [--partial]`：agent 先抓原文存临时文件，脚本负责规范化落盘（frontmatter + dedup 判重）。daily-watch skill 流程增加「引用文章顺手存快照」一步（见 §10 文档同步）。

### 5.6 `query_market.py`（DuckDB 查询层，唯一需要 duckdb 的组件）

- `quote --ticker 600276.SH` / `range --ticker X --start ... --end ...`（series 与 sector 目录按代码自动路由）；
- `finance --ticker 300476 [--last 4]`（跨期文件 glob 后按 code 过滤）；
- `sector [--top 20]`（按最后一日涨跌幅排板块榜）；
- `custom --series X [--tail N]`；
- `sql --sql "SELECT ..."`：暴露**四个具名视图** `market_quotes` / `sector_index` / `finance` / `custom_series`（各对各自目录 glob read_json_auto），不做跨组单 glob（schema 异构混不了）；示例查询（含「找 tail 落后 >N 日的票」缺口审计）写 README。
- 规模预期：~7000 文件 / ~450 万行 / ~700MB，read_json_auto 全扫 Apple Silicon 秒级，个人交互够用，README 记预期延迟；parquet 物化等加速列为非目标。坏行容忍：read_json_auto 容忍 torn 尾行跳过（原子写把概率压到最低，查询层不因单行崩）。
- duckdb 缺失时报错并指向 `requirements-market-data.txt`，不降级。

## 6. 调度

- **ZCode 定时任务**：每日 16:30 一条自动化（交易日历不判断——非交易日由 §5.2 交易日闸门整轮短路，成本近零），依次跑 `update_market_series --scope all` → `update_finance_snapshots`，合计 ~4 分钟（全市场 ~6000 票串行 ~3 分钟 + 板块 ~1037 个 ~40 秒 + 财务列表检查秒级）。
- **与既有 cron 共存（硬约束，实施计划必须处理）**：工作区已挂「每月 3/8/10/21 H1 巡检」一条，且平台一个会话只能挂一条 cron——每日批量须在**另一会话**挂载，或与 H1 巡检合并为一条按日期分支；二选一在实施计划拍板，此处只钉死约束。
- 日报钩子与新闻快照随 /dw-today 流程走，不进定时任务。
- 定时任务的具体注册（CronCreate）在实施计划里做，不在本设计范围。

## 7. 依赖

- 新文件 `tools/daily-watch/requirements-market-data.txt`：`duckdb`（仅查询层需要；批量更新脚本不 import duckdb）。
- 其余复用现有：mootdx（含 Affair / index_bars）、标准库。
- conda env Quant-3.11 安装：`python -m pip install duckdb`。

## 8. 边界与已知限制

1. series 层不含北交所/B股/债券；财务层 gpcw **含北交所**（2026-09-30 期实测 353 行，白拿的覆盖不丢，README 注明口径差）。
2. 海外票无历史回补，自启用日起累积；缺字段 null。
3. 退市票文件冻结（增量自然停更），不删除。
4. gpcw 无公告日期（只有报告期），披露时间线不可考。
5. 早期 gpcw（约 2005 年前）字段口径不全，全历史回补属可选取舍。
6. 板块指数是通达信自编指数（非交易所官方、非申万/东财分类），日报引用需标 TDX 口径；板块 volume 量纲与个股不同，原样保留不换算。
7. 自定义层不校验数值正确性；事件原文/纪要走新闻快照与 wiki，不进自定义层。
8. 派生指标（比值/相对强度/滚动窗）不物化，查询层 SQL 就地计算。
9. 明文 TCP 协议声明沿用 DATA-SOURCES 既有免责（个人研究参考，非授权口径）。
10. 存储量级：满配约 1GB（market 3 年 ~650MB + finance 148 期 ~300MB + sector ~120MB）；退市票只冻不删、单调慢涨；文件无校验和，单文件损坏的恢复手段 = 该票 `--backfill` 重拉（原子写已把损坏概率压到最低）。

## 9. 测试计划（pytest，全部封闭 tmp 目录，外部调用一律 mock）

| 模块 | 用例 |
|---|---|
| persist_market_data | 快照写入/同日覆盖；series 追加幂等；钩子路径合并只补 null；tradeDate 空/非 ISO 跳过 series（负样本）；「钩子盘中价 → 批量收盘权威覆盖」端到端 |
| update_market_series | 交易日闸门整轮短路；tail==最新日跳过；缺行补齐；回补早于 tail 的日期按序插入（非纯 append）；新票建文件；中途失败重跑续传；前缀白名单过滤（含 88/债券/B股/LOF 口径负样本）；枚举乱序 sort；--backfill 透传 offset；torn 尾行容忍 |
| sector | 段位白名单（880099/880299 排除、880300/881999 边界含、888880 排除）；清单自动生成与补录；index_bars 行映射含 up/down_count |
| update_finance_snapshots | 占位文件（filesize≤1MB）过滤；hash 未变全跳过零下载；变化→整期重写+meta 更新；重复列名 fixture 的位置映射（构造含两列同名的 DataFrame） |
| save_custom_data | append+registry 首写注册；同 (series,date) 拒绝与 --overwrite；csv-import 列映射；period 可选 |
| save_news_snapshot | URL 规范化 dedup；partial 标记 |
| query_market | fixture 目录树上的 glob 查询、finance 跨期过滤、sector top 榜（duckdb 未装时 skip 标记） |

网络路径全部 mock mootdx_source / Affair；真实连通性靠 §11 的 e2e 验收覆盖。

## 10. 文档同步清单（实现 PR 必须六处齐改，缺一不算完成）

1. `tools/daily-watch/README.md`：新增「本地持久化」章节（目录树、schema 字段字典、量纲与口径注记、CLI 示例）；
2. `DATA-SOURCES.md`：mootdx 条目扩展 Affair 财务与板块指数两个用途；
3. `system/skills/daily-watch.md`：日报流程加新闻快照步骤与持久化钩子说明（含调度）；
4. `AGENTS.md` + `CLAUDE.md` + 两模板（`system/templates/AGENTS.md`、`system/templates/CLAUDE.md`）：数据源表 mootdx 行补用途说明 + 核心路由表「日报监控」行「主要写入」列补 `data/`（同源四文件）；
5. `workspace/workspace-config.md` + 模板（`system/templates/workspace-config.md`）：目录表加 `data/` 一行；
6. `ARCHITECTURE.md`：「目录结构」树补 `data/`。

另：`.gitignore` 加 `data/`；`CHANGELOG.md` 记条目。

## 11. 验收标准（e2e，Quant-3.11 真跑）

1. 回补抽查：`update_market_series --tickers 600276.SH,300476.SZ,513880.SH --backfill 800` 成功，300476 头三行与东财网页口径人工对照一致（价格不复权、日期对齐）；
2. 板块：`--scope sectors` 生成 sector-list.json（数量以过滤日志实测为准——探测段位过滤后 ~1037，服务器段位可能调整，不硬编验收数）+ 880301 系列回补成功；
3. 财务：生成 `gpcw-2026-09-30.jsonl`，300476 行 `inventory == 9249440768`、`revenue_yoy ≈ 30.77`，三票人工校验记录在 PR；
4. 自定义：append 两条 + `--overwrite` 一条 + csv-import 一个样例文件，`query_market custom` 查询回读一致；
5. 新闻：对同一 URL 二次保存触发 dedup 跳过；
6. 日报钩子：跑一次 /dw-today 流程，`data/market/daily/` 出快照、watchlist series 全部追加、日报本身不受 persist 失败影响（人为制造失败验证 warning 路径）；
7. 首次全市场初始化：`update_market_series --scope all --backfill 800` 全量回补成功并计时落档——这是目标 1「3 年回补」唯一的兑现路径，与日常增量分开记录。计时口径注明实际执行部分（sectors 已先行初始化且有标记时本步实际只跑 stocks）；若当日 cron 已写过 stocks 完成标记，须先清标记再跑（标记闸门的固有语义）；
8. 日常增量计时落档分两段：同日重跑（闸门整轮短路，秒级）与移走标记后的真实增量路径（预期 ~4 分钟，几乎全 skip）；fail 汇总与退出码正确，缺口审计 sql 示例可跑（验证 cron 停摆超 30 交易日可被发现；该 sql 只看已有文件，「整批缺失」不可见，须以 ok+skip 总数交叉印证）；
9. `pytest` 全绿 + `ruff check` 干净；文档六处同步逐项勾验。

## 12. 实现期注意（探测已踩的坑，别再踩）

- gpcw 列表取最新文件必须按 filesize 过滤占位（未来期 164 字节空壳，解析出 0×0）。
- 财务列映射按**列位置**取数：659 列 = 403 个中文名 + 256 个无名 colNN + 9 组重名（各 ×2）——约半数列连名都没有，按列名取数必错。
- Affair 默认 bestip 可能不通：保留「改用行情服务器 bestip」兜底（探测已验证）。
- series 落盘必须原子（临时文件+rename）：半行 JSON 会让 DuckDB read_json_auto 报错，重写中途崩溃会毁掉整只票的序列。
- 板块指数枚举列表**未按代码排序**（888880 出现在 880301 之前），过滤后须显式 sort。
- pytdx/tdxpy 单 socket：一切取数走 `mootdx_source` 的 RLock 单例通道。
- mootdx `bars(offset)` 服务器单次上限 800 行，回补 3 年恰好在单次内；超过需 start 分页（mootdx `k()` 已有实现，必要时复用）。
- A 股 volume 量纲=手、不复权价、除权跳空保留——README 必须写，防未来误用。
