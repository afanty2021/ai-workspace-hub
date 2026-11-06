---
type: sector-rotation-universe
status: confirmed
# 2026-11-06 美股域重开（R20261106-02，用户指令+论文 §1.1 原始清单）：11 成员
# 退化情形 index_code==ETF 符号；limit_pct=1.0 禁用涨停闸门；无簇表（cluster_for→None）；
# 单候选集由 build_weekly_frame(pick_bypass_single=True) 旁路 pick（§7 第 5 行）。
---

## 成员（指数 → ETF 候选集，point-in-time 引擎每周择一）

| index_code | index_name | etf_candidates | limit_pct |
|---|---|---|---|
| XLK | Technology Select Sector SPDR | XLK | 1.0 |
| XLV | Health Care Select Sector SPDR | XLV | 1.0 |
| XLY | Consumer Discretionary Select Sector SPDR | XLY | 1.0 |
| VOX | Communication Services Select Sector SPDR | VOX | 1.0 |
| XLF | Financial Select Sector SPDR | XLF | 1.0 |
| XLI | Industrial Select Sector SPDR | XLI | 1.0 |
| XLP | Consumer Staples Select Sector SPDR | XLP | 1.0 |
| XLU | Utilities Select Sector SPDR | XLU | 1.0 |
| XLB | Materials Select Sector SPDR | XLB | 1.0 |
| IYR | iShares U.S. Real Estate ETF | IYR | 1.0 |
| XLE | Energy Select Sector SPDR | XLE | 1.0 |

## 簇代（滞后滚动窗：代 g 用 [g, g+1] 年收益聚类，g+2 年起可用）

| generation | index_code | cluster |
|---|---|---|
