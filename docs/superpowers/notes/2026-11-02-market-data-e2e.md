# 市场数据持久化层 E2E 验收记录（Task 11）

- 执行日：2026-11-03 凌晨 00:58–01:30（CST），赶在当日 16:30 cron 首跑前完成全部步骤
- 解释器：`/opt/homebrew/Caskroom/miniconda/base/envs/Quant-3.11/bin/python`（duckdb 2.0.0）
- 分支：`feat/market-data-persistence`；本 Task 唯一允许写真实 `data/`
- cron（Task 9 注册）：**automation-1e7fca91-567c-4e93-ad06-7a96a591b72d**，每日 16:30，首跑今天（2026-11-03）——本验收完成后，cron 将以同日增量（几乎全 skip）运行，闸门与标记语义已在 11.8 验证
- 对照数据源：东方财富公开 API（push2his K 线 fqt=0 不复权；datacenter `RPT_LICO_FN_CPD` 业绩报表 / `RPT_DMSK_FN_BALANCE` 资产负债摘要 / `RPT_F10_FINANCE_GINCOME` 利润表），与上市公司三季报公告数值同源

## Step 11.1 回补抽查 — 通过

- 命令：`update_market_series --scope stocks --tickers 600276.SH,300476.SZ,513880.SH --backfill 800`
- 结果：`{'ok': 3, 'skip': 0, 'fail': 0}`，耗时 4.8s
- `query_market range --ticker 300476.SZ --start 2024-01-01 --end 2026-11-02 | head -40` 正常输出（BrokenPipeError 来自 brief 自带的 `| head` 截断，预期行为非缺陷）

300476（胜宏科技）头三行与东财不复权日 K 对照（OHLC 顺序 open/close/high/low）：

| 日期 | OHLC（本地 vs 东财） | volume（本地 vs 东财） | amount（本地 vs 东财） |
|---|---|---|---|
| 2024-01-02 | 18.50/18.23/18.62/18.21 **完全一致** | 119,039 vs 119,040（差 1 手） | 218,633,008 vs 218,633,006（差 2 元） |
| 2024-01-03 | 18.20/17.63/18.23/17.48 **完全一致** | 161,376 vs 161,377（差 1 手） | 286,528,224 vs 286,528,225（差 1 元） |
| 2024-01-04 | 17.67/17.43/17.67/17.33 **完全一致** | 84,731 vs 84,732（差 1 手） | 147,949,520 vs 147,949,526（差 6 元） |

结论：日期对齐、价格不复权口径完全一致；volume 差 1 手 / amount 差个位元系通达信浮点截断与东财取整口径差，相对差 <1e-5，可接受。

## Step 11.2 板块 — 通过

- 命令：`update_market_series --scope sectors --backfill 800`
- 结果：`{'ok': 1037, 'skip': 0, 'fail': 0}`，耗时 46.5s
- `data/sector/sector-list.json` 实测 **1037** 项（880300–881999 白名单过滤后实测值，非硬编）；880301 系列 800 行；`last_sectors_round = 2026-11-02` 写入

## Step 11.3 财务三票对照 — 通过

- 命令：`update_finance_snapshots.py` → 非占位 83 期、本次处理 1 期（backfill=0），`gpcw-2026-09-30.jsonl` 5571 行，`{'ok': 1, 'skip': 0, 'fail': 0}`
- 断言：300476 `inventory == 9249440768` **精确命中**；`revenue_yoy = 30.77`（30.770000457763672）**命中**

三票 2026-09-30 报告期（累计口径）与东财对照表（单位：元）：

| 指标 | 本地 gpcw/mootdx | 东财 | 差额（相对差） |
|---|---|---|---|
| **300476 胜宏科技** | | | |
| 营业收入 | 18,460,532,736 | 18,460,532,503.25 | +232.75（1.3e-8） |
| 归母净利润 | 3,383,763,712 | 3,383,763,767.52 | −55.5（1.6e-8） |
| 基本每股收益 | 3.63 | 3.63 | 一致 |
| 营收 YoY | 30.77% | 30.7654% | 一致（取整） |
| 归母净利 YoY | 4.28% | 4.28% | 一致 |
| 存货 | 9,249,440,768 | 9,249,440,419.21 | +348.79（3.8e-8） |
| 货币资金 | 10,276,478,976 | 10,276,478,965.68 | +10.3 |
| 资产总计 | 71,296,745,472 | 71,296,744,870.30 | +601.7（8.4e-9） |
| 负债合计 | 32,984,334,336 | 32,984,335,341.61 | −1,005.6（3.0e-8） |
| **600519 贵州茅台** | | | |
| 营业收入 | 130,970,746,880 | 130,970,743,649.04（OPERATE_INCOME） | +3,231（2.5e-8） |
| 归母净利润 | 64,467,427,328 | 64,467,425,981.95 | +1,346（2.1e-8） |
| 基本每股收益 | 51.53 | 51.53 | 一致 |
| 营收 YoY | 1.82% | 1.8179% | 一致 |
| 归母净利 YoY | −0.25% | −0.25% | 一致 |
| 存货 | 61,390,819,328 | 61,390,820,964.46 | −1,636（2.7e-8） |
| 资产总计 | 318,304,878,592 | 318,304,891,882.72 | −13,291（4.2e-8） |
| **601398 工商银行** | | | |
| 营业收入 | 695,946,969,088 | 695,947,000,000 | −30,912（4.4e-8，东财按整数元档存） |
| 归母净利润 | 285,639,999,488 | 285,640,000,000 | −512（1.8e-9） |
| 基本每股收益 | 0.78 | 0.78 | 一致 |
| 营收 YoY | 8.74% | 8.7370% | 一致 |
| 归母净利 YoY | 5.83% | 5.83% | 一致 |

**600519 口径说明**：东财 `TOTAL_OPERATE_INCOME`（营业总收入）= 133,283,652,508.95，与本地图差 23.13 亿 = 财务公司利息收入等（`INTEREST_INCOME` = 2,312,908,859.91 + 其他金融子项），属「营业总收入 vs 其中：营业收入」报表口径差而非数据错误；mootdx 列映射取「其中：营业收入」（spec §5.3 累计口径），与东财 `OPERATE_INCOME` 逐元对齐。601398 银行股两条口径重合。

## Step 11.4 自定义层读写回环 — 通过

- append 1.0（2026-11-02）→ 成功落 `data/custom/e2e-smoke.jsonl`
- 同 (series,date) 再 append 2.0 → **ValueError 拒绝 + exit 1**（「人工数据不可静默重写」）
- `--overwrite` append 2.0 → 成功
- csv-import 样例（2026-11-01, 3.0）→ `{'imported': 1, 'skipped': 0}`
- `query_market custom --series e2e-smoke` 回读两行（11-01=3.0，11-02=2.0）**一致**
- 清理：删文件 + registry 移除，`data/custom/` 仅剩 registry.json（空对象）

## Step 11.5 新闻 dedup — 通过

- 带 `?utm_source=t` 首存 → `saved: data/news/2026/11/2026-11-02-e2e.md`
- 同 URL 去参数二存 → **`skipped`**（URL 规范化 dedup 命中）

## Step 11.6 日报钩子 + 失败不阻塞 — 通过

- 真流程：报告生成 `output/daily-watch/2026-11/2026-11-03.md`（exit 0）；`data/market/daily/2026-11-03.json` 快照落盘；watchlist series 追加（`data/market/series/` 含 000630.SZ、002415.SZ、513130.SH 等）
- `chmod 000 data/market/daily` 后重跑：stderr 出现 **`Warning: 持久化钩子失败（不阻塞日报）: [Errno 13] Permission denied ...`**，日报仍生成、exit 0；chmod 755 恢复后目录完好
- 附带观察：海外票（NVDA/^IXIC 等）tradeDate 美式格式不可解析时「只进快照不进 series」，属设计内降级

## Step 11.7 首次全量初始化计时 — 通过（3 年回补目标兑现）

- 前置：`data/.state/` 仅有 `last_sectors_round`（11.2 所写）；`last_stocks_round` **本就不存在**（11.1 带 `--tickers`，标记只在干净全量轮写），brief 的 `rm -f` 为空操作——如实记录
- 命令：`time ... update_market_series.py --scope all --backfill 800`
- 结果：**5 分 10 秒**（5:10.33 total）；stocks `{'ok': 7483, 'skip': 21, 'fail': 0}`（待更新 7504 只，前缀白名单实测数）；EXIT=0
- 计时口径：sectors 已在 11.2 完成当日初始化且有自己的标记，本次实际执行 **stocks 部分（7504 只 × 800 bars）**；sectors 段为闸门零调用——日志确有 **「交易日闸门（sectors）：服务器最新 2026-11-02 ≤ 上轮批量 2026-11-02，整轮跳过」**（per-scope 隔离正确）
- 21 skip = 11.1 三票 + 日报钩子已写过当日行的 watchlist 票；落盘 7459 个 series 文件。对账算式：7504(ok+skip) − 7459(文件) = **45 只 ok-but-empty 长期停牌/无数据票**（服务器返回空 bars，计数 ok 但无行可写；21 只 skip 的本就有文件，故不参与此差），fail=0
- 干净轮结束 `last_stocks_round = 2026-11-02` 自动写入

## Step 11.8 日常增量两段计时 + 缺口审计 — 通过（N4 兑现并修复）

① 同日重跑（闸门短路成本）：**4.7 秒**（4.667s total），日志两处「整轮跳过」（stocks + sectors 各一），EXIT=0。

② 真实增量路径（`mv` 走两个标记模拟次日首跑）：**16.7 秒**（16.720s total）——远优于 ~4 分钟预期，skip 路径纯本地读尾行。stocks `{'ok': 50, 'skip': 7454, 'fail': 0}`、sectors `{'ok': 0, 'skip': 1037, 'fail': 0}`，EXIT=0；干净轮结束后两标记自动重写为 2026-11-02（无须手工还原）。ok=50 解释：≈45 只 11.7 空返回票重试仍空 + 少量尾部滞后票补齐。

**整批缺失交叉印证**（SQL 盲区补偿）：② stocks ok+skip = 50+7454 = 7504 == 11.7 ok+skip（7483+21）——全市场枚举对账一致，无整批漏网。

**口径注记（2026-11-03 追加）**：本文 11.7 的 ok=7483/skip=21 与 11.8 的 ok=50 是 v0.3a（amount 指纹）与 `_upsert_bars` 空/锁返回语义修正**之前**实测；复跑时「钩子已写当日行」票将从 skip 转 ok、空返回票将从 ok 转 skip，数字会移位，历史数字不回改。

缺口审计 SQL（~7459 文件显式视图的首次真实检验，**N4 前后对比**）：

| 阶段 | ensure_view 形态 | 结果 |
|---|---|---|
| 前（Task 8 原实现） | 显式文件列表 + `union_by_name=true` | `CREATE VIEW` 即 **OutOfMemoryException**（38.3 GiB/38.3 GiB，schema 并集探测爆炸） |
| 中（docstring 预案退路） | glob 串 + `union_by_name=true` | **仍 OOM**——隔离出真凶是 `union_by_name` 本身（`SET threads=1` 无效），显式列表只是同病诱因 |
| 后（最终修复） | glob 串 + 无 union + 存在性预检 + `ignore_errors` | **0.64s** 返回 `[]`（0 缺口，全部文件新鲜）；sector top 真实数据 0.19s；torn 尾行跳过语义不变（单测验证） |

修复落点：`tools/daily-watch/scripts/query_market.py` ensure_view（glob 串、去 union_by_name，同构性由四目录各唯一写者保证——实测 market 7459 文件仅 1 种键集）+ `tests/test_query_market.py` 新增 `test_view_sql_glob_and_no_union` 防回归测试（钉死视图 SQL 必须是 glob 串且无 union_by_name）；另附 N4 全过程 friction-log 记录。缺口审计盲区照 spec 注明：SQL 只看已有文件，「整批缺失」不可见，须以 ok+skip 总数交叉印证（已做，见上）。

## Step 11.9 全量收口 — 通过

- `$PY -m pytest tests/ -q` → **224 passed, 3 subtests passed**（原 223 + N4 防回归 1）in 1.38s
- `$PY -m ruff check tools/daily-watch/scripts tests` → **All checks passed**
- 六处文档勾验（对照 spec §10）：
  1. `tools/daily-watch/README.md` L380「本地持久化（市场数据层）」章节（目录树/schema 字段字典/CLI 示例）✅
  2. `DATA-SOURCES.md` L14 mootdx 行扩展「财务快照（gpcw，148 期至 1988）；板块指数（880/881 段，通达信自编口径）」✅
  3. `system/skills/daily-watch.md` L40 持久化钩子（失败不阻塞）+ 新闻快照步骤、L104 每日 16:30 调度说明 ✅
  4. `AGENTS.md` + `CLAUDE.md` + `system/templates/AGENTS.md` + `system/templates/CLAUDE.md`（同源四文件）：L33 核心路由「日报监控」行主要写入补 `data/`（持久化钩子）、L106 mootdx 数据源行补用途 ✅
  5. `workspace/workspace-config.md` + `system/templates/workspace-config.md` L27 目录表 `data/` 行 ✅
  6. `ARCHITECTURE.md` L159 目录树 `data/` ✅
- 另：`.gitignore` L46 `data/` ✅；`CHANGELOG.md` L13 持久化条目 ✅

## Step 11.10 落档与提交

- N4 修复 commit（query_market.py + 防回归测试）：`fix: ensure_view 退回 glob 串（N4：~7000 文件显式列表 DuckDB 解析未过 e2e）`
- 验收 commit（本文件）：三票对照实测数值入 message body，计时实测值替换占位
- 不 push（按 Task 约束）

## 结论

Step 11.1–11.10 全部通过，无带病过关项。3 年回补目标由 11.7 兑现（7504 只 × 800 bars，5m10s）；日常增量成本 4.7s（非交易日/已跑日闸门短路）与 16.7s（真实增量几乎全 skip）两段均落档；唯一计划外事件 N4 已修根并防回归。
