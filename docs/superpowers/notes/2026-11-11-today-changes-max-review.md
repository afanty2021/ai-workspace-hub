# 2026-11-11 当日变更 max 评审报告

- **范围**：c5c83d4..7e22566（11 笔提交）+ 工作树（EXP-03 stat-dirty，内容与 HEAD 一致，无实际变更）。其中 4 笔已带闭环标记（9cc2005 / bdc30ea / ad56085 / 4087f97，frontmatter 家族五波修根+prune 粘连），只查交互不重审；本次焦点 = **baaae43**（美股指数通道修根，唯一代码提交）+ 6 笔 docs 提交（218c911 / fa41f45 / f4e8b39 / 2935b67 / 506c8a7 / 7e22566）
- **方式**：评审子代理深读（降级链逐环 / 测试 mock 纪律 / docs 数字自洽抽查 / _index 与生成器对拍）+ /tmp 变异重放 + 协调员逐条复核（复核中抓到评审漏网 1 条，见 I-2）
- **测试**：全套 `conda run -n Quant-3.11 python -m pytest tests/ -q` → **749 passed + 16 subtests 全绿**（基线 734+16；+1 = 本次补的 secid 分发测试，+14 = baaae43 契约测试）
- **结果**：**0C / 1I（评审）+ 1I（复核补充）+ 4M，判定 Yes**；当日全部修复闭环

## Strengths（择要）

- **baaae43 三项关键声称全部核实为真**：①降级链位——^GSPC/^DJI 依次被 nasdaq（US 闸门）/nasdaq-index（无映射）拒后命中东财主源，断连时腾讯备份可达，与已知美股指数源黑名单（FMP key 失效/Yahoo/stooq/新浪 int_ 冻结）完全一致（fetch_market_data.py:1247-1296）；②「布局同 us 股票零新解析器」属实——`TENCENT_US_INDEX_SYMBOLS`（:550-560）仅加前缀，解析与 us 股票共用分支；③fltt=2 原值不缩放（:1139-1179 直读 f43）。
- push2his 节流未破坏：`--throttle` 默认 3.0s + `fetch_kline_rows` 5s 重试原样保留，+10 行只动 docstring 与 SECIDS。
- 端到端实证：`data/market/series/^GSPC.jsonl`/`^DJI.jsonl` 各 550 行全窗，11-10 收盘与 AP/CNBC 逐位一致；usIXIC 25065.87 与 100.NDX 本地 series 逐位一致。
- 五处 docs 同步字节级一致，契约测试 token regex（`\d{3}\.[A-Z][A-Z0-9]*` 锁 secid、反引号锁 usINX 族）全命中。
- 6 笔 docs 提交：三张新卡 _index 手写行与 `rebuild-index` 生成器**逐字节一致**（干跑 changed:false）——同时证明 4087f97 抽出的 frontmatter_parse 公共模块与同日 docs 提交交互干净；review-queue 确认流程合规（Q-02/05/08/12/18 全 done）；卡内数字自洽抽查 6 组全过；EXP-03 一手/二手逐条标注纪律是全 repo 范例。
- 7e22566 模板硬规则与两案事实一致，且 `research-report.md` 无生成脚本消费（仅 first-research skill 引用），不破坏既有报告生成。

## Issues 与修复闭环

### Important

**I-1（评审）历史侧 secid 无测试锁** — `update_cross_asset_history.py:56-57` 新增 `^GSPC→100.SPX`/`^DJI→100.DJIA` 此前只有实时侧断言（test_cn_free_sources），历史侧 dict 分发零覆盖；评审变异重放（100.DJIA→100.DJI）21 项全绿坐实盲区。**已修**：补 `test_main_dispatch_routes_gspc_dji_to_eastmoney_secids`（`--tickers ^GSPC,^DJI --throttle 0`，断言两次请求 `params["secid"]` 序列）；变异复放（DJI→100.DJI + GSPC→100.SP500）新测试**红**、其余 21 绿——区分度验证通过。同族前科（secid 家族漏锁契约测试 I-1 注释在案）第 4 案，本轮补锁。

**I-2（复核补充，评审漏网）research-profile 源杰条目勘误前旧数字残留** — `workspace/research-profile.md` 第 18 次应用条目（7e22566 提交）仍写「扣非环比 **-20.4%** 的裂口……费用/减值/税率归因 [待验证]」，而同日 friction-log 与报告勘误锚明确：真实值 **+21.7%**（-20.4% 系单季÷累计混用），归母 -2.5% 系 Q2 投资收益基数光学、归因已验证非待验证。勘误改了报告和模板，漏了同日写入的 profile 条目。**已修**：该分句改为「环比动能从爆发级降档到平台级（营收/扣非环比 +20.0%/+21.7% 同速健康、归母 -2.5% 系基数光学——首版误写勘误锚见 friction-log）」。教训：勘误的同步范围清单应包含 research-profile（同日多 artifact 写入时勘误易漏其一）。

### Minor（4 条全修）

- **M-2** EXP-20261111-03 frontmatter 缺 `related`/`entity_salience`/`tagging` 三字段（20 keys vs 同日两卡 23 keys）→ 已补：related 两条（`[[EXP-20261111-01]]`/`[[EXP-20261110-03]]`，正文实际引用）、`entity_salience: {}`（无 ticker，内联空 dict 兼容 frontmatter_parse）、tagging 三行（对齐 EXP-02 形态）；`rebuild-index` 干跑 changed:false（0 处）验证解析容忍。
- **M-3** research-profile 四模块序号 16→18 跳号（第 17 次=旭创 R20261111-08 缺行）→ 已补第 17 次条目一行：四问检验首个个股实证（四问→估值裁决接法：PE 低位读作利润峰值定价非错杀）+ PB 分位口径断裂科技股首实证（BPS 35.74→80.11，A+H 融资票纵向 PB 分位募资前后不可比），内容全部来自 EXP-03:138 复审记录与报告 :84 落盘原文，无新造事实。
- **M-4** 模板硬规则未覆盖金辰案根因（gpcw 两位小数精度不足，脚本化也救不了）→ 已在 `research-report.md:31` 同条 blockquote 追加小基数例外：「单季利润千万级的票……±0.005 亿舍入即可翻转同比方向（金辰案推算 -5.7% vs 公告原文 +1.21%），必须回源公告原文精确值或第三方精确单季接口」（措辞取自 friction-log :322 原文）。
- **M-5** AGENTS.md 系四处「^GSPC/^DJI/^IXIC 备份……对拍**东财主源**」对 ^IXIC 不精确（其实时主源是 Nasdaq COMP，NASDAQ_INDEX_SYMBOLS:945 在东财之前）→ 已改四处（AGENTS.md/CLAUDE.md/templates×2，DATA-SOURCES.md 该行无此尾缀不涉及）：「^GSPC/^DJI 对拍东财主源、^IXIC 对拍 Nasdaq 主源（COMP），收盘逐位一致」；改后四文件行 md5 逐字节一致，契约测试绿。

### 评审简报勘误（非 repo 缺陷）

- 简报（协调员提供）称 218c911 含「EXP-20261111-03 早期版本」，实为 EXP-20261111-**02**；repo 内编号自洽。
- 简报要求「[[链接]] 必须落盘」，但 repo 既有约定是 Obsidian 短名/短 ID；今日提交沿用约定，非缺陷。

## Recommendations

- ~~机制层：`CROSS_ASSET_HISTORY_SECIDS` 与 `EASTMONEY_GLOBAL_SYMBOLS` 对「实时/回补同 secid」的票做派生一致性断言~~ **已当日落地（用户点名）**：`tests/test_repository_contract.py` 新增 `EastmoneySecidContractTests` 两项——①交集票（当前 8 票）secid 严格相等、无白名单豁免；②单侧独有票登记集（`LIVE_ONLY={000660.KS}`、`HISTORY_ONLY={DX-Y.NYB}`），未登记的单侧新票即红。**落地时勘误本报告原文**：「DX-Y.NYB 分叉需白名单」系评审时误记——核实后 DX 的分叉是跨源不对称（实时主源新浪 DINIW 不走东财、历史才走东财 100.UDI），不在东财实时表内，不构成 secid 冲突，故落登记集而非交集豁免。变异重放三发全红（①交集一侧改 100.DJI→红；②删 DX-Y.NYB→登记集红；③实时表加未登记 NQ1=F→登记集红；首发③ replace 未落上出假绿，验证落点后重放真红——变异必须验证落点的教训再+1）。全套 751+16 绿、ruff 净。

## 附：早轮 baaae43 单独评审（0C/0I/3M）留档项本轮处置

早轮 3 条 Minor 当日留档未修，本轮顺手闭口 2 条、实质覆盖 1 条：

1. README:239 全球指数枚举缺标普500/道指 → 已补齐（对齐 AGENTS.md 数据源行全枚举：纳指、标普500、道指、费半、美十债、小型纳指连续、美元指数、伦敦金、伦铜、恒生科技、海力士）。
2. 腾讯/东财指数 volume 口径差 ~1.7% 无注释 → 已在 `fetch_market_data.py` TENCENT_US_INDEX_SYMBOLS 注释块补两行（价格字段逐位对拍成立、volume 不得跨源锚）。
3. 无效 secid 负向探针无测试固化 → 本轮 I-1 分发测试以变异锁形式实质覆盖（改成 100.DJI/100.SP500 即红）。

## Assessment

**Ready? Yes**（修复已全部落工作树，749+16 全绿）
**Reasoning:** baaae43 核心声称经代码逐环+本地数据逐位对拍全部属实，docs 提交数字自洽、_index 零漂移；两条 Important（secid 测试盲区、勘误残留）均当日修复并变异/回归验证，无遗留 Critical。
