# 免费数据源接入指南

> 最近核对：2026-09-30。免费额度和接口权限会变化，接入前请以各服务商官方页面为准。

`daily-watch` 和 `podcast` 已随 Hub 安装，不需要再安装独立项目。下面只是在启用自动行情、自动标签或播客摘要时，选择数据源和安装可选依赖。

## 先按市场选择

| 需求 | 推荐起步方式 | 成本与限制 | 要做什么 |
|---|---|---|---|
| 美股基础行情 | Nasdaq 无 Key 降级源 | 免费、无需注册；只提供基础行情，稳定性不作承诺 | 安装基础依赖后直接运行，脚本会自动使用 |
| 美股备用行情 | Finnhub | 注册后取得 API key；免费端点和额度以官方当前账户为准 | 把 key 写入 `FINNHUB_API_KEY` |
| 个人研究的多市场备用行情 | yfinance | 无 Key；非官方 Yahoo 接口，只适合个人研究/教育用途 | 安装 `yfinance`，再设置 `ENABLE_YFINANCE=1` |
| A 股日线 | Tushare | 官方当前规则下，120 积分档的非复权日线价格为 0 元；更完整数据需要更多积分或单独权限 | 注册、补全资料、取得 token，并安装 tushare 依赖 |
| 港股 / 韩国 / 芬兰小股票池 EOD 备用 | EODHD | 免费账户当前为 20 次调用/日，可取任意 ticker 过去一年 EOD 历史；不是实时行情 | 把 key 写入 `EOD_API_KEY` |
| 美股 EOD / profile 测试 | FMP Basic | 免费 Basic 当前为 250 次调用/日；全球覆盖和高级数据属于更高套餐 | 把 key 写入 `FMP_API_KEY` |
| 后台 wiki 自动标签 / 播客摘要 | 任一兼容的 LLM API | 通常按量计费；不是 Core Mode 前提 | 在 `config/pod2wiki.env` 选择 provider 并填写 `LLM_API_KEY` |

交互会话可以由当前 Agent 完成摘要和标签，不需要独立模型 Key；播客使用 `--agent-handoff` 准备原文和待处理队列。

FMP 的免费 Basic 不能概括为“免费全球行情”；官方当前把 Global Coverage 放在更高套餐。Tushare 的免费日线也不等于所有 A 股数据免费。Hub 会在缺少 key 时保留报告骨架并标记缺口，不会编造数据。

## 三条最短路径

### 1. 美股：零 Key 先跑通

```bash
python3 -m pip install -r requirements.txt
python3 tools/daily-watch/scripts/check_setup.py --init
```

把几只美股加入 `config/daily-watchlist-watchlist.md`，然后运行：

```bash
python3 tools/daily-watch/scripts/generate_daily_report.py
```

个股基础行情会先尝试 FMP（如果配置），缺失时自动走 Nasdaq。宏观、财报日历等仍可能因为没有 FMP key 而显示 `N/A`。

### 2. A 股：接入 Tushare

1. 在 [Tushare](https://tushare.pro/register) 注册、补全资料并在个人中心取得 token。
2. 安装额外依赖：

```bash
python3 -m pip install -r tools/daily-watch/requirements-tushare.txt
```

3. 在 `config/daily-watchlist.env` 填写：

```dotenv
TUSHARE_TOKEN=你的_token
```

4. 股票代码使用 `601857.SH` / `000001.SZ`，再运行检查：

```bash
python3 tools/daily-watch/scripts/check_setup.py
```

### 3. 多市场个人研究：启用 yfinance

```bash
python3 -m pip install yfinance
```

在 `config/daily-watchlist.env` 填写：

```dotenv
ENABLE_YFINANCE=1
```

yfinance 是 FMP、Nasdaq、Finnhub、EODHD 之后的最后降级源。它不是 Yahoo 官方 SDK，项目作者明确提示数据接口仅适合个人用途；公开产品或商业用途应另行确认数据授权。

EODHD 在 Hub 中走免费档可用的 EOD 历史接口，取最近两个交易日计算涨跌，不冒充盘中实时价。

## Key 放在哪里

- 行情：`config/daily-watchlist.env`
- LLM：`config/pod2wiki.env`
- 不要把真实 key 写进 README、AGENTS、聊天截图或 Git 仓库。
- `config/*.env` 已被 `.gitignore` 排除，但仍建议在提交前运行 `git status` 检查。

检查当前状态：

```bash
python3 system/scripts/check_workspace.py
python3 tools/daily-watch/scripts/check_setup.py
```

Windows 用户把 `python3` 换成 `python` 或 `py -3`。

## 官方入口

- [FMP Pricing](https://site.financialmodelingprep.com/developer/docs/pricing)
- [Tushare 积分与权限](https://tushare.pro/document/1?doc_id=290)
- [Finnhub API Docs](https://finnhub.io/docs/api)
- [EODHD Pricing](https://eodhd.com/pricing)
- [yfinance 项目与使用边界](https://github.com/ranaroussi/yfinance)

<!-- 文件说明：安装后免费与低成本数据源的选择、配置和验证入口。 -->
