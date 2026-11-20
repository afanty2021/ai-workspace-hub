# 2026-11-20 max 评审·复查评审修复 r3（ee73c9f..dbcbc04 三笔 + gitignored 本地 Q-20261119-03 落盘）

- **触发**：用户指令 `[$requesting-code-review] max 复查评审修复`。
- **范围**：ee73c9f（上轮 r2 复查报告）→ dbcbc04 三笔修复——a069b69（friction-log 节「修根覆盖面硬规则」四文件）/ f8bb11a（tagger LLM deadline 修根：llm_client.chat + wiki_tagger.request_tags + tests/test_llm_deadline.py）/ dbcbc04（模板补同步+profile:150）；外加 Q-20261119-03 按推荐先行执行的 gitignored 本地落盘（板块报告勘误/单票报告尾注/entity 688012 挂起段/queue 行/friction-log/active-context）。
- **评审员**：general-purpose max 级，47 次工具调用；/tmp worktree 三节点全量复跑（a069b69=847+1、f8bb11a=852+1、dbcbc04=853 全绿）+ 双变异独立复验均红 + blob hash 四文件对拍 + 第四查全形态 grep。
- **结论**：0 Critical / 2 Important / 4 Minor，主会话逐条核实全属实，当日全处置。

## 逐条核实与处置

| # | 级别 | finding（评审员） | 核实 | 处置 |
|---|---|---|---|---|
| I-1 | Important | 板块报告 :161 勘误植入 -48.2% 是 11-18 锚读数，与表 11-16 收盘口径时点错位（按本表 233.20/2,234 亿复算应 -50.5%，差 2.3pp）；:167 注段同样无时点标注 | 属实。数学复算：2234/4517−1=−50.54%、233.20/471.59−1=−50.55%；-48.2% 来自 2338.76 亿（11-18 锚，单票报告 :124 自标「11-18 锚」） | :161 改 `-50.5% \| 2026-07-09`；:167 注段写明两时点读数（表口径 -50.5% vs 单票 11-18 锚 -48.2% 勿跨行混用）+标注「复查 r3 勘正口径时点」；单票 :127 尾注同步；profile:150 尾句+queue 状态列同步（M-5 一并） |
| I-2 | Important | f8bb11a「无关键词（慢响应/trickle）同由 deadline 封顶」overclaim——deadline 只在 attempt 边界检查，单次 session.post 内字节间隔 <read timeout 的滴流响应可无限存活；docstring 已知限制未覆盖该形态；违反新立的修根覆盖面规则（「堵不住的形态要写明限制」——既没堵住也没写明） | 属实。:217-223（attempt 边界）+ :234 `min(timeout, remaining)`（收窄的是字节间隔上限非单请求总时长）——trickle 确实不被封顶；docstring 第一段自己写明 read timeout 语义 | **实现侧第二刀修根**：chat() 改 `stream=True`+新增 `_drain()` 读循环逐字节边界检查 deadline（trickle 封顶至 deadline+至多一次 read timeout）；docstring 已知限制如实改写（字节边界执行、在途 chunk 至多再等一次 read timeout）；修法选择依据=新规则「堵得住就堵」，改动面一个函数+15 行 |
| M-3 | Minor | wiki_tagger.py `except LLMError: raise` 连带收紧 extract_json 形状校验（合法 JSON 非对象 → _ensure_json_object 抛 LLMError 原走外层重试、现直接终止），与「JSON 解析/校验失败保留外层重试原语义」声明偏差 | 属实。llm_client.py:261 形状校验与网络层同抛 LLMError，合并 try 无法区分 | 拆双 try：网络层（chat_func）LLMError 上抛、校验层（extract_json+validate_payload）`except (json.JSONDecodeError, LLMError, TaggingError)` 保留外层重试 |
| M-4 | Minor | f8bb11a message「全量 853 绿」在该 commit 节点不成立（评审员 worktree 复跑 852+1 契约红；853 是 11 秒后 dbcbc04 终态），按 M-R4 判例记录勘误 | 属实（时间线：a069b69 提交→全量 852+1 契约红→模板修复→853 绿，拆两笔提交时 f8bb11a 的测试数声明用了工作树终态口径） | 记录勘误不改史（非交互环境 reword 中间 commit 成本>收益；与 11-18 M-5 同判例处置）。本笔修根（r3）测试数声明按 commit 终态节点口径：855 绿 |
| M-5 | Minor | profile:150 行尾「勘误候选挂 Q-20261119-03 a」未随同行前半句更新（同一行内自相矛盾） | 属实 | 尾句改完成时+口径说明（与 I-1 同步修） |
| M-6 | Minor | entity 688012.md updated_at: 2026-11-19 未随 11-20 新增「方法论挂起候选」段刷新（1bc395c M-1 判例） | 属实 | updated_at → 2026-11-20 |

## 修根与验证

- **I-2 第二刀**：`system/lib/llm_client.py` chat() stream 化+`_drain()`；**M-3**：`system/scripts/wiki_tagger.py` 拆双 try。
- **测试**：tests/test_llm_deadline.py 5→7 例（+`test_trickle_body_aborted_by_deadline` 滴流例：iter_content 字节间隔 0.4s<timeout=10，断言 deadline 0.3s 封顶+elapsed<2.0；+`test_shape_error_still_retried_outer` 形状校验重试例："[1, 2]" 合法 JSON 非对象断言 call_count=2）；tests/test_wiki_tagger.py FakeResponse 适配 stream 协议（`__enter__`/`__exit__`/`iter_content`，503 时 yield b"temporary 503"）；MagicMock `_ok_response` 补 `__enter__.return_value = response`。
- **全量 855 passed**（853 基线+2 新例）。
- **变异验证四发**：①删 attempt 边界 deadline 检查→挂死拦截例红（f8bb11a 已验，拆 try 后复验仍绿）；②删 `_drain` 读循环 deadline 检查→**滴流例红（新）**；③恢复外层「LLMError 吞掉重试」→收紧例红（f8bb11a 已验）；④恢复合并 try（形状校验归网络层上抛）→**形状校验例红（新，仅目标例失败）**。
- **复验四件套**：tagger scan 0 问题；序号账本 OK（28/71）；触发器对账 OK（72/59/0）；第四查全形态 grep 剩余 3 处命中逐条判定=真挂起合规表述（「挂起」为已决定态用词；queue 行内「待拍板」已随 a 项执行改「勘误已执行·待追认」）。另 -48.2% 全库检索（含 gitignored）：单票 :113/:124 上下文自带 11-18 锚标注合规保留，其余命中均为无关数字。

## 教训

1. **修根覆盖面自查必须逐形态落到「哪一行代码挡住」**：f8bb11a 的三形态自查用「慢响应」一词把「停滞（无字节→read timeout 杀，已修）」与「滴流（字节间隔<read timeout→单请求无限存活，未修）」两形态混为一谈——落笔前对每个形态问「具体由哪一行代码挡住」，答不出=没堵住。这是修根覆盖面硬规则（a069b69 当日刚立）的第一次自我应用即被抓获，规则有效性得证。
2. **勘误引入数字须对目标表格口径复算，不能直接搬源报告读数**（I-1）：单票报告的 -48.2% 在其自身 11-18 锚语境正确，搬进 11-16 收盘口径的板块表即成时点错位——与 11-17 r2「数字真、归属/锚点错」同族。跨文件勘误=跨口径搬运，先问目标表自己的口径是什么。
3. commit message 测试数声明按 commit 节点口径（M-4 判例重申）：工作树终态≠commit 节点态，连续拆笔时尤其注意。

## 终态

- 代码：llm_client.py（stream+_drain+docstring）+ wiki_tagger.py（拆双 try）+ 测试 7 例，855 绿+四变异。
- 文案：板块报告 :161/:167、单票报告 :127、profile:150、entity 688012 updated_at、queue Q-20261119-03 行三处（gitignored 本地）。
- friction-log 11-20 条目补 r3 后记；本报告入库。
- Q-20261119-03 保持 pending 待追认（a 项勘误数字随 r3 勘正，追认时按 -50.5% 版本追认）。
