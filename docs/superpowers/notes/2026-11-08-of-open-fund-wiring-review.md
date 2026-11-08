# 场外基金 .OF 接线批次 —— max 实施评审报告（2026-11-08）

> 评审对象：`b5e2c3d..99452de` 六笔（核心 = `31d0851` .OF 场外基金接线 + `99452de` 契约行同步；另含 `0738955` 轮动四批次 merge、`b57ed61`/`d7d5776`/`a93c56b` docs/chore）+ 工作树 `_index.md` +2 行（评审中由并行会话收编为 `6cb4cdc`，核实与已评审 diff 一致无夹带）。
> 范围口径：今日已闭环两批（`1ad155c..cc741d6` 港股降级链、`a9ce2a8..5c1939f` 腾讯美股）不重复评；`output/research/` 内容质量不在范围。
> 模式：单趟 max 评审员（生产代码 / 测试+变异区分度 / 文档契约 / 实网四合一，72 次工具调用含 /tmp 变异重放），实施方逐条核实后修复、四变异独立复验全红。

## 结论速览

**0C / 2I / 4M → With fixes 已全闭环**（2I+4M 全修，0 条有据不修）；随后独立复查趟裁定 **Yes 可提交**（12 发变异独立重放全符合，抓 3 Minor 当场修/注记 + 1 注记进 queue）。终态：全量 **674 passed + 16 subtests**、ruff 净、修复波四变异 + 复查趟 12 变异 + R-1 修复复验全红。

## 评审员核实记录（修复前）

- **夹具真实性（实网两发）**：腾讯 `jj021179` 返回与夹具**逐字节一致**；tushare `fund_nav(021179.OF)` 518 行降序、最新三行（20261106/2.8052、20261105/2.8625、20261104/2.8094）与夹具**逐位一致**——载荷确实镜像真实抓取，双源自算 -2.0017% 独立对拍吻合。
- **短链覆盖点干净**：长链全 lazy lambda，`get_cached_tushare_client` 在 gate 内（.OF 不触发），`fetch_market_data.py:1192-1202` 整链重写发生在执行前；degradations 只记 fund 短链真实环。
- **`_CN_CODE_RE` 白名单回归**：全池 41 票段位 100% 覆盖零误伤；002910 形状重叠边界在档锁定（防线=`.OF` 约定本身）。
- **轮动 merge 零丢行**：ID 层超集；两处内容级差异均取 main 侧更新版（其一另存分支版全文+收口段），spec 数字逐项对拍全中（V0 锚 -11.14/-12.07/-11.15%、持仓周 115/118/155、U=69、-16.42% vs -14.65%）。
- **时间炸弹零命中**：新增 5 文件 grep `date.today|datetime.now|date(20` 零结果，硬编码日期均为冻结协议常量。

## Issues 闭环明细

### I-1（Important）：DATA-SOURCES.md 漏同步——契约七处唯一漏网，同类第 3 次 → 修根进测试

- **事实**：`grep -cE "fund_nav|场外|\.OF" DATA-SOURCES.md` = 0；`ARCHITECTURE.md:110` 却指引"详细边界见 DATA-SOURCES.md"。前两次同类（模板漏同步）已有案，本例触发 friction-log 硬规则"第 2 次起禁止再打补丁"。
- **修复**：①tushare 行补"场外基金净值（fund_nav，watchlist `.OF` ticker 主源，2026-11-08 实测 120 积分同档可调，T-1 口径）"、东财/腾讯/新浪行补"场外基金净值（腾讯 jj 前缀，tushare-fund 断供时的轻量备份）"，措辞与 AGENTS.md 契约行同源；核对日期 2026-11-02→11-08（两源当日实网复核）。
- **修根**：`test_repository_contract.py` 新增 `test_data_sources_doc_covers_entrypoint_wirings`——从 AGENTS.md 数据源表**派生**接线 token 集（`\d{3}(?:/\d{3})? 段 | [a-z]{2,3} 前缀 | [a-z]+_nav | gpcw | datacenter`，当前 8 个），断言每个 token 在 DATA-SOURCES.md 出现。清单不再靠人记：往 AGENTS.md 加新接线而 DATA-SOURCES.md 不跟，测试直接红；解析失效（表挪位置）时 `assertTrue(tokens)` 宁红不静默。README/skill 为操作手册覆盖面天然不同，不做 token 平价（取舍写入测试注释）。
- **复验**：MUT-C（删 DATA-SOURCES.md 的 fund_nav）→ 契约测试红 ✓。

### I-2（Important）：腾讯 jj 夹具字段位 5↔6 零区分度（评审员变异重放实锤）

- **事实**：真实 021179 无分红，单位净值=累计净值=2.8052，`fields[5]`↔`fields[6]` 漂移时 `test_parses_jj_payload` 仍绿（评审员 /tmp 变异 4 passed 实证）。有分红/拆分的基金会读到错误净值。
- **修复**：新增合成夹具 `TENCENT_JJ_DISTINCT_NAV_PAYLOAD`（unit 2.8052 ≠ accum 3.4100，注释声明非真实抓取、专职锁字段位）+ 断言 `price == 2.8052`。
- **复验**：MUT-A（解析索引 5→6）→ 新断言红、原 4 条仍绿（零区分度事实同时被测试固化）✓。

### M-1：`never_touches` 测试对路由移除零区分度 → 补路由锁

- **事实**：长链各环对 `.OF` 全 gate 掉零 HTTP，`mock_get.assert_not_called()` 在路由移除变异下恒绿；路由正确性实际由另两条 quote 断言测试锁定。
- **修复**：补 `degradations` 断言——全 miss 时恰好 `[tushare-fund, tencent-fund]` 两环、fallback `[tencent-fund, none]`；路由漏进长链时长链环名会让断言红。
- **复验**：MUT-B（`is_open_fund_ticker` 强制 False）→ 链测试 5 红 ✓。

### M-2：fund_nav 净值停发时"日涨跌"实为期间涨跌且无法检测 → 透传 previousTradeDate

- **事实**：最新两行差分不区分相邻披露日与隔月停发（封闭期/暂停申赎/QDII 延迟）；长假**不**触发（净值行本身是披露日序列）。
- **修复**：`fetch_tushare_openfund_nav` 返回 `previousTradeDate`（单行=None，语义注释就位）；`build_quote_record` 白名单同步透传（`_iso_trade_date` 归一 20261106→2026-11-06）。隔月夹具测试 + record 透传断言 + 单行 None 断言。
- **复验**：MUT-D（删 record 透传行）→ 红 ✓。

### M-3：`part2_cells` 返回注解与实返不符

- `-> tuple[dict, dict]` 实返 `(cells, anchors, cover)` 三元组（调用点 `:265` 三元解包）→ 注解改 `tuple[dict, dict, dict]`。

### M-4：干净拒绝 vs 异常拒绝 reason 区分器无测试锁定 → 补语义断言

- **事实**：截断载荷（干净拒绝，reason="returned no data"）与 HTTP 异常（reason=真实异常文本）在代码里有区分（`fetch_market_data.py:1217-1218`），但测试只有 `assertIsNone`，两路径互换不红。
- **修复**：新增 `test_clean_reject_and_exception_reject_have_distinct_reasons`——同一 tencent-fund 环两路径 reason 各锁一例（"returned no data" vs "connection reset"）。

## 修复波操作插曲（已记 friction-log）

1. 变异脚本经 `conda run python - <<EOF` 管道执行全部空跑（conda run 不透传 stdin），首四变异假绿——改 /tmp 脚本文件 + grep 落盘确认后重放才作数。跨会话第 2 次，操作程序修根：变异一律落文件。
2. MUT-C 还原误用 `git checkout -- DATA-SOURCES.md`，把工作树未提交的 I-1 修复一并还原——脏文件还原必须 cp 备份回拷。两误均当场发现当场修正，终态 diff 复核为纯修复内容（5 文件 +117/-6）。

## 复查趟（2026-11-08 第二双独立眼睛，用户点名）

**裁定：修复波可提交（Yes）。** 复查员独立重放 **12 发变异**（原四发 + 自加 8 发）全数按预期红/绿；逐条对靶六条 findings 全部**命中靶本体**（无表面修复、无偏靶）；previousTradeDate 下游全链核查**零破坏**（series 落盘显式白名单不含新 key、日报渲染只取固定字段、快照 JSON 多一 key 但 `data/market/daily/` 不入 git）；既有测试改动逐行核对**零弱化**（均为追加断言/传参）；报告全部可验证声明核实**属实**（含 673−669=4 的账目自洽、HEAD 基线 worktree 独立复跑 669 绿）。

复查抓到 3 条新 Minor + 1 条注记，当场处置：

| # | 级别 | 内容 | 处置 |
|---|------|------|------|
| R-1 | Minor | 契约正则 `[a-z]{2,3} 前缀` 依赖空格：AGENTS 改无空格写法+DATA-SOURCES 删行时**静默漏锁**（MUT-H2 实证） | **已修**：正则空格可选化 `[a-z]{2,3} ?前缀`（段同步 `? ?段`）；复验：无空格变异+删行下契约测试由静默绿转**红** ✓ |
| R-2 | Minor | `prev_date` 的 `str()` 包 NaN：nav_date 缺失时产出 `"nan"` 字符串穿透进快照 | **已修**：`\d{8}` fullmatch 防御，非 8 位披露日置 None；NaN 夹具测试锁定 |
| R-3 | Minor | tencent-fund 备份源无前值日期位，gap 检测缺位（已知边界） | **已注记**：`fetch_tencent_openfund_quote` docstring 边界在档 |
| R-4 | 注记 | 已提交 `_index.md` 链接 4 个 gitignore 的 EXP 正文——干净检出（新克隆/CI）下链接测试红（与修复波无关，仓库既有状态） | **进 review-queue Q-20261108-20 pending**（三方向待拍板，推荐正文解除 ignore 入库） |

遗留风险（复查员在档，不阻塞）：previousTradeDate 目前"有钥匙无锁匠"（报告/series 落盘尚未消费 gap 检测，等待未来下游）；R-1 修复前的漏锁需"AGENTS+模板同批无空格改写+DATA-SOURCES 删行"三处协同才触发，现已被空格可选化关死。

## 终态

- 全量 `pytest tests/ -q`：**674 passed + 16 subtests**（评审前 669 + 修复波 4 + 复查波 1：jj 字段位锁 / fund_nav 隔月 / reason 区分器 / record 透传并入既有用例 / NaN 防御）。
- ruff 对 4 个改动 py 文件 All checks passed（复查波后复跑同净）。
- 变异复验：修复波四发全红（A: jj 索引 / B: 路由 / C: 契约 token / D: 透传）+ 复查趟 12 发独立重放全符合 + R-1 修复复验转红。
- 修复未提交（等用户点名）：DATA-SOURCES.md、tests/test_open_fund_source.py、tests/test_repository_contract.py、tools/daily-watch/scripts/fetch_market_data.py、tools/sector-rotation/ashare_hold_probe.py + 本报告。
