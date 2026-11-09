# Max 评审报告：HSTECH 备份源修根 + 批量脚本接入 run-log 账本（2026-11-09）

**范围**：工作树未提交变更（base a68be7e），17 个已跟踪文件修改 + 2 个 untracked 新文件（`batch_ledger.py` / `test_batch_ledger.py`）。
**结论**：**0 Critical / 4 Important / 6 Minor**。4I 全闭环（2 修根 + 2 账本收口，用户拍板 I-3/I-4 均按推荐执行）；**6M 用户拍板「都修掉」后全部闭环**（M-1~M-5 修复+防回归测试，M-6 提交时拆分）。终态 **730 passed + 16 subtests 绿、ruff 绿、run-archive verify 全部干净**。

---

## 一、评审方法（reviewer 独立执行）

- 语义基准逐点比对：`persist_market_data.py`（账本钩子）、`run_archive.py`（ORPHAN/verify/row_anchor_hash 实现）全文核对「同语义」声明，不信注释信实现。
- 独立重跑：全套测试（728 passed + 16 subtests，8.04s，与实现者声称一致）、ruff（**实红 1 error，与声称不符→I-2**）、真实账本 verify 只读巡检。
- /tmp 副本变异 4 发 + 端到端复现 1 个，全程零扰动工作树（收尾 `git status` 与 `run-log.jsonl` md5 前后一致）。

## 二、Strengths（核实为真的部分）

1. **rt_hk 布局反转锁是真防御**：`fetch_market_data.py:817-866` + `test_cn_free_sources.py:383-413`，夹具为真实探针 payload 逐字拷贝；变异 M1（互换 fields[2]/fields[3]）实测红。
2. **映射表白名单闸门**：`TENCENT_HK_INDEX_SYMBOLS`/`SINA_HK_INDEX_SYMBOLS` 显式 allowlist，`test_unmapped_bare_ticker_stays_gated_off` 用 NQ00Y 反例断言 `assert_not_called()`。
3. **降级链序正确**：HSTECH = 东财 124 → 腾讯 hkHSTECH → 新浪 rt_hkHSTECH，与文档一致（`fetch_market_data.py:1238/1266/1267`）。
4. **batch_ledger 与 persist 钩子「同语义」逐点成立**：sentinel 纪律（双层 try）、`_repo_rel` 逐字同构、jsonl 行锚定、open 失败 close 静默跳过。
5. **孤儿判定声明属实**：`run_archive.py:87` `ACTIVITY_TYPES` 含 data-close，两行制与 verify 兼容；roundtrip 测试用真 `verify_ledger` 断言双空。
6. **sink 锚定口径自洽**：`upsert_series_rows`/`append_record` 写后按日期排序，「尾行日期」≥任何被改行，评审担心的「upsert 改中段漏报」不成立。
7. **文档同步真齐**：AGENTS/CLAUDE/templates×2 字节同源（契约测试过）；新 token 落在既有契约锁覆盖内，无需扩锁。
8. **测试纪律**：新 main 型测试全部同时 patch requests + `resolve_data_root`（patch 源模块正确姿势）。

## 三、Issues 与处置

### I-1 社融月度锚 `YYYY-MM` 炸 fromisoformat（已修根，先红后绿）

- **链路**：`update_cn_liquidity.py` 社融 `item["date"]="2026-04"` → sink → `batch_ledger` 拼 `path#2026-04` → `run_archive.py:374` `date.fromisoformat` 抛 ValueError → **data-close 整批失败、当天 Shibor 申报一并丢失、open 成孤儿、sentinel**。MOFCOM 月度出新行即触发（定时炸弹）；现有测试全 mock 掉 `update_social_financing` 故未暴露。
- **核实**：/tmp 端到端复现实锤；修复后新测试在未修状态跑红（sentinel 捕获 `Invalid isoformat string: '2026-04'`）=天然变异验证。
- **修法**（评审方案①）：`_append_many` 锚归一——`len==7` 补 `-01`。社融行内 date 不可解析被 `row_anchor_hash` 保守计入 = 截至本次写入的整文件哈希语义，**账本保护不缩水**（方案②剔除锚会让社融永远裸奔，故不取）。
- **新增**：`test_social_monthly_anchor_gets_day_suffix`（main 级集成，断言锚 `2026-04-01` + verify 双空）。

### I-2 ruff E741 实红（已修）

- `tests/test_cn_liquidity.py:119` `json.loads(l)` → `l` 改 `line`。实现者声称「ruff 绿」不实——收尾验证跑的不是最终状态。

### I-3 真实账本 4 行幻影 run（已收口，用户拍板：abort 留痕 + 勘误）

- `data/.state/run-log.jsonl:61-64`：`RUN-20261109-1929-batch-liquidity`（/-r2）两轮，missing 理由与测试夹具逐字相同 = dev 期测试裸跑写入（update_* 被 patch 但 **main 本体经 batch_ledger 写账本**这条新路径漏算，「数据零污染」收口声明不完整）。verify 不报（两行制完整）= 静默审计污染。
- **处置**：append-only 不删行，两条各补 `abort --reason「幻影 run：测试误写，该批量从未发生」`；friction-log 勘误条目已记（含教训：账本接入新写路径后，测试裸跑爆炸半径从 data/ 扩到 .state/）。

### I-4 三份 E-20261109 证据正文改未 amend = verify 3 红（已收口 + 流程修根，用户拍板）

- 时间线：18:17 close 登记 4 证据 → 19:30-31 三漂移 amend 收口（verify 干净）→ **19:33:44 Q-20261109-12 收账编辑三份正文（补巡检注记）未走 amend** → 评审时 verify 3 红。
- **病灶**：I4 豁免（frontmatter 状态字段迁移不误报）被误读为「收账动证据不用 amend」——巡检注记是正文改动。E-20261105 同款为第 1 次，本次第 2 次，按 friction-log 硬规则修根。
- **处置**：①三条补 amend intent+done（挂 RUN-20261109-1807-watch），verify 回绿实测 ✓；②`daily-watch.md` 修订纪律段点名「review-queue 收账/复盘补巡检注记也是正文改动」+ 两案留痕。

### Minor

- **M-1（已修）**：`run_archive.py` 三处「六值」旧文案（模块 docstring 只列六值/append_open docstring/CLI help）→ 十值补全 batch-* 四值及两行制语义。
- **M-2（已修）**：market_series 锚口径统一为 **upsert 后文件尾行日期**（与 cross_asset 同口径，`_upsert_bars` 回读 `rows_now[-1]`）；新增 `test_sink_anchor_is_file_tail_not_fetch_max`（钩子先写当日行+服务器滞后场景），/tmp 变异（改回 fetch 最大日期）实测红。
- **M-3（已修）**：四脚本 data-close 填 `sources_used`——market_series 按 scope 成功记（mootdx/mootdx-index，闸门跳过不虚报）、**cross_asset 在写入点收行内 source 指纹**（nasdaq 降级东财时记实际写入源而非分发意图）、finance 记 `mootdx-gpcw`（gpcw 行无 source 字段）、liquidity 按系列成功记（eastmoney-datacenter/mofcom）；cross_asset/liquidity 两处 main 级测试补断言锁。
- **M-4（已修）**：`batch_ledger` 模块 docstring 明示**无 RUN_LOG_DISABLE 逃生门**的已知偏差及理由（批量无报告产物、sentinel 已兜底，确需跳过须调用方自行短路）。
- **M-5（已修）**：volume 口径**对拍定案**——东财主源 ~2e9 级、腾讯 ~4e6、新浪 ~4e7，两备份源数字逐位同只差小数点（同一底层数不同缩放，恒差 10×）；`SOURCE_CALIBER_NOTES["HSTECH"]` 记注「volume/amount 不得跨源比较，价格/涨跌幅三源逐位一致」，腾讯/新浪双夹具注释同步补对拍事实。
- **M-6（提交时处理）**：`workspace/research-profile.md` 中国巨石观察条目与本两批无关，建议提交时拆开或说明。

## 四、验证实录

| 项目 | 结果 |
|---|---|
| 全套测试（reviewer 独立 / I 批修复 / M 批修复终验） | 728 → 729 → **730 passed + 16 subtests** |
| ruff（reviewer 独立 / 终验） | 1 error（I-2）→ **All checks passed** |
| 变异 M-2 锚改回 fetch 最大日期（实施者 /tmp 副本） | 红（新锚口径测试有区分度） |
| 变异 M1 反转 rt_hk 字段序 | 红（反转锁有效） |
| 变异 M2 删 close_batch 缺锚剔除 | 红 |
| 变异 M3 同 path 去重保留首锚 | 红 |
| 变异 M4 删 resolve_data_root mock | 红（且复现账本杂散行=I-3 成因实证） |
| 社融锚端到端复现（修复前） | ValueError 实锤 |
| I-1 新测试先红后绿 | 红（sentinel 捕获 isoformat 报错）→ 绿 |
| run-archive verify（I-3/I-4 收口后） | **全部干净** |
| 契约测试（数据源三层锁/模板同源） | PASS（新 token 在既有锁覆盖内） |

## 五、遗留与观察哨

1. **明晚 16:30 cron 首跑四条版**：按当前代码可跑；跑完 `verify` 应见 4 条 batch-* 两行制。社融出新月份行前 I-1 已落，届时不再炸。
2. **HSTECH push2his 未结算观察哨**（与本评审无关仍挂着）：明日核对 11-09 行仍 4,040.73，被覆盖回 4,103.22 = 第 2 次触发修根。
3. M-2~M-5 已全部修复（2026-11-09 用户拍板「都修掉」），细节见 Minor 段；无遗留。

## 六、Assessment

**Ready to commit?** Yes（4I 全闭环后）

**Reasoning**：两批修根核心机制（HSTECH 双备份、batch_ledger 两行制与 persist 钩子同语义、四脚本 sink、文档同步）经逐点核对与 4 发变异全部成立；评审抓出的 ruff 实红与社融月度锚定时炸弹均已修根并先红后绿验证，账本两处污染已按 append-only 语义收口，verify 全部干净。
