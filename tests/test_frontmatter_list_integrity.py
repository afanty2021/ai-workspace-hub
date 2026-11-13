"""frontmatter 列表折叠断言（EXP-08-01 同日两案修根）。

2026-11-13：EXP-20260108-01（实为 EXP-20261108-01）ticker 列表因缩进不一致被
YAML 折叠成单字符串，同日两次（I-1 f273dc4 + 牧原进卡复发）。修根=
rebuild-index / wiki_tagger 读写两侧接 check_list_integrity，折叠即报错。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "system" / "scripts"))
import frontmatter_parse as FM  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "knowledge_lifecycle", REPO_ROOT / "system/scripts/knowledge_lifecycle.py"
)
assert _SPEC and _SPEC.loader
KNOWLEDGE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(KNOWLEDGE)

TAGGER_SPEC = importlib.util.spec_from_file_location(
    "wiki_tagger", REPO_ROOT / "system/scripts/wiki_tagger.py"
)
assert TAGGER_SPEC and TAGGER_SPEC.loader
TAGGER = importlib.util.module_from_spec(TAGGER_SPEC)
# dataclass 处理依赖 sys.modules 里有本模块条目
sys.modules["wiki_tagger"] = TAGGER
TAGGER_SPEC.loader.exec_module(TAGGER)


def write_md(root: Path, name: str, frontmatter: str) -> Path:
    folder = root / "wiki/explorations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"---\n{frontmatter.strip()}\n---\n\n# note\n", encoding="utf-8")
    return path


class CheckListIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_consistent_indent_passes(self) -> None:
        path = write_md(
            self.root,
            "good.md",
            """
id: EXP-1
ticker:
  - 601899.SH
  - 002714.SZ
based_on: [a.md, b.md]
""",
        )
        self.assertEqual(FM.check_list_integrity(path), [])

    def test_mixed_indent_is_flagged(self) -> None:
        # 复刻 2026-11-13 实案：末两项 2 空格、首项列首 0 空格
        path = write_md(
            self.root,
            "bad-indent.md",
            """
id: EXP-2
ticker:
- 601899.SH
  - 688702.SH
  - 002714.SZ
""",
        )
        violations = FM.check_list_integrity(path)
        self.assertEqual(len(violations), 3)  # 两条缩进异常 + 一条折叠指纹
        self.assertIn("缩进 2 与本块首项 0 不一致", violations[0])

    def test_folded_scalar_fingerprint_is_flagged(self) -> None:
        # 复刻折叠结果本身：解析后单项命中「token - token」指纹
        path = write_md(
            self.root,
            "folded.md",
            """
id: EXP-3
ticker:
- 688702.SH - 688981.SH - 002714.SZ
""",
        )
        violations = FM.check_list_integrity(path)
        self.assertEqual(len(violations), 1)
        self.assertIn("折叠指纹", violations[0])
        self.assertIn("ticker", violations[0])

    def test_fold_fingerprint_ignores_natural_language(self) -> None:
        # 概念短语里的空格 + 短横线不应误报（须 token 边界即无空格）
        path = write_md(
            self.root,
            "prose.md",
            """
id: EXP-4
concepts:
- PE-PB 分位分裂
- 单季差分 禁用舍入累计值
""",
        )
        self.assertEqual(FM.check_list_integrity(path), [])

    def test_missing_frontmatter_and_inline_list_pass(self) -> None:
        plain = self.root / "plain.md"
        plain.write_text("# no frontmatter\n", encoding="utf-8")
        self.assertEqual(FM.check_list_integrity(plain), [])
        inline = write_md(
            self.root, "inline.md", "id: EXP-5\nticker: [601899.SH, 002714.SZ]\n"
        )
        self.assertEqual(FM.check_list_integrity(inline), [])


class RebuildIndexGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_rebuild_blocked_by_folded_list(self) -> None:
        write_md(
            self.root,
            "broken.md",
            """
id: EXP-20261113-09
type: exploration
title: t
status: tentative
summary: s
based_on:
- a.md
  - b.md
""",
        )
        results = KNOWLEDGE.rebuild_indexes(self.root, apply=True)
        self.assertTrue(
            any(item.get("type") == "frontmatter_list_violations" for item in results)
        )
        # 索引不得在缺项元数据上重建
        self.assertFalse((self.root / "wiki/explorations/_index.md").exists())

    def test_rebuild_passes_on_clean_pages(self) -> None:
        write_md(
            self.root,
            "clean.md",
            """
id: EXP-20261113-10
type: exploration
title: t
status: tentative
summary: s
based_on:
- a.md
- b.md
""",
        )
        results = KNOWLEDGE.rebuild_indexes(self.root, apply=True)
        self.assertFalse(
            any(item.get("type") == "frontmatter_list_violations" for item in results)
        )


class TaggerGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_tagger_refuses_pre_folded_file(self) -> None:
        path = write_md(
            self.root,
            "entity.md",
            """
title: x
type: entity
ticker:
- 601899.SH
  - 002714.SZ
""",
        )
        with self.assertRaises(TAGGER.TaggingError) as ctx:
            TAGGER.tag_file(path, root=self.root, apply=True, chat_func=None)  # type: ignore[arg-type]
        self.assertIn("已折叠", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
