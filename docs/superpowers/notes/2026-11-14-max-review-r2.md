# 2026-11-14 max 评审（r2）：尾批两提交

- **范围**：`6c0ec6a..8aa63bc`（16 文件 +662/−28）——689e2d0 知识沉淀组批量入库 + 8aa63bc us_backfill 静默改史根修两案。两笔均在上一次 max 评审闭环（6c0ec6a，见 [2026-11-14-max-review.md](2026-11-14-max-review.md)）之后。
- **评审员**：general-purpose subagent（max 级，read-only，66 次工具调用）。结论 **0C / 3I / 4M**。
- **协调者逐条核实**：7 条 findings 全部独立复核属实（M-2 定性略修正：源报告 `R20261109-04-jinniu-backtest.md:20` 原文即「3-10 日 +4.4~7.4bp、t=2.4~6.2」，卡内系区间标签笔误，数字本身无错）。

## 逐条核实与处置

### I-1 update_market_series `--force` 未映射 repair（属实 → 已修）

- **核实**：`update_market_series.py:125` `_upsert_bars` 调 `upsert_series_rows(path, rows, writer="batch")` 无 repair；`:308-311` `--force` 帮助文本仍承诺「历史回补/盘中数据修正用」+「收盘后须再跑同命令 --force 修正」；对照 `update_cross_asset_history.py:292-293` 已映射 `repair=force`。全仓 grep 实证仅两个 `--force` 载体、A 股域这个未接。后果：盘中脏数据拖过 30 交易日再 `--force`，拉得到数据但 upsert 拒写，修复不可达；`--backfill 800` 遇源端历史重述同样锁死。
- **修复**：`_upsert_bars` 加 `repair` 形参，stocks（`:160`）与清单制 scope（`:250`）两调用点均传 `repair=force`；帮助文本补映射说明。新增 `ForceRepairMappingTests` 2 行为用例（force 解锁改写窗外历史行 / 无 force 反事实腿拒绝并保留原值+新日期照常追加）。
- **变异**：`repair=repair`→`repair=False` 一发，force 腿红、反事实腿绿 ✓。

### I-2 「批量脚本族同款语义审视」对 backfill.py 覆盖不全（属实 → 注记不改语义）

- **核实**：`backfill.py:60` 写 `source="mootdx-backfill"`，`:81` skip 门槛 `rows >= total`；cron 先建仓的新候选 ETF（31..total-1 行）重拉全史时，既存行 `source`（mootdx/mootdx-index）与 incoming 必然不同 → 非尾部全拒+每票一条告警。数据无损（正是防改写），但 commit message「backfill.py 断点续传 skip+新日期追加不受影响不改」未审视此场景。
- **处置**：不改防护语义——`source` 参与防护有专门测试（`test_source_field_also_guarded`）且行为方向正确（保留原 provenance、OHLCV 真差异被拒更是本意）。落两处注记：backfill.py 调用点就地注释（告警属预期非回归）+ queue Q-20261110-08 done 行补记。

### I-3 data_snapshot 对不存在路径静默产出 0 文件清单（属实 → 已修）

- **核实**：`data_snapshot.py` `_iter_files` 对不存在目录 `rglob` 返回空 → `files=0` manifest 正常落盘零告警。`sha256("")` 是合法指纹——等于给报告绑上「空数据态」的假信心；TRACKER_LOG 改名/移档场景下 B 案状态载体门出现盲区（hold_crash_check 自身因 `:112` 先 open 会炸，但模块层防线缺失）。
- **修复**：base 路径不存在 → `FileNotFoundError`（预注册依赖漂出指纹链必须炸）；存在但空目录 → stderr 告警。新增 2 用例。
- **变异**：`if not base.exists():`→`if False:` 一发，missing 用例红、empty 用例绿 ✓。

### M-1 告警区间依赖 incoming 顺序（属实 → 已修）

`market_data_io.py:229` `rejected[0]}..{rejected[-1]}` 按迭代序取首末——当前调用方均日期升序无害，改 `min(rejected)}..{max(rejected)` 一行事。无测试断言该文案，零回归。

### M-2 EXP-20261109-05 summary 区间标签松（属实，定性修正 → 已修）

源 `:20` 原文「3-10 日 +4.4~7.4bp、t=2.4~6.2」（+4.4bp/t=2.4 是 h=3 端点）；卡 summary 误写「5-10 日」。卡 `:92`「5-10 日 t（5-6）」与源 `:72` 逐字一致不动。修复=summary 改「3-10 日」；`_index.md:29` 逐字引用该 summary，走 `rebuild-index --apply` 同步（二跑 diff 幂等确认，`_index` 净变更恰 1 行）。

### M-3 EXP-20261107-05 注记时序过时（属实 → 已修）

复审行尾「数据层根修挂 Q-20261110-08 待拍板」——两笔提交相差 10 秒同批落地，卡落地时已修完。改为「已落地（8aa63bc A/B 两案）」并注自新消费跑起指纹自动留存。

### M-4 新卡缺 schema 建议字段 date / entity_salience（部分属实 → 记录不改）

实测库内惯例：`date:` 全库 **0/35** 卡使用（加了反成孤例）；`entity_salience` 19/35 卡使用（16 卡同缺，属批量卫生项非本批缺陷）。必填五项+status 三张新卡齐全。结论：schema 建议字段与库内实际惯例分歧，留结构体检（structure-health）另议，不在本评审顺手改。

## 评审员实测记录（协调者抽核）

| # | 项目 | 声明 | 评审员实测 | 协调者抽核 |
|---|---|---|---|---|
| 1 | 全量 pytest（HEAD） | 819 绿 | 819 passed | 修复后 823 passed（+4 新用例）✓ |
| 2 | 全量 pytest（BASE） | 806 基线 | 806 passed（git archive 快照） | — |
| 3 | A/B 变异 | 4 红/3 红 | 逐一复现 | — |
| 4 | 金牛卡数字 vs R20261109-04 | -8.18pp 等 | 逐位一致（含勘误注记在卡+queue 原值） | summary 区间标签除外→M-2 ✓ |
| 5 | 聪明钱卡 vs R20261109-03 | 六条判断 | 全部数字逐位在源 | ✓ |
| 6 | 归属卡 vs 中免/龙佰源报告 | 双向数字 | 逐位一致 | ✓ |
| 7 | EXP-20261107-05 vs R20261110-05 | -7.32% 等 | 逐位一致 | ✓ |
| 8 | yaml 项数四卡 | 全独立 | 2/0/7/5/2、1/0/5/4/2、2/2/5/4/2 dup-free、ticker 带引号 | ✓（M-2 修复不动列表结构） |
| 9 | 881101.jsonl 双写者 | cron 零变化 | 3206 行=3171 backfill+35 index，cron 写入区在尾窗内 | ✓ |
| 10 | tagger scan | 0 问题 | 0 问题 | ✓ |
| 11 | rebuild-index | 二跑 no-op | changed=false | 修复后再次实测幂等 ✓ |

## 修复与验证（协调者）

- 全量 **823 passed**（819 基线+ForceRepairMappingTests 2+data_snapshot 2），run_archive/契约测试随全量通过。
- 两发变异（force 映射退化为 False / exists 检查退化 if False）各自红、反事实腿绿，文件已复原（diff 复原验证）。
- 提交拆分：fix(data)（I-1/I-3/M-1 代码+测试+backfill 注释）一笔；docs(wiki)（M-2 卡+_index 同步+M-3 卡+queue 注记+本报告）一笔。

## 遗留

- M-4：schema 建议字段 vs 库内惯例分歧 → structure-health 周检顺带议。
- 评审员 R-3（存量报告无 manifest、快照前向生效）已落 queue 注记；4 runner 下次真实运行起自动带快照行。
