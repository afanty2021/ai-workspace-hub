# Workspace Config

> 这个文件描述当前项目是什么、材料在哪里、输出写哪里。它是项目级配置，不是全局人格设定。

## 项目定位

- name: `MY_AI_WORKSPACE`
- primary_use: `research / writing / investing / podcast / mixed`
- language: `zh-CN`

## 核心目录

| 目录 | 用途 |
|---|---|
| `inbox/` | 临时输入材料 |
| `wiki/raw/` | 原始材料归档 |
| `wiki/sources/` | 结构化来源页面 |
| `wiki/entities/` | 公司、人、项目等实体 |
| `wiki/concepts/` | 概念和主题 |
| `wiki/explorations/` | 综合判断和阶段性结论 |
| `output/` | 报告、日报、文章草稿等输出 |
| `workspace/monitoring/` | 用户阅读的监控看板，不驱动日报 |
| `workspace/archive/` | 已退出主流程但暂时保留的历史材料 |
| `hypothesis/` | 假设、证据引用和复盘 |
| `evidence/` | 独立证据账本，保存来源、方向和审核状态 |
| `output/daily-watch/` | 日报输出 |
| `data/` | 市场数据持久化（gitignore 运行时生成；spec：docs/superpowers/specs/） |
| `portfolio/` | 交易记录 |
| `config/` | 用户配置文件（不入 git） |
| `tools/` | 内置工具代码 |
| `system/` | 机器零件箱 |
| `workspace/meta/` | active-context 和 friction-log |
| `wiki/patterns/` | 跨案例可迁移模式卡；按召回信号选择性加载 |
| `wiki/rules/` | 已达到独立验证门槛的决策规则；按适用范围调用 |
| `workspace/review-queue.md` | 需要用户确认后才能生效的动作 |
| `workspace/research-profile.md` | 从真实研究中学习的用户研究偏好 |

## 输出约定

所有输出都要尽量包含：

1. 核心结论
2. 关键证据
3. 反方证据
4. 待验证问题
5. 下一步动作

## 数据标注

涉及事实或数字时，标注来源：

- `[本地]` 来自本地文件
- `[网页]` 来自联网资料
- `[tushare]` / `[FMP]` 来自日报脚本 API；`[Longbridge Skill]` 来自独立 Agent 扩展
- `[推测]` agent 的推理
- `[待验证]` 尚未确认

## 简单规则

1. 输入材料时，先按 `wiki/_schema.md` 分类。
2. 研究、分析、写作或输出时，先查 `workspace/meta/active-context.md`，再用 `knowledge_lifecycle.py load --context ...` 选择性加载 `rule / pattern / exploration`；输出里保留一行 `Wiki check`。
3. 遇到路径不清、规则不清、工具缺失或重复绕路时，写入 `workspace/meta/friction-log.md`。

对象 ID、frontmatter 当前状态和待确认队列统一遵循 `system/integrations/object-model.md`。

## 内置核心

### personal wiki

- status: `enabled`
- wiki_root: `./wiki`
- source_schema: `karpathy-claude-wiki compatible`
- reads_from:
  - `wiki/raw/`
- writes_to:
  - `wiki/sources/`
  - `wiki/entities/`
  - `wiki/concepts/`
  - `wiki/explorations/`
  - `wiki/patterns/`
  - `wiki/rules/`
- loading_indexes:
  - `wiki/explorations/_index.md`
  - `wiki/patterns/_index.md`
  - `wiki/rules/_index.md`
- distillation: `source -> exploration -> pattern -> rule`
- lifecycle_script: `system/scripts/knowledge_lifecycle.py`
- usage_log: `workspace/knowledge-usage.jsonl`
- auto_tagging:
  - script: `system/scripts/wiki_tagger.py`
  - env: `config/pod2wiki.env`
  - fields: `domain / ticker / concepts / related / entity_salience / tags`
  - policy: `只补空字段；单文件摄入自动写入；历史 backfill 默认预览`
  - cache: `workspace/cache/wiki_tagger.json（预览与 apply 复用，不保存正文或 key）`

### research（研究闭环）

- status: `enabled`（基座能力，wiki + websearch 零依赖起步）
- skill: `system/skills/research.md`
- profile: `workspace/research-profile.md`（v1.0 已固化，2026-11-07 经 7 次研究校准）
- inputs: `wiki/` + `websearch` + `data_sources`（可选）
- preflight: `system/scripts/research_preflight.py`（先扫描 Rule / Pattern / Exploration + Entity / Concept / Source）
- preflight_receipts: `output/research/preflight/`
- writes_to: `output/research/` → 确认后回写 `wiki/explorations/`
- focus_points: 默认 `业务/驱动因子, 竞争格局, 关键数据, 风险, 催化剂`（按需自定义）
- deep_research_template: 用户说「深度研究 / 深度分析 / 深挖」时默认套用四模块——**公司结构 + 财务传导 + 竞争格局 + 估值裁决**，外加反方证据与观察哨事件表（2026-11-07 Q-20261107-18 用户确认固化，7 次跨行业复现）；**四要素必答子项（2026-11-13 用户拍板强化，Q-20261113-05）**：①财务传导模块必含「成长拆解」小节（量价拆分 + 环比三指标：营收/归母/扣非，爆发期票禁只用同比）与「现金流质量」小节（净利润 vs 经营现金流对齐度 + FCF，背离即写明方向）；②竞争格局模块必含「护城河证据」小节（定价权/ROE 持续性/份额趋势三选二，落公司层面证据，禁只写行业描述）；③估值裁决模块原有双分位纪律不变；**模块四裁决必含「技术面验证」子项（与论点同向/矛盾/无关；矛盾时裁决默认不得高于「观察等待」，豁免须显式论证市场错在哪并留痕；「观察等待」裁决必带时间变量触发器，见 EXP-20261109-01）——2026-11-09 Q-20261109-03 德鲁肯米勒借鉴落地**；快速筛选与轻量问答不受影响，仍走 focus_points
- wiki_ingest_grant: 「报告落盘进 wiki / 报告落盘进入 wiki」= 预先授权 entity 建档（当日收账），报告本体仍按 skill 约定落 `output/research/`

### screen（快速筛选）

- status: `enabled`（基座能力，websearch + 可选数据源）
- skill: `system/skills/screen.md`
- inputs: `websearch` + `data_sources`（可选）
- writes_to: `output/screen/`
- presets: `价值股` / `AI产业链`

### 假设追踪（基座自带，无需安装）

- status: `enabled`
- 契约: `system/integrations/hypothesis-tracker.md`
- reads_from:
  - `hypothesis/`
  - `wiki/`
- writes_to:
  - `hypothesis/`
  - `wiki/explorations/`

## 内置工具

### podcast（播客/博客摄入）

- status: `enabled`
- skill: `system/skills/podcast.md`
- project_path: `./tools/podcast`
- writes_to:
  - `wiki/sources/`
  - `wiki/raw/podcasts/`
  - `output/pod2wiki/`

### daily-watch（日报监控）

- status: `enabled`
- skill: `system/skills/daily-watch.md`
- project_path: `./tools/daily-watch`
- reads_from:
  - `config/daily-watchlist-watchlist.md`
  - `wiki/entities/`
  - `wiki/concepts/`
- writes_to:
  - `output/daily-watch/`
  - `evidence/`
  - `hypothesis/`（只追加证据引用，不自动改变状态）

### masters（大师面板：个股多视角评分）

- status: `enabled`
- skill: `system/skills/masters.md`
- project_path: `./tools/masters`
- reads_from:
  - `data/market/series/`
  - `data/finance/`（gpcw 财务快照）
  - `config/daily-watchlist-watchlist.md`（批量模式）
- writes_to:
  - `output/masters/`
  - `data/.state/run-log.jsonl`（运行账本 open/close；冒烟跑账本随 `--out` 隔离）

## 数据源（按市场选择，没配降级不报错）

> 完整接入指南见 `DATA-SOURCES.md`。key 走环境变量或 `config/*.env`，不要写进 repo。没配的字段 agent 会标 `[待验证]` 而不是编造。

### nasdaq（美股基础行情，无 Key 自动降级）

- status: `enabled-no-key`
- env_key: none
- markets: US
- used_by: `daily-watch`
- limits: 基础行情，稳定性与覆盖不作承诺

### finnhub（美股备用）

- status: `available-unconfigured`
- env_key: `FINNHUB_API_KEY`
- markets: US
- used_by: `daily-watch`
- pricing: 免费账户端点可用，额度以官方当前账户为准

### eodhd（小额度 EOD 备用）

- status: `available-unconfigured`
- env_key: `EOD_API_KEY`
- markets: HK, KR, FI
- used_by: `daily-watch`
- pricing: 免费账户当前 20 次调用/日，可取过去一年 EOD 历史；不是实时行情

### yfinance（个人研究备用）

- status: `optional-no-key`
- env_key: `ENABLE_YFINANCE=1`
- markets: multiple
- used_by: `daily-watch`
- dependency: `yfinance`（需额外安装）
- boundary: 非官方 Yahoo SDK，仅适合个人研究/教育用途

### longbridge-skill（外部 Agent 扩展）

- status: `optional-external`
- auth: 独立安装后通过 Longbridge CLI / MCP 授权，不读取 `config/*.env`
- markets: 以 Longbridge 官方当前支持范围为准
- used_by: `screen`, `research`
- note: 不是 `tools/daily-watch/` 的内置数据源
- 安装方式: https://open.longbridge.com/zh-CN/skill/

### mootdx（A 股 + ETF 实时行情，主源）

- status: `enabled-no-key`
- env_key: none（`DISABLE_MOOTDX=1` 整体停用）
- markets: CN (.SH/.SZ，股票 + ETF)
- used_by: `daily-watch`
- transport: 通达信 TCP 7709 直连，实时快照 + 日线；服务器逐台真实取数验证，全网不可用时记 5 分钟负缓存并自动降级 tushare / 东财 / 腾讯 / 新浪
- dependency: `tools/daily-watch/requirements-mootdx.txt`

### tushare（A 股行情 / 财务，首备用）

- status: `available-unconfigured`
- env_key: `TUSHARE_TOKEN`
- markets: CN (.SH/.SZ), HK (.HK)
- used_by: `daily-watch`, `screen`, `research`
- pricing: 当前 120 积分档可取非复权日线；其他接口看积分或单独权限；daily-watch 里降为 mootdx 之后的首备用
- 获取方式: https://tushare.pro/register

### fmp（可选：EOD / profile / 财报 / 宏观）

- status: `available-unconfigured`
- env_key: `FMP_API_KEY`
- markets: 免费 Basic 以 EOD/profile 测试为主；扩展和全球覆盖取决于套餐
- used_by: `daily-watch`, `screen`, `research`
- pricing: 免费 Basic 当前 250 次调用/日；高级端点和全球覆盖为更高套餐
- 获取方式: https://site.financialmodelingprep.com/developer/docs/pricing
