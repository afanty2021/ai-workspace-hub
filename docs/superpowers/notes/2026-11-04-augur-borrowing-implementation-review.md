# 实施评审报告：feat/augur-borrowing（c6cbac1..ea2ae2f）

> 日期：2026-11-04 · 规格：max（4 并行评审位：vendored 对拍 / 账本与接线 / masters 适配 / 计划对齐与实测；协调者逐条复核关键发现）
> 对象：21 commits，+9,870/−75（vendored 约 5,900 行）
> **总裁决：With fixes——1 Critical 合并前必修，5 Important 建议同批；骨架质量高。**

## 实测结果（Quant-3.11 可复跑）

| 命令 | 结果 |
|---|---|
| `pytest tests/ -q` | **402 passed + 16 subtests，2.33s**，阶段数字 294→315→381→402 单调无回退 ✅ |
| `ruff check .` | 全过 ✅ |
| `python system/scripts/evidence_lint.py` | 6 份真实 evidence 全绿 exit 0；M1 时区修正落地（sox observed=11-02、available=`2026-11-03T05:00:00+08:00` EST 换算正确；KOSPI 15:30+09:00 正确）✅ |
| `python system/scripts/run_archive.py verify` | **exit 1**：未申报修订 1 条——masters 冒烟 close 行 report 指向已不存在的 `/private/tmp/masters-smoke/2026-11/300476.SZ-2026-11-04.md`（见 Important #2）⚠️ |
| `run_archive.py ledger --from 2026-11-01 --to 2026-11-04` | 三段输出正常 ✅ |
| `run_masters.py --help` | CLI 存在，参数全文档化 ✅ |

## Critical（1 条，协调者亲核坐实）

### C1 · 锚点收缩：受保护行被篡改后 verify 仍 clean
- verify 顺扫对同 path 的 series 权威**取最后一条 data-close 覆盖**（run_archive.py:512-520 `series_auth[path] = {...}` 无条件赋值）；persist 钩子锚取**本轮写入行的最大日期**（persist_market_data.py:260 `max(targets.get(path, row_date), row_date)`）。
- 场景：某轮只补写迟到旧行（回填 11-01，快照写者不限制行日期早于已有行）→ 新锚 11-01 < 历史锚 11-03 → 权威三元组整体回退，原锚与新锚之间的行脱离哈希保护。评审员实证复现：run2 补 11-01 → 篡改 11-03 行 → verify clean。
- 修法：data-close 锚取 `max(历史权威锚, 本轮最大日期)`；或 verify 合并同 path 多锚区间而非覆盖。

## Important（5 条，均协调者亲核）

1. **宏观 fetch 前移回归**：generate_daily_report.py:998-1008 调用序 fetch_market → fetch_macro → persist hook，macro 无 try 包裹；fetch_macro_data ImportError 时 sys.exit(1) → **macro 崩则市场数据整个不落盘**（旧序只丢报告不丢数据）。19 个新测试未覆盖"macro 失败 hook 仍执行"。修法：macro 包 try 或 hook 先行+macro_meta 事后补记账。
2. **真实账本被冒烟跑污染且无收口机制**：run-log.jsonl 现存 2 行（RUN-20261104-1903-masters，git_head 0c3c542），close report 指向 /private/tmp（--out 指向 tmp 而 --data-root 默认真实仓库，无联动防护）→ verify 永久 exit 1。append-only 模型下 amend-done 对缺失文件抛 FileNotFoundError、abort 不清权威表——需裁定收口机制（如 amend-done `--missing` 记"产物已消亡"摘除权威）+ 清理该记录 + run_masters 冒烟默认隔离 data-root。
3. **【上轮 I8 同型洞】eps=0/None → shares=0 → market_cap=0 被当极小市值加分**（adapter.py:283-294）：market_cap/debt_ratio 无条件进 replay_fields；cathie_wood market_cap<10 +1、thiel <5 +2、duan durability（debt_ratio 缺=0）同型。亏损股恰是面板最常被问的标的，且 market_cap 不在任何 persona deps 表无降权补救。修法：推导字段输入缺失时标 missing 并入 deps。
4. **并发追加无互斥**：run_archive._append 读全文→算 prev→写，无 flock/O_APPEND 保护；日报 persist 与 run_masters 双写者并发则链必断（verify 能检测不能阻止）。至少加 flock 或 object-model 声明单写者假设。
5. **masters 缺 RUN_LOG_DISABLE 逃生门 + AGENTS.md/CLAUDE.md/workspace-config.md 三处无 masters 路由**（"六大能力"表未加行；AGENTS/CLAUDE 同源两边都没改）。

## 各层详评摘要

### vendored 引擎（With fixes）
- 逐字节对拍：18 persona（头注 3 行+import 1 行）+ lynch（另删 8 行 agent_hyperparams 块）+ base（删 _merge_saved_thresholds 干净无残留）+ industry_matrix（仅头注）——**零未声明差异**。engine.py 摘取版数学主干与上游逐段等价（信号计数/sector 增益/coverage 归一/多数表决/calibrate/half-Kelly 三分支/低参与度/分歧度），剥离彻底（import 网仅 stdlib+augur_core）。
- **I-A（Important）**：对拍测试读上游**工作树**而非 0c721ac（tests/test_masters_engine.py:20-21）——当前恰好相等，上游一 pull 锁即失效。修法：fixture rev-parse 断言或 git show 0c721ac: 导出 tmp。
- Minor：上游 compute 的 timing_ms/calibration_status/industry_label/regime 四个 metadata 项静默丢弃未列剥离清单；权重表内 0 值→均分与上游语义不同（当前不可触发）；industry_matrix:127 残留 augur.data 懒 import（头注已披露、适配层不走）；空结果 agent_name "Multi-Agent Consensus" vs 上游 "Consensus"。

### 运行账本与接线（With fixes）
- 扎实项：两步 amend（verify 只认 done、series done 自动继承锚）；I4 归一化哈希（frontmatter 闭合块正则锚定、三路径端到端测试）；尾链断链报行号；降级链表驱动与旧链 13 环逐条等价（唯一偏差链级 try/except 属实且是改善）；三时点 writer EST/EDT/回退注记全覆盖；persist 失败分层正确（落盘失败不吞、账本失败写 sentinel）；fetch 失败不会留孤儿 open。
- Minor（评审 B #5-12）：I4 正则不认 `review_status :` 变体；mootdx 环崩溃 reason 误标 returned no data；verdict 解析不强制八槽字段序与补数槽；快照 json 无哈希覆盖（设计留白应记录）；watch 有 data-close 无 close 永不进任何清单；verify 对非 UTF-8 evidence 抛异常违反自述；run_masters 自带复制版 _ledger_failed 与 ea2ae2f 单一事实源方向不一致；账本文件带 BOM 会 append 全崩（fail-loud 可接受）。

### masters 适配层（基本就绪）
- 扎实项：TTM 合成（FY 直取/三期公式/backfill=5 实测依据/缺期 raise 不编造/--no-fetch 离线开关）；测试 81 个全绿 0.3s 零联网（autouse fixture 把补拉打成 AssertionError）；行业直填绕开 detect_industry 有键合法性测试；边界纪律机检通过（无写 evidence/hypothesis 路径，Kelly 只在报告）；批量 17+4/失败不中断/error 行有测试。
- Important：**605016 百龙创园行业映射错**（industry_map.json:20 写 食品饮料/consumer，申万一级实为基础化工/materials——影响行业权重与报告标签）；RUN_LOG_DISABLE 不适用 masters（见 #5）。
- Minor：munger deps 漏 fcf（munger.py:147 用 context.fcf 打分但 deps 表无 fcf——纯可见性）；汇总表月份提示按 trade_date 而实际目录按 series 末日月份（11 月初跑行情截至 10 月末会指错）；"逐字 spec §5.5"实为 4 条拆 5 条（近似非逐字）；_quarter_of 非标期末 KeyError 报错不友好；USD 注释口径与实现不完全一致（ebitda/cash/debt 声称换算实未填）；ETF 行弃权数 18 vs 个股行 2 语义不一致。

### 计划对齐（Yes with fixes）
- **6 Critical 处置 6/6 兑现、11 Important 11/11 兑现**（C1-C6 逐条核对全过——注意本报告的 C1 是实施代码新引入的洞，非上轮设计 C1 未修）；SDD T1-T7 达成，**T8 部分达成**（mock 全过、真实 --watchlist 从未跑，active-context 已如实声明顺延）。
- 文档缺口：masters 路由三处缺失（#5）；design §4.2 与 plan GC8 的 verdict 文法仍七槽未回写 6348005 的八槽裁定；其余交叉引用自洽（三时点字段表/八槽/close 命令示例/I4 豁免三处一致）；上轮 Minor 事实修正全部进文档（359bbc9/4,144 行/字段表/sma20-50-200/303 行+shim）。
- 仓库卫生：21 commit 按关注点如实拆分（抽查 4 个信息与 diff 相符）；75 行删除全在申报的重构文件内；工作树干净，实例数据 gitignore 隔离正确。

## 处置建议（合并闸门）

**必修**：C1（锚收缩）+ #1（宏观回归）+ #2（账本清污+收口机制）。
**同批顺手**：#3（I8 洞）、#5（路由两行+逃生门一行）、605016 一词、对拍锁断言、七/八槽 spec 回写、munger fcf。
**可延后**：#4 并发（先声明单写者假设）、快照哈希覆盖、其余 Minor。
**合并后收口**：首次真实 `--watchlist` 跑作 T8 验收 + verify 回到干净基线。

---
*协调者亲核项：C1（verify 覆盖式赋值+persist max 锚）、#1（调用序代码）、#2（run-log.jsonl 实文件）、#3（adapter replay_fields）、#5（grep 路由）、对拍工作树路径、605016 映射行。评审全程只读（测试/lint/只读脚本除外），未改工作树。*
