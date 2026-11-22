# 2026-11-22 max 评审：近期变更（eded5cc 后两笔提交 + Fed 一手源三项接线工作树）

- **范围**：Part A = `eded5cc..ea7b970` 两笔未评审提交（4e9064c chat() thinking 参数第三刀、ea7b970 podcast batch_summarize 换位补堵）；Part B = 未提交工作树「Fed 一手源三项接线」（Q-20261122-01：ON RRP 序列+两房窗口标注+preflight Fed 源段，13 modified + 3 untracked）。
- **评审员**：general-purpose 子代理，93 次工具调用；工作树全量 872 绿复跑 + 双节点 worktree 复跑（4e9064c=858 / ea7b970=858，与 message 声明逐字一致，M-4 判例未复发）+ 数据独立回源（jsonl 342 行/峰 217.841/末 0.401/30 日均 0.5917 全属实）+ 只读 curl 双源对拍（NY Fed 401000000 ↔ FRED 0.401 逐位一致；紧凑日期格式实测 HTTP 400）+ `pdftotext` 验 memo p5 机制原文存在。
- **结论**：**0 Critical / 2 Important / 6 Minor，当日全处置**，处置后全量 873 绿（+1 新测试）+ M-2 变异验证（恢复旧形态→新测试红）。

## Findings 与处置

| # | 级别 | 内容 | 处置 |
|---|---|---|---|
| I-1 | Important | ea7b970「全部 chat() 调用方」覆盖面声明漏 `fetch_podcasts.py` 三处同族调用点（:909 单条全文摘要 json_mode 8000 tokens / :978 转写翻译块 / :1223 多日汇总 JSON）——大 prompt × glm 默认 thinking 同族两死法（推理超 timeout / 烧 max_tokens 截空 content），违反修根覆盖面硬规则换位形态 | 三处各补 `thinking=False`（:909 带完整注释，另两处一行指回）；py_compile 过；全库 chat() 调用点终验=4 处全已修。**随后续 commit 勘误 ea7b970 覆盖面声明，不 amend 已提交节点** |
| I-2 | Important | Part B 文档同步漏三处：a `system/integrations/object-model.md:84` 仍「kind 十值」（11-09 上次扩容时同步过，本次漏步有先例）；b `run_archive.py:345/:1041` 与同文件 :10「十一值」自相矛盾；c `tools/daily-watch/README.md` 缺 NY Fed 数据源行+CLI 示例未提 18:25 档（README 是 11-02 修根「文档同步四点 checklist」第 1 点） | a 改十一值+batch-us-liquidity+独立档口径；b 两处「十值」→「十一值」；c 补 NY Fed markets API 表行（含连字符 400 坑）+FRED 行扩 RRPONTSYD+CLI 示例补第五条 |
| M-1 | Minor | queue:309「新增 19」实为 14（872−858；逐文件 8+3+3=14），「872 绿」正确 | queue 行勘误 19→14 并注明评审出处 |
| M-2 | Minor | `update_us_liquidity.py:165` `used.add("nyfed-markets-api")` 两失真：FRED 降级成功仍记主源名；全 skip 幂等重跑也记源（账本 r2 行 sources_used 非空×data_targets 空实证），违反 sibling「实际写入才记源」口径（update_market_series 11-09 M-3 修根） | `update_rrp` 返回 stats 加 `source` 键，main 改 `imported>0` 才记；新测试 `test_main_records_source_only_on_write` 断言首跑记 fred-rrpontsyd/重跑 sources_used 空+data_targets 空（+auto_fallback 加 source 断言）；变异验证：恢复无条件旧形态→新测试红 |
| M-3 | Minor | CHANGELOG.md Unreleased 无本批条目（11-16 M-3 判例后系统性滞后第 2+ 次） | 补一条完整条目（三项+评审补漏）；系统性修根挂 Q-20261122-02①待拍板 + friction-log 已记 why |
| M-4 | Minor | 两房窗口：memo p5 只证 P&I 周期机制、未给 15-25 数字，现表述诚实但代码未注明日历界为近似；测试 25 日只断 truthy 未断「剩 0 天」文案 | 代码注释补「日历界为运维化近似」；测试改 assertIn("剩 0 天") |
| M-5 | Minor | `fed_source_hint` "fed" 子串假阳性（FedEx/feed 实测命中） | 评估后维持现状并写明取舍：advisory-only（只多渲染一段链接）、误命中代价≈0，docstring 注明已知接受 |
| M-6 | Minor | inbox PDF（1.1MB）未被 .gitignore 覆盖，git add -A 会进公开历史 | **已追认（2026-11-22 用户「PDF 入库」）：入库 tracked**——仓库已有 2 个 tracked PDF 先例（examples/inbox sample）、公开政府文件、preflight/dashboard 两处引用其存在；随 Part B 提交笔入库 |

## 主会话核验（评审员结论抽查）

- 三处 fetch_podcasts 调用点、object-model:84、run_archive:345/:1041、README 两处、queue 19、used.add 无条件——逐处读源码核实属实后落修。
- host 侧（评审员不可见）自查：CronList 确认 automation-2b56f6a0（18:25 档）存在 enabled；8:00 盘前自检 prompt 已含五组 open（batch-us-liquidity）——「四组扩五组」声明属实。
- 变异纪律：M-2 行为修复按旧形态变异→新测试红→恢复→873 绿。

## 遗留（非本批引入）

- 账本 7 条存量 undeclared（11-12~11-16：报告哈希/000300.jsonl 缺失/证据哈希）→ Q-20261122-02②。
- CHANGELOG 系统性滞后修根（checklist 扩第五点 vs 契约测试轻量检查）→ Q-20261122-02① + friction-log 2026-11-22 第二条。

## 终态

- 全量 873 绿（872+1）；工作树 18 modified + 3 untracked 待用户点名提交（建议拆两笔：Part B 含全部评审修复一笔、fetch_podcasts I-1 勘误一笔，均不 push）。
- queue Q-20261122-01 done（含评审处置收账表述）；Q-20261122-02 pending（两项系统级观察待拍板）。
