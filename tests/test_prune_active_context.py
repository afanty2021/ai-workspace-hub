from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from _test_paths import REPO_ROOT  # noqa: F401


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRUNE = load_module(
    "prune_active_context", REPO_ROOT / "system/scripts/prune_active_context.py"
)

TODAY = date(2026, 3, 20)


def build_workspace(tmp: Path, entries: str) -> Path:
    """Create a minimal workspace root with an active-context.md."""
    (tmp / "workspace" / "meta").mkdir(parents=True)
    (tmp / "workspace" / "workspace-config.md").write_text("# config\n", encoding="utf-8")
    active = tmp / "workspace" / "meta" / "active-context.md"
    active.write_text(
        "# Active Context\n\n## 最近对话延续\n\n"
        + entries
        + "\n## 当前关注\n\n- 这一段脚本不许碰\n",
        encoding="utf-8",
    )
    return active


def make_workspace_tail_section(tmp: Path, entries: str) -> Path:
    """延续段为最后一段的最小 workspace（真实布局；compress-at-EOF 场景用）。"""
    (tmp / "workspace" / "meta").mkdir(parents=True)
    (tmp / "workspace" / "workspace-config.md").write_text("# config\n", encoding="utf-8")
    active = tmp / "workspace" / "meta" / "active-context.md"
    active.write_text(
        "# Active Context\n\n## 最近对话延续\n\n" + entries,
        encoding="utf-8",
    )
    return active


def run(active: Path, **kwargs) -> dict:
    lines = active.read_text(encoding="utf-8").split("\n")
    result = PRUNE.plan(
        lines,
        kwargs.get("today", TODAY),
        kwargs.get("cutoff_days", 14),
        kwargs.get("max_entries", 20),
        kwargs.get("line_cap", 1500),
    )
    assert result is not None
    PRUNE.apply_plan(
        active,
        active.parent,
        lines,
        result,
        kwargs.get("cutoff_days", 14),
        kwargs.get("line_cap", 1500),
    )
    return result


class PruneActiveContextTest(unittest.TestCase):
    def test_archives_entries_older_than_cutoff(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            active = build_workspace(
                tmp,
                "- **2026-01-05：很久以前的事（DONE）** -> `output/a.md` 摘要\n"
                "- **2026-03-19：昨天的事（PAUSED）** -> `output/b.md` 摘要\n",
            )
            run(active)
            body = active.read_text(encoding="utf-8")
            self.assertNotIn("很久以前的事", body)
            self.assertIn("昨天的事", body)
            archive = tmp / "workspace/meta/active-context-archive-2026-01.md"
            self.assertIn("很久以前的事", archive.read_text(encoding="utf-8"))

    def test_keeps_other_sections_untouched(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            active = build_workspace(
                tmp, "- **2026-01-05：老条目（DONE）** -> `output/a.md` 摘要\n"
            )
            run(active)
            self.assertIn("这一段脚本不许碰", active.read_text(encoding="utf-8"))

    def test_entry_count_cap_archives_oldest(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            entries = "".join(
                f"- **2026-03-{day:02d}：第 {day} 条（DONE）** -> `output/{day}.md` 摘要\n"
                for day in range(8, 20)
            )
            active = build_workspace(tmp, entries)
            result = run(active, max_entries=5)
            self.assertEqual(len(result["to_keep"]), 5)
            self.assertEqual(result["over_count"], 7)
            body = active.read_text(encoding="utf-8")
            self.assertNotIn("第 8 条", body)
            self.assertIn("第 19 条", body)

    def test_line_cap_compresses_long_entry_and_keeps_full_text(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            long_body = "  详细正文，" * 400  # 远超 1500 字节
            active = build_workspace(
                tmp,
                "- **2026-03-18：超长条目（PAUSED）** -> `output/long.md` 摘要\n"
                f"{long_body}\n",
            )
            run(active)
            body = active.read_text(encoding="utf-8")
            self.assertIn("超长条目", body)
            self.assertNotIn("详细正文", body)
            self.assertIn("📦 全文见", body)
            self.assertIn("`output/long.md`", body)
            index_line = next(ln for ln in body.split("\n") if "超长条目" in ln)
            self.assertLessEqual(len(index_line.encode("utf-8")), 1500)
            archive = tmp / "workspace/meta/active-context-archive-2026-03.md"
            self.assertIn("详细正文", archive.read_text(encoding="utf-8"))

    def test_line_cap_zero_disables_compression(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            long_body = "  详细正文，" * 400
            active = build_workspace(
                tmp,
                "- **2026-03-18：超长条目（PAUSED）** -> `output/long.md` 摘要\n"
                f"{long_body}\n",
            )
            result = run(active, line_cap=0)
            self.assertEqual(result["to_compress"], [])
            self.assertIn("详细正文", active.read_text(encoding="utf-8"))

    def test_idempotent_on_rerun(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            active = build_workspace(
                tmp,
                "- **2026-01-05：老条目（DONE）** -> `output/a.md` 摘要\n"
                "- **2026-03-18：超长条目（PAUSED）** -> `output/long.md` 摘要\n"
                + "  详细正文，" * 400
                + "\n",
            )
            run(active)
            first_jan = (tmp / "workspace/meta/active-context-archive-2026-01.md").read_text(
                encoding="utf-8"
            )
            first_mar = (tmp / "workspace/meta/active-context-archive-2026-03.md").read_text(
                encoding="utf-8"
            )
            run(active)
            run(active)
            self.assertEqual(
                first_jan,
                (tmp / "workspace/meta/active-context-archive-2026-01.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(
                first_mar,
                (tmp / "workspace/meta/active-context-archive-2026-03.md").read_text(
                    encoding="utf-8"
                ),
            )

    def test_missing_section_returns_none(self):
        lines = "# Active Context\n\n## 别的段\n\n- 内容\n".split("\n")
        self.assertIsNone(PRUNE.plan(lines, TODAY, 14, 20, 1500))

    def test_ensure_trailing_newline_normalizes_and_stops_cat_append_glue(self):
        # 2026-11-10 修根回归：尾行无换行 + cat>> 追加 → 新条目粘上尾行成一行 →
        # 行长闸门把粘连行整体归档原地留索引（吞掉新条目，active-context 第 2 案）。
        # 场景构造：条目 A 独立时低于行长闸门、粘连条目 B 后超过——即「若粘连，
        # 闸门必吞 B」。延续段构造为最后一段（真实布局），尾行 = A 的正文行。
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "workspace" / "meta").mkdir(parents=True)
            (tmp / "workspace" / "workspace-config.md").write_text("# config\n", encoding="utf-8")
            active = tmp / "workspace" / "meta" / "active-context.md"
            title_a = "- **2026-03-18：条目 A（DONE）** -> `output/a.md` 摘要\n"
            body_line = "  " + "详" * 470  # 1412B；A 独立块 ~1474B < 闸门
            active.write_text(
                "# Active Context\n\n## 最近对话延续\n\n" + title_a + body_line,
                encoding="utf-8",
            )
            self.assertFalse(active.read_text(encoding="utf-8").endswith("\n"))

            # 事故形态自检：粘连态下 plan 必须触发行长闸门、B 不在行首（数学错了这里先红）
            b_line = "- **2026-03-19：条目 B（DONE）** -> `output/b.md` 摘要\n"
            glued_lines = (
                "# Active Context\n\n## 最近对话延续\n\n" + title_a + body_line + b_line
            ).split("\n")
            glued_plan = PRUNE.plan(glued_lines, TODAY, 14, 20, 1500)
            self.assertTrue(glued_plan["to_compress"], "粘连块未超闸门，场景构造失效")
            self.assertTrue(glued_plan["glued"], "粘连特征未被告警")
            self.assertTrue(
                all(not ln.startswith("- **2026-03-19") for ln in glued_lines),
                "粘连态下条目 B 独立成行，事故形态未复现",
            )

            # 治愈路径：读侧规范化 → cat>> 追加 B → B 独立成行、不被压缩、原样保留
            normalized = PRUNE.ensure_trailing_newline(active)
            self.assertTrue(normalized.endswith("\n"))
            self.assertTrue(active.read_text(encoding="utf-8").endswith("\n"))
            # 幂等：已有尾换行时不再写文件（内容字节不变）
            again = PRUNE.ensure_trailing_newline(active)
            self.assertEqual(normalized, again)

            with active.open("a", encoding="utf-8") as fh:
                fh.write(b_line)
            raw_lines = PRUNE.ensure_trailing_newline(active).split("\n")
            glued = [ln for ln in raw_lines if "条目 A" in ln and "条目 B" in ln]
            self.assertEqual(glued, [])  # 未粘连在同一行
            result = PRUNE.plan(raw_lines, TODAY, 14, 20, 1500)
            self.assertEqual(result["to_compress"], [])
            # 主文件 rewrite 后两行都在行首独立存在（B 没被闸门吞掉）
            PRUNE.apply_plan(active, active.parent, raw_lines, result, 14, 1500)
            body = active.read_text(encoding="utf-8")
            self.assertTrue(
                any(ln.startswith("- **2026-03-18：条目 A") for ln in body.split("\n"))
            )
            self.assertTrue(
                any(ln.startswith("- **2026-03-19：条目 B") for ln in body.split("\n"))
            )

    def test_apply_plan_compress_at_eof_keeps_trailing_newline(self):
        # C1 回归（max 评审）：延续段是最后一段时，压缩末条目会把 raw.split 的尾部
        # "" 一并 drop，apply 产物以压缩索引行裸尾结束（无尾换行）——2026-11-10 第 2
        # 案粘连事故的前提正是这个形态（索引行裸尾 + cat>> 粘连）。写出侧归一后，
        # apply 重写永远以 \n 结尾。
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            active = make_workspace_tail_section(
                tmp,
                "- **2026-03-18：超长末条（PAUSED）** -> `output/long.md` 摘要\n"
                + "  详细正文，" * 400
                + "\n",
            )
            run(active)
            body = active.read_text(encoding="utf-8")
            self.assertTrue(body.endswith("\n"), "apply 产物裸尾（无尾换行）——写侧归一失效")
            self.assertIn("超长末条", body)
            self.assertNotIn("详细正文", body)  # 正文已压缩进归档
            archive = tmp / "workspace/meta/active-context-archive-2026-03.md"
            self.assertIn("详细正文", archive.read_text(encoding="utf-8"))

    def test_main_apply_normalizes_missing_trailing_newline(self):
        # I2 回归：main() 的读侧接线是独立防御位置——只删接线、保留函数时函数级
        # 测试全绿，只有这里能红。用「无归档/压缩对象」的场景：apply_plan 不会重写
        # 文件，尾换行只能来自 main() 的读侧补齐。
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            active = build_workspace(
                tmp, "- **2026-03-20：今天的事（PAUSED）** -> `output/c.md` 摘要\n"
            )
            active.write_text(
                active.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8"
            )
            stderr = io.StringIO()
            with mock.patch.object(
                sys, "argv", ["prune", "--root", str(tmp), "--today", "2026-03-20", "--apply"]
            ), contextlib.redirect_stderr(stderr):
                self.assertEqual(PRUNE.main(), 0)
            self.assertTrue(
                active.read_text(encoding="utf-8").endswith("\n"),
                "--apply 后文件仍裸尾——main() 读侧接线缺失",
            )

    def test_main_dry_run_leaves_file_byte_identical(self):
        # I1 回归：dry-run 契约 = 一个字节都不写（AGENTS.md「dry-run 先看会剪什么」）。
        # 文件缺尾换行 + 有可剪条目 → 字节必须完全不变（旧行为会 +1B）；同时锁定
        # 「尾行无换行」告警的接线。
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            active = build_workspace(
                tmp, "- **2026-01-05：老条目（DONE）** -> `output/a.md` 摘要\n"
            )
            active.write_text(
                active.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8"
            )
            before = active.read_bytes()
            stderr = io.StringIO()
            with mock.patch.object(
                sys, "argv", ["prune", "--root", str(tmp), "--today", "2026-03-20"]
            ), contextlib.redirect_stderr(stderr):
                self.assertEqual(PRUNE.main(), 0)
            self.assertEqual(active.read_bytes(), before, "dry-run 写了文件——违反只读契约")
            self.assertIn("尾行无换行", stderr.getvalue())

    def test_plan_flags_embedded_entry_start_as_glue(self):
        # 粘连特征检测：条目起始嵌在行中（cat>> 无尾换行追加的残损形态）必须显性
        # 暴露，不许等行长闸门静默吞掉；行首条目与干净行不得误报。
        lines = (
            "# Active Context\n\n## 最近对话延续\n\n"
            "- **2026-03-18：条目 A（DONE）** -> `output/a.md` 摘要\n"
            "  前缀文字- **2026-03-19：粘连条目（DONE）** -> `output/b.md` 摘要\n"
            "\n## 当前关注\n\n- 这一段脚本不许碰\n"
        ).split("\n")
        result = PRUNE.plan(lines, TODAY, 14, 20, 1500)
        self.assertEqual(result["glued"], [5])

        clean = (
            "# Active Context\n\n## 最近对话延续\n\n"
            "- **2026-03-18：条目（DONE）** -> `output/a.md` 摘要\n"
        ).split("\n")
        self.assertEqual(PRUNE.plan(clean, TODAY, 14, 20, 1500)["glued"], [])


if __name__ == "__main__":
    unittest.main()
