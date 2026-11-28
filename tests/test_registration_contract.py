"""接线登记契约（2026-11-23 max 评审 r3 修根 B 刀；I-1/I-2 同族第 2 次后的机械兜底）：

① run_archive kind 白名单 ↔ object-model.md `kind` 枚举行全等——11-22 I-2 与
   11-23 I-1 两轮同为「接线新 kind 漏登 object-model」，除 skill checklist ⑥
   （同日新增的人工面）外加机械网。
② 18:25 档两脚本（update_us_liquidity / update_damodaran_erp）+ 18:10 链内
   update_money_etf_premium 的 data/custom 序列名 ↔ 三文档登记（README /
   DATA-SOURCES / skill）——11-23 I-2「README 零同步」系 11-22 I-2 同族第 2
   次，硬规则要求修根不止于补丁。2026-11-28 评审：发现约定放宽为「以 SERIES
   结尾的大写常量」（原 [A-Z_]*SERIES 不容数字，PREM_511880_SERIES 型名字
   逃逸发现靠手工 PINNED；ump 常量已按约定改名，DISCOVERY 扩第三脚本）。
③ 关键事实值锁（2026-11-28 评审 I-10 新增）：四处同源行（AGENTS/CLAUDE +
   system/templates 双模板）的触发线数值与代码常量对拍——原 token 级存在性
   断言对「四处一起改事实」（D08：<-5bp 漂到 <-3bp）全绿，点锁不是面锁。

已知限制（与 test_changelog_freshness 限制③同款先例，评审 A 侧人工兜底）：
- 序列自动发现只认脚本内「以 SERIES 结尾的大写常量 = 序列 id」命名约定；
  新脚本或新命名约定逃逸发现，须同步扩 DISCOVERY_SCRIPTS / PINNED_SERIES。
- cn 侧 update_cn_liquidity 序列按内容名（Shibor/社融/中国 10Y）而非序列 id
  登记，不在本机械网内。
- cron prompt 一致性（checklist ⑥ 的另一半）无可解析本地载体，仍靠人工核对
  （skill checklist ⑥ 已改为点名三份 prompt + 列 kind 名去计数词）。

变异验证：HUB_REPO_ROOT 指向 /tmp 仓库副本、改副本内文档应红（doc 侧两方向
均验证过：object-model 删 kind → test①红；README 删序列名 → test②红；
2026-11-28：AGENTS/CLAUDE 触发线数值漂移 → test③红，四处同改事实同红）。
2026-11-28 评审 B-I7 修根：网自身配置原无自保护——发现正则回退旧约定、清单
缩减、事实值文档集缩水，全量均绿（9 发变异全零锁）。NetSelfCheckTests 把
三份清单与字面量元组对拍、发现集 ⊇ 已接线序列字面量（首发即抓到 us-rrp-daily
常量名裸 SERIES 逃逸发现）、发现脚本缺失即红。
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

import _test_paths  # noqa: F401  （tools/daily-watch/scripts 上 sys.path）
import batch_ledger

ROOT = Path(os.environ.get("HUB_REPO_ROOT",
                           Path(__file__).resolve().parents[1]))

# data/custom 序列发现脚本（18:25 档两脚本 + 18:10 第 4 条链内货币ETF +
# us-321-crack 手工档裂解价差（2026-11-28 接线 Q-20261128-04）；
# cn 侧 update_cn_liquidity 见模块 docstring 限制）
DISCOVERY_SCRIPTS = ("update_us_liquidity.py", "update_damodaran_erp.py",
                     "update_money_etf_premium.py", "update_crack_spread.py")
# 命名约定逃逸时的手工钉入位（当前为空——ump 常量已按约定改名）
PINNED_SERIES: tuple[str, ...] = ()
DOC_FILES = ("tools/daily-watch/README.md", "DATA-SOURCES.md",
             "system/skills/daily-watch.md")

_KIND_ENUM_RE = re.compile(r"`kind`\s*[^\s：`]+：`([^`]+)`")
_SERIES_CONST_RE = re.compile(
    r'^[A-Z][A-Z0-9_]*SERIES\s*=\s*"([a-z0-9][a-z0-9-]*)"', re.M)

# 事实值锁（I-10）：四处同源行所在文件——触发线数值以 ump 常量为真值来源
FACT_VALUE_DOCS = ("AGENTS.md", "CLAUDE.md",
                   "system/templates/AGENTS.md", "system/templates/CLAUDE.md")


class KindEnumContractTests(unittest.TestCase):
    def test_object_model_kind_enum_equals_run_archive_kinds(self) -> None:
        doc = ROOT / "system" / "integrations" / "object-model.md"
        m = _KIND_ENUM_RE.search(doc.read_text(encoding="utf-8"))
        self.assertIsNotNone(
            m, "object-model.md 找不到 `kind` 枚举行——漏登或格式漂移")
        doc_kinds = {k.strip() for k in m.group(1).split("/")}
        kinds = set(batch_ledger._load_run_archive().KINDS)  # 生产同款加载路径
        self.assertEqual(
            doc_kinds, kinds,
            f"object-model kind 枚举与 run_archive.KINDS 漂移（skill 文档同步硬规则⑥）："
            f"只在文档={sorted(doc_kinds - kinds)} 只在代码={sorted(kinds - doc_kinds)}")


class SeriesRegistrationContractTests(unittest.TestCase):
    def _discovered(self) -> set[str]:
        names: set[str] = set()
        for fname in DISCOVERY_SCRIPTS:
            path = ROOT / "tools" / "daily-watch" / "scripts" / fname
            # B-I7：发现脚本缺失=配置漂移，直接 fail（原静默跳过=网可被整体关掉）
            self.assertTrue(path.exists(), f"发现脚本不存在（路径漂移？）: {fname}")
            names |= set(_SERIES_CONST_RE.findall(
                path.read_text(encoding="utf-8")))
        return names

    def test_1825_series_registered_in_three_docs(self) -> None:
        missing: dict[str, list[str]] = {}
        for name in sorted(self._discovered() | set(PINNED_SERIES)):
            for doc in DOC_FILES:
                path = ROOT / doc
                self.assertTrue(path.exists(), f"{doc} 不存在（路径漂移？）")
                if name not in path.read_text(encoding="utf-8"):
                    missing.setdefault(name, []).append(doc)
        self.assertEqual(
            missing, {},
            f"18:25 档序列未按 checklist ①②③ 落三文档：{missing}")


class NetSelfCheckTests(unittest.TestCase):
    """登记网自身配置的自保护（2026-11-28 评审 B-I7）：改测试自身 9 发变异
    全零锁——发现正则回退、清单缩减、事实值文档集缩水全量均绿。本组把配置
    钉进字面量：改网先红在这里。"""

    def test_config_lists_locked_by_literals(self) -> None:
        self.assertEqual(DISCOVERY_SCRIPTS,
                         ("update_us_liquidity.py", "update_damodaran_erp.py",
                          "update_money_etf_premium.py", "update_crack_spread.py"))
        self.assertEqual(DOC_FILES,
                         ("tools/daily-watch/README.md", "DATA-SOURCES.md",
                          "system/skills/daily-watch.md"))
        self.assertEqual(FACT_VALUE_DOCS,
                         ("AGENTS.md", "CLAUDE.md",
                          "system/templates/AGENTS.md", "system/templates/CLAUDE.md"))
        self.assertEqual(PINNED_SERIES, ())

    def test_discovered_covers_all_wired_series(self) -> None:
        # ⊇ 已接线序列字面量：命名约定逃逸（如裸 SERIES 常量）在此先行暴露
        discovered = SeriesRegistrationContractTests()._discovered()
        required = {"us-rrp-daily", "us-hy-oas", "us-erp-monthly",
                    "us-321-crack", "cn-money-etf-prem-511880",
                    "cn-money-etf-prem-511990"}
        self.assertTrue(required <= discovered,
                        f"已接线序列逃逸发现约定（须改常量名或钉入 PINNED_SERIES）："
                        f"{sorted(required - discovered)}")


class FactValueContractTests(unittest.TestCase):
    """关键事实值锁（2026-11-28 评审 I-10，B 席 D08 判例）：四处同源行「一起
    改事实」（触发线 <-5bp 漂到 <-3bp）原全绿——存在性断言不锁值。本组把
    触发线数值锚到代码常量：文档漂移或代码漂移任一方向都红。
    B-M8 扩面（同行其余事实原不在锁内）：毒行阈值 ±200bp 四处一起改成 ±50bp、
    「方向不明」第三分支整段删除，原全量绿——同源行关键数值/分支一并入锁。
    needle 一律锚「数值/分支 token」而非整句格式（同源行允许转义竖线等排版
    差异，D-M1 修根后 `|溢价|` 带反斜杠不碍值锁）。"""

    @staticmethod
    def _needles() -> list[str]:
        import update_money_etf_premium as ump
        days = str(ump.CONSEC_DAYS)
        thresh = f"{abs(ump.ALERT_THRESH_BP):g}"
        return [
            f"连续 {days} 日 <-{thresh}bp 且双基金同向",       # 触发线（I-10）
            f"±{ump.POISON_PREM_BP:g}bp",                     # 毒行阈值（B-M8/D-E10）
            "方向不明",                                       # 第三分支（B-M8/D-E11）
            f"P5={ump.BASELINE_P5_BP:+.1f}bp",                # 基线（B-M8 同行事实）
            f"P95={ump.BASELINE_P95_BP:+.1f}bp",
        ]

    def test_trigger_line_value_locked_in_four_entrypoint_docs(self) -> None:
        needles = self._needles()
        for doc in FACT_VALUE_DOCS:
            path = ROOT / doc
            self.assertTrue(path.exists(), f"{doc} 不存在（路径漂移？）")
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                self.assertIn(needle, text,
                              f"{doc} 事实值与代码常量漂移（期望 {needle}）"
                              "——四处同源行一起改也须同步改代码")
            # 空壳形态不可过：核心语义 token 被掏空（只留序列名）即红
            self.assertIn("双基金同向", text, f"{doc} 触发语义句被掏空")
            self.assertIn("risk-off", text, f"{doc} 性质标注句被掏空")

    def test_trigger_threshold_matches_code(self) -> None:
        # 代码侧反向锚：常量被误改（如 -3.0）而四处文档没跟 → 本组也红
        import update_money_etf_premium as ump
        self.assertEqual(ump.ALERT_THRESH_BP, -5.0,
                         "触发线阈值漂移须四处同源行+skill+CHANGELOG 同步")
        self.assertEqual(ump.CONSEC_DAYS, 2)


if __name__ == "__main__":
    unittest.main()
