# Changelog

## Unreleased

### 新增

- planted 多种子校准 `calibrate` 子命令（2026-11-25，Q-20261125-02 用户拍板「升格」当日落地）：`synth.py` 三市场构造器加强度参数与种子偏移（`event_market_tickers(bounce=,mom_coef=,seed_shift=)`、`noise_market_tickers(seed_shift=)`、`write_sr_market(mom_coef=,seed_shift=)`；None 哨兵读模块常数保测试 monkeypatch，出厂默认逐字节等价——配对结构与票码不变）+ `run_check.py calibrate`——对照侧 `--n-markets`（默认 50）个独立噪声市场（种子偏移 1000·k，k≥1：0 号市场是回归阈值标定种子，不算独立抽样，避免「标定集上测误报」的循环论证）按出厂对照判据统计实测误报率（jinniu 接线核对逐市场照跑，读错臂即抛、校准统计作废）；埋边侧边强度 5 档（反弹注入 0.2%~1.0%/日、动量系数 0.05~0.25）×`--edge-seeds`（默认 3）测检出率并逐条判据报通过率（看哪条在弱边上先掉）；`--calib-targets` 子集、`--out-json` 落逐市场原始读数。**测量工具不是闸门**（exit 恒 0、不进单测，queue 原议）；README 新增「多种子校准」节（口径声明=合成市场率不直接等于真实率）。首次全量实测（50 市场×5 档×3 种子，n_perm=1000，`data/planted-benchmark/calib-20261125.json`）：event 双臂联合误报 10%（chuji 1/50、jinniu 4/50；2σ 名义 ≈5%/臂），检出边界 bounce ≥0.8%/日全过、0.6% 2/3（t 判据先掉）、≤0.4% 0/3；sr 六格全过 0/50、逐格 vs随机 5/50=10% 与名义 α 精确吻合、其余格 ≤1/50、mom_coef ≥0.10 全检出（0.05 已 2/3）；rps 价差腿 9/50=**18%**（对照侧最松、与弱边上 binding 同源）、去重叠 t 腿 1/50、双判据干净 41/50、检出边界 mom_coef ≥0.10；**naive 重叠 t 36/50=72% 纯噪声过 2 vs 去重叠 1/50**（|t| 中位 3.5 vs 0.8、90 分位 7.3 vs 1.5）=√20 膨胀的多种子实证（Q-20261125-05 定量注脚）。planted 59 用例全绿。

- planted 合成对照检查 `tools/planted-benchmark/`（2026-11-25，借鉴 Allencake/mit-trader-skill 的 `--planted`；范围与定位用户未答，按推荐先行**待追认** Q-20261125-01）：**定位=固定种子回归基线（单实现、非校准）**——合成市场里埋已知尺寸的边，配一个同种子、只差边项的对照市场，把真实验证管道跑在上面，程序化判定「埋边被检出 / 对照沉默 / 样本不足」，用途是防回归。它不回答误报率，也不回答多弱的边检得出，「量具正常」不等于该管道的历史负结果都可信。覆盖三条管道的部分部件（清单见 README「未覆盖部件」）：SR 检验矩阵 3 行×2 档、stage-bottom chuji 臂、jinniu buy 臂（只判阴性）、rps 臂 A/C。构成：`synth.py`（59 只合成票=12 反弹边+12 动量边+35 噪声，代码取真实缓存空闲的 609xxx/309xxx 段；写守卫 `guard_root`——合成数据只能落 `data/planted-benchmark/` 或仓库 `data/` 之外，`write_cache` 拒绝非本模块产出的 jsonl）+ `run_check.py`（`sr|event|rps|all`；`--strict` 把管道契约注记算失败；`--real-bundle` 只读报真实 RPS 数据上的两种 t）+ README。出厂市场读数（n_perm=1000）：SR 埋边宇宙六格 p=0.001、对照宇宙六格过一格；chuji 臂 h=5 alpha +1.44%/t 8.2（对照 +0.03%/t 0.3）；jinniu 点火与注入窗富集比 0.97、阳性未验证；rps D9−D0 +16.5pp、去重叠 t 8.65（对照 +0.32pp/t 0.02）。对现有管道零修改。检查顺带报出三处既有管道与自身口径不符（只报不改，均挂 review-queue）：①事件研究 `event_returns` 的停牌过滤拿 YYYYMMDD 整数差当天数，前瞻窗跨月的样本被误删（零停牌合成市场 h=5 保留率 72.4%；真实 600519.SH 应剔 4 个实剔 1039 个）②`validity.py` 臂 C 的 RankIC t 是重叠窗口径（真实 bundle RPS250 naive −16.27 / 去重叠 −3.98）③`rps_core` 上市年数门槛实际 500 根而非 docstring 的 250 根。run-log kind 不扩、不开 EXP/R 卡。1001 绿（planted 59 用例，变异 33 发全红）。
- 盘前档第零步自检 d 项（2026-11-24，Q-20261124-01；本条为登记补记——2026-11-25 max 评审 r4 B-I-1 查出当时漏记）：08:00 盘前日报第零步扩「盘前档自身完整性」——上一交易日 kind=watch open 行应 ≥2 笔（盘前+收盘各一）且上一交易日 `-premarket.md` 存在，缺失出红色警告；CronUpdate automation-c2895bd5 同步；`system/skills/daily-watch.md` 新增「盘前档第零步自检」节作同步副本。设计边界：08:00 档自身失败当晨不可自见，由下一交易日 08:00 档检出（首案 2026-11-24 turn 6 秒 failed，11:00 补跑闭环）。文档与 cron 改动，无代码变更。
- 达摩达兰标普500隐含 ERP 月度通路（2026-11-23，Q-20261123-05；同日查证属实后用户拍板「接线」）：新建 `update_damodaran_erp.py`——NYU Stern `Damodaran 官方 ERPbymonth.xlsx` 固定文件名整本全量拉取（他本人每月初更新、本档每日幂等拉自动捕获；**表头名定位列防 schema 漂移**，缺表/缺主列拒绝解析；ERP(T12m) 主值存 %、SP/TB/sust/ER 上下文进 note；幂等+batch-damodaran-erp 账本两行制，run_archive kind 白名单扩十二值）+ 18:25 档 cron 双命令化（顺带补登 Q-20261123-04 HY OAS 未入 cron prompt 的缺口；ERP 失败非零但只警告不影响流动性主档判读，连续 7 天失败才 friction-log）+ 日报宏观段 `{ERP_SECTION}` 自动渲染（最新月读数+2008-09 起历史分位「N 个月中仅 M 个月更低」+陈旧 45 天标注，零网络只读本地序列，失败降级一行）。首拉 218 行（2008-09→2026-11-01），11-01=3.79% 与主页快照逐位一致=218 个月最低档（中位 5.25%/2022-10 峰 6.21%）——要价温度计只记读数不作灯（清单预注册纪律之外，不设阈值）；12-01 月读=11-20 崩盘后首读且在 12-09 FOMC 前窗。登记：skill 运行账本+18:25 档、AGENTS/CLAUDE 数据源行+system/templates 双镜像同步、DATA-SOURCES。926 绿（+14 用例）。
- 科技回补三灯清单接线五项（2026-11-23，Q-20261123-04「做」；清单 v1.0=`workspace/monitoring/tech-reentry-three-lights.md`，用户三信号框架同日评审修订后拍板）：① 新建 `three_lights.py`（本地序列只读计算灯1a 美元 60 日新高止步/1b 利率 20 日新高止步∧不收复 5.12/1c HY OAS 380bp×2 日否决/1d RV20 年化 %<30×5 日/灯2 黄金完整周收 ≥3534.64 贴线标注/灯3 IXIC+SOX 21EMA 走平·站稳·8/21 金叉，today 注入防时间炸弹）+ 日报模板 `{THREE_LIGHTS_SECTION}` 段（零网络，失败降级一行提示不炸日报）+ 四灯总览行与 FedWatch/BTC 两人工槽位（③④补读程序入清单读数窗段）；② `update_us_liquidity.py` 扩双系列——`us-hy-oas`（FRED BAMLH0A0HYM2，% ×100 存 bp，cosd 限窗，单源无降级链；失败告警+missing 不阻塞 RRP 不置非零，降级语义同社融；18:25 档 cron 自动带上）；⑤ NDX-100 vs COMP 一次性对拍（Nasdaq 官方双序列 79 交易日：日收益相关 0.9877/同向 91.0%/崩盘三日差 ≤0.33pp/同峰同破位）回填清单 3a 注记判定等价。接线过程中冒烟抓获 fast/slow EMA 种子错位 13 根 bar 的金叉误判（崩盘死叉被报成金叉 23 日前）当日修复+回归测试。912 绿（+28 用例）。HY OAS 首拉 358 行，11-19=352.0bp 与 11-22 衰退判定读数逐位一致。
- 账本 verify 全净收口 + CHANGELOG 记账纪律契约（2026-11-22，Q-20261122-02）：① 7 条存量 undeclared 按两步 amend 补账——11-12/11-18 日报盘后评审补记句（C-1 影子序列勘误/HG00Y「同日已修根」注记）、`data/market/series/000300.jsonl` 产物消亡收口（裸码影子序列修根后权威迁 `data/index/series/000300.jsonl` 核心指数管道）、4 张 11-16 mover 证据卡 11-18 用户确认句（Q-20261118-01③）——复检 verify 全部干净；② CHANGELOG 系统性滞后双修根——skill「文档同步 checklist」扩第五点（CHANGELOG Unreleased 增量条目）+ 新契约测试 `tests/test_changelog_freshness.py`（CHANGELOG 末次提交后不允许 tools/system 非 md 代码的 feat/fix 零条目；5 合成形态例+真实仓库集成例，集成例当场抓获 32a7870 滞后即本条目补记的变异证明）。
- Fed 一手源三项接线（2026-11-22，Q-20261122-01「做缺的一半」）：① 美元 ON RRP 每日用量序列——新建 `update_us_liquidity.py`（主源 NY Fed markets API 桌面操作一手数据，**日期参数须带连字符、紧凑格式 HTTP 400**；备份 FRED RRPONTSYD，双源 2026-11-20 对拍逐位一致；幂等 + batch-us-liquidity 账本两行制，run_archive kind 白名单扩为十一值）+ 每日 18:25 独立档 cron（不并 18:10 批量档）+ 盘前自检 open 组四组扩五组；② 两房 P&I 付息窗口（每月 15-25 日，机制 FOMC20150723memo02 p5，日历界为运维近似）日报跨资产段自动标注；③ research_preflight context 命中 Fed/美元流动性词时输出「Fed 一手源」入口段（机制层作真锚、观点层与卖方同级）。同批 max 评审（0C/2I/6M）补漏：object-model kind 十一值同步、run_archive 两处「十值」文案、工具 README 数据源行与 CLI 示例、账本记源改「实际写入才记源」（全 skip/FRED 降级不虚记）。
- 持久化层追加交易所核心指数（2026-11-03 用户拍板，spec v0.3c）：`update_market_series.py --scope indices`（并入 all，固定清单 8 个：上证指数/上证50/沪深300/中证500/中证1000/科创50/深证成指/创业板指），落 `data/index/series/{裸6位}.jsonl`（source=mootdx-index，`last_indices_round` per-scope 完成标记，与 stocks/sectors 闸门隔离）；query_market 加 `index_series` 视图、裸 000/399 段路由指数、88 段仍走板块；北证50 899050 不收（mootdx 按 89 前缀路由 SZ 而 BSE 是 market=2，同样到不了，维持排除 BSE）。同批：`--force` 绕过闸门与逐票 skip 强制重拉（历史回补/盘中数据修正场景，friction 第 2 次触发修根；**盘中执行会把动态 bar 当收盘写并推进完成标记，收盘后须再跑一次 --force 修正**），17 只 watchlist 票 30 行缺口已用其回补至 800 行。

### 修复

- `event_returns` 停牌跳空过滤跨月误删修根 + 全市场重跑勘误（2026-11-25，Q-20261125-04 用户拍板当日闭环；planted 接线核对独立重数对不上暴露，与 11-10 年化 `/10000` 同族第 2 次→friction 硬规则当日修根）：三处同写法一并改历法日（stage-bottom `run_backtest.py` `civil_days`、jinniu `run_backtest.py` `_days_from_civil`、`sleeve.py` U4 同修）——原 `di[nxt]-di[idx] <= gap` 跨月 1201−1130=71>10 把跨月前瞻窗全当停牌误删，真实 600519.SH 应剔 4 个实剔 1039 个、修后逐位对上 queue 记载。全市场 7 脚本+3 池臂重跑（池=36 票重建名单：config 行内入池日期注记+queue 拍板记录逐票回溯，指纹与 11-10 原跑逐位吻合，名单落档 R20261110-01 勘误②），六文件勘误全量同步（R20261110-01+EXP-20261110-01、R20261109-04+EXP-20261109-05、R20261110-04+EXP-20261110-03；正文表格全量替换消除新旧并存、EXP 卡 summary/复审记录/updated_at 同步、不受影响段落显式注记）。**结论面变化如实记录**：KD 金叉 h10 由正转负（−15.5bp t=−17.7，反方证据撤销）、优化层 ADX>67 三窗全过降级两窗过（h20 OOS 仍过 lift ×1.6）、jinniu 全市场交替持仓由「打平 −0.05pp」变「+0.57pp（t=4.2）=负漂移宇宙少持仓躲跌假象」（池依赖主叙事更干净：池日线 −7.51pp t=−4.8、毛收益都输不变）、买入「3-10 日短动量」消失大半（正漂移只剩 h=3~5 的 2-4bp）。planted `event_filter_retention` 合成市场保留率 72.4%→**100.0%**，指标转为该修法回归哨兵；一处过时测试断言同步（修后出厂无契约注记，`--strict` 恢复 exit 0，注记触发路径另有用例守）。
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
