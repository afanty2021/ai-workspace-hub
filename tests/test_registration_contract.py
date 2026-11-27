"""接线登记契约（2026-11-23 max 评审 r3 修根 B 刀；I-1/I-2 同族第 2 次后的机械兜底）：

① run_archive kind 白名单 ↔ object-model.md `kind` 枚举行全等——11-22 I-2 与
   11-23 I-1 两轮同为「接线新 kind 漏登 object-model」，除 skill checklist ⑥
   （同日新增的人工面）外加机械网。
② 18:25 档两脚本（update_us_liquidity / update_damodaran_erp）的 data/custom
   序列名 ↔ 三文档登记（README / DATA-SOURCES / skill）——11-23 I-2「README
   零同步」系 11-22 I-2 同族第 2 次，硬规则要求修根不止于补丁。

已知限制（与 test_changelog_freshness 限制③同款先例，评审 A 侧人工兜底）：
- 序列自动发现只认两脚本内 `*_SERIES = "..."` 常量命名约定；新脚本或新命名
  约定逃逸发现，须同步扩 PINNED_SERIES。
- cn 侧 update_cn_liquidity 序列按内容名（Shibor/社融/中国 10Y）而非序列 id
  登记，不在本机械网内。
- cron prompt 一致性（checklist ⑥ 的另一半）无可解析本地载体，仍靠人工核对。

变异验证：HUB_REPO_ROOT 指向 /tmp 仓库副本、改副本内文档应红（doc 侧两方向
均验证过：object-model 删 kind → test①红；README 删序列名 → test②红）。
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

# 18:25 档两脚本（同族漏登两次的发生地；cn 侧见模块 docstring 限制）
DISCOVERY_SCRIPTS = ("update_us_liquidity.py", "update_damodaran_erp.py")
# 2026-11-27 起补 update_money_etf_premium.py 两序列（脚本常量名 SERIES_511880/
# SERIES_511990 不匹配 *_SERIES 发现约定，按 docstring 限制钉进 PINNED）
PINNED_SERIES = ("us-rrp-daily", "us-hy-oas", "us-erp-monthly",
                 "cn-money-etf-prem-511880", "cn-money-etf-prem-511990")
DOC_FILES = ("tools/daily-watch/README.md", "DATA-SOURCES.md",
             "system/skills/daily-watch.md")

_KIND_ENUM_RE = re.compile(r"`kind`\s*[^\s：`]+：`([^`]+)`")
_SERIES_CONST_RE = re.compile(r'^[A-Z_]*SERIES\s*=\s*"([a-z0-9][a-z0-9-]*)"', re.M)


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
            if path.exists():
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


if __name__ == "__main__":
    unittest.main()
