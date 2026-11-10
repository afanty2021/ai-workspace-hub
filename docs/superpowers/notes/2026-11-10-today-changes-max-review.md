# 2026-11-10 当日变更 max 评审报告

- **范围**：62309fa（docs-only）+ 工作树全部未提交（B 弱票反转日报接线 / C stage-bottom 全链 / D rps / E hold_crash_check / F EXP 沉淀 / G jinniu 昨夜尾巴）
- **方式**：协调员前置验证（全量测试、占位符契约、weak_scan 全读、产物在位）+ 评审子代理深读（stage-bottom/rps/hold_crash_check/EXP 卡/jinniu）+ /tmp 变异重放
- **测试**：`conda run -n Quant-3.11 python -m pytest tests/ -q` → **734 passed + 16 subtests，全绿**（基线 730+16，+4 = test_weak_reversal.py）
- **结果**：**0C / 5I / 8M，判定 With fixes**（核心链路质量高，Important 均为低成本修复）

## Strengths（择要）

- stage_bottom.py 翻译核：`_ewm` 种子+NaN 透传、`roll_sum` 整窗无效、`safe_div` 除零、`cross_up` NaN→False 全部对靶通达信"无效不触发"语义；`_selftest`（:210-265）含随机游走因果断言，实跑绿；无前视。
- sleeve.py：`_civil_days` Hinnant 历法修"YYYYMMDD 差不是天数"坑（:219-239）、预注册/post-hoc 分层标注、EW-universe 锚声明。
- weak_scan.py：append-only+尾部 7 日刷新窗+原子写、U4 日历差、台账幂等、非交易日探测票静默退出（静默改史教训当日落地）。
- rps/validity.py：前视修复后内置 2024-09 手工对靶断言（<1e-9）；**B 臂前视偏差确认已修**（月末信号配次月收益、fwd=shift(-h) 方向正确）。
- hold_crash_check.py：单次消费防覆盖、W45 缺行 fail-loud、冻结配置断言；与 proposal §5/§8 逐条一致。
- 今日产物链闭环：模板占位符 ↔ context 15/15 对上（SafeFormatDict 缺 key 留原样不炸）→ 2026-11-10.md 3 只 gate70 → 台账 3 行逐位一致。
- EXP-01/02 卡 frontmatter/列结构/互链与 knowledge_lifecycle 生成器逐列吻合。

## Issues

### Important（5 条，协调员已逐条复核原始证据属实）

1. **`/10000` 年限近似三处遗留**（oos_check.py:139 / followup.py:137 / run_backtest.py:240）——sleeve.py:239 已用 `_civil_days/365.25` 修根，同目录三脚本未跟进（friction-log"第 2 次禁止再打补丁"场景）。14 年窗 yrs 偏低 ~5%→年化差读数系统性放大（+4.24pp/-3.36pp/+7.72pp/+5.92pp 等全部受影响；符号与显著性不翻转）。
2. **orthogonality.py:52 前瞻口径与注释/文档不符**——`o[idx+21]/o[idx+6]` 实为第 6 日开盘进持有 15 根，注释与文档引用（"低桶 +1.51%"）按 20 日口径叙述；应改 `o[idx+21]/o[idx+1]` 并重跑更新读数。
3. **R20261110-01 文档内部矛盾并已传播 wiki 层**——结论 5 与 EXP-20261110-01 卡（summary/正文/两问）引用"用户池 **-7.36pp**/yr（t=-3.0）"，但同文档表格"用户池全部 36 票"仅 **-5.50pp**（t=-3.0/33%/43% 与该行完全同——疑另一轮口径数字）。EXP 卡与 _index 行已收账，需澄清出处→更正卡+_index。
4. **rps_bundle.pkl 实为 977MB（任务书误载 2.2MB）、未被 ignore、位于待提交目录**——`git add tools/rps/` 一次即 977MB 入库。建议移位 `data/research/R20261110-04/`（data/ 已 ignore）+ 脚本默认路径跟进；可选：bundle 去 close_adj/转 float32 再生。
5. **生产 cron 依赖未提交文件**——automation-b15d4a34（16:10）执行的 weak_scan.py 及依赖链全部未跟踪，工作树清理/换机后静默失败。上线日至少提交 weak_scan.py+stage_bottom.py+测试。

### Minor（8 条）

1. weak_scan `--no-update`+陈旧缓存 → 把"数据缺失"伪装成"今日无信号"写入 {today}.md（cron 正常路径有探测票闸门，仅手动组合可触发）；建议 --no-update 模式加只读探测检查。
2. weak_scan.py:79 `float(r["amount"]) if r.get("amount")==r.get("amount")`——amount=None → `float(None)` TypeError（现仅因 mootdx 恒返回 float 列未炸；对齐 :78 volume 行写法即可）。
3. test_weak_reversal.py:53 `kind in ("gate70","deep10")` 对 gate70 专属性无区分度（变异 D：ADX 比较反转仍绿——gate70 静默退化 deep10 不被发现）；深 V 夹具加 `kind=="gate70"` 断言。
4. proposal §8 状态载体门子句"roc.last_t 与 11-06 决策索引吻合"未在 hold_crash_check.py 实现（主对照在）。
5. oos_check.py:33-36 `arm_events` 死代码。
6. weak_eval.py:113 非重叠=同月去重近似，与预注册"前信号 20 日窗未了结跳过"有跨月重叠偏差（判定窗 2027-02 启动，现在改零成本）。
7. user_pool.py RAW 残留 002910（注释称已剔场外基金；缓存无此票自然 NaN，无实害）。
8. 两套 ETF_RE 并存（run_backtest vs rps_core 对 56 段口径不同）+ 北交所票两边不剔——宇宙边界未在 docstring 声明。

## 变异重放（/tmp 副本，4 处）

| 变异点 | 预期 | 实际 |
|---|---|---|
| A：降级 return → 空串 | 红 | 红（双断言红）|
| B：artifact.exists() 分支失效 | 红 | 红 |
| C：gate70 分支 return None | 红 | 红 |
| D：ADX_CUT 比较反转（灵敏度探测）| — | 绿 → 证实 Minor#3 区分度缺口 |

基线复绿 4/4；/tmp/review-p1 已清理。

## 评审员实跑命令

- pytest tests/test_weak_reversal.py（/tmp 副本 5 轮：基线+4 变异）
- stage_bottom.py selftest（绿）、weak_scan.py --help、rps_core import+单票 fixture 验证
- git log/status/show、check-ignore、crontab -l、产物/台账/模板/build_report 抽查
- 未重跑：全量 pytest（协调员已验证）、回测主链（静态对靶为主）

## 处置建议（待用户拍板）

- **修 I-1/I-2 + 重跑受影响读数**：三处换 `_civil_days`、orthogonality 口径修正，重跑 run_backtest/oos_check/followup 受影响臂，R20261110-01 文档补勘误行。
- **I-3 澄清**：重跑用户池臂拿可复现数字 → 更正 R20261110-01 结论 5 + EXP-20261110-01 卡（2 处 -7.36）+ _index 行（-7.4pp）。
- **I-4 pkl 移位** data/research/R20261110-04/ + 脚本路径跟进（低风险直接做）。
- **I-5 提交授权**：weak_scan.py+stage_bottom.py+test_weak_reversal.py 按用户点名惯例待批。
- Minor 1-8 可同波修复（M-6 判定窗前零成本改）。

---

## 修复波收口（2026-11-10 当日，用户拍板「全修+重跑勘误」「提交三件套+报告」）

### 处置明细

| 项 | 处置 | 验证 |
|---|---|---|
| I-1 | `civil_days` 上移 stage_bottom.py 公共核（sleeve 改导入防循环），oos_check/followup/run_backtest 三处修根 | py_compile 绿；ETF 臂 -3.36→-3.18pp 恰为理论修正幅度 ×0.95 |
| I-2 | orthogonality `o[idx+6]`→`o[idx+1]` | 重跑：F3 低/中/高桶 +1.51/+0.84/-0.26 → **+1.93/+0.91/-0.31**（n=1530 不变） |
| I-3 | -7.36 全臂重算不可复现，定性早稿残留；正确读数 **-5.22pp（t=-3.0）**；R20261110-01 就地修正+文末勘误节；EXP-01/02 卡+_index 两行+R20261110-02 引用同步 | 陈旧数字 grep 清零（勘误节 old→new 除外） |
| I-4 | rps_bundle.pkl 977MB → `data/research/R20261110-04/`（gitignore 生效），四脚本默认路径跟进 | reproduce_hs300 新路径冒烟 5/5 命中 |
| I-5 | 三件套提交（本笔 + 后续两笔）；friction-log 立门禁「生产 cron 脚本当日入库」 | 见下方提交 |
| M-1 | weak_scan `--no-update` 陈旧缓存拒扫守卫 | /tmp 离线验证：陈旧缓存→skip 提示+exit 0+不写产物 |
| M-2 | amount None/NaN/0 与 volume 行同语义 | py_compile+代码审 |
| M-3 | 测试断言锁 `kind=="gate70"` | 实跑 4 passed；变异 D（ADX 比较反转）复放**红**——区分度缺口闭环 |
| M-4 | hold_crash_check 补 §8 last_t 子句（state.json per_n.roc.last_t == t1106，三格实测 931 一致） | 静态+state.json 离线核（重放级验证留待下次实跑） |
| M-5 | oos_check arm_events 死代码删除 | py_compile 绿 |
| M-6 | weak_eval 非重叠去重改 28 日历日窗（原同月近似跨月偏差） | py_compile 绿；判定窗 2027-02 前零成本修正 |
| M-7 | user_pool 剔 002910 残留（RAW+NAMES） | grep 清零 |
| M-8 | **升级修根**：五处裸 glob → `UNIVERSE_RE` 白名单（run_backtest 定义，by_year/optimize/followup/oos_check/sleeve 共享）——归因剔除 367 非标的文件（16 段 LOF×344+52 段基金×4+跨资产序列×10+881.TDX×2，原全部落入「个股」臂） | UNIVERSE_RE 行为对靶断言过；用户池 36 票指纹（26+10/t=-3.0/33%/43%）与原表逐位复现 |

### 重算结果（六臂：run_backtest×2 / followup×2 / oos_check / orthogonality）

数据窗 2026-11-10（含 11-09/10 两日增量）。**全部符号/显著性/定性结论不变**；关键 old→new：个股 +4.24→+4.37pp、ETF -3.36→-3.18、用户池 -5.50（误引 -7.36）→**-5.22**、rsi_up20 费后 +7.72→+7.77、OOS 费后 +5.92→+5.98、adx67 OOS +2.47→+2.59（lift ×2.1→×2.0）、护栏 -0.43→-0.44、深桶 +3.36→+3.42。全表见 R20261110-01 文末勘误节。

### 回归验证

- 全量 pytest：**734 passed + 16 subtests**（修复前后各跑一轮，全绿）
- stage_bottom selftest 绿（chuji=168）、reproduce_hs300 5/5、变异 A-D 复放（A/B/C 红、D 修复后红）
- friction-log 立案两条：/10000 家族修根教训（同族脚本口径 bug 必须覆盖整个家族）+ cron 入库门禁

### 提交（用户 2026-11-10 点名）

1. cron 生产链三件套：tools/stage-bottom/{stage_bottom.py, weak_scan.py} + tests/test_weak_reversal.py
2. 日报接线：generate_daily_report.py + daily-watchlist-report-template.md
3. 本评审报告

其余（stage-bottom 其余脚本、rps/、jinniu/、hold_crash_check.py、EXP 卡/_index/研究文档勘误）留工作树待点名。

---

## 修复波复查（2026-11-10 晚，第二轮 max 评审）

独立复查评审员对 62309fa..23dc6ac 八笔+工作树+/tmp 六组重跑日志逐条对靶：**13 条原 findings 全部确认修对**（含变异 D 红、hs300 5/5、civil_days 历法逐位、勘误表六组对六个日志逐位）。**新发现 0C/3I/3M**：

1. **weak_eval.py 宇宙过滤 `p.name` 坑第二次**（p.stem 首犯在案）→ 评估器静默空转，2027 判定窗前必修
2. **jinniu 家族漏网**：/10000 年化两处+裸 glob——违反当日「同族覆盖」门禁
3. **R20261110-01 正文多张表新旧数字并存自相矛盾**（事件表/除权/A1·A2/C 段/结论 3·4 未同步重算值）
4. Minor×3：生产脚本 docstring 引旧读数 / EXP-01 卡 +7.72 无标注 / EXP-02 卡缺 sleeve 口径注

### 二波修复（当日闭环）

- I-A：`weak_scan.stock_files()` 单一事实源（p.stem）+ 回归测试 `test_stock_files_stem_filter` + weak_eval 空文件 loud abort；实跑验证评估器复活（台账 3 事件正常评估）
- I-B：jinniu `_ymd_days`+`UNIVERSE_RE` 修根+全市场/池臂重跑——**周线 +0.35pp（t=2.9）显著性消失（t=0.4）**，用户池 -8.13→-8.18pp（t=-5.2 不变），R20261109-04 勘误节落盘，「无效」判定更干净
- I-C：R20261110-01 事件表/除权对照/A1·A2/C 段月度/结论 3·4 全量同步重算值（A2 WR10 内部负信息弱化已如实改写）
- Minor×3 全修；friction-log 补两条（p.name 用法须共享+空输入响亮失败 / 修根家族按共享缓存+代码形态划定并全仓 grep）
- 验证：**735 passed + 16 subtests**（+1 回归锁）；_index 重建（金牛 -8.2/EXP-02 口径注带出）
