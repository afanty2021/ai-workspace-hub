from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_entrypoint_templates_match_public_entrypoints(self) -> None:
        pairs = (
            ("system/templates/AGENTS.md", "AGENTS.md"),
            ("system/templates/CLAUDE.md", "CLAUDE.md"),
            ("system/templates/workspace-config.md", "workspace/workspace-config.md"),
            ("system/templates/active-context.md", "workspace/meta/active-context.md"),
            ("system/templates/friction-log.md", "workspace/meta/friction-log.md"),
            ("system/templates/research-profile.md", "workspace/research-profile.md"),
            ("system/templates/review-queue.md", "workspace/review-queue.md"),
        )
        # active-context and friction-log are append-only working logs: the
        # in-repo workspace accumulates real entries the moment anyone
        # dogfoods the hub here. Only the static instructions above their
        # first append sections are contractual; entries below are usage.
        append_only = {
            "system/templates/active-context.md": "## 最近对话延续",
            "system/templates/friction-log.md": "## Log",
            # review-queue 是被跟踪的实例文件，但表格行是使用数据（agent 自动追加）：
            # 只有表头以上的静态说明是契约，分隔线以下的行不比较。
            "system/templates/review-queue.md": "|---|---|---|---|---|---|---|",
            # research-profile 的「本轮观察」同理（2026-11-06 首条观察触发此缺口）：
            # 引导句以上的静态说明与已确认偏好是契约，观察条目是使用数据不比较。
            "system/templates/research-profile.md": "> 记录用户在真实研究中的追问、删改和反驳。观察不等于偏好",
        }
        for template, public in pairs:
            public_path = REPO_ROOT / public
            if not public_path.exists():
                # Instance files (active-context / friction-log) are untracked:
                # a fresh clone has no workspace/meta yet until the installer
                # rebuilds them from templates. Nothing to compare there; the
                # tracked entrypoints below always exist.
                continue
            template_text = (REPO_ROOT / template).read_text(encoding="utf-8")
            public_text = (REPO_ROOT / public).read_text(encoding="utf-8")
            marker = append_only.get(template)
            if marker is not None:
                marker_index = template_text.find(marker)
                if marker_index != -1:
                    template_text = template_text[:marker_index]
                    public_text = public_text[: public_text.find(marker)]
            self.assertEqual(
                template_text,
                public_text,
                f"{template} and {public} diverged",
            )

    def test_all_relative_markdown_links_resolve(self) -> None:
        pattern = re.compile(r"\[[^]]*\]\(([^)]+)\)")
        broken: list[str] = []
        for markdown in REPO_ROOT.rglob("*.md"):
            if set(markdown.relative_to(REPO_ROOT).parts) & {
                ".git", "node_modules", ".venv", "venv", "dist", "build", ".next",
            }:
                continue
            for target in pattern.findall(markdown.read_text(encoding="utf-8")):
                target = target.split("#", 1)[0].strip()
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                path = (markdown.parent / target.replace("%20", " ")).resolve()
                if not path.exists():
                    broken.append(f"{markdown.relative_to(REPO_ROOT)} -> {target}")
        self.assertEqual(broken, [])

    def test_longbridge_is_not_claimed_as_builtin_env_provider(self) -> None:
        market_script = (
            REPO_ROOT / "tools/daily-watch/scripts/fetch_market_data.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("LONGBRIDGE_APP_KEY", market_script)
        self.assertNotIn("fetch_longbridge", market_script)

    def test_optional_transcription_is_not_in_base_requirements(self) -> None:
        requirements = (
            REPO_ROOT / "tools/podcast/requirements.txt"
        ).read_text(encoding="utf-8")
        active = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertFalse(any(line.startswith("faster-whisper") for line in active))
        self.assertTrue(
            (REPO_ROOT / "tools/podcast/requirements-transcribe.txt").is_file()
        )
        self.assertTrue(
            (REPO_ROOT / "tools/daily-watch/requirements-tushare.txt").is_file()
        )

    def test_example_secrets_are_treated_as_unconfigured(self) -> None:
        market_script = (
            REPO_ROOT / "tools/daily-watch/scripts/fetch_market_data.py"
        ).read_text(encoding="utf-8")
        macro_script = (
            REPO_ROOT / "tools/daily-watch/scripts/fetch_macro_data.py"
        ).read_text(encoding="utf-8")
        self.assertIn('startswith("your_")', market_script)
        self.assertIn('startswith("your_")', macro_script)

    def test_data_sources_doc_covers_entrypoint_wirings(self) -> None:
        """契约修根（friction-log 硬规则，同类第 3 案）：AGENTS.md 数据源表里
        登记的接线 token（fund_nav / jj 前缀 / 116 段 / gpcw …）必须在
        DATA-SOURCES.md 的选择表同步出现。

        历史三次漏同步（模板×2、DATA-SOURCES×1）都败在"人工记七处清单"——
        本测试把清单变成派生断言：往 AGENTS.md 加新接线 token 而
        DATA-SOURCES.md 不跟，这里直接红。锁 DATA-SOURCES.md 一处（README/
        skill 是操作手册，覆盖面天然不同，不做 token 平价）。
        """
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        # 「## 数据源」段内的表格行（| 数据源 | 市场 | env key | 费用 |）。
        section = agents.split("## 数据源", 1)[1].split("\n## ", 1)[0]
        # 空格可选：无空格写法（"jj前缀"）也要被提取成 token 并要求两处
        # 一致（复查 R-1：原 `[a-z]{2,3} 前缀` 依赖空格，无空格改写 +
        # DATA-SOURCES 删行时静默漏锁）。
        token_re = re.compile(
            r"\d{3}(?:/\d{3})? ?段|[a-z]{2,3} ?前缀|[a-z]+_nav|gpcw|datacenter"
        )
        tokens: set[str] = set()
        for line in section.splitlines():
            if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
                continue
            tokens.update(token_re.findall(line))
        # 解析失效（表挪位置/改格式）时宁可红也不静默通过。
        self.assertTrue(tokens, "AGENTS.md 数据源表解析不到任何接线 token")
        doc = (REPO_ROOT / "DATA-SOURCES.md").read_text(encoding="utf-8")
        missing = sorted(t for t in tokens if t not in doc)
        self.assertEqual(
            missing, [], f"DATA-SOURCES.md 缺少接线 token 同步: {missing}"
        )


if __name__ == "__main__":
    unittest.main()
