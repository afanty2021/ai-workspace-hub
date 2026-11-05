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

> **文档同步硬规则**：改动 `tools/daily-watch/` 的代码、数据源顺序或依赖时，必须同步四处，一次不落——
> ① `tools/daily-watch/README.md`（工具自带说明：数据源表、Fallback 顺序、零 Key 矩阵、环境变量）；
> ② `DATA-SOURCES.md`；③ 本 skill 的「数据源优先级」；④ `AGENTS.md` + `CLAUDE.md` 数据源表（含 `system/templates/` 同名模板）。
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
6. Agent 扫描 `hypothesis/H*.md`。可确认的行情/财报信号先写入 `evidence/YYYY-MM/`，再把证据 ID 引用到相关假设；主题匹配仍只提示，不自动造证据。登记前判业务时点与可得时点，跨时区按当期实际偏移填 `available_at`（三时点口径见 `system/integrations/object-model.md`）
7. 最终报告写入，更新 `workspace/meta/active-context.md`
8. 报告落盘后补运行账本 close 行（一步命令，含 `--evidence`，见「运行账本」）

日报默认只处理上一份日报之后的新证据，使用 `dedup_key` 避免重复堆积；这仍是现有 `daily-watch`，不是新的日报类型。日报不自动改变假设确定性或状态。命中证伪条件、关键催化剂、财报或连续多条同方向证据时，追加待确认复盘项，并提示按 `system/skills/hypothesis-review.md` 启动复盘。

## 数据源优先级

| 优先级 | 数据源 | 市场 | env key | 费用 | 获取 |
|--------|--------|------|---------|------|------|
| 1 | mootdx | A 股 + ETF (.SH/.SZ) + 板块指数（880/881 段 `.TDX`） | 无（`DISABLE_MOOTDX=1` 停用） | 免费，TCP 7709 直连通达信，实时快照（板块指数走 index_bars 日线） | [项目](https://github.com/mootdx/mootdx) |
| 2 | tushare | A 股 (.SH/.SZ) + HK | `TUSHARE_TOKEN` | 120 积分非复权日线当前 0 元（EOD）；其他看权限 | [注册](https://tushare.pro/register) |
| 3 | FMP | 免费 Basic 以美股 EOD/profile 测试为主；扩展市场看套餐 | `FMP_API_KEY` | 免费 250 次/日 / 付费 | [Pricing](https://site.financialmodelingprep.com/developer/docs/pricing) |
| 4+ | Nasdaq / Finnhub / EODHD / 东财 / 腾讯 / 新浪 / yfinance | 各自覆盖 | 无 Key 或各自 key | 自动 fallback | `DATA-SOURCES.md` |

mootdx 未命中或缺装 → A 股在降级链里先试 tushare（首备用），再东财/腾讯/新浪。mootdx 服务器全网不可用时记 5 分钟负缓存快速失败，不影响整份日报生成。

无任何 key 且未装 mootdx → 美股基础行情先尝试 Nasdaq，其余缺口在报告骨架中标 `[待补充]`，agent 用 websearch 补充。

Longbridge Skill/CLI 是独立 Agent 扩展，不是 `tools/daily-watch/` 的内置数据源。需要时可用于 Agent 的临时查询，但不要把它写成日报脚本已接入。

## 输出路径

| 输出 | 路径 |
|------|------|
| 日报 | `output/daily-watch/YYYY-MM/YYYY-MM-DD.md` |
| 独立证据 | `evidence/YYYY-MM/E-*.md` |
| 假设证据 | `hypothesis/H*.md`（只追加证据引用） |
| 长期结论 | `wiki/explorations/`（可选沉淀） |

## 运行账本

每次运行在 `data/.state/run-log.jsonl` 记存在证明与修订痕迹（schema 见 `system/integrations/object-model.md`「运行账本」）。`open` / `data-close` 由持久化钩子自动写入；报告落盘后 skill 一步补全 close 行：

```bash
python3 system/scripts/run_archive.py close --run-id RUN-YYYYMMDD-HHMM-watch \
    --report output/daily-watch/YYYY-MM/YYYY-MM-DD.md \
    --evidence E-20261103-mover-300476-sz-h1
```

`--evidence` 可多次传（本次 run 产出的每个独立证据文件一个 E-ID）。缺 `E-ID:sha256` 时自动按归一化口径现算注册（I4 豁免：review_status/direction/confidence 三个状态字段的合法生命周期迁移不误报，只有正文改动才算修订）。

修订纪律：任何对已 close 运行产物的修改（报告正文、series 行、evidence 文件），**先 `run_archive.py amend` 记 intent，改完 `amend --done`** 补哈希，两步都不可省，漏记会被 verify 抓出。报告里的「数据修正披露」散文段保留（给人看），amend 行是其机器可读镜像。

## 股票池格式

`config/daily-watchlist-watchlist.md` 是 markdown 表格：

```markdown
| Ticker | Name | Market | Market Cap | Category | Tier | Hypothesis | Notes |
|--------|------|--------|------------|----------|------|------------|-------|
| NVDA | NVIDIA | US | Mega | Semiconductor | HOT | H1 | AI GPU leader |
```

必需列：Ticker, Name, Market, Market Cap, Category
可选列：Tier, Hypothesis, Notes

A 股个股/ETF 用交易所后缀（`.SH`/`.SZ`）；通达信 880/881 段板块指数用 `.TDX` 后缀（如 `881075.TDX` 贵金属，Market 列填 CN，volume 为板块成分合计口径）。

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

每日 16:30 ZCode 定时批量跑 update_market_series + update_finance_snapshots（幂等，非交易日自动零增量）。
