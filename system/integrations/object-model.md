# 研究对象与状态契约

> Markdown 是用户界面，frontmatter 是机器可读的当前状态。正文保存分析和历史，不重复维护另一份“当前状态”。

## 稳定 ID

| 对象 | ID 示例 | 唯一真相 |
|---|---|---|
| 研究 | `R20260711-01` | `output/research/*.md` frontmatter |
| 假设 | `H1` | `hypothesis/H*.md` frontmatter |
| 证据 | `E-20260711-mover-ifx-de-H1` | `evidence/YYYY-MM/*.md` frontmatter |
| 待确认动作 | `Q-20260711-01` | `workspace/review-queue.md` 表格 |
| Exploration | `EXP-20260720-01` | `wiki/explorations/*.md` frontmatter |
| Pattern | `PAT-20260720-01` | `wiki/patterns/*.md` frontmatter |
| Rule | `RULE-20260720-01` | `wiki/rules/*.md` frontmatter |
| 公司 / 标的 | `IFX.DE` | 市场 ticker；无 ticker 时用稳定 entity slug |

ID 创建后不因标题、文件名或观点变化而改变。旧文件没有 `id` 时仍可读取，并在下次人工更新时补齐，不做批量重写。

## 状态唯一来源

- 假设的当前 `status`、`certainty`、`updated_at`、`last_reviewed_at` 只认 frontmatter。
- 研究的当前 `status` 只认 frontmatter；建议值为 `draft / active / closed / archived`。
- 研究开始前的本地扫描只认对应 `output/research/preflight/{R-ID}.md` 回执；研究 frontmatter 用 `preflight_id / knowledge_used / wiki_pages_loaded` 引用，不把“我记得查过”当记录。
- 证据的当前审核状态只认 `review_status`；建议值为 `pending / confirmed / rejected`。
- Exploration、Pattern、Rule 的当前 `status`、`review_due`、适用范围和失效信号只认各自知识卡 frontmatter；短索引是自动生成的路由，不是状态真相。
- 规则调用事实只追加到 `workspace/knowledge-usage.jsonl`，调用次数不能覆盖证据和生命周期状态。
- `config/daily-watchlist-watchlist.md` 是驱动日报的唯一股票池。`workspace/monitoring/` 只做用户看板和专题视图。
- 正文日志记录“曾经发生过什么”，不能反向覆盖 frontmatter 的当前状态。

## 证据最小字段

```yaml
---
id: E-20260711-mover-ifx-de-H1
type: evidence
observed_at: '2026-07-11'
available_at: '2026-07-11T17:30:00+02:00'
recorded_at: '2026-07-11T23:45:00+08:00'
source_type: daily-watch
source_path: output/daily-watch/2026-07/2026-07-11.md
source_url:
direction: pending
confidence: pending
review_status: pending
linked_hypotheses: [H1]
linked_entities: [IFX.DE]
metric: price_change
dedup_key: DW-2026-07-11-mover-ifx-de-H1
---
```

**三时点规范**（`available_at` 必填）：

| 字段 | 格式 | 语义 |
|---|---|---|
| `observed_at` | `YYYY-MM-DD`（裸日期） | **业务时点 = 事实发生地的当地日历日**。美股收盘按美东日历日，A 股按北京日历日；跨市场事件（如“SOX 破线传导 KOSPI”）主事实在哪发生就填哪 |
| `available_at` | **必填，ISO 8601 带时区时刻**（如 `2026-11-03T05:00:00+08:00`） | 该事实最早可被知晓的时刻。跨时区市场按“交易所当地收盘/公布时刻 + 当期实际时区偏移”换算填写 |
| `recorded_at` | 新文件用带时区时刻；旧文件裸日期按当日 00:00+08:00 归一 | 证据文件写入时刻 |

**单调性判定（lint 实现）**：不做 naive/aware 直接比较（会抛 TypeError），统一**按日粒度包含判定**——`date(observed_at) ≤ date(available_at 换算+08:00) ≤ date(recorded_at 换算+08:00)`，等号允许（同日可得同日记录合法）。YAML 双类型归一：裸 date 与引号字符串先统一解析为字符串再走规则。

**时区正确性是人工责任**：lint 不做时区数学（DST 换算无法从字段本身证明），填表按当期实际时区偏移。

**旧文件缺省口径**：缺 `available_at` 的旧文件视为 = `recorded_at`，语义是“无法证明更早可得”；lint 对缺省文件单独列「未核实」清单，不算通过也不算失败，禁止被当作“已核实”。与 augur 校验的知情分歧：augur 禁止 `available_at == retrieved_at`，AWH 的保守缺省是**有意放宽**。

证据正文写清“观察到什么”和“为什么可能相关”。`direction` 只有复盘后才改成 `strengthen / weaken / neutral`；行情涨跌本身默认保持 `pending`。

## 运行账本

`data/.state/run-log.jsonl`：追加式 JSONL，实例数据随 `.state/` gitignore。定位是**存在证明 + 修订痕迹**——不复制快照，对产物记哈希，改可以改但必须先记账。**不轮转不分区**（估算 <2MB/年）。写入分两级：数据侧 `open` / `data-close` 由持久化钩子自动写，报告侧 `close` / `amend` 走 `system/scripts/run_archive.py` 一步命令。

**单写者假设**：账本追加无互斥锁；当前调用面（日报 persist 钩子、masters CLI）串行使用，并发双写会断链并由 verify 检出。

| type | 写入者 | 语义 |
|---|---|---|
| `open` | persist 挂钩自动 | 运行开始；`run_id` 格式 `RUN-YYYYMMDD-HHMM-<kind>`，同分钟重试加序号 `-r2` |
| `data-close` | persist 挂钩自动 | 数据侧收口；series 目标用行锚定三元组，missing 来自 fetch meta 结构化降级清单 |
| `close` | 报告落盘后 skill 一步命令 | 记报告路径 + 整文件哈希 + `evidence_registered`（带哈希） |
| `amend` | 修订第一步 | intent 行，此刻 `post_sha256: null` |
| `amend-done` | 修订第二步 | 改完文件后补完成行；verify 只认 done |
| `abort` | 运行中止 | 显式记账中止原因 |

`kind` 六值：`watch / inspect / research / screen / masters / backfill`（backfill 无 close 语义，不参与 verify）。

**行锚定哈希**：series 是追加式 jsonl，整文件哈希次日必过期。data-close 的 series 目标记三元组 `{path, anchor_date, sha256}`，其中 sha256 = **对文件中 `date ≤ anchor_date` 的全部行（按文件序）拼接的哈希**。效果：追加新行（date > anchor）不触发 verify；改写旧行（date ≤ anchor 的行内容变化）才触发。报告类目标（md）用整文件哈希。amend 的 `--data-target path#date` 同口径。该模型同时兼容 `update_market_series.py`（writer=batch 权威覆盖，不走 persist）——它的合法覆盖更新若发生在 anchor 之后不影响验证，改 anchor 内旧行则须先 amend。

**两步 amend**：任何对已 close 运行产物的修改，先记 intent（`post_sha256: null`）→ 改文件 → `amend --done` 补哈希，两步都不可省；有 intent 无 done 列入“未完成修订”清单。evidence 状态字段（review_status/direction/confidence）的合法生命周期迁移不属修订，不触发 amend 义务；verify 对 evidence_registered 目标的哈希将这三个字段值归一化（视为待更新态）后计算。

**尾行哈希链**：每行带 `prev_sha256`（前一行整行哈希），verify 顺带校验链——整行删除或篡改会断链可见。

**生命周期**：孤儿 open（>24h 无后续）由 verify 列 stale 清单；同报告被多次 close 合法，verify 以**最后一条** close / amend-done 为准。

## 巡检判定词表

巡检与复盘对检查点的判定统一用四值词表：

| verdict | 含义 | 记账要求 |
|---|---|---|
| `normal` | 查了，未触发 | 记 as_of 与关键读数 |
| `warn` | 接近预警线 / 一级压力 | 同上 + 距离 |
| `trigger` | 触发（压力升级 / 证伪证据） | 同上 + 关联 evidence ID |
| `missing` | 该查没查成（源挂、停市、key 缺、口径断裂、**关键证据 pending review**） | 必须写 `reason` + **补数命令** |

复盘时关键证据 `review_status: pending` 的情形统一降级为 `missing`（reason: `关键证据 pending review [E-ID]`）——语义差异在 reason 表达，词表不膨胀到五值。

判定行文法（字段序固定）：

```
- YYYY-MM-DD | check: <检查项id> | verdict: <四值之一> | as_of: <读数时点> | reading: <值或—> | evidence: <E-ID或—> | 补数: <仅missing时必填，可执行命令> | reason: <仅 missing 必填，禁竖线>
```

空值统一 `—`；**值内禁竖线**（`|` 是分隔符）；补数命令为自由文本但同样禁 `|`。ledger 脚本按此文法解析，解析失败显式报错降级为“人工读取”，不静默跳过。

## 待确认队列

以下动作必须先进入 `workspace/review-queue.md`：

- 把研究结论沉淀进 wiki；
- 新建假设或改变假设确定性、状态；
- 把标的加入执行股票池；
- 把研究偏好观察固化成稳定偏好。

用户确认后先执行动作，再把队列状态改成 `done`；拒绝则改成 `rejected`，保留决策记录。
队列新增、去重和状态更新由 `system/scripts/review_queue.py` 执行。

知识卡的状态迁移、晋级门槛、索引重建和选择性加载由 `system/scripts/knowledge_lifecycle.py` 执行；迁移命令默认只预览，只有同时提供 `--apply --confirmed` 才会写入。

<!-- 文件说明：跨研究、假设、证据和待确认动作的统一对象协议。 -->
