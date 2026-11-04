# Masters（大师面板）

> 18 位投资大师公开投资理念的规则化模拟（vendored `tools/masters/augur_core/`），对 A 股个股产出共识信号 + half-Kelly 建议仓位。**输出是推测层**，边界纪律见下。

## 触发词

"大师面板" / "跑一下大师" / "masters" / "这票大师们怎么看" / "watchlist 批量跑大师"

## 场景路由

| 场景 | 命令 | 输出 |
|---|---|---|
| 单票 | `python3 tools/masters/run_masters.py 300476.SZ` | `output/masters/YYYY-MM/<code>-<date>.md` |
| watchlist 批量 | `python3 tools/masters/run_masters.py --watchlist` | 汇总表 `output/masters/YYYY-MM/watchlist-<date>.md` + 每只个股单票报告 |
| 何时用 | ① 个股深度研究后想要一个结构化的多视角对照；② 周期性扫一遍 watchlist 找分歧大的票；③ screen 结果想加一列大师共识作辅助 | — |

批量模式细节：

- 读 `config/daily-watchlist-watchlist.md`，只取 `Market=CN` 行：**17 只 A 股个股逐票跑 + 4 只 ETF 全员 abstain 记一行**；海外/指数/宏观段（NVDA、000660.KS、^SOX、商品等）属界外，不进批量（无 gpcw 财务面）。
- **单票失败不中断批量**：失败行在汇总表记 error 摘要，其余照常。
- 批量与单票各自写 run-log（kind=masters，open + close 指向报告路径）。
- 汇总表列：ticker / 名称 / score / signal / 参与大师数 / 弃权数 / half-Kelly / 关键分歧（一列内摘要）。

## 分歧 → 研究问题

汇总表尾部「分歧 → 研究问题（候选）」段：每个存在对向分歧的标的给一句可验证的研究问题候选措辞。这些是**候选**——agent 或用户确认后手动追加到 `workspace/review-queue.md`，**工具不自动写队列**。

## 边界纪律（spec §5.5，逐字）

1. **大师输出 = 规则化模拟观点 = 推测层**：不是 evidence，不进 `evidence/`，不写 hypothesis frontmatter。报告页眉固定声明：模拟观点基于公开投资理念的规则化实现，不代表本人立场，不构成投资建议。
2. **Kelly 是建议数字不是指令**：只出现在报告；`portfolio/` 写入照旧只走 review-queue。
3. **缺数据不编造 + 弃权是常态**：A 股个股 18 位中常态 **16 位参与**（ARPS/Serenity 常驻弃权，报告注明）；缺毛利率/FCF 的半盲大师降权并说明——宁可 16 位发言里再有几个半盲，不出全勤假象。
4. **ETF / 界外 abstain**：watchlist 21 只 = **17 只 A 股个股跑 + 4 只 ETF abstain（19%）**；NVDA / 000660.KS / ^SOX / 商品属界外（美股/韩股/指数无 gpcw 财务面），面板声明边界，留待数据源扩展。
5. **大师意见一致性可作辅助观察**：作为假设的辅助观察项，自身不构成任何触发。

## 输出目录约定

- 单票报告：`output/masters/YYYY-MM/<code>-<report_date>.md`（report_date = series 末日）。
- 批量汇总表：`output/masters/YYYY-MM/watchlist-<YYYY-MM-DD>.md`（日期 = 批量运行日）。
- run-log：`data/.state/run-log.jsonl`（open kind=masters + close 带报告相对路径；写失败落 `.state/run-log.error` sentinel，不中断报告）。

## 边界与已知口径

- **roe / 增长字段是 gpcw 累计期 YTD 未年化**（营收/净利/eps 已按 TTM 四期合成，roe 与 yoy 直值未年化）。
- **技术指标缺省降权（已知保守方向）**：RSI/MACD/ATR/波动率族等 series 技术面本轮未补算，dalio/soros/marks 等命中 persona_deps 的大师已 coverage 降权；批量汇总表与单票报告均注明。补算留待后续。
- **市值按固定汇率 USD/CNY=7.2 换算**成 USD 十亿参与 persona 规模档判定；报告侧换回人民币亿元展示。
- 数据缺期时 mootdx 自动补拉（`--no-fetch` 禁用，缺期直接报错不编造）。

## 相关

- 设计与裁决：`workspace/proposals/2026-11-04-augur-borrowing-design.md`
- screen 集成（可选辅助列）：`system/skills/screen.md`「大师共识作辅助列（可选）」
