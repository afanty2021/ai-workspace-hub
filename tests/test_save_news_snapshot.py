"""save_news_snapshot 单测：URL 规范化 dedup、撞名后缀、partial 标记。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401

import save_news_snapshot as snp  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_dedup_equivalent_urls_share_key(self) -> None:
        a = "HTTPS://Example.com/News/Article/?utm_source=x&id=1#top"
        b = "https://example.com/News/Article?id=1"
        self.assertEqual(snp.normalize_url(a), snp.normalize_url(b))
        self.assertNotEqual(snp.dedup_key(a), snp.dedup_key("https://example.com/other"))


class SaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.body = self.root / "raw.md"
        self.body.write_text("标题党正文第一行。\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _save(self, url: str, slug: str = "tsmc-oct", **over):
        kwargs = dict(url=url, title="台积电 10 月营收", date="2026-11-10",
                      slug=slug, input_path=self.body)
        kwargs.update(over)
        return snp.save_snapshot(self.root, **kwargs)

    def test_save_then_dedup_skip(self) -> None:
        path, status = self._save("https://example.com/a?utm_source=rss")
        self.assertEqual(status, "saved")
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("dedup:", text)
        self.assertIn("台积电", text)          # frontmatter title
        self.assertIn("标题党正文第一行。", text)  # 原文保留
        again, status2 = self._save("https://example.com/a")  # 规范化后同 URL
        self.assertEqual(status2, "skipped")
        self.assertEqual(again, path)

    def test_same_slug_different_url_gets_hash_suffix(self) -> None:
        self._save("https://example.com/a", slug="dup")
        path2, status = self._save("https://example.com/b", slug="dup")
        self.assertEqual(status, "saved")
        self.assertNotEqual(path2.name, "2026-11-10-dup.md")
        self.assertIn("2026-11-10-dup-", path2.name)

    def test_partial_flag(self) -> None:
        path, _ = self._save("https://example.com/x", partial=True)
        self.assertIn("partial: true", path.read_text(encoding="utf-8"))

    def test_path_escape_slug_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._save("https://example.com/e", slug="../../evil")

    def test_path_escape_date_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._save("https://example.com/e", date="2026/../../evil")


if __name__ == "__main__":
    unittest.main()
