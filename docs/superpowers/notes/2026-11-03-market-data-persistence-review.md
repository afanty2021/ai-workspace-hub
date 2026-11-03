# 市场数据持久化层评审记录（max 评审 + 修复波复查）

- 评审日：2026-11-03（两轮同日）
- 分支：`feat/market-data-persistence`，未 push 未合并
- 第一轮 max 评审范围：`7e97b7c..c5eadcd`（15 commits，实现全量）
- 修复波：`c5eadcd..ff32866`（5 commits）
- 第二轮复查范围：`c5eadcd..ff32866`（逐条对靶 + 回归扫描）
- 方式：第一轮三席位并行（写入核心 / 卫星模块+查询层 / spec-文档一致性）；第二轮单复核席位；协调者两轮均独立实测（测试套件 + 真实 `data/` 取证 + 活体复现）
- 测试基线：第一轮 225 全绿 → 修复波后 238 全绿（+13，全为行为级断言）
- 当前状态：**With fixes（余 1 Important 一行修复 + triage 清单）**，待用户拍板

---

## 第一轮：max 评审（7e97b7c..c5eadcd）

### 总评

三席位一致 **With fixes**。共性确认的优点：

- 三档 upsert 语义精确（batch 按字段覆盖且 `val is None` 跳过；snapshot 只补空位），行为级测试钉死（`tests/test_market_data_io.py:85-93`）
- 锁机制选型正确：`O_CREAT|O_EXCL` 内核级跨进程互斥、非阻塞、600s 陈旧接管、`finally` 释放无泄漏（`market_data_io.py:95-128`）
- 旁路完成标记（N1）per-scope、三条件独立测试覆盖；amount 写者指纹（v0.3a）端到端验证（钩子盘中价 70.01 → 批量收盘 71.54 权威覆盖）
- 财务按位置列映射的 19 列重名 fixture 忠实复刻 gpcw 陷阱（roe/归母/扣非 ×2），失败方向正确（raise 而非静默错列）
- N4 OOM 决策留痕完整（docstring → friction-log → plan 注记 → 防回归测试锁 SQL 形状）
- 六处文档同步零矛盾；e2e 数字与磁盘实况逐一吻合

### 发现

**C1（Critical，已亲核verify）**：`parse_trade_date` 三个格式串全用 `%B` 全拼月名；Nasdaq 真实 payload 为 `Nov 2, 2026 12:03 PM ET`（`%b` 缩写月 + PM 前有空格），三串全失配 → NVDA/^IXIC/^SOX series **零积累且每天静默**。磁盘实证：`data/market/series/` 无这三个文件，对照组 `000660.KS`（eod）、`^TNX`（fred）正常。测试自造样本 `"November 2, 2026 4:00PM ET"` 与真实格式不符，从未暴露。spec §3/§8.2「海外票自启用日累积」承诺对这类票未兑现。

**I1**：`save_custom_data` `_series_path` 直接拼接、series 名零校验，`--series "../market/series/600276.SH"` 可写穿 `custom/` 污染行情序列（与 news 侧 slug 防线不对称，违反 spec §4.4）。

**I2**：`_upsert_bars` 锁冲突与空 df 返回都无声，调用方无条件计 `ok` → ok/skip/fail 对账口径失真；且锁冲突轮 `fail==0` 仍写完成标记 → 该票当日缺口（T+1 自愈）。

**I3**：`parse_trade_date` 只验形状不验合法性，`"00000000"` → `"0000-00-00"` 可成 date 主键。

**I4**：e2e notes 11.7/11.8 的 skip 归因是 v0.3a 修复前语义（钩子行被 skip），现行代码下数字不可复现且未加注。

**Minor（择要）**：README spec 版本指针二次漂移（friction 硬规则应修根）、`--value nan/inf` 写非标 JSON、registry/jsonl 读改写无锁、URL 规范化不排序 query 参数（dedup 漏口）、`find_existing` 全文 MULTILINE 误命中、news/query CLI traceback 收口不对称、`query_market custom` 被 `_require_duckdb` 挡、财务占位过滤零明细日志、iterrows 性能（仅 `--backfill all`）、`_raw` zip 缓存 ~700MB 无清理不在存储估算、README 目录树缺 `.locks/`/`_raw/`、spec §9 表残留旧口径、`daily-watchlist.md` 缺 `data/`、锁 TOCTOU、快照文件名本地时区、锁异常释放无测试、`import_csv --overwrite` 未测。

---

## 修复波（c5eadcd..ff32866）

| commit | 内容 |
|---|---|
| `1d7af20` | C1+I3：parse_trade_date 扩 8 格式（%b 变体）+ 三路径日历校验收口 |
| `dcbff3a` | I1：custom slug `[a-z0-9][a-z0-9-]*` 白名单（读 registry 之前）；I2：`_upsert_bars` 三态 written/empty/locked 分流 + 锁冲突不写完成标记 |
| `9c41743` | NaN/inf 行值清洗（persist/update_market_series 两处）、新闻 URL 参数排序 dedup、财务占位过滤明细日志 |
| `76e46bf` | README spec 指针去版本号修根 + e2e notes 口径注记（I4）+ spec v0.3b |
| `ff32866` | friction 修根（计划外）：persist CLI `--snapshot-file` 自动解包 wrapper——直传 daily 快照曾零追加+双层包裹 |

---

## 第二轮：修复波复查（逐条对靶 + 实测）

### 核验表

| 原始发现 | commit | 结论 | 证据 |
|---|---|---|---|
| C1 Nasdaq 格式失配 | `1d7af20` | **真修** | 8 格式覆盖真实 payload 全变体（缩写/全拼月、`Nov 2`/`Nov 02`、无空格 PM、纯日期）；`%B` 不误撞 `%b` 串（en_US 月名表不相交，实测落穿）；**NVDA/^IXIC/^SOX/^TNX 已回填 `date=2026-11-02` 行**（磁盘实证，mtime 11-03 08:34）；friction-log 留痕六格式被红测试打回扩八格式 |
| I3 日历校验 | `1d7af20` | **真修** | 8 位/ISO/长戳三路径全收口；`0000-00-00`/`2026-13-99`/`Feb 30` 全拒；各源合法格式（ISO/8 位/epoch）零回归 |
| I1 slug 写穿 | `dcbff3a` | **真修** | 白名单在 registry 读之前（坏名连目录都不建）；拒 `..`/`a/b`/`a\b`/大写/Unicode；负样本断言含「行情文件字节未变」 |
| I2 ok 虚高 | `dcbff3a` | **真修** | 三态分流 stocks/sectors 双调用点；`lock_conflict` 不写标记；「empty 不阻标记」为落档取舍（~45 只长期停牌票）有专测；e2e 对账口径移位已加注 |
| I4 notes 注记 | `76e46bf` | **真修** | notes:103「数字会移位，历史不回改」 |
| URL 参数序 dedup | `9c41743` | **真修** | query.sort() + 测试 |
| 占位过滤明细 | `9c41743` | **基本真修** | 有明细但缺 filesize、只列前 5 期 |
| README 指针修根 | `76e46bf` | **真修（机制级）** | 去版本号 + 「版本号只在 spec 头部维护」注记；spec v0.3b 正文 §5.2/§5.4 同步 |
| 计划外解包 wrapper | `ff32866` | **真修** | `payload` 键识别无误触发、幂等成立、三行为级测试含双层包裹防回归 |

**回归扫描：零回归**。三档 upsert、amount 指纹、N1 标记条件、锁语义均未触碰。测试 225→238（+13）无摆设测试。

### 协调者实测证据（两轮）

- 第一轮：三格式串对真实 payload `Nov 2, 2026 12:03 PM ET` 离线复现全 FAIL、`%b %d, %Y %I:%M %p ET` 可解析；series 目录三文件不存在（对照组存在）——C1 坐实
- 第二轮：238 测试全绿（1.52s）；`append_record(series='t', value=nan)` 活体复现落盘 `{"value": NaN, ...}`、严格 `json.loads` 拒绝——遗留项坐实

### 遗留（待拍板）

**Important-1：NaN 清洗修错对象（已活体复现）**
`9c41743` 修在 `persist_market_data.py` / `update_market_series.py`（同构缺陷，那两处修得对），但原始靶子 `save_custom_data.py:60` 原样——`float(value)` 直落 `json.dumps`（默认 allow_nan=True）。一条 NaN 让 `query_market` 读整条 custom series 失败。修法：`append_record` 加 `math.isfinite` 校验（一行）+ CLI `--value nan` 负样本测试。触发面：仅手工经 CLI 写 custom series 且传 nan/inf；16:30 cron 不受影响。

**复查新发现 Minor 六条**
1. `last_round_date` docstring 漏本波新增的 `not lock_conflict` 维度（`update_market_series.py:55-56`）
2. `import_csv` 对坏 series 名静默 skipped、退出 0（`save_custom_data.py:100-101`）——安全无虞但排障误导，建议循环前先校验坏名即报错
3. 回填**旧日期**快照会用旧 payload 重写当日快照文件（`persist_market_data.py:29-30` 用 `datetime.now()` 命名）——本次回填传当日文件无实害，静默损坏模式仍在；建议 `--snapshot-file` 路径跳过 `save_daily_snapshot` 或按 payload 日期命名
4. 占位过滤日志缺 filesize 且只列前 5 期（`update_finance_snapshots.py:165`）
5. `--snapshot-file` 对无 quotes 的垃圾 JSON 静默接受、退出 0——建议 CLI 加 `if "quotes" not in snapshot: parser.error(...)`
6. e2e notes line 85「属设计内降级」旧定性在 C1 根修后不再成立，未入注记范围

**上轮 14 项 Minor triage 盘点（修复波零留档，此处补记；处置为建议、待用户确认）**

| 项 | 建议处置 |
|---|---|
| registry/jsonl 读改写无锁 | 接受不修（并发场景弱：人工/巡检 agent；`series_lock` 现成可后补） |
| `find_existing` 全文 MULTILINE 误命中 | 低频，建议随 NaN 收尾 commit 顺手修（只解析首 `---` 块） |
| news/query CLI traceback 收口不对称 | 建议修（复制 `save_custom_data` 873502b 的干净收口模式） |
| `query_market custom` 被 `_require_duckdb` 挡 | 建议修（`_require_duckdb()` 下移到非 custom 分支，一行） |
| iterrows 性能（仅 `--backfill all`） | 接受不修（日常增量 1 期无感） |
| `_raw` zip 缓存无清理 | 接受不修，README 补一句隐性占用注记 |
| README 目录树缺 `.locks/`/`_raw/` | 建议修（口径源文档应完整） |
| spec §9 表残留「tail==最新日跳过」旧口径 | 建议修（spec v0.3b 漏网） |
| `daily-watchlist.md` 接线文档缺 `data/` | 建议修（六处同步清单漏的第七处） |
| 锁 TOCTOU（陈旧接管窗口） | 接受不修（触发条件苛刻，单机个人工具） |
| 快照文件名本地时区 | 接受不修，README 注记一句 |
| ticker 文件名清洗 | 接受不修（watchlist 信任边界内） |
| 锁异常释放无测试 | 建议补（一个用例钉 `finally` 路径） |
| `import_csv --overwrite` 未测 | 建议补（一个用例） |

---

## 结论

- 第一轮：**With fixes**（1 Critical + 4 Important + Minor 若干）
- 修复波：7 项对靶 **6 项真修、零回归**，1 项修错对象（NaN）
- 当前分支状态：**With fixes**——余 NaN 一行修复 + triage 确认 + 六条小 Minor，全部不阻塞核心正确性；C1 数据缺口已实证恢复（NVDA/^IXIC/^SOX 已有 2026-11-02 行，此后 cron 正常累积）
- 教训（已入记忆）：修复波自查「全 ADDRESSED」不算数，必须独立对靶复查——本次正是独立复查抓住了修错对象

---

## 处置记录（2026-11-03 同日，用户拍板后执行）

拍板：NaN + 复查新 Minor 六条 + triage 表 8 项建议修/补**全修**；6 项接受不修（其中 `_raw` 隐性占用与快照文件名时区两项按建议折进 README 目录树注记）。249 测试绿（+11），双 rule set 过，真实 `data/` 冒烟三发（custom 免 duckdb / quote 正常 / `--value nan` 干净退出 1 且零落盘）。

| 项 | 落点 |
|---|---|
| Important-1 NaN | `append_record` isfinite 守卫（与 slug 守卫同位，读 registry 之前）+ 单元/CLI 负样本测试 |
| 新 Minor ① | `last_round_date` docstring 补锁冲突维度 |
| 新 Minor ② | `_validate_series` 提为共享守卫，import_csv 循环前整批拒绝；main csv 分支补 ValueError 收口（+2 测试） |
| 新 Minor ③ | `save_daily_snapshot` 文件名日期优先 payload `meta.fetched_at`（UTC 日期段，日历校验），缺失/非法退墙钟；today 注入仍最高优先（+3 测试） |
| 新 Minor ④ | 占位过滤日志含 filesize、全量列出 |
| 新 Minor ⑤ | CLI 解包后校验顶层 `quotes` 数组，非 dict/缺 quotes → exit 2 拒绝，拒绝点在落盘之前（+1 测试） |
| 新 Minor ⑥ | e2e notes:85 追加 C1 根修后定性失效注记 |
| triage·find_existing | 只解析首 `---` 块（+正文伪 dedup 行回归测试） |
| triage·CLI 收口 | news/query main 补 ValueError → log + 退出 1（与 save_custom_data 同款） |
| triage·custom 免 duckdb | `_require_duckdb()` 下移到 custom 早退之后 |
| triage·README | 目录树补 `.locks/`、`finance/_raw/`；`_raw` ~700MB 隐性占用与快照文件名时区口径折进树注记 |
| triage·spec §9 | 「tail==最新日跳过」→「tail==最新日且 tail 行 amount 非空才跳过」 |
| triage·daily-watchlist.md | 接线图/文件契约/workspace-config 三处补 `data/` |
| triage·补测 | 锁 `finally` 释放路径（body 抛异常锁必删、释放后可重取）+ `import_csv --overwrite` 覆盖路径 |
