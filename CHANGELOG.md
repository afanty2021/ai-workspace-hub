# Changelog

## Unreleased

### 新增
- 美国 3-2-1 裂解价差派生序列接线（2026-11-28，Q-20261128-04 能源腿「接线」拍板；背景=Mills/Hatfield 文章对拍（source 卡 wiki/sources/2026-11-28-fed-outdated-war-gold.md）引入「能源腿降温领先指示器」——Mills 引裂解价差六周 -36%、汽油期货两月 -45%，12-09 FOMC 三分支复盘观察清单数据源）：新建 `tools/daily-watch/scripts/update_crack_spread.py`，写 `data/custom/us-321-crack`（series us-321-crack，单位美元/桶，公式 (2×RB+HO)×42−3×CL 再 ÷3）。**三腿统一 yfinance 前月连续 RB=F/HO=F/CL=F（ET 日切、同源同滚）**——禁止与本地 `CL=F.jsonl` 跨源拼腿：该序列混装新浪北京日切快照与东财 kline，11-28 探针同日对拍 yahoo CL=F 83.08 vs 本地 sina 行 85.817（错位一天+滚合约口径不同），错配即系统性毒化派生值（PAT-20261128-02 同族修根=消灭混源，不做对齐补丁）。守卫全形态：三腿日期交集缺腿不写行（无 ffill，逐日 missing 计数）、RB/HO $/gal→$/bbl 单位断裂毒带（20~150）可见拒收（HG00Y 单位断裂案同族）、价差毒带 [-20,80] $/bbl、毒行/缺腿聚合进 data-close missing 不静默（C1 语义）、0 行可算/三腿全空=退出码 1（I-1 fail loud）。手工档无 cron（kind=batch-crack-spread 进 run_archive.KINDS+object-model 枚举同步，**不进盘前自检组清单**——不参与每日完整性核对，复盘窗前手工跑）；常量字面量锁 6 组+测试 16 用例（换算 26.4 字面量、缺腿/单位断裂/毒带两侧、幂等 skip、0 行上抛、main 退出码、yfinance NaN 剔除、KINDS 契约）；DISCOVERY_SCRIPTS 扩第四脚本（us-321-crack 入三文档发现网）。文档同步：DATA-SOURCES 宏观行、tools/daily-watch/README（yfinance 行+CLI 段）、daily-watch skill 运行账本段。2018 对照值同日核定（FRED T10YIE 2017-2019 逐日：2018 峰 2.18→11-14 首破 2.00（市场底前 6 周）→周期谷 1.68@2019-01-03；2019 全年未回上 2.0⇒「回上 2.0」非 pivot 确认条件；破 2.0 须与 10Y 名义同步回落配对判读——单独破=实际利率反升非 2018 形态）已回写 queue 行。
- 货币ETF折溢价温度计接线（2026-11-27，Q-20261127-01 用户拍板「接」；触发=用户问「银华日利 511880 折价=做多信号？」当日核查：溢价率 11-17 +2.85bp→11-23~26 -0.36~+0.20bp 处噪声地板内非异动（2026-11-28 勘误：原记 -0.1~-0.4bp 漏 11-25 的 +0.20 正读数），折价三解 risk-on/risk-off/机制性不能单独当多信号）：新建 `tools/daily-watch/scripts/update_money_etf_premium.py`——511880 银华日利（净值漂移型）主锚：净值链 pingzhongdata `Data_netWorthTrend` 主源→天天基金 lsjz 分页备份（双源对拍一致）× mootdx 收盘，**除权修复**=F10/pingzhongdata 除权日标签比场内价格除权提前一交易日（2023/2024/2025 三年假溢价 +174/+155/+115bp 实锤）→净值回落日用前一日净值对价、修复后 |bp|>50 毒行弃用不落盘；511990 华宝添益（原 511988 已换码，腾讯/TDX/东财基金搜索三处旧码消失）第二腿：固定净值型 100 锚（**lsjz/fundmobapi 对固定净值型货基 DWJZ=万份收益非单位净值**，禁跨基金复用解析）。写 `data/custom/cn-money-etf-prem-511880/511990`（回填 539+540 行=2024-09-03→2026-11-26/27 共 26.7 个日历月，11-26 溢价 -0.15bp 与会话手工核查逐位一致；2026-11-28 勘误：原记「18 个月回填」只对标定窗 2025-06~2026-11 成立），batch-money-etf 两行账本（run_archive KINDS 白名单 + object-model kind 枚举十三值同步，契约测试当场抓获漏登后补）。触发线=连续 2 个交易日 < -5bp 且双基金同向（基线 2025-06~2026-11 P5=-0.8bp/P95=+2.8bp 样本内未出现，标定与验证分离；对齐基准=511880 末 2 日期——511990 走 100 锚无净值依赖天然超前一日，按各自末行比较会永久错位），触发时联动上证日涨跌+Shibor 1W 日变动标注 risk-on/risk-off/方向不明（嫌疑级不裁决）；除权窗静默。日报骨架新增 `{MONEY_ETF_SECTION}`（零网络渲染，读数截至上一交易日=货基净值 T+1 披露，失败降级同行）；挂 18:10 批量第 4 条链内（第二腿失败只告警不置非零，语义同社融降级），cron prompt 双档同步（18:10 批量 automation-1e7fca91 第 4 条链+判读句、盘前 automation-c2895bd5 a 项六组→七组）+sqlite 回读逐字节核验。测试 26 用例（除权修复/毒行守卫/100 锚/降级链/幂等/触发判定/静默/标注三分支/kind 契约/main 退出码与记源）+5 发变异全红；PINNED_SERIES 扩两序列进三文档契约（脚本常量名 SERIES_511880 不匹配 *_SERIES 发现约定，按测试 docstring 限制钉入）。全量 1090 绿+ruff 净。文档同步：AGENTS/CLAUDE 数据源表、DATA-SOURCES、daily-watch skill（账本段+18:10 段+自检七组）、tools/daily-watch/README 数据源行。
- 研究回测脚本加 `--end` 显式截尾（2026-11-26，Q-20261126-16 用户点名处理；friction-log 勘误③ 条候选防线转正）：`tools/jinniu/run_backtest.py` 与 `tools/stage-bottom/run_backtest.py` 加 `--end YYYYMMDD`（含当日；缺省 0=不截尾，行为零变化）——截尾发生在 load 后、一切计算前：信号、基础率、交替回测、年化全部继承同一窗口。锁=等价对拍 harness（`--end X` 输出逐字节等于「缓存预截断到 ≤X」的全窗输出；变异验证：两脚本各「忽略 --end」单发全红，且变异首跑抓出测试自身两 run 共用 out 目录致对拍恒真的 bug 已修）+ 缺省全窗/边界 end=末根≡不截尾/截尾在最少样本数前跳过该票三形态。背景：数据窗此前是缓存当日状态的隐式参数，jinniu 全市场交替持仓随窗摆动（-0.05@11-10/+0.57@11-24/+0.79@11-25），「同窗对比」没有显式旋钮（[[baseline-comparison-same-window]] 同窗+同截尾三件套自此机械化）。范围边界：by_year/optimize/followup/oos_check 等臂脚本仍全窗，不在本条落点（需要时按同模式扩）。
- 复查 r2 全修当日闭环（2026-11-26，max 评审修复波 `ce88e74..33a5a9c` 三席复查 0C/4I/10M，Q-20261126-17 用户拍板全修）：**两卡勘误**——EXP-20261110-02「+2.59%（t=28.3）另一窗」系把 R20261110-01 勘误③ old→new 表同一窗 adx67 OOS h20 的旧值（11-10 重算口径）误读成第二窗（严格 OOS 只有 h20 一窗），改单窗 t=25.1+dated 注记；EXP-20261109-05「正值由 2020/2024 两年贡献」系旧名册「2015/2020/2024 三年」只删 2015 的半截更新（勘误③ 复跑口径正值年 8 个：2011/2012/2018/2019/2020/2024/2025/2026），全表改写+代际指针勘正（-0.27% 系勘误③ 值，勘误② 为 -0.26%）。**残留收口**——planted README「待拍板 Q-20261126-04」活残留改已拍板重跑+全表勘误④（收口波改过同文件仍漏，第五查路径表不含 tools/ 的首实证）、daily-watch README「11-26 备用链当日接住」改打桩断连实测措辞（生产盘前三类缺口并未接住）、评审报告头部补「评审落盘时点状态」注记、calib 逐市场快照明示「不入库、审计以复跑为准」、SR 逐格触发率「精确吻合」改「相容（8% vs α=10%，上尾 p≈0.79）」。**closeout 二次修根**——第五查命令改全仓式（跟踪面 `git grep` + 未跟踪面 `grep`，九词表补 挂起/PAUSED/pending，路径枚举必漏换位文件故弃用）+ 无关键词形态（过时事实陈述）限制明示；勘误全句对拍补「新值禁从中间文档转抄」（两卡误读的共同根因=从评审报告转抄而未对拍权威复跑工件）。**代码两处**——`check_commit_health` `--base ""` 空串归一为未设（此前绕过缺省空区间 exit-2 守卫，配第四形态测试）；`deoverlap_t` 补 step=2 顺序锁（step=1 时「先剔后抽」与「先抽后剔」逐位相同、锁不住顺序型变异；step=2 夹具内含对照自检保证区分度）。变异复验 3/3 红（沙箱克隆单点替换、PYTHONDONTWRITEBYTECODE=1 防陈旧字节码假红）。补账：Q-20261126-15 ①②③ docs 笔的 closeout 机制新增（第五查/勘误全句对拍）此前未落 CHANGELOG，随本条一并补记。全量 1059 绿+ruff 净。
- max 评审补锁测试 9 断言 + duckdb 进 CI 测试依赖（2026-11-26，Q-20261126-15⑤/⑥/M-3 用户拍板全 a）：本批新增防御有 9 处变异不红（真零锁，复合施加后全量仍 1047 绿）——补 9 条断言并对其中 6 发做变异复验全红：①②布伦特映射两家各锁（新浪/腾讯 `BZ=F`→`hf_OIL`，断言请求 URL 含 hf_OIL 不含 hf_CL——原用例只喂 payload 不看 URL，映射改指 hf_CL 会静默取到 WTI 价）；③`_calib_seed_uniqueness` 锁（CALIB_STRIDE 退回 1000 病灶值时必须 SystemExit 拒跑）；④新浪债券 `tradeDate` 跨 UTC 日用例（ts 落北京次日凌晨，UTC 日=11-25 本地日=11-26；测试进程内钉 TZ=Asia/Shanghai，防 UTC 时区机器上「去掉 timezone.utc」变异不变红）；⑤`deoverlap_t` 含 NaN 输入须与手工 dropna 结果一致（docstring「可含 NaN」承诺，生产调用点先 dropna 不受影响、直调方受保护）；⑥⑦hf_ 族与新浪债券两处 len<14 干净拒绝区分器（断言 `_note_fetch_failure` 未被调用——摘掉守卫会走异常路径记 degradation+Warning，结果同为 None 但语义变，11-08 惯例写法）；⑧流动性清单字面契约（`CL=F`→WTI原油 等四票在册——原断言按清单自身长度算，抽掉 WTI 照样绿）；⑨两个 `strat_table` 减 1 打印的字面契约（main 内嵌函数无法直测，锁源码标记，r5 N-1 同族回归锁）。`by_year` 周线调用点（X10）有意未锁：真实数据上响亮 ValueError、报告修法清单未列。M-3：`requirements-test.txt` 头注「缺了会直接失败（不是 skip）」改为实情（三文件已有 skip 兜底=缺了会 skip，CI 靠本文件保证不 skip）+四个测试文件守卫收窄（`except ImportError`→`except ModuleNotFoundError` 且 `e.name` 等于被导入包——tushare 已装但缺 six 不再降级 skip 而是当场红）；M-15 拍板项：`duckdb>=1.0` 进 `requirements-test.txt`（CI 上 test_query_market 15 用例不再 skip；CI 首跑 150 用例不跑的缩水绿缺口收口，duckdb 预编译 wheel 本地实测安装即用）。全量 1058 绿+ruff 净。
- 盘前数据缺口备用源接线（2026-11-26，Q-20261126-11；触发=当日 8:35 盘前档东财 push2 断连暴露三类缺口：^TNX 只有东财实时+FRED T+1、NQ00Y 东财单源、原油无任何实时接线；用户指令「其他数据源应该也有，比如腾讯和新浪，添加备用源」）：`fetch_market_data.py` ①新浪 `hf_` 族扩 CL=F→`hf_CL`/BZ=F→`hf_OIL`/NQ00Y→`hf_NQ`；②新增腾讯环球 fetcher——qt.gtimg.cn 代理新浪同名 hf_ 码（hf_XAU/hf_CAD/hf_HG/hf_CL/hf_OIL 五码逗号布局逐字段同位、共用 `_build_hf_quote`；老 nf_ 族已下线逐码 v_pv_none_match；field 1=涨跌幅% 未文档化不作锚、change 一律按昨结自算；`hf_NQ`/`DINIW` 不代理=NQ00Y/美元指数无腾讯备份）；③新增 CNBC fetcher（^TNX→`US10Y`，Tradeweb 实时、美盘收盘对收盘口径，与东财水平差 <1bp——11-25 双锚点对拍；裸请求无 UA 时 http=000 故恒带 UA）与新浪 `globalbd_` 债券族 fetcher（^TNX→`globalbd_usg10y`，**只取水平不取涨跌**——北京日切口径昨收=前北京日尾（ET 11:00），日变动与美盘真变动可反号（11-25 样本 +4.2bp vs 真变动 −3.8bp）且高低字段自相矛盾（gcny10 样本最新<最低），delta/OHLC 恒 None 报告显示「—」；日期取 unix 时间戳 UTC 日）；④降级链扩环 →东财环球→新浪环球→**腾讯环球→CNBC→新浪 globalbd**→FRED→（各 fetcher 映射自闸门，未映射票零请求）；⑤东财实时/回补两表扩原油 102.CL00Y/112.B00Y（suggest API QuoteID 实证、BZ00Y 无效；EastmoneySecidContractTests 同 secid 交集锁自动覆盖），`update_cross_asset_history` 回补默认 10→12 票（新浪期货日线因北京日切不入历史）+原油入 watchlist（WARM，gitignored 本地侧）+跨资产表固定序（铜系后、HSTECH 前）+query_market 流动性仪表；⑥测试 +20（hf 布局新浪/腾讯两变体、映射门控零请求、收益率 % 原值量级防呆拒 ×10 指数与债券净价、链路顺序「东财挂→CNBC/新浪/腾讯接管」今晨缺口逐条回归、降级链扩环 fallback 归属、原油 secid 分发），全量 1047 绿+ruff 净。cron prompt 同步（Q-20261125-09 双登记=本条+review-queue Q-20261126-11）：盘前档 automation-c2895bd5「利率/商品」句（含 sina-bond 涨跌「—」语义）与 18:10 批量 automation-1e7fca91 回补句旧表述「7 票/约 30 秒」勘正「默认 13 票=东财 12+新浪 XAU、3 秒/票」双双 CronUpdate+sqlite 回读逐字节核验。文档同步：AGENTS/CLAUDE 数据源表+system/templates 四处字节一致、DATA-SOURCES、daily-watch skill 数据源优先级、tools/daily-watch/README。遗留：东财 push2/push2his 当日 09:2x 探测期间触发 IP 级封禁（friction-log 同日条），102.CL00Y/112.B00Y 快照与 kline 单位对拍待解封后补做；当晚 18:10 批量可能整轮限流，按既有设计次日自愈。
- 提交纪律硬规则「拆分提交后逐提交健康检查」（2026-11-26，Q-20261126-06 用户拍板② 取 a) 不重排）：事后按关注点拆分提交或一次落多笔的批量提交后，同一会话内必跑 `python3 system/scripts/check_commit_health.py`（逐笔 detached worktree 跑 freshness 测试，`--full`/`--ruff` 加码），有红在后续提交里修、不回写已成历史（改写历史仍须用户点名）。背景：11-25 区间四笔逐提交红（CHANGELOG freshness）系同族第 3 次复发（2026-11-11 cf6bbf2、2026-11-12 8a6dd39），检查脚本先行已落（r5 处置条），本次把规则写进 AGENTS.md/CLAUDE.md「状态与确认」节+system/templates 同名模板四处字节一致同步。

- planted 多种子校准 `calibrate` 子命令（2026-11-25，Q-20261125-02 用户拍板「升格」当日落地）：`synth.py` 三市场构造器加强度参数与种子偏移（`event_market_tickers(bounce=,mom_coef=,seed_shift=)`、`noise_market_tickers(seed_shift=)`、`write_sr_market(mom_coef=,seed_shift=)`；None 哨兵读模块常数保测试 monkeypatch，出厂默认逐字节等价——配对结构与票码不变）+ `run_check.py calibrate`——对照侧 `--n-markets`（默认 50）个对照噪声市场（种子偏移 1000·k，k≥1：0 号市场是回归阈值标定种子，不算抽样，避免「标定集上测误报」的循环论证；**并非严格独立**——2026-11-26 实算，三族种子基数 1000/2000/4000 使 event/rps 对照市场 k 与 k±1/±2/±3 各共享 12 条同种子序列，event 判据不受影响、rps 受影响，见 Q-20261126-07）按出厂对照判据统计实测误报率（jinniu 接线核对逐市场照跑，读错臂即抛、校准统计作废）；埋边侧边强度 5 档（反弹注入 0.2%~1.0%/日、动量系数 0.05~0.25）×`--edge-seeds`（默认 3）测检出率并逐条判据报通过率（看哪条在弱边上先掉）；`--calib-targets` 子集、`--out-json` 落逐市场原始读数。**测量工具不是闸门**（exit 恒 0、不进单测，queue 原议）；README 新增「多种子校准」节（口径声明=合成市场率不直接等于真实率）。首次全量实测（50 市场×5 档×3 种子，n_perm=1000，`data/planted-benchmark/calib-20261125.json`）：event 双臂联合误报 10%（chuji 1/50、jinniu 4/50；2σ 名义 ≈5%/臂），检出边界 bounce ≥0.8%/日全过、0.6% 2/3（t 判据先掉）、≤0.4% 0/3；sr 六格全过 0/50、逐格 vs随机 5/50=10% 与名义 α 精确吻合、其余格 ≤1/50、mom_coef ≥0.10 全检出（0.05 已 2/3）；rps 价差腿 9/50=**18%**（对照侧最松、与弱边上 binding 同源）、去重叠 t 腿 1/50、双判据干净 41/50、检出边界 mom_coef ≥0.10；**naive 重叠 t 36/50=72% 纯噪声过 2 vs 去重叠 1/50**（|t| 中位 3.5 vs 0.8、90 分位 7.3 vs 1.5）=√20 膨胀的多种子实证（Q-20261125-05 定量注脚）。planted 59 用例全绿。

- planted 合成对照检查 `tools/planted-benchmark/`（2026-11-25，借鉴 Allencake/mit-trader-skill 的 `--planted`；范围与定位用户未答，按推荐先行，**2026-11-25 用户已追认**（见下方 r4 处置条），Q-20261125-01）：**定位=固定种子回归基线（单实现、非校准）**——合成市场里埋已知尺寸的边，配一个同种子、只差边项的对照市场，把真实验证管道跑在上面，程序化判定「埋边被检出 / 对照沉默 / 样本不足」，用途是防回归。它不回答误报率，也不回答多弱的边检得出，「量具正常」不等于该管道的历史负结果都可信。覆盖三条管道的部分部件（清单见 README「未覆盖部件」）：SR 检验矩阵 3 行×2 档、stage-bottom chuji 臂、jinniu buy 臂（只判阴性）、rps 臂 A/C。构成：`synth.py`（59 只合成票=12 反弹边+12 动量边+35 噪声，代码取真实缓存空闲的 609xxx/309xxx 段；写守卫 `guard_root`——合成数据只能落 `data/planted-benchmark/` 或仓库 `data/` 之外，`write_cache` 拒绝非本模块产出的 jsonl）+ `run_check.py`（`sr|event|rps|all`；`--strict` 把管道契约注记算失败；`--real-bundle` 只读报真实 RPS 数据上的两种 t）+ README。出厂市场读数（n_perm=1000）：SR 埋边宇宙六格 p=0.001、对照宇宙六格过一格；chuji 臂 h=5 alpha +1.44%/t 8.2（对照 +0.03%/t 0.3）；jinniu 点火与注入窗富集比 0.97、阳性未验证；rps D9−D0 +16.5pp、去重叠 t 8.65（对照 +0.32pp/t 0.02）。对现有管道零修改。检查顺带报出三处既有管道与自身口径不符（只报不改，均挂 review-queue）：①事件研究 `event_returns` 的停牌过滤拿 YYYYMMDD 整数差当天数，前瞻窗跨月的样本被误删（零停牌合成市场 h=5 保留率 72.4%；真实 600519.SH 应剔 4 个实剔 1039 个）②`validity.py` 臂 C 的 RankIC t 是重叠窗口径（真实 bundle RPS250 naive −16.27 / 去重叠 −3.98）③`rps_core` 上市年数门槛实际 500 根而非 docstring 的 250 根。run-log kind 不扩、不开 EXP/R 卡。1001 绿（planted 59 用例，变异 33 发全红）。
- 盘前档第零步自检 d 项（2026-11-24，Q-20261124-01；本条为登记补记——2026-11-25 max 评审 r4 B-I-1 查出当时漏记）：08:00 盘前日报第零步扩「盘前档自身完整性」——上一交易日 kind=watch open 行应 ≥2 笔（盘前+收盘各一）且上一交易日 `-premarket.md` 存在，缺失出红色警告；CronUpdate automation-c2895bd5 同步；`system/skills/daily-watch.md` 新增「盘前档第零步自检」节作同步副本。设计边界：08:00 档自身失败当晨不可自见，由下一交易日 08:00 档检出（首案 2026-11-24 turn 6 秒 failed，11:00 补跑闭环）。文档与 cron 改动，无代码变更。
- 达摩达兰标普500隐含 ERP 月度通路（2026-11-23，Q-20261123-05；同日查证属实后用户拍板「接线」）：新建 `update_damodaran_erp.py`——NYU Stern `Damodaran 官方 ERPbymonth.xlsx` 固定文件名整本全量拉取（他本人每月初更新、本档每日幂等拉自动捕获；**表头名定位列防 schema 漂移**，缺表/缺主列拒绝解析；ERP(T12m) 主值存 %、SP/TB/sust/ER 上下文进 note；幂等+batch-damodaran-erp 账本两行制，run_archive kind 白名单扩十二值）+ 18:25 档 cron 双命令化（顺带补登 Q-20261123-04 HY OAS 未入 cron prompt 的缺口；ERP 失败非零但只警告不影响流动性主档判读，连续 7 天失败才 friction-log）+ 日报宏观段 `{ERP_SECTION}` 自动渲染（最新月读数+2008-09 起历史分位「N 个月中仅 M 个月更低」+陈旧 45 天标注，零网络只读本地序列，失败降级一行）。首拉 218 行（2008-09→2026-11-01），11-01=3.79% 与主页快照逐位一致=218 个月最低档（中位 5.25%/2022-10 峰 6.21%）——要价温度计只记读数不作灯（清单预注册纪律之外，不设阈值）；12-01 月读=11-20 崩盘后首读且在 12-09 FOMC 前窗。登记：skill 运行账本+18:25 档、AGENTS/CLAUDE 数据源行+system/templates 双镜像同步、DATA-SOURCES。926 绿（+14 用例）。
- 科技回补三灯清单接线五项（2026-11-23，Q-20261123-04「做」；清单 v1.0=`workspace/monitoring/tech-reentry-three-lights.md`，用户三信号框架同日评审修订后拍板）：① 新建 `three_lights.py`（本地序列只读计算灯1a 美元 60 日新高止步/1b 利率 20 日新高止步∧不收复 5.12/1c HY OAS 380bp×2 日否决/1d RV20 年化 %<30×5 日/灯2 黄金完整周收 ≥3534.64 贴线标注/灯3 IXIC+SOX 21EMA 走平·站稳·8/21 金叉，today 注入防时间炸弹）+ 日报模板 `{THREE_LIGHTS_SECTION}` 段（零网络，失败降级一行提示不炸日报）+ 四灯总览行与 FedWatch/BTC 两人工槽位（③④补读程序入清单读数窗段）；② `update_us_liquidity.py` 扩双系列——`us-hy-oas`（FRED BAMLH0A0HYM2，% ×100 存 bp，cosd 限窗，单源无降级链；失败告警+missing 不阻塞 RRP 不置非零，降级语义同社融；18:25 档 cron 自动带上）；⑤ NDX-100 vs COMP 一次性对拍（Nasdaq 官方双序列 79 交易日：日收益相关 0.9877/同向 91.0%/崩盘三日差 ≤0.33pp/同峰同破位）回填清单 3a 注记判定等价。接线过程中冒烟抓获 fast/slow EMA 种子错位 13 根 bar 的金叉误判（崩盘死叉被报成金叉 23 日前）当日修复+回归测试。912 绿（+28 用例）。HY OAS 首拉 358 行，11-19=352.0bp 与 11-22 衰退判定读数逐位一致。
- 账本 verify 全净收口 + CHANGELOG 记账纪律契约（2026-11-22，Q-20261122-02）：① 7 条存量 undeclared 按两步 amend 补账——11-12/11-18 日报盘后评审补记句（C-1 影子序列勘误/HG00Y「同日已修根」注记）、`data/market/series/000300.jsonl` 产物消亡收口（裸码影子序列修根后权威迁 `data/index/series/000300.jsonl` 核心指数管道）、4 张 11-16 mover 证据卡 11-18 用户确认句（Q-20261118-01③）——复检 verify 全部干净；② CHANGELOG 系统性滞后双修根——skill「文档同步 checklist」扩第五点（CHANGELOG Unreleased 增量条目）+ 新契约测试 `tests/test_changelog_freshness.py`（CHANGELOG 末次提交后不允许 tools/system 非 md 代码的 feat/fix 零条目；5 合成形态例+真实仓库集成例，集成例当场抓获 32a7870 滞后即本条目补记的变异证明）。
- Fed 一手源三项接线（2026-11-22，Q-20261122-01「做缺的一半」）：① 美元 ON RRP 每日用量序列——新建 `update_us_liquidity.py`（主源 NY Fed markets API 桌面操作一手数据，**日期参数须带连字符、紧凑格式 HTTP 400**；备份 FRED RRPONTSYD，双源 2026-11-20 对拍逐位一致；幂等 + batch-us-liquidity 账本两行制，run_archive kind 白名单扩为十一值）+ 每日 18:25 独立档 cron（不并 18:10 批量档）+ 盘前自检 open 组四组扩五组；② 两房 P&I 付息窗口（每月 15-25 日，机制 FOMC20150723memo02 p5，日历界为运维近似）日报跨资产段自动标注；③ research_preflight context 命中 Fed/美元流动性词时输出「Fed 一手源」入口段（机制层作真锚、观点层与卖方同级）。同批 max 评审（0C/2I/6M）补漏：object-model kind 十一值同步、run_archive 两处「十值」文案、工具 README 数据源行与 CLI 示例、账本记源改「实际写入才记源」（全 skip/FRED 降级不虚记）。
- 持久化层追加交易所核心指数（2026-11-03 用户拍板，spec v0.3c）：`update_market_series.py --scope indices`（并入 all，固定清单 8 个：上证指数/上证50/沪深300/中证500/中证1000/科创50/深证成指/创业板指），落 `data/index/series/{裸6位}.jsonl`（source=mootdx-index，`last_indices_round` per-scope 完成标记，与 stocks/sectors 闸门隔离）；query_market 加 `index_series` 视图、裸 000/399 段路由指数、88 段仍走板块；北证50 899050 不收（mootdx 按 89 前缀路由 SZ 而 BSE 是 market=2，同样到不了，维持排除 BSE）。同批：`--force` 绕过闸门与逐票 skip 强制重拉（历史回补/盘中数据修正场景，friction 第 2 次触发修根；**盘中执行会把动态 bar 当收盘写并推进完成标记，收盘后须再跑一次 --force 修正**），17 只 watchlist 票 30 行缺口已用其回补至 800 行。

### 修复
- 货币ETF温度计 max 评审修复波（2026-11-28，四席并行评审 2C/12I/34M 全部落 docs/superpowers/notes/2026-11-27-max-review.md，Q-20261128-01 用户拍板「全部修复、拍板项按建议」；①-⑦ 全按推荐，⑥ 设计变更项挂 Q-20261128-03）：**2C**——C1 毒行守卫静默变瞎修根：守卫阈值 50→`POISON_PREM_BP=200`（±200bp=货币基金到不了的量级，真实极端读数照记；构造 -60bp 双腿原 exit 0+「正常噪声区间」），弃行不静默=log+stats+data-close missing（object-model：口径断裂属 missing 词表）+`data/.state/money-etf-poison.json` sidecar+日报段「近期弃行」提示行；close 非法（NaN/非正）compute 层拒收不再穿透炸整腿。C2 触发标注语境错位一日修根：`_index_daily_chg`/`_shibor_1w_move` 按 `asof` 对齐（取 date≤asof 末两行，原取序列末两行=语境比读数日新一天，11-27 实测 +3.73% vs 对齐 +0.01%、三分支翻转率 60.3%）；标注行补 Shibor 日期；测试夹具改对齐断言 +0.01%/−0.6bp（原夹具锁死错位）。**12I**——I-1 cron prompt 判据矛盾修（18:10 prompt「失败只告警不置非零」→「主锚 511880 失败置非零、第二腿 511990 失败只告警不置非零不补跑」+ 状态行/日报段转引歧义澄清，CronUpdate+sqlite 回读核验，双登记=本条+Q-20261128-01）；I-2 渲染层零契约补网：`render_money_etf_section` import 挪进 try（模块导入失败原炸整份日报不落盘）+ `{MONEY_ETF_SECTION}` 占位符契约 + 降级/正常态三用例；I-3 文档数字勘误两处就地（本条目原行「18 个月回填」实 26.7 个日历月、「11-23~26 -0.1~-0.4bp」补 11-25 +0.20）+`--days` help 改「回看 K 线根数」；I-4/I-5 计数词修根（同族第 3 轮）：run_archive docstring/help 去「十一值」改指 KINDS（help 用 len(KINDS) f-string）、object-model 枚举行去「十三值」+计数词禁用注记、skill 盘前自检去「六组齐全」改列 kind 名+checklist ⑥ 点名三份 prompt；I-7 顺带「下修不误标」：除权修复加 `EXDIV_MIN_DROP_RATIO=0.0005`（净值回落 ≥0.05% 才算除权，101.1970→101.1965 型数据下修不再误标 exdiv 毒化真触发）；I-8 100 锚论据换 A 席中位数论据（全存量中位 +0.1bp ⇒ 系统性锚偏差 ≤0.1bp 量级）+511990 真净值核实登记 Q-20261128-02 pending；I-9 main 账本 kind/run_id 断言（M69 零锁洞）；I-10 事实值锁升级（registration 契约新增 FactValueContractTests：四处同源行触发线数值锚 ump 常量、双向漂移皆红——原 token 级存在性断言对 D08「四处一起改事实」全绿）；I-11 阈值边界族补锁（触发线恰等/单越线、risk-off Shibor=+3bp 与上证=−0.5% 恰等、risk-on 双边界、陈旧 gap=10/11 边界+gap=5 负例）；I-12 逐提交健康缺省档扩 `tests/test_registration_contract.py`（b7c15e5 registration 红笔原只有 --full 抓得住）。**Minor 1-32 顺手清**——#1 note `%g` 截断改 `:.4f`+修复行存 nav_raw（存量旧行不回写 anchor 内）；#2 `_mootdx_bars` 改 `_mootdx_call` 统一弃服路径（spec §3+第二腿复用坏 client）；#3 删零引用 `EXDIV_QUIET_DAYS`；#4 指数文件 torn 行跳过不整段降级+改走 `index_series_file()`；#6 NaN 收盘 compute 层拒收；#7 幂等 skip 语义同族约定维持；#8 腿内中途失败已写入行 source 仍进 sources_used（S6）；#9 880 序列空回退显式标注 missing 语义；#10 基线/触发线文案改常量拼装；#11 lsjz 分页页数按 (days+40)//20+2 起算（原 days//20+2 在 --days 61~79 窗头缺行）+mootdx offset 800 上限截断告警；#12 `ordered_dates.index()` O(n²) 改 dict 定位；#26 511990 夹具「实录」标注改「构造值」；#27 关键常量字面量对拍组（自引用夹具族防线）；#28 lsjz 请求参数契约锁定（fundCode/pageSize/pageIndex）；#31 registration 发现约定放宽为「以 SERIES 结尾大写常量」+DISCOVERY 扩第三脚本+ump 常量改名 `PREM_511880_SERIES`/`PREM_511990_SERIES` 钉入约定（PINNED 清空）；#32 两处理论午夜 flaky 修根（ucah today 注入固定值、persist 快照墙钟断言改运行前后窗口）。测试 26→52 用例。文档同步：AGENTS/CLAUDE+双模板四处同源行（补「方向不明」第三分支/毒行守卫可见化/基线分位）、DATA-SOURCES 东财基金主机与分页参数 footprint、daily-watch skill（盘前自检 kind 名清单/18:10 段主锚语义+连续 3 天 friction-log 数法+除权窗静默形态说明）、tools/daily-watch/README（CLI 示例补温度计命令）。挂账：I-6 盘中跑写死 511990 动态 bar+`--repair` 通道、I-7 全量价净值联合判定、#14 risk-off「债跌」要素、#33 append_record 跨进程锁→Q-20261128-03 下一轮设计窗。cron prompt 双档 CronUpdate（18:10 判据句+状态行歧义、盘前 a 项部分缺失处置+c 项补跑指 18:10 批量含链内货币ETF）按 Q-20261125-09 双登记（本条+queue）。
- 机械网三洞修根（2026-11-26，Q-20261126-15④ 拍板 a；max 评审 I-4/I-5）：①`ci.yml` checkout 加 `fetch-depth: 0`——浅克隆把边界提交当根提交，`git log -1 -- CHANGELOG.md` 恒返回 HEAD 本身，freshness 测试 `_lagged` 首轮即 break 恒为空=CHANGELOG 契约在 CI 上空转（本地全历史上有效、CI 首跑的绿不含此项检查；浅克隆实验坐实，首跑 run 45758634606 的 checkout 即 depth 1）；②新增 `tests/test_knowledge_index_consistency.py`——真实仓库跑 `knowledge_lifecycle.py rebuild-index`（缺省 dry-run 不写盘）断言三类 `_index.md` changed 全 false：改卡不重建索引此前零机械网（11-25 勘误② 改卡未重建滞后到 ffa8c5c 顺带修好为首案），并并入 `check_commit_health.py` 缺省测试档；缺省档测试文件在历史提交树上不存在时按存在性过滤、全缺则跳过该笔（防逐提交检查被「文件不存在」收集错误整体打红）；③`check_commit_health.py` 缺省区间为空（通常=已全部推送）由静默 exit 0 改为非零退出（2）+提示显式 `--base`，`--allow-empty` 显式放行确属无需检查的场合（假合规路径堵死，配单测三形态：缺省空=2 / 放行=0 / 显式 base 空=0）；④同文件 5 处 `subprocess.run(text=True)` 补 `encoding="utf-8", errors="replace"`（M-14，Windows 裸跑非 UTF-8 模式读中文提交信息会炸，与 ce88e74 Windows 腿编码族同根，顺手同修）。
- CI Windows 腿首跑 19 红分族修根 + fork 仓库 Actions 解闸（2026-11-26，首跑 run 45758634606：ubuntu py3.12 绿、windows py3.12 红 16 failed+3 errors、ubuntu py3.10 被 fail-fast 连带取消）：**本仓是 fork（parent=Benboerba620/ai-workspace-hub），GitHub 对 fork 默认不跑 workflows**——此前八连查（fork 身份最后才查到）期间 API 三读数 `enabled:true`/`state:active`/`allowed_actions:all` 全真却零 run；「关→开」API 循环（`PUT actions/permissions` enabled=false→true）实测定案即解闸、push 即触发（friction-log 同日条）。19 红归五族全修根：①**stdio 缺省编码 cp1252**（7 红：planted 系列脚本 print 中文）→ ci.yml 腿级 `PYTHONUTF8=1`（UTF-8 模式下 stdio/`open()`/text 子进程缺省全 UTF-8）+ `tests/conftest.py` win32 `reconfigure` 兜本地裸跑；②**测试侧裸 `read_text()`**（2 红：test_us_liquidity 读 utf-8 落盘序列）→ 4 处补 `encoding="utf-8"`；③**账本路径原生分隔符**（7 红：`data\market\…` vs 断言 `data/market/…`）→ 账本 path 写入点统一 posix 归一——`run_archive._normalize_data_targets` 入口 `Path(...).as_posix()`、evidence `path` 记录、`batch_ledger._repo_rel` 与 `persist_market_data._ledger_repo_rel` 两分支出界绝对路径同样归一（仓库已有同族先例 knowledge_lifecycle/workspace_status/workspace_doctor；macOS 上逐字节不变、Windows 账本自此跨机可 verify）；④**git 中文提交信息解码**（1 红：freshness `_git` `text=True` 无编码）→ `encoding="utf-8", errors="replace"`；⑤**flock 并发防护**（2 红：Windows 无 fcntl 按「单写者假设」降级无锁=object-model「运行账本」段既载设计）→ 两并发测试按 `fcntl is None` 机制条件 skip（不按 os.name 字面，非 flock 平台全形态覆盖）。另 matrix `fail-fast: false`——一腿红不再连带取消其余腿信号。
- calibrate 对照市场种子族拉开 + 入口机械断言 + 全量复测（2026-11-26，Q-20261126-07 用户拍板④「拉开并重跑」；max 评审 r5 I-7/I-8）：旧方案三族基数 1000/2000/4000、偏移 1000·k 使 event/rps 对照市场在 lag 1~3 各共享 12 条逐字节同种子序列（EDGE_MOM(k)≡EDGE_BOUNCE(k+1)、NOISE(k)≡EDGE_MOM(k+2)、NOISE(k)≡EDGE_BOUNCE(k+3)），标定 0 号与对照 1 号也共享——「50 个独立对照市场」不成立、rps 全横截面统计受影响。修根：同族相邻市场步长 CALIB_STRIDE=100000、四族基数分离（event 埋边 70000037 / SR 埋边 60000041 / rps 对照 80000043 / rps 埋边 90000047），出厂 shift=0 种子算术逐字节不变（标定与阈值不受影响）；calibrate 入口新增 `_calib_seed_uniqueness`——按本次实跑参数把全部计划市场（含出厂 0 号）每条序列种子枚举对撞，撞种子拒绝开跑（50×3 / 100×3 过、101 拒，支持域 n_markets≤100 由断言而非注释维持），synth.py 增 `sr_market_seeds()` 枚举器。全量复测（50 对照市场/侧 × 5 档 × 3 种子，n_perm=1000，`data/planted-benchmark/calib-20261126-seedsep.json`；2026-11-25 首测表作废勿转引）：event 双臂联合误报 10% 不变、两臂 2/50 与 3/50=4%/6% 都贴 2σ 名义（旧 1/50、4/50），检出边界 0.6%/日 3/3 全检出（旧 2/3 t 先掉）、≤0.4% 检不出；sr 六格全过 0/50 不变、逐格最松 vs随机 4/50=8%、0.05 检出 1/3（旧 2/3）、≥0.10 全检出；rps 价差腿 18%→10%、去重叠 t 腿 2%→10%（两腿齐平、联合 18% 不变），检出边界诚实放宽：0.10 检出 2/3（旧全检出）、≥0.15 全检出；**naive t 33/50=66% 纯噪声过 2 vs 去重叠 5/50=10%（与名义精确吻合）**——√20 膨胀结论不变且校准表独立性成立（Q-20261125-05 定量注脚复测）。README 校准节改「2026-11-26 种子分离后复测」表+首测作废注记。I-8 统计口径三缺陷（不足不计干净、空 targets 报错、NaN→None）与 I-7 措辞随 r5 伞条先行，其代码落点随本笔。
- sleeve 执行层两卡全表勘误④（2026-11-26，Q-20261126-04 用户追认重跑；max 评审 r5 I-2）：`sleeve.py` U4 停牌跳空过滤修根（Q-20261125-04）后按白名单宇宙（UNIVERSE_RE，7115 文件）+ 数据截到 2026-11-24 全表复跑（确定性过程，与凌晨新旧对跑存档逐位一致），EXP-20261110-02 主表/分年度/归因阶梯/反方证据/summary 整体替换为复跑口径（R20261110-02 本地侧同波+勘误节重写+改前备份；`wiki/explorations/_index.md` 同步）。归因拆分：U4 修根效应=旧码@11-24 S1 −5.01%→新码 −3.32%，其余为数据窗+宇宙效应。结论面修正 4 处：S1 单笔均值 −0.06%→**+0.12%**；「十四个年度全输」→「2013–2025 全负、2026 年至今 +1.1pp」；最好可执行变体 V3（+1.51%）→V4（+1.21%）；「止损（S3）更差」→「未兑现保护、描述性不入选」（原文与 11-10 原跑自带表格即矛盾，主会话新发现）。结论方向不变：预注册主设计全样本 −3.32%/OOS −4.28% 仍大幅跑输同宇宙 EW（+10.57%），执行层否决维持。

- 盘前档日报日程 8:00→8:35 的仓库侧同步（2026-11-26 补记；日程由用户 2026-11-25 在自动化页面手改为 `35 8 * * 1-5`）：cron prompt 正文 8 处过时时刻表述已于 2026-11-25 经用户授权 CronUpdate 同步并逐字节核验（保留 11-24 首案时间戳 08:00:13 / 08:00:19）；仓库侧 `system/skills/daily-watch.md` 本次跟上 9 处（泛指档位改「盘前档」、具体时刻改 8:35、副本里不存在的「b 步」引用改「上文第 1 项」）。该次 CronUpdate 只改时刻措辞、不改判据；登记 Q-20261126-10（cron 双登记硬规则）。
- max 评审 r5 处置（2026-11-26，范围 `2809b5e..aa04ee0` 八笔，2C / 8I / 12M；主会话逐条回源核实并独立重做关键实测——22 条全部属实或基本属实，另有主会话新发现 3 条；报告 docs/superpowers/notes/2026-11-25-max-review-r5.md。凌晨定时续做时范围提问无人应答，按既有惯例**无争议且可逆项先行、范围待追认 Q-20261126-01**）：①**jinniu 周线路径回归修根**（I-1，Q-20261126-02）——2026-11-25 的历法日修根让 `event_returns` 把周序号（`resample_weekly` 返回值）当 YYYYMMDD 解析，周序号每跨 100 回跳 68 天，跨界的长停牌窗漏剔（全市场对跑：周线基础率均值有差异的票 339~349/臂）；周线调用改为显式传 `dnum=周序号`、阈值按周给（`GAP_WEEKS=21` 即 21 周，原 docstring 写 21 天是既有错配），`di` 含非法年月日直接抛错防再漏调用点；修后周线行与修根前逐位一致。②**交替持仓毛收益单位修根**（主会话新发现，评审员只点了旭创一行）——`tools/jinniu` 与 `tools/stage-bottom` 两个 `run_backtest.py` 的 `strat_table` 把净值倍数（连乘）按 `.2%` 直接打印（×0.94 显示成 94%），改为减 1 后打印；卡上对应数字同步更正。③**勘误③**（C-2 / I-3 / I-4 / M-2，Q-20261126-03）——11-25 勘误② 的三类问题：交替持仓读数变化是数据窗效应而非修根效应（该链路不经过 `event_returns`），归因撤回；池臂数字无法用落档 36 票名单复现（逐交易日扫描均对不上），改用落档名单复跑值（数据到 11-24：stage-bottom 池 −4.75pp t=−2.8，jinniu 池日线 −7.75pp t=−5.1、周线 −4.89pp t=−2.6，入样 36 票）；OOS lift ×1.6 系口径混用，应为 ×2.2。EXP-20261109-05、EXP-20261110-01 与对应 R 卡同步，判定与池依赖性结论不变。④**测试锁**（I-5 / I-8，Q-20261126-05 / 07）——此前 `tests/` 没有任何文件引用 `rps_core` / `validity` / `sleeve`，三发变异同时施加全量照样绿；新增 21 个用例：`rps_from_ret` 缺参抛 TypeError 与首个有效 bar=第 251 根、去重叠 t（实现抽成 `rps_core.deoverlap_t`，`validity.py` 改用）、sleeve U4 跨月保留/长停牌剔除、jinniu 间隔口径（周线跨界剔除、日线跨月保留、前瞻窗规则、`by_year` 宇宙白名单与周线接线）、calibrate 样本不足不计干净 / 空 targets 报错 / NaN 落盘转 None、planted 注记触发路径与出厂市场零契约偏差；变异 12 发全红。⑤**CI 全新环境转绿**（C-1，Q-20261126-08）——修前 fresh clone + 裸 `requirements.txt` 是 12 failed（openpyxl 6 / mootdx 3 / tushare 3）且 `check_workspace.py` 必红；新增 `requirements-test.txt`（openpyxl、mootdx、tushare、six——tushare 未声明的依赖）并在 CI 安装步带上，`check_workspace` 步改为「先全新安装到临时目录、再在该目录检查」（实例文件 gitignored，裸 clone 必红；`check_workspace.py` 以当前目录为根），三个测试文件加缺依赖即 skip 兜底。修后本地模拟 py3.10 / py3.12 两条腿：pytest（969 passed / 21 skipped）、ruff、compileall、全新安装 READY、三个 `--help` 全部 rc=0。⑥**文档**——`by_year` 改走宇宙白名单（M-8）、`run_check.py` 阈值注释与 planted README 尾段更新为当前出厂读数（M-1）、calibrate「独立」措辞改为实情（I-7）、friction-log 11-25 条目收口（M-7）、r4 报告终态节加指针（M-11）、`requirements.lock` 头部注明 numpy 2.3.5 仅适用 py≥3.11。⑦**逐提交健康检查脚本**（I-6 的候选修根，Q-20261126-06）——新增 `system/scripts/check_commit_health.py`：对一段提交区间逐笔在 detached worktree 里跑指定测试与 ruff、出健康度表，任一笔红则非零退出；配 4 个单测；在本次评审区间上运行会点名四笔红提交。全量 1027 passed + 16 subtests（1002 + 25）。**待拍板（2026-11-26 max 评审 Q-20261126-15③ 收口：下列四项当日已全部拍板处置，原「未做、待拍板」系拍板前时点状态，保留备查）**——Q-20261126-06 取 a 不重排五笔、「拆分提交后必跑逐提交健康检查」硬规则已进 AGENTS/CLAUDE；Q-20261126-04 sleeve 已重跑并全表勘误④（原「已修未重跑」注记随之关闭）；Q-20261126-07 calibrate 族种子拉开并复测（`calib-20261126-seedsep.json`，11-25 首测作废）；Q-20261126-09 M-3 停牌阈值维持现状挂起不修。
- `event_returns` 停牌跳空过滤跨月误删修根 + 全市场重跑勘误（2026-11-25，Q-20261125-04 用户拍板当日闭环；planted 接线核对独立重数对不上暴露，与 11-10 年化 `/10000` 同族第 2 次→friction 硬规则当日修根）：三处同写法一并改历法日（stage-bottom `run_backtest.py` `civil_days`、jinniu `run_backtest.py` `_days_from_civil`、`sleeve.py` U4 同修）——原 `di[nxt]-di[idx] <= gap` 跨月 1201−1130=71>10 把跨月前瞻窗全当停牌误删，真实 600519.SH 应剔 4 个实剔 1039 个、修后逐位对上 queue 记载。全市场 7 脚本+3 池臂重跑（池=36 票重建名单：config 行内入池日期注记+queue 拍板记录逐票回溯，指纹与 11-10 原跑逐位吻合，名单落档 R20261110-01 勘误②），六文件勘误全量同步（R20261110-01+EXP-20261110-01、R20261109-04+EXP-20261109-05、R20261110-04+EXP-20261110-03；正文表格全量替换消除新旧并存、EXP 卡 summary/复审记录/updated_at 同步、不受影响段落显式注记）。KD 金叉 h10 由正转负（−0.14% t=−13.4，反方证据撤销；原写「−15.5bp t=−17.7」是 jinniu buy h10 的数字，2026-11-26 更正）、优化层 ADX>67 三窗全过降级两窗过（h20 OOS 仍过，lift ×2.2——原写 ×1.6 系同臂 OOS/IS 口径，2026-11-26 更正）、jinniu 全市场交替持仓读数由「打平 −0.05pp」变「+0.57pp（t=4.2）」——**2026-11-26 勘误③更正：这是数据窗效应，不是修根效应**（交替持仓不经过 `event_returns`，新旧码全市场逐票相同；同一段代码在数据到 11-10 / 11-24 / 11-25 时为 −0.05 / +0.57 / +0.79pp），原「负漂移宇宙少持仓躲跌假象、池依赖主叙事更干净」的归因撤回；池臂按落档 36 票名单复跑为日线 −7.75pp t=−5.1、周线 −4.89pp t=−2.6、入样 36 票（原 −7.51 / −3.99 / 33 票无法用落档名单复现，池臂仍大幅跑输、毛收益都输不变）、买入「3-10 日短动量」消失大半（正漂移只剩 h=3~5 的 2-4bp）。planted `event_filter_retention` 合成市场保留率 72.4%→**100.0%**，指标转为该修法回归哨兵；一处过时测试断言同步（修后出厂无契约注记，`--strict` 恢复 exit 0，注记触发路径另有用例守）。
- rps 管道双修根 + bundle 重建勘误（2026-11-25，Q-20261125-03/05 用户拍板当日闭环；均 planted 检查暴露）：①`rps_from_ret` 上市年数门槛 250+N 根→`bar_count` 显式传 close 帧计数（缺省抛 TypeError 不留静默回退），修后全市场首根 RPS250 第 251 根、600519.SH 首个 RPS250=2013-06-25（docstring 口径，修根前 2014-07-03 第 500 根，docstring 与实现不符坐实）；②`validity.py` 臂 C RankIC t 改双口径（判定=去重叠 t 相位 0，naive 重叠 t 仅对照打印）——fwd20 逐日重叠零分布膨胀 √20 倍，真实 RPS250 naive −16.27 对去重叠 −3.98（膨胀比 ≈4）。bundle 重建后 R20261110-04+EXP-20261110-03 全量重算勘误：负向方向与显著性结论不变、量级如实降级（「t=−15~−17」不再作强度证据引用；RPS250 去重叠 −2.8 贴 5% 显著边缘、RPS50/120 稳健），月度窗 150→162 个月、2013 成第四正贡献年（+15.8pp）、EW null +10.13%→+8.75%（年轻票入宇宙拉低基准）。planted `_warmup_contract` 转绿并转该修法回归哨兵。
- max 评审 r4 挂账九项同日全处置（2026-11-25，Q-20261125-01/06/07/08/09 用户逐项拍板「修」；处置记录已附各 queue 行）：①Q-01 planted 范围（三管道部分部件+jinniu 只判阴性+cron 实跑的 weak_scan/weak_eval 未覆盖）与定位（固定种子回归基线）用户追认落账；②Q-06 三灯「金叉后回退」闩锁语义补定义——清单 3c 行补注记（置 True 后本轮金叉内不复位、收复不复位、等下一次 8/21 交叉重新武装；只熄加强项、灯3 判定仍=3a∧3b）+`trend_state` docstring 同步+新增「回退后收复不复位」测试（three_lights 31 绿）——代码现有行为即闩锁，此为定义追认+补测试缺口；③Q-07 盘前自检 d 项参照日改「上一交易日」口径——automation-c2895bd5 CronUpdate 全文同步+`daily-watch.md` 副本对齐（参照日 P=series 尾行日期 D：周一查上周五、长假后首日查节前最后交易日，不再以「昨天=交易日」为前提、不再跳过；「上一自然日 batch 六组齐全」的周末验证仍挂 11-30 周一首验）——**本 CronUpdate 即 Q-09 新规则的第一个遵守案**；④Q-08 CI 同款 lint 35 错清零（E741 `l`→`ln`/`lo` 按语境分族改名、E702 分行、E731 lambda→def、F841 纯死变量/F401 未用 import/F541 清理；`ruff check system tools tests`=All checks passed）+`requirements.txt` 补 numpy≥2.0/pandas≥2.2+`requirements.lock` 重钉（numpy 2.3.5/pandas 2.3.3+三个传递依赖，dry-run 解析通过）；CI 真跑仍待 push 验证（gh run list 无输出）；⑤Q-09 cron 行为变更双登记硬规则入 AGENTS.md/CLAUDE.md「状态与确认」节（`CronCreate`/`CronUpdate` 改任务行为→同一会话补 ① CHANGELOG 条目 ② review-queue 登记；只改日程表达式不在此列；cron prompt 无可解析工件、`test_changelog_freshness.py` 按设计只盯 tools/system 非 md 改动，本条补其盲区）+system/templates 同名模板四处字节一致同步（repository_contract 18 绿）。

- max 评审 r4 处置（2026-11-25，planted 首版未提交即评审：A 档 0C/9I/10M、B 档 2I/4M，主会话逐条回源核实后全处置，B-M-4 核实为误报；报告 docs/superpowers/notes/2026-11-25-max-review-r4.md）：①`--cache-root`/`--sr-root` 无写守卫（首版 60 只合成票码有 34 只与真实缓存同名，`write_cache` 以 "w" 直接打开）→`guard_root` + 票码迁到空闲代码段 + SR 的 ETF/bench 改合成名；②「预注册」口径不成立（阈值按同一种子事后标定，全漂移对照判据名义误报上界 19%、实测 10%~18%）→改标固定种子回归基线、删没有鉴别力的漂移对照（事件族 alpha 里漂移代数抵消、SR 全体同漂移与噪声宇宙等价）、埋边与对照市场改配对种子；③rps 输出拆分：判定用去重叠 t，出厂 naive t 口径与 `rps_core` 预热契约偏差单独报，新增「样本不足」态（空对照样本原先判成干净）；④jinniu 标「阳性未验证」，接线核对改为「消费到的样本数=独立推得的 buy 样本数」（只验管道输出行时，读错臂仍全绿），VAR19 富集比的基准从单日注入占比改为同域「前瞻窗含注入日」比例（0.97，首版口径不对等）；⑤测试 10 例重写为 59 例，评审员点名的零锁全部堵上（对照可整体禁用、两行 bootstrap 钉常数、读错臂、定点位舍入、锚点取时钟、漂移与可复现无断言），变异 33 发全红；⑥README/CHANGELOG 过度声明改写（「6 条管道量具级证明」「两臂归零」「对接 power_note」均超出实际验证）；⑦登记补齐：review-queue 新增 9 项 pending、friction-log 11-25 条目、`daily-watch.md` 第零步副本补「昨天=交易日」前提（cron 原文有、副本漏，照副本补跑周一会误报）、「五组」改「六组」。处置中新发现既有管道缺陷并挂队列：`event_returns` 停牌过滤跨月误删（见新增条与 Q-20261125-04）。
- 盘中快照行管线修根——增量起点回撤自愈（2026-11-23，Q-20261123-08 用户拍板「修」当日执行；r3 I-4 深层，读数层防御见 r3 处置条）：`update_cross_asset_history.py` 新增 `incremental_beg`——增量 beg 除锚尾行外，**回撤到尾部回看窗（15 行 ≤ upsert repair_window 30）内最早的快照源行**（收盘写者指纹 `KLINE_CLOSE_SOURCES`={eastmoney-kline/nasdaq-historical/sina-global} 的补集，source 缺失亦算——未来新实时源自动纳入）重拉官方收盘，batch 档覆盖愈合；浅 series 全窗口与 `--force` 语义不变。**回源勘误：真病灶非写入层幂等**（`upsert_series_rows` batch 档对尾部 30 行本就允许覆盖，账本回放 11-17/11-20 两晚即由此愈合 11-16/11-19），**而是 `update_ticker` 增量起点锚尾行**——push2his 限流夜整批失败（近 10 晚 7 晚）后尾行被次日快照行顶替，孤儿日期永不重拉（DX 11-12/13/18 sina 行幸存即此形态）；修根后限流夜孤儿在下一成功晚自愈、与「美股未收」解耦（kline 未到货照旧空手、下晚继续回撤重试）。契约测试 +8（回撤/唯一脏行非 sina/source 缺失/三指纹不回撤/越窗忽略/空行/浅表/端到端愈合），四发变异全红（禁用回撤/白名单化快照源/清空指纹集/绕过接线，击杀名单逐一核对）。存量清洗：DX-Y.NYB 4 行由修复后脚本自清（beg 回撤拉官方收盘覆盖；当日 push2his 小时级封禁则后台重试、次日 18:10 cron 用工作树代码兜底），^TNX 11-23 行 kline 未到货、次日 cron 自愈=修复实证点。README push2his 行同步。
- max 评审 r3 处置（2026-11-23，区间 3de273f..7aa99d2 七笔=三灯/HY OAS/ERP/百济批次，0C/6I/5M 当日全处置，报告 docs/superpowers/notes/2026-11-23-max-review-r3.md）：① I-1/I-2 接线登记漏点=11-22 I-2 同族第 2 次硬规则触发，A+B 双修根——skill 文档同步 checklist 扩第⑥点（object-model `kind` 白名单与 `run_archive.KINDS` 同步+cron prompt 一致性）+新契约测试 `tests/test_registration_contract.py`（kind 枚举全等+18:25 档两脚本序列名三文档登记，doc 侧双向变异红）；存量补齐 object-model 十二值（batch-damodaran-erp）、README 数据源表/CLI（FRED 行补 HY OAS、新增 Damodaran 行、18:25 双命令）。② I-3 灯2 边界澄清（Q-20261123-09 同日用户追认「同意」）：`gold_state` 改严格 `>`（等值=未收复——11-20 崩盘周收恰=体温计位，原 `>=` 令灯2 在崩盘当周即亮，与清单「首读窗 11-27 当周」矛盾），渲染符号 ≥/< 改 >/≤，清单 v1.0 补勘误级注记。③ I-4 `assess_three_lights` 增 today 注入，日频腿收盘输入剔除 `date>=today` 当日盘中快照行（DX/^TNX 当日 sina/eastmoney 行实测改变 1a/1b 读数；US 官方收盘最早北京次日可得）；管线层修根（快照行永久占位+存量 4+1 行清洗）挂 Q-20261123-08 待拍板。④ I-5 补实现 3c 金叉回退（金叉后连续 2 日收盘失守 21EMA 才回退，原 commit message 声明未兑现）。⑤ I-6 friction-log 补两条（登记/cron 滞后族 A+B 修根、盘中快照占位族）。⑥ M-1/M-2 测试缺口补齐（1c 否决→灯1 熄灭联动、erp_state today 注入钉死）。⑦ M-4 8:00 盘前自检 CronUpdate 五组→六组（batch-damodaran-erp）。新增 8 用例全变异验证（>回退/过滤失效/回退禁用/否决摘除/注入失效/契约双侧均红）。934 绿（926+8）。
- tagger exploration 卡 related 修根 + EXP-20261123-01 落卡（2026-11-23，Q-20261123-01，同日 max 评审 0C/3I/2M 全处置）：① `wiki_tagger.py merge_generated_metadata` 按 frontmatter type 过滤可写字段——`type: exploration` 恒不写 `related`（Q-20261113 M-3 拍板 6ff98c9 当时只落文档未落脚本，11-14 首案手工移除打补丁、11-23 第 2 次触发 friction 硬规则当日修根；tag/backfill 两入口单点覆盖，sources/concepts/entity 卡不受影响，存量值保留）+`MergeRelatedPolicyTests` 3 例；② 评审 I-1 补修根覆盖面换位形态——`wiki/_schema.md` 自动标签契约表 `related` 行加 exploration 豁免句（交互会话补空字段走契约表不经 merge 函数，原表与 :182 废弃注记自相矛盾）+代码注释补三通路限制声明（交互契约表/append_frontmatter 手动路径/LLM 生成侧保留写侧丢弃的取舍）；③ 评审 I-3 归属勘误——卡内美元 103.6/10Y 5.12 实为 11-16~18 日报读数（`2026-11-17.md:34`/`-premarket.md:24`/`2026-11-18.md:33`），原 based_on 误指 us-ai-crash 档案（该档 11-22 段为 103.9/4.93），「大跌日 -3bp」=11-16 SOX -5.28% 日非 11-20，三处补日期限定+真源指针；④ M-1 测试 docstring 变异策略照实写（去过滤仅第一例红，第二例钉存量语义）。884 绿复跑属实。复查 r2 通过（五项处置+自验声明全核验属实，r1 漏报 1M 补正：判定表 #7 NVDA 查账「恰在 10Y 5.12 时点」改 11-20 披露+5.12 平台=11-16~18 日期限定）。
- max 评审 r3 处置（2026-11-22，ea7b970..d18b31e 四笔批次复查，0C/2I/4M）：① 契约测试正则扩冒号形态——`_SUBJECT` 由 `^(feat|fix)\(` 扩为 `^(feat|fix)[:(]`，`feat:`/`fix:` 无括号写法（本库历史各 25/24 笔，约占三成）不再逃逸机械兜底；已知限制补③（refactor(/chore( 等改代码前缀不在机械范围，评审 A 侧兜底）+2 合成用例；② FRED RRPONTSYD 备份源请求补 `params={"id", "cosd"}` 服务器端限窗（sibling fetch_market_data 2026-10-31 cosd 判例的同族换位形态复发，同一个坑第二次硬规则当场修根）；M-2 误报勘正——中微 Q-20261119-03 追认实发生于 2026-11-20（queue done 单元三处锚点），d4fe4c0 commit message「2026-11-22 用户确认」系会话视角日期错写，profile 现文正确不改。881 绿（+2 用例），双变异验证（旧正则/无 cosd 均红）。
- LLM 调用链挂死/超时修根系列（2026-11-19~11-22，f8bb11a/eded5cc/4e9064c/ea7b970/32a7870）：wiki_tagger 挂死三刀收口——`llm_client.chat()` 硬 deadline（max_total_seconds=300，外层重试收紧不再放大挂死窗）+ 读循环内逐字节 trickle 封顶（stream+_drain，deadline 只在 attempt 边界的 overclaim 修根）+ `thinking` 参数（glm-5.x 推理模型默认 thinking 服务端 >120s 无首字节，tagger/摘要等机械任务显式 thinking=False）；换位覆盖面：podcast 侧 batch_summarize（ea7b970）+fetch_podcasts 三处调用点（32a7870，ea7b970「全部调用方」声明漏记、11-22 max 评审 I-1 勘误补堵）。
- 评审修复（2026-11-02 mootdx 接入评审）：mootdx 批量快照按服务器端单次 80 行上限分块（pytdx 客户端不截断、超量部分服务端静默丢弃，股票池超 80 只时尾部票会缺数），配分块测试；`_preserve_mootdx_bestip` 注释威胁模型按 mootdx 0.11.7 源码更正（`config.set()` 只改内存不落盘，保护对象是本进程内裸 factory 兜底读到的 BESTIP，非跨进程配置）；降级测试重构为真实穿过 fallback 链（原 mock 使 missing 为空、链路未被测到，且按票 mootdx 未 patch 存在真实联网风险）；mootdx 测试不再 mock 锁并断言可重入类型（RLock 被改回 Lock 时当场红）；补齐 `tools/daily-watch/README.md` 八处过时（数据源表、Fallback 顺序、零 Key 矩阵、目录结构、环境变量等）并修 CHANGELOG 重复标题与 DATA-SOURCES 重复段两处编辑事故；DATA-SOURCES 补通达信协议明文无加密声明；`system/skills/daily-watch.md` 新增文档同步四点 checklist（工具 README / DATA-SOURCES / skill / AGENTS+CLAUDE+模板），根治「改入口文档漏其余处」第二次返工。追加固化：锁契约测试补真实重入的限时守护线程检测（普通 Lock 回归由死锁挂起转为 5 秒内确定性失败，其余批量用例不再触发真实重入），`get_cached_tushare_client` 补缓存语义直测（空 token 不建连、同 token 复用、换 token 重建、初始化失败不缓存）；候选服务器无上限与 bars 失败 tradeDate 空串两项作为已记录取舍维持现状（取舍理由写入模块 docstring）。
- 评审修复（2026-10-31 第二轮）：证据 ID 修根对齐契约——`build_evidence_id` 改生成 `E-YYYYMMDD-*`（object-model 口径），消除带连字符日期的双轨命名；FRED 请求加 `cosd` 只拉近 30 天，不再下载全量历史；新浪环球周末快照的 tradeDate 回滚到最后交易日（周六采集冻结的是周五收盘）；日报「数据覆盖与日期」表为口径与 ticker 名义不一致的标的（HG=F → LME 三月铜 USD/吨等）追加口径注记；新浪环球 Referer 改 HTTPS 并补东财环球 HTTPS 断言；KRX UTC 日期测试 fixture 移到 UTC/北京分属两天的判别边界上；仓库契约测试把 review-queue 纳入「静态段契约、表格行属使用数据」的处理（与 active-context/friction-log 同一先例）。
- 仓库不再跟踪 `hypothesis/`、`evidence/` 目录内容（已加入 .gitignore，README 契约文档除外）：本仓库原地使用产生的个人假设与证据不再有 `git add -A` 误入公开历史的风险。

### 新增

- 市场数据持久化层落地（spec：docs/superpowers/specs/2026-11-02-market-data-persistence-design.md）：全市场行情/板块时序、日报快照、新闻快照、财务快照、自定义序列 + DuckDB 查询；每日 16:30 定时盘后批量；`data/` 整目录 gitignore。
- daily-watch 接入 mootdx（通达信 TCP 7709）并升为 A 股主源：无 Key 实时快照 + 日线，覆盖沪深股票与 ETF（tushare `daily` 不含基金），tushare 降为首备用，降级链变为 mootdx 按票重试 → tushare → 东财/腾讯/新浪；`DISABLE_MOOTDX=1` 可整体停用。客户端管理参考 TradingAgents-astock：候选服务器（实测精选表 + mootdx HQ_HOSTS）经 TCP 预筛与逐台真实取数验证后选用，探测期间保护 mootdx 持久化 BESTIP 配置，全网不可用时记 5 分钟负缓存快速失败并优雅降级（缺数据落备用链，整份日报不受影响）；适配本仓库线程池场景，以可重入锁串行化 pytdx 单 socket。`vol` 量纲实测为手（与 tushare/腾讯一致），昨收用交易所官方 `last_close`（除权日口径正确）。配套单元测试覆盖 ticker 门禁、字段映射、批量装配、降级链新序与 mootdx 全挂降级。
- daily-watch 新增全球指数与宏观无 Key 行情源，覆盖纳指（^IXIC）、费城半导体指数（^SOX）、美十债收益率（^TNX → FRED DGS10 官方序列）、美元指数（DX-Y.NYB → 新浪 DINIW）、伦敦金（XAUUSD=X → 新浪 hf_XAU）与伦铜（HG=F → 东财 109.LCPT 主源 / 新浪 hf_CAD 备用，LME 三月铜），并经东财韩股市场（177）接通 SK 海力士（000660.KS → 177.000660，当前唯一无 Key 的 KRX 通路）。watchlist 统一写 Yahoo 风格逻辑 ticker，脚本内映射表转换为各源代码，yfinance 恢复可用时同一 ticker 自动成为备源；海外/宏观/韩股行情不再依赖 yfinance 可用性。东财环球映射按完整 ticker 匹配（KR 000660 与 A 股 000660.SZ 同码防碰撞），全球 fetcher 交易日按 UTC 归一，配套单元测试覆盖字段解析、非映射拒绝、同码防误路由和链路路由。
- daily-watch 新增东方财富、腾讯、新浪三个无 Key 的 A 股备用行情源，在 tushare 未返回时依次尝试（东财 → 腾讯 → 新浪）；同时覆盖 tushare `daily` 接口取不到的场内 ETF，使全 A 股股票池在零 key 时也能拿到完整行情。字段映射与量纲（成交量统一为手）与既有源对齐，配套单元测试覆盖正常解析、非 CN 拒绝和链路顺序。
- 仓库契约测试只校验 active-context / friction-log 的静态说明段：这两个文件是设计上的追加式工作日志，在本仓库原地使用 Hub 时必然积累真实条目，逐字节比对模板与使用方式冲突。

### 改进

- 盘后批量 cron 16:30→18:10（2026-11-16 用户拍板，automation-1e7fca91；18:10 版新闻面以已发布收评为准并注记晚间公告缺口）；8:00 盘前日报增上一交易日收盘轮完整性自检（Q-20261116-04：查 run-log batch-* open 行+series 尾行判交易日查收盘日报文件，缺失只红色警告不自动补跑，收盘轮整轮丢失盲窗 24h→~14h）。同步 `system/integrations`、skill 与工具 README 共七处现行时间表述。
- 仓库不再跟踪 `workspace/meta/active-context.md` 与 `friction-log.md` 实例文件（已加入 .gitignore）：本仓库原地使用 Hub 产生的个人条目不再进入公开仓库历史，模板仍由 `system/templates/` 提供，新工作区由安装器重建。
- 评审修复：腾讯 / 新浪行情端点从明文 HTTP 改为 HTTPS；`build_quote_record` 把 `YYYYMMDD` 形式的 tradeDate 统一归一为 ISO 格式（tushare / 腾讯原始口径混排曾并存）；东财请求去掉未使用的 f58 字段；新浪涨跌额按 Nasdaq 源惯例 round 到 6 位；AGENTS.md / CLAUDE.md 数据源表补东财 / 腾讯 / 新浪行。
- `check_setup.py --init` 初始化股票池改用空模板，与安装器统一：新工作区不再被种入美股演示股票（AAPL/MSFT/NVDA 等），避免用户直接追加时把演示股混进日报；新增回归测试守住该边界。
- 日报保留行情来源、交易日和抓取时间，区分财报未配置、获取失败和成功但无事件，标明宏观与行情覆盖缺口。
- 播客新增 `--agent-handoff`，准备原文、待处理页面和持久队列，由当前 Agent 完成摘要，不要求独立模型 Key。
- 文档链接检查排除第三方依赖及构建目录，避免本地 UI 原型干扰测试。

- 新增 `DATA-SOURCES.md` 安装后数据源向导，并随新工作区复制；按美股、A 股和多市场需求区分 Nasdaq 无 Key、Tushare 基础日线、yfinance 个人研究备用，以及 Finnhub / EODHD / FMP 免费档的真实边界。
- 安装器和 `check_workspace.py` 明确 daily-watch / podcast 已内置，显示 Finnhub、EODHD、yfinance 的配置状态，并给出免费数据源下一步。
- EODHD 降级改用最近 EOD 历史接口，用最近两个交易日计算涨跌并明确不是实时价。
- 修正把 FMP 笼统描述为“免费全球行情”的文档偏差；免费 Basic、全球覆盖与高级端点不再混写。

## 0.8.1 - 2026-08-27

### 新增

- 新增 `system/scripts/prune_active_context.py`：把 active-context 的上限从"agent 自觉遵守"变成可执行的三道闸门——日期（超 14 天整条归档）、条数（仍超 20 条剪最旧）、行长（单条正文超 1500 字节时全文进归档、原地只留索引行）。第三道补的是前两道够不着的地方：一条写成小作文的条目既不老也不多，却能单独吃掉整个文件的预算。脚本只动「最近对话延续」段，其余状态段一个字节都不碰；归档 append-only 且按内容 hash 幂等，重跑不会重复追加。
- 新增 friction-log 硬规则「同一个坑不打第二次补丁」：同一问题第 2 次出现时禁止再绕，要么当场修根，要么把修根成本摆给用户拍板。补丁的成本摊在未来每一次执行上，修根只付一次。规则写进 `CLAUDE.md` / `AGENTS.md`，模板增加「第几次」字段。

### 改进

- Obsidian 阅读台改为优先读取资料日期和文件名日期，避免同步旧库后把历史资料全部误判为今天新增；阅读状态可直接在表格中填写。

## 0.8.0 - 2026-08-18

### 新增

- 新增可选 Obsidian 阅读台：安装时询问是否使用 Obsidian（或检测到目标目录已有 `.obsidian/`），是则安装 `reading-hub.base` + `reading-hub.md`，用 Bases 仪表盘汇总 inbox / 研究 / 筛选 / 播客 / 日报新内容；默认不安装，不影响 Core Mode。
- 新增统一 wiki 自动打标器，新材料与历史补标共用 `domain / ticker / concepts / related / entity_salience / tags` schema。
- 新增 Hub 共享 LLM 客户端，支持严格 JSON、瞬时网络重试，并保留 podcast 原导入路径兼容。
- 新增分层知识编译链：`source -> exploration -> pattern -> rule`，被证伪且可能重复出现的直觉进入 `false-beliefs.md`。
- 新增 `exploration / pattern / rule` 三类独立知识卡、状态机、复审日期、替代关系和失效条件；规则从单文件入口升级为 `wiki/rules/` 卡片目录，旧 `wiki/rules.md` 保留兼容入口。
- 新增 `knowledge_lifecycle.py`：支持生命周期汇总、三类短索引重建、按场景选择性加载、实际调用记录和带确认门槛的升降级迁移。
- 新增 `wiki/explorations/_index.md`、`wiki/patterns/_index.md`、`wiki/rules/_index.md` 自动摘要索引；默认只加载生效知识，弱化/退役内容需显式复盘加载。
- 新增 `knowledge-lifecycle.md` 可执行协议，定义跨案例晋级、降级、归档、复审和调用记录边界。
- 新增 `research_preflight.py`：研究开始前一次加载有效 Rule / Pattern / Exploration，并扫描配置 Wiki 的 Entity / Concept / Source；支持外部 `wiki_root`，默认不扫 raw、不调用 LLM。
- 新增研究前置回执 `output/research/preflight/{R-ID}.md`；研究报告记录 `preflight_id / knowledge_used / wiki_pages_loaded`，使“先查本地”可验证。

### 改进

- README 明确 daily-watch 与 podcast 已随 Hub 内置，无需单独安装，并补充 Obsidian 阅读台的安装条件和使用边界。
- 刷新 `requirements.lock` 的可复现依赖版本，移除旧锁定版本中的已知安全漏洞。
- 收拢顶层目录：日报归入 `output/daily-watch/`，看板与归档归入 `workspace/`；旧工作区已有的 `daily-watchlist-reports/`、`monitoring/` 和 `_archive/` 仍被识别，不自动搬动用户文件。
- 笔记、PDF 和 pod2wiki 来源统一接入自动标签；只补空字段，历史批量处理默认预览并缓存结果，确认写入不重复调用 API。
- 安装器、安全升级清单和 Core Mode 检查器接入新索引与空白模板，旧工作区只补缺失文件、不覆盖用户知识。
- Doctor 与 `workspace_status.py` 增加知识卡 ID、来源链、生命周期状态、复审日期、晋级门槛和失效信号检查；旧卡缺字段只提示渐进迁移。
- 修正冷安装仍复制演示股票池的问题；新工作区和仓库默认股票池为空，Doctor 不再因不存在的示例假设报错。
- 研究入口统一改走 Research Preflight；命中结果附带相关度原因、摘要片段和显式过期/弱化/反方章节提示，之后才进入联网补充。

## 0.6.0 - 2026-07-11

### 新增

- 新增统一研究对象契约：研究 `R*`、假设 `H*`、证据 `E-*` 和待确认动作 `Q-*` 使用稳定 ID；Markdown frontmatter 成为当前状态唯一来源。
- 新增独立 `evidence/` 证据账本。daily-watch 的可确认行情与财报信号先生成带来源、去重键、关联假设和审核状态的证据文件，再在假设中追加引用。
- 新增 `workspace/review-queue.md`，持久保存 wiki 沉淀、假设调整、股票池新增和研究偏好固化等需要用户确认的动作。
- 新增 `review_queue.py`，统一生成队列 ID、去重候选动作并更新确认状态，避免 Agent 手改表格造成格式漂移。
- 新增 `workspace_status.py`：汇总进行中研究、开放假设、待复盘证据、到期复盘、待确认动作和下一步建议。
- 新增 `upgrade_workspace.py`：默认预览新旧差异；明确确认后更新 Hub 受管文件并自动备份。迁移清单只补缺失的新目录和空白模板，混合文件保留人工合并，用户内容不覆盖。

### 改进

- 收口股票池唯一来源：`config/daily-watchlist-watchlist.md` 驱动日报，`monitoring/` 只作为用户看板，避免维护两份标的状态。
- 研究偏好改为“本轮观察 -> 待确认调整 -> 已确认偏好”的演化机制，不再让 Agent 根据单次研究直接覆盖用户方法。
- 首次研究、研究收口、日报和假设复盘统一接入对象 ID、证据账本与待确认队列。

### 文档

- README 演示动图沿用 0.5.0 的首次股票研究流程，并补充状态检查、证据账本和新目录说明。
- 架构文档新增状态层、证据流、待确认队列和安全升级边界。

## 0.5.0 - 2026-07-11

### 新增

- 默认用途调整为股票研究，新增 `START-HERE.md` 和 `first-research` 引导：用户第一次研究公司时，不需要预先设计模板，而是在真实研究中逐步形成研究偏好。
- 新增 `workspace/research-profile.md`，沉淀用户关注维度、证据标准、估值习惯和反方偏好，后续研究可直接复用。
- 新增研究收口与假设复盘协议，把研究报告、长期知识、可证伪假设和每日监控连接成完整闭环。
- 新增 Hub 文件归属清单与 `workspace/.hub-state.json` 安装状态，为后续升级区分系统管理、用户所有和混合文件。

### 改进

- 假设模型改为自上而下的主题假设，公司作为受益映射和验证载体；模板补充时间跨度、公司角色、主题关系和公司特有风险。
- daily-watch 可从主题假设读取关联 ticker，并将公司异动、财报等可确认信号回写证据时间线；纯主题匹配只提示核验，不冒充已写入证据。
- 补充 `IFX.DE` 等欧洲 ticker 的回归验证；首次安装默认 `primary_use=investing`，并安装用户首页、研究偏好和升级状态文件。

### 修复

- 收紧研究结束时的文件落点和链接规则，避免结论只留在对话或报告中，未进入 wiki、假设与后续跟踪。
- 安装器继续沿用 0.4.0 的缓存与本地 `.env` 过滤规则，同时记录实际安装版本，不覆盖已有用户状态。

## 0.4.0 - 2026-07-05

### 修复（2026-07-05 全量体检批次）

三路并行代码审查（podcast / daily-watch / 安装链路）后的批量修复，共 40+ 项：

**daily-watch**

- 零 key 承诺兜底：`generate_daily_report.py` 缺 env 文件时警告后继续（原直接 `FileNotFoundError` 崩溃）。
- `hypothesis_tracking.enabled` / `auto_writeback` 配置真正生效：关闭后不再回写 `hypothesis/H*.md`（原开关形同虚设）。
- 关联标的识别支持 `601857.SH` / `0700.HK` / `BRK.B` / 单字母美股（原正则对 A 股、港股、类别股全部静默失效）。
- Nasdaq/EOD 降级源只剥已知市场后缀，`BF.B` 不再被剥成 `BF` 查错公司；yfinance 增加 `.SH` → `.SS` 映射（原对上交所永远失败）。
- `run_json_script` 失败时透出子进程 stderr（原真实错误被吞）；`generate_daily_report.py` 补 argparse，`--help` 不再误跑真报告。
- `check_setup.py --init` 补创建 `hypothesis/` 和 `portfolio/journal/`，FAIL 项附修复提示；根目录探测失败时回退 cwd 并警告。
- `sync_hypothesis.py` 容错手改的 frontmatter（`certainty: 80%`、坏 YAML 单文件跳过不崩全表）。
- `focus_areas.exclude` 真正实现；示例 yaml 标注仅 skill 层使用的字段；假设文件读取兼容 BOM；tushare 窗口 10 → 14 天覆盖长假；证据时间线插入段尾 `---` 之前。

**podcast**

- LLM provider/model 优先级改为「显式入参 > 环境变量 > 默认值」，并防止通用 `LLM_*` 变量串到显式指定的其他 provider（反转 0.3.1 的「环境变量优先」：config/CLI 显式指定不该被 .env 默认块静默压过）。
- Whisper 转录语言默认自动检测（原硬编码英文，中文播客产出错误转录并污染 wiki）；config 支持 `whisper.language`。
- history 去重前移到下载/转录之前，且逐条落盘——中途崩溃不再重付 LLM/Whisper 成本；显式 `--youtube-url` 绕过去重。
- 代理改为显式配置：`PODCAST_PROXY` 未设置即直连，`auto` 才扫描本地端口（原盲扫 12345-12350 误伤开发服务）；requirements 补 `requests[socks]`（原配了 SOCKS 代理必挂 Missing dependencies）。
- 单条坏 `pubDate` 不再毁掉整个 feed（逐条容错）；新增 Atom feed 支持（原静默 0 条）。
- `.m4a` 剪辑沿用源容器（原静默退化为整集转录）；LLM 返回非对象 JSON 走跳过路径不再崩整轮；转录 frontmatter 转义特殊字符；`podcast_rss_transcribe.py` / `podcast_feed_registry.py` 补 UTF-8 输出兜底（0.3.1 已覆盖其余入口）。

**安装 / 测试**

- 安装器不再把 `.ruff_cache` / `__pycache__` / `.DS_Store` / 本地 `.env`（含 API key）复制进新工作区；`--target` 指向文件时给友好报错。
- `check_workspace.py` 兼容带 BOM 的 env 文件；`inbox/first-note.md` 降级为可选项，post-install-cleanup 归档后不再误报 NOT READY。
- 文档修正：删除与 `.gitattributes` 冲突的 autocrlf 建议；post-install-cleanup 步骤编号与 installer 路径说明；daily-watch 数据源表列对齐。
- CI 统一 pytest 收集（unittest 会漏掉 pytest 风格用例）、钉 ruff 版本、补 `generate_daily_report.py --help` 冒烟；新增 41 个针对上述修复的单测（全套 55 个通过）。

以下修复来自一次完整的冷启动安装模拟测试（陌生环境、只凭 README 分享句从 GitHub 安装）：

### 修复

- **安装分享句改用 raw 链接 + git clone 双通路**：原 blob 页面链接是约 340KB 的 HTML，网页抓取只能拿到摘要，agent 可能凭残缺协议安装；raw 链接是 12KB 纯 markdown，与源文件逐字一致。协议开头同时提醒 agent 自检"拿到的是全文还是摘要"。
- `install_workspace.py` 完成提示指错下一步：原来指向 `check_setup.py`（Enhanced Mode 配置），会把新用户引向 API key；更正为协议 Step 5 的 `check_workspace.py --root`（Core Mode 检查）。
- `INSTALL-FOR-AI.md` 补两处 agent 只能靠猜的空白：用户没有现成 wiki 时 `--wiki-root` 直接省略（默认 `./wiki`）；临时克隆目录按平台取 `%TEMP%` / `/tmp`。
- `first-ingest.md` 步骤对齐 `wiki/_schema.md` 的「MVP 最低合格标准」（补 raw 归档、至少一个分类页、output 试跑报告），不同 agent 的产出不再因两份文档标准不一致而波动。

### 文档

- README「30 秒上手」新增「还没有 AI agent？先花 2 分钟装一个」：Claude Code / Codex CLI / Cursor 三条最短安装路径，收礼的朋友从零也能起步。
- README 开头与仓库 homepage 挂上设计思路长文《从0构建 AI 协作系统（一）：从最小可运行的 MVP 开始》（作者公众号）。
- **README 顶部新增 33 秒演示动图**（`docs/demo.gif`）：一句话安装 → 3 个问题 → Core Mode READY → 第一次摄入 → 配 API key（Enhanced Mode）→ 断点续传收尾。按安装协议真实流程脚本化生成（生成脚本 `docs/gen_demo_gif.py` 一并入库，流程变更时改台词重跑即可），并在图下注明"非实录"。

### 改进

- 仓库开启 GitHub template：点 "Use this template" 即可创建自己的（可私有）工作区副本，个人研究数据不必公开 fork。

## 0.3.1 - 2026-07-02

### 修复

- **手动 clone 不再继承维护者的工作状态**：`workspace/meta/active-context.md` 和 `friction-log.md` 重置为干净模板，仓库契约测试新增这两对模板一致性检查，防止个人工作日志再次混进发布内容。
  之所以这样改：README 的"手动 clone 直接用"路径会把维护者的断点记录带给新用户，走安装协议的用户不受影响，但两条路径应该拿到同样干净的工作区。
- **smoke-test 演示产物移入 `examples/smoke-test/`**：原先散在 `wiki/` 和 `output/` 里的 2026-06-05 试跑产物（含未在文档声明的 `output/first-ingest/` 等三个子目录）统一收进 `examples/`，配 README 说明"这是示例、可整目录删除"。用户的 `wiki/` 和 `output/` 现在从空白开始。
- `TROUBLESHOOTING.md` 播客排障段指错配置文件：`config/llm.env` 更正为实际存在的 `config/pod2wiki.env`。
- **Windows 西文 locale 下中文输出崩溃**：8 个入口脚本（`check_workspace.py`、`check_setup.py`、`fetch_podcasts.py` 等）在 cp1252 控制台打印中文会触发 `UnicodeEncodeError`；现在启动时统一把 stdout/stderr 重配为 UTF-8。新加的 Windows CI job 第一跑就抓到了这个问题。
- 新增标准库安装器，安装协议明确先取得源码；非空目标默认停止，`--merge` 只补缺失文件、不覆盖用户资料。
- 修复 all-in-one 工作区在配置文件创建前无法识别根目录的问题，`check_setup.py --init` 可安全初始化缺失配置。
- 更正 Longbridge 定位：它是独立 Agent Skill/CLI/MCP，不再宣称为 daily-watch Python 脚本的内置环境变量数据源。
- `faster-whisper` 拆到可选的 `requirements-transcribe.txt`，避免基础播客安装拉取重型转录依赖。
- LLM 环境变量优先于示例 YAML；摘要全部失败时返回非零状态，不再静默报告成功。

### 改进

- **CI 新增 Windows job**（windows-latest × Python 3.12）：README 明确支持 Windows 用户，编码、路径分隔符、`python`/`python3` 别名类问题现在能在 CI 被抓住。
- CI 的 pytest 步骤去掉 `|| true`，测试失败不再被吞掉。
- 新增安装、路径、文档链接和仓库契约测试，以及 Python 3.10/3.12 CI。

### 文档

- 数据源表（README / AGENTS / CLAUDE）补上代码里实际支持的 daily-watch 降级源：Finnhub / EOD / yfinance（`FINNHUB_API_KEY` / `EOD_API_KEY` / `ENABLE_YFINANCE`）。
- README「30 秒上手」和 SMOKE-TEST 的第一条命令内联标注 Windows 写法（`python` 代替 `python3`），不用翻到故障排查才发现。
- `AGENTS.md` 补上与 `CLAUDE.md` 的双向同步声明（此前只有 CLAUDE.md 单向声明）。
- 日报监控路由行补充 `system/integrations/daily-watchlist.md` 接线说明的入口。

### 移除

- 删除冗余的 `tools/daily-watch/.env.example`（与 `config-examples/daily-watchlist.env.example` 内容重复，安装器和文档都只用后者）。

## 0.3.0 - 2026-06-22

### 新增

- **All-in-One 集成**：pod2wiki（播客/博客摄入）和 daily-watchlist（日报监控）代码合并进 `tools/podcast/` 和 `tools/daily-watch/`，一次 clone 拿到全部六大能力。原始独立 repo 继续存在。
- **screen 快速筛选**（基座能力）：给定主题 → websearch 候选 → 拉数据 → 过滤 → 表格 + Top 5 分析。内置两个预设模板（价值股 / AI 产业链）。无 API 时降级为纯 websearch。
- **Longbridge 数据源**：新增 Longbridge 为默认免费数据源（HK + US 行情），与 tushare（A 股）并列为零成本起步选项。FMP 降为付费可选。（勘误：0.3.1 已更正——Longbridge 是独立 Agent Skill/CLI/MCP 外部扩展，不是日报脚本的内置数据源；FMP 仍为内置可选源。）
- **统一 config/ 目录**：所有工具的用户配置文件统一放在 `config/`（不入 git）。

### 改进

- **README 重写**：从"最小种子 + 槽位"改为"all-in-one 六大能力"。
- **INSTALL 简化**：移除"选模块"步骤，全量安装是唯一路径。
- **ARCHITECTURE 更新**：架构图和目录结构反映 tools/ + 数据源层。
- **AGENTS.md / CLAUDE.md 路由表扩展**：新增 podcast、daily-watch、screen 三条路由。
- **workspace-config 更新**：新增数据源段（Longbridge/tushare/FMP）+ screen 能力 + podcast/daily-watch 内置登记。

### 移除

- `system/skills/deploy-modules.md`（不再需要 clone 外部模块）。
- 文档中"外部模块 clone"流程和相关引导。

## 0.2.4 - 2026-06-22

### 修复

- **INSTALL 路径补上试跑材料**：走 `INSTALL-FOR-AI.md` 安装的用户 `inbox/` 是空的，README「直接试跑」段引用的 `first-note.md` 不存在导致跑不通。现在 Step 2 复制清单包含 `inbox/first-note.md`，两条安装路径都能直接试跑。

## 0.2.3 - 2026-06-07

### 改进

- **active-context 上限与自动清理**：给断点续传协议补上"内联自动剪"。agent 写断点时自检「最近对话延续」段，把**超过 14 天或超过 20 条**的旧条目整行移到 `workspace/meta/active-context-archive-YYYY-MM.md`（保留续接锚点）——零脚本、自动执行、不等手动体检。`structure-health` 的 active-context 检查改为**周度兜底**（万一内联没剪到位才点出来），并对齐归档路径。

## 0.2.2 - 2026-06-07

### 改进

- **active-context 断点续传协议落地**：把"今天停、明天接"做成 agent 自动行为，不再只是格式说明。AGENTS / CLAUDE（含 `system/templates/`）新增「active-context：断点续传」段，写明两条自动触发规则——① 开场说"继续 / 接着 / 昨天"→ 自动读 `active-context.md` 顺着「续接锚点」接上；② 用户说"今天到此 / 明天继续 / 暂停"或工作落盘 / 做决策 / 长对话收尾 → 自动追一行（含状态标签 `PAUSED` / `DONE` / `决策` + 续接锚点）。`active-context.md`（含模板）头部说明与段名同步为 `## 最近对话延续`，README 增加大白话说明。

## 0.2.1 - 2026-06-07

### 改进

- **假设追踪改为基座自带能力**：不再当作"要另装的外部模块"。`hypothesis/` 目录记假设与证据（一假设一 `H*.md`），复盘结论回写 `wiki/explorations/`，开箱即用、零依赖、无需安装。README / AGENTS / CLAUDE / ARCHITECTURE / INSTALL 全量改为「内置」口径。

### 修复

- 移除文档中指向已转为私有的 `hypothesis-tracker` repo 的失效链接，以及"帮我安装假设追踪"的部署引导（deploy-modules 触发词、workspace-config 模块登记、interfaces 契约同步清理）。

## 0.2.0 - 2026-06-07

### 新增

- **research 研究闭环**（基座自带能力，零依赖起步）：输入源 = `wiki/` + websearch + 可选数据源（tushare / gangtise / 自有 API，key 走环境变量）；按研究要点模板输出到 `output/research/`，每条事实标来源（`[本地]` / `[网页]` / `[推测]` / `[待验证]`）；讨论升级后主动提示"是否沉淀进 wiki"，确认后回写 `wiki/explorations/`，形成闭环。见 `system/skills/research.md`。
- **ARCHITECTURE.md**：架构图（基座 + 槽位 + 维护）+ 文件夹结构图 + 完整闭环图。

### 改进

- **结构精简**：把机械零件（`skills/` `integrations/` `scripts/` `interfaces/` `templates/`）统一收进 `system/`，顶层目录 13 → 8，新人一眼能分清"自己读的"和"agent 用的"。
- **防臃肿加固**：`structure-health` 不再把 `status: planned` 模块的未来输出目录误报为"缺失"；`post-install-cleanup` 增加"瘦身后清扫归档样例残留引用"的步骤，避免死链。

### 文档

- README / INSTALL-FOR-AI 全量同步到 `system/` 路径；README 增加「研究闭环」示例段、「最近更新」段，以及「安装到你自己的工作区」段（首次把 `INSTALL-FOR-AI.md` 链进 README）。

## 0.1.0 - 2026-06-06

- Initial Codex-first, Claude-compatible starter workspace.
- Added personal wiki core with `wiki/_schema.md`.
- Added first-ingest smoke test.
- Added PDF ingest smoke path with optional Python + pypdf path.
- Added simple workspace rules in `workspace/workspace-config.md`.

<!-- 文件说明：版本变化记录。 -->
