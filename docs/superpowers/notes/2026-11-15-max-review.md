# 2026-11-15 今日变更 max 评审报告

- **范围**：`fb9fa6c..0ed8041` 五笔（全部 2026-11-15、未推送）——25aba3e 伊利+蒙牛双票观察行 / a0f7637 EXP-08-01 第九形态第五源进卡 / 0a97225 春风（并行会话）/ 4655595 伟星 / 0ed8041 浔兴（伟星同链对照批）。
- **结论**：**0 Critical / 0 Important / 5 Minor + 3 建议**。判定 Ready to push。M-1/M-2/M-3 + Rec-1 当日修复（21ab398 + 5aa1bc9 + entity 本地修），遗留三项决策挂 Q-20261115-06。

## Strengths（择要）

1. **YAML 完整性全过**：EXP-08-01 frontmatter 三字段 based_on/ticker/entity_salience 各 19 项独立解析无折叠，ticker 全 str，`600887.SH: core` 在位，无 `related`（停用规则遵守）；5 个 entity 文件齐全，002003/002098 裸零码原文带引号（八进制陷阱免疫），002003↔002098 双向互链在位。
2. **数字回源对拍零偏差**：伊利 EXP 坐标行 13+ 数字与报告逐位一致；春风/伟星/浔兴/蒙牛四组抽检全部命中报告原文。
3. **算术自洽**：DPS 1.19（隐含 63.2 亿股与报告 0.42 元=26.56 亿锚互证）、~77% 守 1.22、PB p50 3.22×BPS 8.99≈28.9 元均成立。
4. **工具链全绿**：workspace_status 账本三查 OK；rebuild-index dry-run 三索引 no-op（a0f7637 幂等声称至今成立）；_index 行逐字含卡 summary；契约+frontmatter+append 32 测试通过；模板静态部分 diff 零（本批纯行追加，同步不触发）。
5. **append_frontmatter bug 声明属实**：评审在 /tmp 独立复现（多 --list 同 call → 全部 --item 归属末字段），friction-log 五要素齐全，后续 Q-04/Q-05 互链确实改用单字段调用=规避纪律被执行。
6. **Message↔diff 逐笔诚实**：4655595 确实仅伟星行、0a97225 仅春风行（hunk 级确认）；queue Q-20261115-01..05 全 done 与 commit 声明吻合。

## Issues 与处置

### Critical / Important

无。

### Minor（5 条）

| # | 发现 | 处置 |
|---|---|---|
| M-1 | 浔兴行触发器压缩为 T1/T2，message 与报告均 T1-T6，message↔行不对称 | **已修**（21ab398）：行尾补 T3-T6 全列 |
| M-2 | 蒙牛行「27E +8~11%」上界无源（报告 26E 50.08-50.96 亿×27E 55 亿=+7.9~+9.8%） | **已修**（21ab398）：改 +8~10% 并回源标注 |
| M-3 | 「谱系最薄档」同日双持：2319.md（+0.62pp，09:26 写）与 002098.md（+0.46pp，10:16 写）均自称最薄；2319.md 两处在 **live 段**（估值读数+裁决），非 dated 日志 | **已修**（本地，entity gitignore 不入库）：2319.md 两处改「次薄档」+dated 注记（「2026-11-15 建档时为最薄档，同日浔兴 +0.46pp 入谱系后垫底」）；profile 两行 dated 观察不改史（浔兴行已自带正确排序） |
| M-4 | entity ticker 裸码/带后缀混用（全库 40 裸/71 带后缀，000807 两形态并存）——既有方差非本批引入 | 挂 Q-20261115-06 ①待拍板（库级卫生立项+tagger scan 规则） |
| M-5 | 带内压缩两处：拉链毛利率差 ~13pp（报告口径 10-13pp，取拉链对拉链 Q3 可辩护）；妙可蓝多 36.63%（报告另注 2026 最新 37.89%，两数同在报告内） | 不修——同源内口径选择非错误；下次引用妙可蓝多时优先 37.89% 最新数 |

### 建议（3 条）

1. append_frontmatter `--help` 顶部加「多 --list/--map 字段禁止同 call」提示 → **已落地**（5aa1bc9，docstring 已知坑段；13 用例绿；配对逻辑修复仍按 friction 闸门挂起待第 2 次复发）。
2. ticker 统一 → 挂 Q-20261115-06 ①。
3. 观察行触发器格式统一（T 编号 vs 散文）→ 挂 Q-20261115-06 ③。

### 工作区惯例层面观察（与本批无关）

`system/templates/research-profile.md` 内嵌 53 条真实观察行（止于第 61 次），实例已 66 条——契约测试只比静态部分所以合法，但「模板含使用数据」是历史 cp 同步产物；若模板定位是干净脚手架，可择机清空观察段 → 挂 Q-20261115-06 ②。

## 验证台账

评审员 20 项验证全过（diff 对账×5、PyYAML 独立解析×6、数字回源 grep×4 组、算术×1、workspace_status、rebuild-index dry-run no-op、_index 逐字包含、pytest 32 绿、preflight 时序戳、queue/friction-log 闭环、based_on 19 路径存在、模板静态 diff、工作树干净）。修复后复验：32 测试绿 + 账本三查 OK（20 序号/58 行，in-place 编辑不扰动）。

## 修复记录

| 修复 | 落点 | SHA |
|---|---|---|
| M-1+M-2 | workspace/research-profile.md | 21ab398 |
| M-3 | wiki/entities/2319.md（本地，gitignore） | 无 commit（entity 惯例） |
| Rec-1 | system/scripts/append_frontmatter.py | 5aa1bc9 |
| 遗留决策 | workspace/review-queue.md Q-20261115-06（pending） | 本地 |

**Ready to push? Yes**（五笔原始提交 + 两笔修复提交，共 7 笔待推送）。
