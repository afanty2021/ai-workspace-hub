"""append_frontmatter 工具测试（EXP-08-01 修根第②件：替代手工 Edit 列表）。"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "system" / "scripts"))
import yaml  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "append_frontmatter", REPO_ROOT / "system/scripts/append_frontmatter.py"
)
assert _SPEC and _SPEC.loader
APPEND = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(APPEND)


def write(tmp: Path, name: str, frontmatter: str, body: str = "# note\n") -> Path:
    path = tmp / name
    path.write_text(f"---\n{frontmatter.strip()}\n---\n\n{body}", encoding="utf-8")
    return path


def meta(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8").split("---")[1]
    return yaml.safe_load(raw)


class AppendListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_to_indented_list_keeps_style_and_count(self) -> None:
        path = write(
            self.root,
            "a.md",
            """
id: E1
ticker:
  - 601899.SH
  - 600660.SH
related:
  - '[[601899]]'
""",
        )
        result = APPEND.append_to_file(path, list_field="ticker", items=["002714.SZ"])
        self.assertTrue(result["written"])
        m = meta(path)
        self.assertEqual(m["ticker"], ["601899.SH", "600660.SH", "002714.SZ"])
        # 新项继承本块 2 缩进
        self.assertIn("  - 002714.SZ", path.read_text(encoding="utf-8"))
        # 其他字段不受影响
        self.assertEqual(m["related"], ["[[601899]]"])

    def test_append_to_zero_indent_list(self) -> None:
        path = write(
            self.root,
            "b.md",
            "id: E2\nbased_on:\n- a.md\n- b.md\n",
        )
        APPEND.append_to_file(path, list_field="based_on", items=["c.md"])
        m = meta(path)
        self.assertEqual(m["based_on"], ["a.md", "b.md", "c.md"])
        self.assertIn("\n- c.md", path.read_text(encoding="utf-8"))

    def test_idempotent_skip_existing(self) -> None:
        path = write(self.root, "c.md", "id: E3\nticker:\n- 601899.SH\n")
        result = APPEND.append_to_file(path, list_field="ticker", items=["601899.SH"])
        self.assertFalse(result["written"])
        self.assertEqual(meta(path)["ticker"], ["601899.SH"])

    def test_new_field_created_at_zero_indent(self) -> None:
        path = write(self.root, "d.md", "id: E4\ntitle: t\n")
        APPEND.append_to_file(path, list_field="concepts", items=["双分位镜像"])
        m = meta(path)
        self.assertEqual(m["concepts"], ["双分位镜像"])

    def test_inline_list_converted_to_block(self) -> None:
        path = write(self.root, "e.md", "id: E5\nticker: [601899.SH, 600660.SH]\n")
        APPEND.append_to_file(path, list_field="ticker", items=["002714.SZ"])
        m = meta(path)
        self.assertEqual(m["ticker"], ["601899.SH", "600660.SH", "002714.SZ"])

    def test_scalar_field_refused(self) -> None:
        path = write(self.root, "f.md", "id: E6\nticker: 601899.SH\n")
        with self.assertRaises(SystemExit):
            APPEND.append_to_file(path, list_field="ticker", items=["002714.SZ"])

    def test_dry_run_writes_nothing(self) -> None:
        path = write(self.root, "g.md", "id: E7\nticker:\n- 601899.SH\n")
        before = path.read_text(encoding="utf-8")
        result = APPEND.append_to_file(
            path, list_field="ticker", items=["002714.SZ"], dry_run=True
        )
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertFalse(result["written"])


class AppendMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_nested_mapping_entry(self) -> None:
        path = write(
            self.root,
            "h.md",
            "id: E8\nentity_salience:\n  601899.SH: core\ntags:\n- a\n",
        )
        result = APPEND.append_to_file(
            path, map_field="entity_salience", entries=[("002714.SZ", "core")]
        )
        self.assertTrue(result["written"])
        m = meta(path)
        self.assertEqual(
            m["entity_salience"], {"601899.SH": "core", "002714.SZ": "core"}
        )
        self.assertEqual(m["tags"], ["a"])

    def test_map_skip_existing_key(self) -> None:
        path = write(
            self.root, "i.md", "id: E9\nentity_salience:\n  601899.SH: core\n"
        )
        result = APPEND.append_to_file(
            path, map_field="entity_salience", entries=[("601899.SH", "mention")]
        )
        self.assertFalse(result["written"])
        self.assertEqual(meta(path)["entity_salience"], {"601899.SH": "core"})


if __name__ == "__main__":
    unittest.main()


class RendererAndEncodingTests(unittest.TestCase):
    """评审 I-2/I-3 + --entry 可重复（2026-11-13 max 评审当日尾批）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_special_yaml_chars_quoted_stay_str(self) -> None:
        path = write(
            self.root,
            "q.md",
            """
id: E1
concepts:
- 双高型战略溢价定价
""",
        )
        APPEND.append_to_file(
            path,
            list_field="concepts",
            items=["a: b", "[x]", "*ref", "#注释", "分位差 >40pct 时（分裂）"],
        )
        m = meta(path)
        tail = m["concepts"][1:]
        self.assertTrue(all(isinstance(c, str) for c in tail))
        self.assertIn("a: b", tail)
        self.assertIn("[x]", tail)
        self.assertIn("*ref", tail)
        self.assertIn("#注释", tail)

    def test_repeatable_map_entries_all_applied(self) -> None:
        path = write(
            self.root,
            "m.md",
            """
id: E1
entity_salience:
  601899.SH: core
""",
        )
        result = APPEND.append_to_file(
            path,
            map_field="entity_salience",
            entries=[("000333.SZ", "core"), ("600900.SH", "core")],
        )
        self.assertEqual(len(result["applied"]), 2)
        self.assertEqual(
            meta(path)["entity_salience"],
            {"601899.SH": "core", "000333.SZ": "core", "600900.SH": "core"},
        )

    def test_bom_and_crlf_preserved(self) -> None:
        path = self.root / "bom.md"
        path.write_bytes(
            b"\xef\xbb\xbf"
            + "---\r\nid: E1\r\nticker:\r\n- 601899.SH\r\n---\r\n\r\n# note\r\n".encode(
                "utf-8"
            )
        )
        APPEND.append_to_file(path, list_field="ticker", items=["600900.SH"])
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n600900", raw.replace(b"\r\n", b""))
        m = yaml.safe_load(raw.decode("utf-8-sig").split("---")[1])
        self.assertEqual(m["ticker"], ["601899.SH", "600900.SH"])


class InlineQuotedCommaTests(unittest.TestCase):
    """内联列表引号内逗号不切（2026-11-13 max 评审 Minor）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quoted_comma_kept_in_one_item(self) -> None:
        path = write(
            self.root,
            "i.md",
            "id: E1\nrelated: ['a, b', c]",
        )
        APPEND.append_to_file(path, list_field="related", items=["d"])
        self.assertEqual(meta(path)["related"], ["a, b", "c", "d"])
