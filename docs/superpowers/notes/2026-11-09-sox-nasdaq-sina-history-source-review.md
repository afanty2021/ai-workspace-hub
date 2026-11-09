# ^SOX Nasdaq 主源切换 + XAUUSD=X 新浪历史接线批次 max 评审 + 修复闭环报告

- **评审对象**：工作树未提交变更（BASE=f79dbc2）——^SOX 历史主源切 Nasdaq 官方 historical（票级分发+东财降级）、XAUUSD=X 历史主源切新浪全球期货日线（无降级如实 fail）、push2his 800 天回补收尾、CROSS_ASSET_NOTE 口径更新、七处文档同步、仪表盘刷新（12 文件 +425/-48）
- **评审方式**：max 强度（独立 reviewer subagent + /tmp 变异重放授权），需求源=用户会话指令（Q-20261109-04 出界项批次的后续演进，无独立 plan 文件）
- **日期**：2026-11-09
- **复查**：同日修复波复查（原评审 agent 带上下文复核）——**5 项修复逐项对靶属实 + 独立重放 11 发 9 捕获、0 新 Critical/Important、裁定 Yes**（详见文末复查节）

## 评审结论：0 Critical / 2 Important / 4 Minor，裁定 With fixes → 已全修复验

## 自报声明验证（5 条中 4 条精确属实，1 条数字误报但全绿属实）

| 声明 | 结果 |
|---|---|
| 全量 709 passed + 16 subtests | ❌ 数字误报（全绿属实）：实跑 **714 + 16**，净增 **10** 个测试方法（自报 5） |
| ^SOX Nasdaq 548 行全窗、双锚点逐位命中 | ✅ 548 行（2024-09-03→2026-11-06）；11-05 收 9011.14/开 9806.31 与 H1 档案逐位一致；11-06 收 9390.25 与东财重叠窗一致；source 全部 nasdaq-historical |
| XAUUSD=X 新浪 565 行（2024-09-02 起） | ✅ 11-06 全 OHLC 与 hf_XAU 快照行逐位一致；source 全部 sina-global |
| 腾讯 usSOX 空数组不接、代码无接线 | ✅ 全 scripts grep 仅 docstring 说明性文字 |
| 七处契约同步零漂移 | ✅（带保留意见）四镜像字节一致；**hf_XAU AGENTS 有 / DATA-SOURCES 无=真漂移已发生**（→ I-1） |

附带核对：仪表盘 8 票 × 7 字段与 jsonl 按 `closes[-1-w]` 同口径直算全部一致（上批 I-2 手抄错读数风险本案为零）；CROSS_ASSET_NOTE「各票 ~2024-09 起」与 8 票实际首行一致。

## 首轮变异重放记分：13 发 10 捕获 / 3 漏网

漏网 3 发全部定位为锁缺口（I-1 × 2、I-2 × 1），无一发指向管道行为错误。捕获面覆盖：千分位剥离/升序排序/降级链/分发/浅 series 判定/`--tickers` 白名单/volume '--' 容错/权威覆盖条件。

## 问题与修复

### I-1（Important，修根+复验）契约锁未覆盖新 token 家族——同族第 4 案、补 regex 路线第 2 次复发

- **事实**：本批登记 `Nasdaq 官方 historical`、`新浪全球期货日线`、`hf_XAU` 三个新 token，无一进 `test_repository_contract.py` 派生 regex（仅 251.SOX 被 secid 形态锁住）。变异实证：删 DATA-SOURCES 对应句测试不红；且 hf_XAU 漂移已真实发生。
- **修法（弃补 regex，走机制修根——按 friction-log 硬规则不再打第二次补丁）**：「**反引号即锁**」——契约测试 token 派生新增 `backtick_re`，表行内反引号包裹的 token 一律进锁；四镜像数据源行给三个新 token 加反引号；DATA-SOURCES 补 hf_XAU 同源族口径（真信息补全，非 token stuffing）。登记新接线的动作从「人工记清单+回头补 regex」解耦为书写约定：源名用反引号写即自动受锁。
- **复验**：R1/R2/R3 三发变异（删 DATA-SOURCES 三 token）全红 ✅；存量反引号 token（9 枚 .TDX/.OF/env key 等）进锁零误伤；regex 旧家族兜底仍在。
- **残留边界（复查裁定接受）**：忘加反引号=静默不进锁（标记类锁固有属性，R7' 实证）；失效需「新形态+无旧家族特征+作者忘反引号」三条件叠加。机制化后继建议=数据源表第 1 列按 `/` 拆分子源名整列入锁（结构提取不依赖作者记标记），下次动这张表时顺手做。

### I-2（Important，已修+复验）新浪 800 天窗口过滤无测试守卫

- **事实**：`fetch_sina_global_history_rows` 的窗口过滤（`from_iso <= date <= to_iso`）删除后测试全绿——mock 3 行全在窗内，区分不了「过滤 2006-2024 全史段」与「没过滤」。API 返回 2006 年起全史，过滤回归会一次性吞入 ~5000 行致 8 票窗口口径漂移。
- **修法**：`_sina_mock()` fixture 加窗口外行 `2020-01-02`（含注释），现有 `len(lines)==3` 断言自动成过滤锁。
- **复验**：R4 删过滤 → 红 ✅。to 边（未来日期）无测试=复查观察项（防御性代码，主风险方向 from 边已锁，价值/成本比低接受现状）。

### M-1~M-4（Minor）

| # | 内容 | 处置 |
|---|---|---|
| M-1 | `parse_nasdaq_history` volume="N/A" 整行丢弃（哨兵元组缺 N/A 家族，float("N/A") ValueError 静默吞行——半日市/数据缺口日 SOX 会缺行） | ✅ 元组扩 `("N/A","n/a")` + `test_volume_na_sentinel_keeps_valid_row`；R5 哨兵回退红 ✅ |
| M-2 | Nasdaq 200+data:null（典型反爬）成功-空静默降级无日志，主源失效不可见（^SOX 悄悄退化回 89 行浅历史） | ✅ try 内成功路径加 Warning（异常路径原 Warning 保留不双打）+ `test_nasdaq_empty_response_degrades_with_warning`（stderr 捕获+call_count==2 锁「空成功不重试」语义）；R6 删告警/R8 文本弱化/R10 改重试三发红 ✅ |
| M-3 | README push2his 行把 XAUUSD=X 塞进东财票列表、^SOX 主源切换未注，9 票全走 push2his 的误读 | ✅ 改「默认 800 天主源 6 票…；^SOX 与 XAUUSD=X 票级主源覆盖见下两行，^SOX 失败时仍降级本源」 |
| M-4 | ^SOX.jsonl 混合写者指纹（2026-07 起东财残留 volume/amount=0.0 + source=nasdaq-historical；upsert 按 writer 区分行为无恙） | 不动——未来读数溯源注意点，docstring/测试已说明合并语义 |

## 修复后复验

- `pytest tests/ -q` → **716 passed, 16 subtests passed**（714 + 新增 2），0 fail
- `ruff check tools/daily-watch/scripts tests` → All checks passed
- 修复方变异六发（R1-R6）全红；工作树 13 个 M 文件与首轮 12 个逐文件比对无外来变更混入

## 复查（修复波独立对靶，2026-11-09 同日）

原评审 agent 复核，**逐项属实、独立重放、未采信修复方声明**：

| 复核项 | 结果 |
|---|---|
| I-1 反引号锁（测试/四镜像/hf_XAU 补全/零误伤） | ✅ 四点全中；backtick_re 仅表行提取；hf_XAU 补句为真信息补全；无奇数反引号配对错位风险 |
| I-2 fixture 窗口外行 | ✅ R4 独立复现红 |
| M-1 哨兵+边界测试 | ✅ R5 独立复现红 |
| M-2 告警+测试 | ✅ R6/R8/R10 三发红；redirect_stderr 与 log 实现匹配；side_effect 耗尽设计区分「重试 vs 不重试」非平凡断言 |
| M-3 README 文案 | ✅ 歧义消除 |
| 716+16 + ruff | ✅ 独立实跑一致 |
| 反引号锁残留风险 | ✅ 复查员裁定接受（严格改进论：修复前全新形态 100% 漏网）；后继建议=第 1 列结构锁 |
| 数字勘误 | 存量反引号 token 实为 9 枚（全集 12=9+3），修复方自报 10 枚，无实质影响 |

复查独立重放 11 发：**9 捕获 / 2 漏网**（R7' 忘反引号边界、R9 to 边——均裁为观察项不阻塞）。

**新发现 Issue：0 Critical / 0 Important / 0 必修 Minor。**

## 后继实施：第 1 列结构锁（同日用户拍板，建议提出者验收 Yes）

复查建议 1 当日落地：契约测试 token 派生新增**第 1 列结构提取**——数据源表「数据源」列按 `/` 拆分子源名整名入锁（表头行排除、strip 入库），新源进表即受锁、不依赖作者记得写反引号，「忘加反引号=静默不进锁」的约定边界（R7'）正式关闭。三层锁分工：结构锁管「哪些源」、反引号锁管第 4 列接线 token 族、regex 家族兜底旧形态。

- **上线即抓真漂移**：dry-run 15 个子源名对 DATA-SOURCES 唯一 MISS=`Longbridge Skill`（AGENTS 表有、DATA-SOURCES 全文零提及）→ 表尾补行（内容映射 AGENTS L116+L121，真信息）。
- **验收**（原评审员独立重放）：S1（四镜像第 1 列加新源名不带反引号、DATA-SOURCES 不跟——R7' 精确复刻）捕获 ✅；S2 删 Longbridge 行 / S3 删存量子源名「新浪环球」均捕获；全集 40 枚 token（15 结构+12 反引号+13 regex）零 MISS；裁定 **Yes**。
- **验收新发现 Minor-1（已顺手修+差分复验）**：子源名 token 曾带首尾空格入库（`if n.strip()` 判空未 strip 入库），全绿依赖 DATA-SOURCES 第 2 列恰好同空格排版（S4 实证排版微变即误伤红）——改 `n.strip() for ... if n.strip()`；修复后 T1（去空格排版）单独绿=误伤面消除、T2（加新源名）两态差分红=锁效力不变。
- Minor-2（表头字面匹配 `!= "数据源"`，改表头措辞会红）不修——验收裁定「宁可红」方向可接受。
- 修后全量 **716 passed + 16 subtests** + ruff 绿。

## 评审员建议（记录，供后续参考）

1. ~~数据源表第 1 列子源名结构锁（消除「忘记反引号」路径，下次动表顺手做）~~ **已实施（见上节）**。
2. 新浪过滤 to 边如未来出现未来日期数据再补 mock。
3. 运行时注意点：仪表盘 XAUUSD=X/^TNX/NQ00Y/DX-Y.NYB/HG=F/HSTECH 的 2026-11-09 行为盘中值，次日晚间 batch 权威覆盖修正（与 CROSS_ASSET_NOTE 口径一致）。
