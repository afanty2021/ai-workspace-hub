# sector-rotation：A 股周频行业轮动研究工具（P1 结案状态）

> 状态：**P1 闸门未过，研究已按预注册协议结案**（2026-11-05）。L1/L2 模型（models.py）与周信号（signal.py）未实施。结案报告：`workspace/proposals/2026-11-05-sector-rotation-p1-closure.md`；设计 spec：`workspace/proposals/2026-11-05-sector-rotation-design.md`（v1.2.2）；实施计划：`docs/superpowers/plans/2026-11-05-sector-rotation-p0-p2.md`。本目录全部代码与数据管线可复用于后续研究。

## 数据流

```
backfill.py        mootdx 深回补：881 指数 + ETF 候选池（start 分页 ≤800/页，series_lock 写回）
    ↓ data/market/series/*.jsonl
build_universe.py  候选池过滤 + 行业→ETF 候选集 + point-in-time 逐年宇宙曲线 + 滞后滚动簇
    ↓ config/sector-rotation-universe.md（confirmed，416 成员/5 簇代）
sector_rotation/universe.py    Member/UniverseSpec/cluster_for(t)（簇代 g+2 ≤ 当年）
sector_rotation/data.py        build_weekly_frame：周决策帧（C7 决策期 dvalid vs 执行期 valid 双口径）
                               + 拆分防护（>30% 单日跳空 member-week valid=False，周一生效豁免）
sector_rotation/weekly.py      窗口块 + 训练窗内标准化（L1/L2 用，未消费）
sector_rotation/cost.py        CostModel 两档（base/stress）
sector_rotation/baselines.py   point-in-time 等权（年再平衡）/动量/反转/随机（callable 协议）
sector_rotation/portfolio.py   执行闸门（涨停弃买/低流动/缺数）+ 六风控 RiskState + 净换手计费
sector_rotation/metrics.py     指标集 + 同簇触发频率
sector_rotation/walkforward.py 引擎（起点=可用行业 ≥50 首周，S5）+ t_rows 对齐账本
sector_rotation/permtest.py    置换检验（n=1000 下限）+ 配对 block bootstrap（H0 重定心）
backtest.py         CLI：检验矩阵回测，两段式预注册（--pre-oos 选择窗 → 预注册 → 确认性检验）
```

## CLI 速查

```bash
export CONDA_EXE=/opt/homebrew/Caskroom/miniconda/base/bin/conda
# 数据深回补与完整性核查
conda run -n Quant-3.11 python tools/sector-rotation/backfill.py indices|etfs|verify ...
# 宇宙构建（改动候选映射后必须重跑 Step 5 再确认）
conda run -n Quant-3.11 python tools/sector-rotation/build_universe.py
# 检验矩阵回测（两档成本 × 检验矩阵；探索性变体只报告不判定）
conda run -n Quant-3.11 python tools/sector-rotation/backtest.py --level L0 \
  --k 3 --direction momentum --lookback 1 --tier both [--pre-oos] [--exploratory] [--slice FROM:TO]
```

报告落 `output/sector-rotation/YYYY-MM/`（gitignore 运行时产物）。测试 `tests/test_sr_*.py`；ruff 规则集 E4/E7/E9/F。

## 两档成本（spec §3.7）

| 档位 | 佣金 | 单边点差 | 单边合计 | roundtrip |
|---|---|---|---|---|
| base | 1bp | 10bp | **11bp** | 22bp |
| stress | 1bp | 20bp | **21bp** | 42bp |

计费按净换手（逐资产 |Δw| × 单边，上周权重漂移调整后）；α 永远只报成本后；所有出口闸门两档都必须过。

## P1 闸门结果（真实运行，output/sector-rotation/2026-11/）

预注册配置 k=3/momentum/lb1，OOS 2020-07-10 起 324 周：**6 格全未过**——vs 随机 0.626/0.271、vs 等权 0.490/0.508、vs 沪深300 0.559/0.571（base/stress）；主策略成本后 CAGR -1.90%/-1.76%。反事实（停用全停 overlay）：裸选择显著为负。详见结案报告。

## 已知限制清单（原计划 T15 收口，由本 README 承载）

**执行与计费简化**
- 跌停顺延简化：周五清仓一律按 close 计损益，顺延只影响成本时点（周频口径影响 ≤1bp，I13 敏感性已量化）。
- blocked 已持有资产按全额卖出计净换手、当周损益不记账——偏保守多计成本（引擎续持的正确做法是不放入 weights_new）。
- pause 周提前 return 跳过 banned.clear()：连停多周后旧禁令残留（保守方向无害）；cooldown 观察期为每周重设而非按周递减。
- limit_pct 为 Member 单值近似（M12）：同行业不同 ETF 的实际涨跌停档未区分。

**数据现实**
- 退市 ETF 不可得：通达信不留退市数据（16 个公告核实代码全空返回）——宇宙含幸存者近似，point-in-time 规则部分缓解。
- 除息未复权：除息日价格自然回落计入收益，方向为轻微低估（I9；量级见 backfill.py ex_dividend_scan）。
- coverage 曲线末年为部分年（M3）；无年份覆盖率达 80%（峰值 65%，S5 起点规则改绝对数 ≥50 的原因）。
- 通达信 880/881 为自编口径指数，历史回测存在口径漂移近似（官方指数副口径对照未执行——原 T14 停止）。

**引擎语义**
- `window_blocks` 要求窗口内全列齐——单一新行业缺史会丢整帧（M10，weekly.py，L1/L2 消费端）。
- 全周停牌 fallback 取 wk+14 收盘，执行周错位未记（M11）。
- 周一生效的拆分（≤30% 幅度）当周涨跌停判定基准失真：拆分防护只拦 >30% 跳空 member-week，小幅度周一生效拆分不拦（已知未处理）。
- 周频重训 vs 论文增量更新、金融损失/trailing ROC 阈值为实现方口径（论文未给公式）——L1/L2 未实施，该两条仅记录设计期口径。

**报告口径**
- 2026-11-05 生成的 12 份探索性（-preoos）报告中「OOS 起点/样本外 N 周」标签实为**选择窗**起点与周数（已修正代码，旧报告未重生成）。
- 毛收益 ≤0 时成本拖累记 nan（M7 设计）；`--tier stress` 单跑时指标表行名/拖累列为回退显示（cosmetic）。
