# daily-watch 三提交评审报告（0fa4b8e / eebe943 / 22e6f08）

- **日期**：2026-11-05
- **分支**：feat/sector-rotation-design（三提交均按文件隔离插在 sector-rotation 提交之间）
- **评审方式**：requesting-code-review subagent（max 深度：逐行 diff + 实跑测试 + 对照本机 mootdx 0.11.7 源码 + NaN 桩数据实证）→ 主会话逐条对代码核实（5 条 Important 全部核实属实）
- **处置拍板**（用户，2026-11-05）：5 条 Important 全修，#2 双管齐下（marker 改事件日 + 事件级闸门）；**修复由平行会话执行**，本报告即交接载体

## 评审对象

| 提交 | parent | 主题 |
|---|---|---|
| 0fa4b8e | c9efbe2 | mootdx 板块指数 .TDX 接线（880/881 段 index_bars 两根日线装配） |
| eebe943 | eeaf19e | A 股财报预约披露日历（东财 datacenter 无 Key，-40/+35 窗口） |
| 22e6f08 | eebe943 | ^TNX 切东财实时主源 + NQ00Y 入池（103.NQ00Y） |

## 测试实跑

`/opt/homebrew/caskroom/miniconda/base/envs/Quant-3.11/bin/python -m pytest tests/test_mootdx_source.py tests/test_cn_disclosure_calendar.py tests/test_daily_watch_fixes.py -v`
→ **69 passed, 0 failed（1.33s）**。注：`conda run -n Quant-3.11` 在本机有权限问题，直接用上述解释器路径。

## 逐提交裁定

- **0fa4b8e**：With fixes（Important #5）。commit message 声明逐条兑现：两根装配、单根无涨跌、888 拒绝、误配交易所后缀拒绝均有测试断言；`.TDX` 在东财/腾讯/新浪（`fetch_market_data.py:521-530`）和 tushare（:1007）闸门都被正确拒绝。
- **eebe943**：With fixes（Important #1/#2/#3/#4 全在本提交射程）。UA/Referer + 1 次重试真实存在；status 悲观预设 failed 的契约模式正确；窗口 -40/+35 与文档一致。
- **22e6f08**：**Yes**。链序重排影响面论证成立（FRED 映射表只有 ^TNX）；`mock_fred.assert_not_called()` 验证实时优先，测的是真实链序；与 eebe943 无破坏性交互。

## Strengths（摘要）

- 资格闸门 `^88[01]\d{3}$` 精确圈定板块段，多源闸门一致拒绝 `.TDX`（`mootdx_source.py:75-100`）
- index_bars 网络调用单票 try/except 不连坐；删除旧 `if not by_code: return []` 早退后混批行为正确（`mootdx_source.py:454-461`）
- 装配列名与 mootdx 0.11.7 实际行为核对一致（88 段自动路由 SH 市场、`vol`→`volume` 复制）
- `_merge_earnings_status` clear+update 保持 dict 引用稳定，调用方零感知
- watchlist 不入库约束遵守：无硬编码票池、无凭据

## Important（全部需修，已逐条核实）

### #1 `_merge_earnings_status` 丢弃 period_start/period_end，报表覆盖段必现退化

- **位置**：`tools/daily-watch/scripts/fetch_market_data.py:1201-1209`
- **事实**：ok 分支 `fmp_status.clear()` 后只回填 `state/sources/fmp/cn/cn_count`，而 FMP（:1182）与东财（:1319）各自写在自己 status dict 上的 `period_start/period_end` 被一并丢弃；唯一消费方 `generate_daily_report.py:949-950` 从 merged dict 读 → **每次成功运行**都渲染「财报检查区间：未提供 至 未提供」。这是对 FMP 既有正常路径的回归（合并前能显示周一至周五）。
- **修复**：ok 分支把生效通道的窗口带出来。两通道窗口口径不同，建议分别存 `fmp_period_start/fmp_period_end` 与 `cn_period_start/cn_period_end`（或 `period_start/period_end` 取生效通道 + 单独带另一通道），渲染端 `generate_daily_report.py:949-950` 分别展示。
- **验收**：单测断言 merged ok dict 含两通道 period 键；渲染快照不再出现「未提供 至 未提供」。

### #2 同一财报事件每天重复写回信号与证据，最长 40 天（用户拍板：双管齐下）

- **位置**：`generate_daily_report.py:714-718`（marker 含报告日）× `fetch_market_data.py:1239-1240`（-40 回看窗）
- **事实**：去重 marker `DW-{今天}-earnings-{ticker}-{hyp}` 含报告日而非事件日；CN 已披露行在 -40 天回看窗内**每天**重新进入 `earnings`，对任何 `linked_entities` 含该票的假设每天新写一条时间线条目 + 一个 `E-YYYYMMDD-earnings-…` 证据文件（`write_signal_evidence` :721-726 按日建新文件）。持续污染假设时间线并堆积证据文件。
- **修复方案（用户已拍板"两者都做"）**：
  1. **marker 幂等**：`build_signal_marker` 对 earnings 信号改用**事件日**（`actualDate or appointDate`）替代报告日构造 `DW-{事件日}-…`。实现建议：signal dict 增带 `event_date` 字段，marker 构造时 earnings 类型优先取它；其他信号类型维持报告日。旧条目 marker 格式不变，不受影响。
  2. **事件级闸门**：`collect_hypothesis_signals` 对 `source=eastmoney-disclosure` 的行，仅当 `daysUntil ∈ [0, 7]`（临近预约披露）或 `actualDate` 距今 ≤ 7 天（刚披露）时进入信号列表。**闸门只管信号写回，渲染端 earnings 表格仍展示 40 天窗口全量**——数据可见性与时间线卫生分离。7 天为建议值，可调；若要更保守可用 5。
- **验收**：同一事件构造两天报告日跑 collect，只写一条 marker/时间线条目；`daysUntil=30` 的已预约行不进信号但仍在表格渲染。

### #3 `date.fromisoformat(appoint)` 无保护，畸形日期拖垮整份日报

- **位置**：`fetch_market_data.py:1296-1298`（解析循环无 try；`build_snapshot` 的 future `.result()` 与 `generate_daily_report.py` 的 `run_json_script` 均无兜底）
- **事实**：东财一旦返回非 ISO 日期（字段格式变更/脏数据），ValueError → fetch 脚本 exit 1 → **当日报告不生成**，违反「单源失败不拖垮日报」原则。FMP 对应路径有整段 try（:1149-1153），东财路径没对齐。注意 `_day` 返回 `str(value)[:10]`，`"2026/11/20"`、`"None"` 这类值都能穿透到 fromisoformat。
- **修复**：对齐 FMP 契约——解析段（:1282-1314 循环）整段 try/except，单行解析失败 log warning 跳过该行（不 return [] 整批丢弃），或 `_day` 内 `re.fullmatch(r"\d{4}-\d{2}-\d{2}")` 校验。
- **验收**：桩数据喂非 ISO `APPOINT_PUBLISH_DATE`，函数不抛异常、跳过坏行、其余行正常返回。

### #4 pageSize=100 单页无 pages>1 防护，静默截断

- **位置**：`fetch_market_data.py:1257`（`pageSize=100&pageNumber=1`，`sortTypes=-1` 按预约日降序）
- **事实**：行数超 100 时**最旧的行被静默丢弃**且无告警。当前 ~28 票安全；watchlist 自由扩池 + 窗口内多报告期/改期记录时可能触线。
- **修复**（一行级）：`payload["result"]["pages"] > 1` 时 `log warning` 明示截断（或循环拉全页，成本略高）。
- **验收**：桩响应 `pages=2` 时日志出现 warning。

### #5 `_index_quote_from_bars` 在单票 try 之外 + NaN 守卫缺口（NaN 行为已桩数据实证）

- **位置**：`mootdx_source.py:462`（装配调用在 :455 try **之外**）× `:373-374`（`price <= 0` 挡不住 NaN，NaN 比较为 False）× `:386-387`（`startswith("Na")` 大小写敏感，抓不到小写 `"nan"`；fallback 里 `int(nan)` 抛 ValueError）
- **事实**：坏行异常逃逸 → `fetch_mootdx_quotes` 整体抛 → `build_snapshot` 判 mootdx 批次失败 → **全部 CN 票（含正常个股）落 HTTP 降级链**。日报不挂但降级面放大，违反该函数 docstring 自己声明的「单票失败只降级那一票」。实测三个穿透：NaN close 进报告（price=NaN）、NaN datetime → `tradeDate='nan'`、datetime 缺失 + year NaN → `int(nan)` 炸。
- **修复**：① `:462` 装配调用挪进 :455 的 try（或独立 try）；② `:374` 守卫加 `math.isnan(price)`（`_to_float` 已保证 float 或 None，`price != price` 亦可）；③ `:387` 判断改 `trade_date[:2].lower() == "na"` 或 `len(trade_date) != 10` 兜底。`_quote_from_snapshot` 有同款 NaN 守卫缺口（既有模式），顺带对齐。
- **验收**：桩 bars 喂 NaN close / NaN datetime / 缺 datetime+NaN year 三例，`_index_quote_from_bars` 均返回 None 或安全跳过，批次内其他票不受影响。

## Minor

1. 0fa4b8e commit message 写「测试 +7」实际新增 6 个（`grep -c "def test_"` 前后核对）——记录即可，无代码可修。
2. **顺手修**：`.TDX` 票会进 FMP 批（`fetch_market_data.py:1546-1550` 只排除 `.SH/.SZ/.HK`），空查询一次占批额度——排除条件加 `.TDX`。
3. 交易所重建不含北交所（:1284 `startswith(("6","9"))` 之外全落 `.SZ`）；当前池无 .BJ 票，属文档级边界，可不修但建议在 README 已知限制提一句。
4. 信号截断 `earnings[:10]`（:549，FMP 行在前）与渲染端 FMP `[:6]` / CN 无上限不一致——建议统一排序后截断。
5. `_day` 闭包在 for 循环内重复定义（:1289）——挪到循环外。
6. filter URL 由 watchlist 自由文本拼入（:1249-1257）——本地 gitignore 配置、最坏 graceful 失败，无实际注入面；可加 `^\d{6}$` 预校验增强健壮性。

## 给修复会话的执行注意

1. **环境**：一律 `/opt/homebrew/caskroom/miniconda/base/envs/Quant-3.11/bin/python`（系统 Python PEP-668；`conda run` 本机有权限问题）。
2. **共享分支**：当前在 feat/sector-rotation-design，与 sector-rotation 会话共存。本次修复只动 daily-watch 文件（`fetch_market_data.py` / `generate_daily_report.py` / `mootdx_source.py` + 对应 tests），与 sector-rotation 文件不相交；提交前 `git log` 查外来 commit，按文件隔离提交在分支 HEAD 上，commit message 标注与 sector-rotation 无关（沿用三提交的写法）。
3. **测试**：修完全量跑 `python -m pytest tests/ -q`（不止三个目标文件），新增强调用例见各条「验收」。
4. **提交**：用户点名才提交；按关注点拆 commit（如 #1+#3 一组报表回归/防御、#2 一组信号幂等、#4+#5 一组守卫）。
5. **friction-log**：建议顺手记一条——「同类路径防御覆盖不一致」（FMP 有 try 东财没有；个股装配与指数装配守卫不对称），范围项目级，修根即本批修复。
6. **复查**：修复波必须独立对靶复查（教训来自 data-persistence 五轮评审）：每条 Important 修完后单独验证该条验收项，不许只跑全量绿就收工。

## 总裁定

**22e6f08 — 可合并；0fa4b8e / eebe943 — 修完上述 Important 后可合并。**

---

## 第二幕：修复波独立对靶复查（同日，requesting-code-review max）

修复由平行会话以工作树未提交改动执行（5 文件 +230/-26）。复查按三件套：逐条对靶 + 全量实跑 + /tmp 变异（10 变异 9 红）。

### 对靶结果

| # | 裁定 | 要点 |
|---|---|---|
| #1 period 键 | **PASS** | 双通道 `fmp_period_*`/`cn_period_*` 分开带出，渲染分「美股/A 股」双窗口；m1/m2a/m2b 变异红 |
| #2 信号重复写回 | **PARTIAL** | marker 事件日 + 事件级闸门双管真装上（渲染表格不受闸门影响）；但证据文件维度未根除（见 N-2）+ 链路级验收测试缺失 |
| #3 fromisoformat | **PASS** | `_day` ISO fullmatch + 解析循环整段 try 双层防御 |
| #4 pages 告警 | **PASS** | `pages>1` warning；m6 红 |
| #5 NaN + try | **PASS** | 装配进单票 try、`price != price` 守卫两处、日期三重守卫；m7/m8/m9 红 |

附带项：Minor#2（.TDX 排除）已修；friction-log 已记「同类路径防御覆盖不一致」；`_day` 挪出循环顺带修。

### 复查新抓（修复波引入，2 Important + 4 Minor）

- **N-1 Important·时间炸弹测试**：`test_near_appointment_and_recent_actual_included` recent 用例硬编码 `actualDate="2026-11-03"`，闸门 `date.today()` 不可注入 → **2026-11-11 起全量跑必红**。
- **N-2 Important·证据文件按日新建**：`write_signal_evidence` 在 marker 去重前无条件执行、evidence_id 用报告日 → 7 天窗内同一事件每天新建一个 `E-YYYYMMDD-…` 文件（堆积从 40 天缩到 ≤8 天，未根除）。
- N-3 Minor：`_within_days` 用 `abs` 放行未来 0~7 天的脏 `actualDate`。
- N-4 Minor：坏行测试用池外票（600309），票池交集先剔除，except 防线零覆盖（m5 变异绿的根因）。
- N-5 Minor：末根 close 外其他列 NaN 无守卫（超出 #5 守卫清单，记录）。
- N-6 Minor：旧口径 earnings 条目迁移到事件日 marker 后一次性再写一条（影响一次性极轻）。

## 第三幕：复查返工（本会话执行，用户拍板）

用户拍板本会话修 N-1/N-2（顺手 N-3/N-4）：

1. **N-1 修根**：`collect_hypothesis_signals` 加 `today: date | None = None` 参数（`gate_today = (today or date.today()).isoformat()`），测试 `_collect` 注入 `today=date(2026, 11, 5)`——测试不再随真实日历漂移。
2. **N-2 修根**：`apply_hypothesis_updates` 顺序反转——先读假设文件做 `append_signal_to_hypothesis` 去重，**真追加（changed=True）才写证据文件**；证据路径拆纯函数 `_evidence_path_for`（append 渲染要用 relpath，先算路径后落盘同源）。
3. **N-3**：`_within_days` 改有向 `-days <= delta.days <= 0`（未来 actualDate=脏数据拒收）。
4. **N-4**：坏行测试改池内票 300476（同票坏日期行），except 防线进测试射程。
5. **补链路级验收**（复查指出缺失）：`ApplyWritebackDedupTests`——同一财报事件跨两个报告日（11-05/11-06）跑 `apply_hypothesis_updates`，断言 `(1, 0)`、证据文件恰 1 个（E-20261105-*）、时间线 marker 恰 1 条。

**变异验证四发全红（/tmp 副本）**：V1 时间流逝 +10 天 → recent 用例红（证明注入修根有效）；V2 去重回退（证据写回去重前）→ 链路测试红；V3 回 `abs` → 未来 +3 天用例红（首版用例 +15 天无区分度已修正——abs 也能拦更远的未来，漏洞窗口只在 0~7 天）；V4 删 except → 坏行测试红（m5 盲区补上）。

**全量**：539 passed / 0 failed（+4 用例：future actual 拒收、链路去重、注入版 near/recent、池内坏行改写）。

### 最终裁定

**三条提交的修复全链闭环（5 Important 全 PASS + 复查新抓 2 Important 修根 + 变异四发全红）：工作树改动可提交。** 建议 commit 拆法：平行会话修复（5 Important）与本会话返工（N-1~N-4）可合为一个 fix(daily-watch) 或按「报表回归+防御 / 信号幂等+去重」拆两个，用户点名执行。
