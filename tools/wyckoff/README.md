# Wyckoff 示意图状态机（A 股移植验证）

LunqFX TradingView 脚本「Wyckoff Accumulation & Distribution, Spring, UTAD, SOS」
（https://www.tradingview.com/script/y9jjEUGv-.../）的本地 python 移植，
在自选股 + 核心指数上验证 track record 与条件概率。

**v2（2026-11-07）：Pine 源码全文对靶版。** 源码在 `reference/lunqfx-wyckoff.pine`
（用户手拷），参数全部取原脚本真实默认值，六处语义差异修正（见 machine.py
docstring）。v1 按页面文字描述+自定参数的版本已废弃（结果留档
output/wyckoff/full-validation.json 作对比）。

## 结构

```
reference/lunqfx-wyckoff.pine  原脚本源码（移植出处，逐行对靶基准）
wyckoff/params.py    参数默认值（= 原脚本 INPUTS 真实默认值）
wyckoff/machine.py   纯状态机：stage 0-5 与原脚本 1:1（派发=镜像），不重绘纪律
wyckoff/loader.py    universe（watchlist CN + 8 核心指数）+ 共享库读取 + mootdx 深历史
wyckoff/stats.py     track record（对齐脚本面板口径）+ 通用箱体突破基线（horizon=maxLeg）
fetch_history.py     深历史回拉 CLI → data/wyckoff/daily/（本工具私有缓存）
run_validation.py    验证 CLI → output/wyckoff/{tag}-validation.{json,md}
forward_returns.py   事件前瞻收益（SOS/SOW vs 基线，+10/+20/+60 根）
```

## 用法

```bash
# 深历史回拉（mootdx，服务器深度约到 2013-2015）
python tools/wyckoff/fetch_history.py

# 全量验证（40 symbol：32 自选 + 8 核心指数）
python tools/wyckoff/run_validation.py --tag full-v2

# 参数变体（覆盖任意 Params 字段）
python tools/wyckoff/run_validation.py --set min_range_len=30 --tag sens-mr30

# 事件后前瞻收益
python tools/wyckoff/forward_returns.py
```

环境：`conda run -n Quant-3.11 python ...`（本机 conda shell 函数有权限坑，
用全路径 `/opt/homebrew/caskroom/miniconda/base/bin/conda`，见 friction-log 2026-11-07）。

## 与原脚本的保真/近似

保真（源码逐行对靶）：五 stage 状态机与判定顺序、RMA(50) ATR、climax 三条件
（lookback 极值+1.2×ATR 宽幅+1.5×SMA20 含当前 bar 放量）、climax 无声延伸、
AR 确认 pivot（阈值用确认 bar ATR）/过高丢弃/trendLen 超时、ST 35% 区、
spring 无 ST 门控/收盘深度 0.30×区间高/pendN>3 失败/minRange 前丢弃、
单 spring 与极值失效位、SOS 优先于 spring、T1/T2=1×/2× 区间高、T2 优先于失效、
超时基点（SC/spring 极值/SOS）、同 bar 终态后再入、一次一个示意图、无 volume 降级。

移植近似（已知差异，低影响）：派发=镜像复用吸筹逻辑（原脚本 dir 乘子逐条对称）；
SC/BC 同 bar 蜡烛色裁决未移植（实际不可能同 bar 触发）；两类独立扫描+时间重叠
去重，近似原脚本单机时序。基线 horizon=300 对齐 maxLeg（v1 的 120 有窗口偏置）。

## 数据边界

- 个股/ETF：`data/market/series/`（只读）+ mootdx 深历史缓存（2013/2015→今）；
- 板块指数 `.TDX`：`data/sector/series/`（共享库已含 2013-09 起深历史）；
- 核心指数：`data/index/series/`（只读）+ 深历史缓存；
- 562800 稀有金属ETF 的 TDX ×10 价位异常对状态机无影响（全部阈值相对化）。

## 验证结论速览（v2，40 symbol × ~11 年）

结构识别可用（锚点：上证 BC 2024-09-26 等）；做多 SOS 对朴素箱体突破基线
**无优势**（P(T2) 41.3% vs 45.8%，前瞻中位为负）；派发 SOW 有早期下行动量
（前瞻 ≈2× 基线）但 62% 被反弹收复失效位。详见
output/wyckoff/2026-11-07-wyckoff-validation-report.md。

