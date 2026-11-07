# 港股行情降级链 + R-ID 撞号修根批次 —— 实施评审报告（max）

- **评审对象**：2026-11-07 会话未提交工作树批次（BASE=`97abde9` HEAD），11 文件 +225/−25
- **范围**：A) `fetch_market_data.py` 东财 116 段/腾讯 hk 前缀接港股个股；B) `research_preflight.py` R-ID 撞号修根（`find_research_id_clash`）；C) 模板镜像与文档同步（AGENTS/workspace-config/research-profile 三对 + skill）
- **排除**：并行会话 sector-rotation 批次（`tools/sector-rotation/`、`tests/test_sr_*`、proposals——另有自己的评审闭环）
- **评审方式**：max 四趟独立子代理——生产代码趟（含编排层逐环追踪）/ 测试趟（夹具对线上逐字段）/ 文档契约趟（镜像字节 diff + AGENTS↔CLAUDE 同源核查）/ 真实行为趟（curl 三组对照探测）
- **结论**：**0 Critical / 1 Important / 6 Minor → With fixes；修复已全部闭环**（2026-11-08 凌晨）

## 发现与逐条核实处置

| # | 级别 | 发现 | 核实 | 处置 |
|---|---|---|---|---|
| I-1 | Important | CLAUDE.md 同步遗漏：AGENTS.md:109 数据源行更新后，`CLAUDE.md:109` 与 `system/templates/CLAUDE.md:109` 仍为旧文案，打破 repo 自身「改一个同步另一个」成文约定；契约测试只管 CLAUDE↔template 字节一致（两文件一起旧、字节仍相等），测不出入口文件间漂移 | 属实（HEAD 时两入口仅差称谓，本批打破） | ✅ 两文件同步新文案；AGENTS↔CLAUDE diff 复核——除 Codex/Claude Code 称谓外零差异，同源恢复 |
| M-1 | Minor | `fetch_market_data.py` 三处链路注释随 HK 接入失真：345-353「Eastmoney/Tencent/Sina (CN A-share + ETF)」、1029-1030「HK tickers only ever reach CN sources via this gate」、1038-1039「_cn_quote_symbol gate … returns None for non-CN」（末条仅对 sina 仍成立） | 属实（均为本批引入的失真） | ✅ 三处改写：东财/腾讯覆盖 CN+HK（HK 走 `_hk_quote_code`）、sina 仅 CN |
| M-2 | Minor | 测试名与断言语义翻转：`test_hk_ticker_scales_per_mille_fields` 实际断言**不缩放**（fltt=2 十进制原值），名是 ÷1000 错误版历史残留 | 属实 | ✅ 改名 `test_hk_ticker_parses_fltt2_decimal_fields_unscaled` |
| M-3 | Minor | clash 回归测试未锁死「自身文件排除」：own=`output/research/my-report.md`('m') 字典序排在 `2026-11/other-session.md`('2') 之后，删掉排除逻辑测试照样过 | 属实；**但 reviewer 修法有缺陷**——`a-my-report.md` 的 'a'(0x61) 仍排在 '2'(0x32) 之后，同样锁不死 | ✅ own 改 `output/research/2026-10/my-report.md`（'0'<'1' 真正靠前）+ 注释说明锁死原理；**变异验证**：临时移除 own 排除 → 测试红；恢复 → 9 绿，区分度成立 |
| M-4 | Minor | 夹具含生产不请求也不解析的 `f58`（fields 参数 9 字段无 f58，线上按此请求也不返回；CN 夹具同病系 HEAD 既有） | 属实（`fetch_market_data.py:560` fields 列表核对） | ✅ CN/HK 两夹具各删 f58 一行，夹具与生产请求形状对齐 |
| M-5 | Minor | volume 单位跨市场未归一：CN 侧腾讯 f6/mootdx 为「手」、HK 侧 f6/f47 为「股」，原样透传，跨市场直接比较差 100 倍 | 属实，消费端注意事项非本批缺陷 | ✅ 按 562800 先例加 `SOURCE_CALIBER_NOTES["03800.HK"]` 口径注记（随日报披露） |
| M-6 | Minor | 评审任务描述自身误标：f169 括注「昨收」——实际 **f60=昨收、f169=涨跌额、f170=涨跌幅**；实现、夹具、线上三方一致 | 属实（任务文本错，代码无错） | 无需动代码；记录在此防后续任务描述复制讹误 |

## 评审确认的优点

- **HK 编排在调用方真实成立**，不只 fetcher 内部：`build_snapshot` 不把 `.HK` 计入 `fmp_tickers`；`is_mootdx_ticker` 后缀白名单挡 mootdx（批量与单票两口）；nasdaq 被 market 闸门挡；四个映射制全球源 map miss 零网络请求；sina 的 `_cn_quote_symbol` 6 位+SH/SZ 双条件挡 `.HK`——无无效请求、无未处理异常，链路确为 tushare → eastmoney(116) → tencent(hk)。
- **5 位校验是真实防线**：实测 `116.00380` 命中中国管业（f43=0.112）而非协鑫——若无校验，4 位码零填充后静默返回错票价格；`test_short_hk_code_is_rejected_without_request` 用 `assert_not_called()` 真验证「不发请求」。
- **fltt=2 注释警告实测准确**：带 fltt=2 返回 `f43=0.64/f169=-0.02/f170=-3.03`，不带返回 `640/-20/-303`——正是防「按裸 curl 探测加缩放」复发的关键注释。
- **夹具与线上逐字节吻合**：HK 夹具 10 字段（含 f86=1793952531→北京时间 2026-11-06 16:08:51）与实测响应一致；三源互拍 0.640 HKD / -3.03% / 2026-11-06。
- **clash 检查位置正确**：位于 `build_preflight`/`update_research_file`/`save_receipt` 之前，exit 2 零写入；错误信息中的 grep 命令实测可直接执行；回执 `PF-` 前缀天然不与 `^id: R` 相撞。

## 修复验证（2026-11-08）

- 相关三套（cn_free_sources / research_preflight / repository_contract）36 绿；
- **全量 642 passed + 16 subtests**（含并行会话 untracked 测试文件）+ `ruff check tools/ tests/ system/` 全绿；
- 变异验证红/绿闭环（M-3）；
- AGENTS↔CLAUDE 同源 diff 复核通过。

## 结论

**Ready to commit（待用户点名）**。批次含本评审修复共 14 个文件：代码 2（fetch_market_data / generate_daily_report）+ 测试 2 + 脚本 1（research_preflight）+ 文档 9（AGENTS/CLAUDE×2、模板×4、skill、watchlist Notes）。仓库惯例按关注点拆 commit：①HK 行情链（fetch_market_data + generate_daily_report + test_cn_free_sources + AGENTS/CLAUDE/模板数据源行）；②R-ID 撞号修根（research_preflight + test_research_preflight + research.md）；③研究文档批次（报告/entity/output，多数 gitignore 不入库）。
