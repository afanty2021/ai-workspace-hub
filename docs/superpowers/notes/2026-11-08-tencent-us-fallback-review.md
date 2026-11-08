# 腾讯美股 keyless 备份源接入 —— max 实施评审报告（2026-11-08）

> 评审对象：工作树未提交的腾讯美股批次（fetch_market_data.py + test_cn_free_sources.py + AGENTS/CLAUDE.md 行 109）。
> 范围口径：今日已推 origin 四笔（cc741d6 等）今晨已 max 评审闭环（Q-20261108-01），不重复；sector-rotation 工作树批次（11-07 遗留）与并行福耀研究批次不在范围。
> 模式：三趟独立评审员并行（生产代码 / 测试+变异区分度 / 文档契约+真实网络），修复波独立对靶复验。

## 结论速览

**0C / 3I / 9M → With fixes 已全闭环**（3I+8M 修复，1M 有据不修）。终态：全量 647 passed + 16 subtests、ruff 净、修复波三变异复验全红。

## 三趟评审结论

### 趟 1：生产代码（fetch_market_data.py）

**结论 0C/0I/2M，Ready: Yes。** 实现与设计六点全部吻合：gate 与 fetch_nasdaq_quote 逐字对齐、分支优先级 hk>us>cn 正确、三种时间戳格式（CN 紧凑/HK 斜杠/US 短横线）解析逐一验证、异常路径完备（gate 零开销/空响应/截断/非 200 全部安全 None）、volume 无新口径债（reviewer 核实下游仅透传持久化不参与计算）、文档同步合规。
- M-1 纯数字 symbol 放行（矛盾输入空跑，与 nasdaq gate 同构）→ **已修**：docstring 记录取舍 + 测试显式断言声明现状。
- M-2 docstring "nasdaq/yfinance serve those" 断言过强（yfinance 需 BRK-B 连字符转换而 to_yfinance_symbol 不做）→ **已修**：弱化为 "fall through to the rest of the chain"。

### 趟 2：测试 + 变异区分度（test_cn_free_sources.py）

**结论 0C/2I/5M，Ready: With fixes。** reviewer 在 /tmp 沙箱重放 8 个变异，实现方声明的三个变异（market gate/isalnum/ISO 日期）全部复现红，同时抓到两个真盲区：
- **I-1（变异 B 实证）**：`_route` 的 AssertionError 哨兵被生产 `except Exception` 静默吞掉——fred map-gate 失效变异下 US 链测试仍绿（纯 US 契约视角漏报）。→ **已修**：链测试尾部改白名单断言（api.nasdaq.com 或 gtimg.cn）+ `len(requested)==2` 锁顺序与完备性；复验 R1（fred gate 注入 FCX）红。
- **I-2（变异 H 实证）**：us 分支丢 `.upper()` 变异全绿——小写 ticker 端到端无锁定。→ **已修**：端到端用例输入改 `"fcx"`（断言仍 q=usFCX）；复验 R2 红。
- M-1 夹具注释称含 PE/市值/PB 实际止于 39 → **已修**：补齐到 52（真实探测值：44/45 市价、47 EPS、51 PB、52 股息率），注释与内容吻合。
- M-2 gate 测试注释描述回归路径有误（"fall through 到 _cn_quote_symbol"）→ **已修**：改为准确描述（无 gate 时 us 分支直接命中发请求）。
- M-3 `len<35` 阈值无锁定（变异 G 全绿；外部行为等价但"干净拒绝"退化为"异常拒绝"）→ **已修（升级）**：截断用例 + `_note_fetch_failure` 未调用作为精确区分器（两条路径外部同为 None，仅异常路径记录失败）。**修复波插曲**：初版用例用 assertIsNone 在变异下仍绿（IndexError 路径外部等价），实验定位后升级区分器；复验 R3（35→30）红。
- M-4 矛盾输入（600276+US）无声明 → **已修**：SymbolRuleTests 加显式断言 + 取舍注释。
- M-5 GBK mock 绕过真实解码路径（A/H 夹具同款历史局限）→ **不修**：US 路径不消费 fields[1] 中文名，实质风险低；改动涉及全部夹具体系，收益不抵风险。记录在案。

### 趟 3：文档契约 + 真实网络

**结论 0C/1I/2M，Ready: With fixes。** 网络验证全过：
- live NVDA（在池）186.64/+2.78%，价格自洽（p−pc=change 精确吻合、落 low~high 区间）；FCX 与 S&P Global 锚全中；
- 三市场混批 `q=usNVDA,hk03993,sh601899` 200 OK，三种时间戳布局并存与代码注释一一对应（**勘误：分隔符是逗号**，任务描述中的"+"是空格编码会返回 pv_none_match；生产代码单票请求不受影响）；
- 负路径 BRK.B/NVDA+CN 均 0 次网络请求返回 None；周日快照正确回落周五 2026-11-06；
- AGENTS↔CLAUDE 镜像逐字节一致（md5 同）；链注释↔链序↔文档表述三者互证（tencent 确为 nasdaq 后第一个能取美股数的 keyless 源：nasdaq-index/eastmoney-global/sina-global/fred 映射制无映射、mootdx 拒裸 ticker、eastmoney/sina 无 US 路径、tushare 仅 CN/HK 后缀）。
- **I-1**：`system/templates/{AGENTS,CLAUDE}.md` 行 109 未同步（install_workspace.py 的源模板——只改产物没改源，新工作区将拿到旧契约；今晨 47e0cef 同类坑重现）→ **已修**：两模板补同一行，镜像校验通过（除称谓外零 diff）。
- M-2 README 数据源表（东财/腾讯行缺港股+美股）与零 Key 段、DATA-SOURCES.md 能力列 → **已修**：三处补齐。
- M-3 system/skills/daily-watch.md "美股先尝试 Nasdaq" 表述 → **已修**：补"腾讯 us 前缀为其后的 keyless 备份"。

## 修复波验证记录

| 验证 | 结果 |
|---|---|
| 全量测试 | 647 passed + 16 subtests（+1 新截断用例） |
| ruff | 净 |
| 变异 R1：fred map-gate 注入 FCX（I-1 修复的靶） | 链测试红 ✓ |
| 变异 R2：us 分支丢 .upper()（I-2 修复的靶） | 端到端红 ✓ |
| 变异 R3：len gate 35→30（M-3 修复的靶） | 截断用例红 ✓（_note_fetch_failure 区分器） |
| 模板↔根镜像 | AGENTS/CLAUDE 除称谓外零 diff ✓ |
| live 端到端 | 评审趟 3 独立复测 NVDA/FCX 通过 |

## 遗留

- 东财美股 105/106 段待 push2 反爬恢复后实测，再决定是否接入（有意不接是纪律不是遗漏）。
- BRK.B 类含点美股入 watchlist 前，需实测 nasdaq API 带点行为 + to_yfinance_symbol 补点→连字符转换（趟 1 Recommendations）。
- GBK mock 解码语义差异（趟 2 M-5）随 A/H 夹具体系一并考虑。

<!-- 评审报告：2026-11-08 max 三趟 + 修复波全闭环，Q-20261108-05 收账。 -->
