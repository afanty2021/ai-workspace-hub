"""CHANGELOG 记账纪律契约（Q-20261122-02① 修根，2026-11-22）。

背景：11-16 评审 M-3 判例「cron 变更须记 CHANGELOG」后 f8bb11a..ea7b970 七笔
feat/fix 仍零条目——判例只活在评审报告里、没有机械检查点（friction-log
2026-11-22「CHANGELOG 记账系统性滞后」）。本测试把纪律变契约：

  CHANGELOG.md 最后一次提交之后，不允许再出现改动 tools/ 或 system/ 下
  非 markdown 文件的 feat(...)/fix(...) 提交。

范围取舍：只盯 infra 代码（tools/、system/ 非 md）——docs/wiki 纯文档小修
不设卡（用 docs( 前缀即免检）；tests/ 不在范围。已知限制（复查 r2 补记）：
① CHANGELOG 处于未提交修改态时检查放行（合规条目随下一笔提交落地时的
进行中信号；长期脏 CHANGELOG 可绕过检查，由评审流程兜底）；② 边界以
「CHANGELOG 末次任何提交」计——一笔只改 CHANGELOG 旧条目错字、不补
Unreleased 的 docs 提交落在漏记账 feat/fix 之后会重置边界、把后者静默豁免
（boundary reset 变体，窗口窄，评审流程兜底）。非 git 环境自动 skip。
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SUBJECT = re.compile(r"^(feat|fix)\(")


def _touches_code(files: list[str]) -> bool:
    return any(f.startswith(("tools/", "system/")) and not f.endswith(".md")
               for f in files)


def _lagged(commits: list[tuple[str, str, list[str]]],
            changelog_sha: str | None) -> list[tuple[str, str]]:
    """commits 按 newest-first；返回 CHANGELOG 末次提交之后仍缺条目的代码提交。"""
    lag: list[tuple[str, str]] = []
    for sha, subject, files in commits:
        if changelog_sha is not None and sha == changelog_sha:
            break
        if _SUBJECT.match(subject) and _touches_code(files):
            lag.append((sha, subject))
    return lag


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def _repo_state() -> tuple[list[tuple[str, str, list[str]]], str | None]:
    changelog_sha = _git("log", "-1", "--format=%H", "--", "CHANGELOG.md").strip() or None
    commits: list[tuple[str, str, list[str]]] = []
    sha = subject = None
    files: list[str] = []
    for line in _git("log", "--format=%H%x00%s", "--name-only").splitlines():
        if not line.strip():
            continue
        if "\x00" in line:
            if sha is not None:
                commits.append((sha, subject, files))
            sha, subject = line.split("\x00", 1)
            files = []
        else:
            files.append(line)
    if sha is not None:
        commits.append((sha, subject, files))
    return commits, changelog_sha


class LaggedPureTests(unittest.TestCase):
    """合成数据：判定规则逐形态。"""

    def _c(self, sha: str, subject: str, *files: str):
        return (sha, subject, list(files))

    def test_feat_after_changelog_flagged(self) -> None:
        commits = [self._c("a", "feat(x): y", "tools/a.py"),
                   self._c("b", "docs(c): d", "CHANGELOG.md")]
        self.assertEqual(_lagged(commits, "b"), [("a", "feat(x): y")])

    def test_fix_touching_code_flagged(self) -> None:
        commits = [self._c("a", "fix(p): q", "system/lib/x.py", "tests/t.py")]
        self.assertEqual(_lagged(commits, None), [("a", "fix(p): q")])

    def test_docs_only_commit_not_flagged(self) -> None:
        commits = [self._c("a", "fix(p): q", "docs/n.md", "wiki/x.md")]
        self.assertEqual(_lagged(commits, None), [])

    def test_md_under_system_not_flagged(self) -> None:
        commits = [self._c("a", "fix(p): q", "system/skills/daily-watch.md")]
        self.assertEqual(_lagged(commits, None), [])

    def test_older_than_changelog_not_flagged(self) -> None:
        # newest-first：changelog 提交在前（更新），更早的 feat 不追溯
        commits = [self._c("b", "docs(c): d", "CHANGELOG.md"),
                   self._c("a", "feat(x): y", "tools/a.py")]
        self.assertEqual(_lagged(commits, "b"), [])


class RepoChangelogFreshnessTests(unittest.TestCase):
    def test_no_lagged_code_commits(self) -> None:
        try:
            commits, changelog_sha = _repo_state()
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.skipTest("非 git 环境，跳过 CHANGELOG 新鲜度检查")
        if changelog_sha is None:
            self.skipTest("CHANGELOG.md 无提交历史")
        dirty = _git("status", "--porcelain", "--", "CHANGELOG.md").strip()
        if dirty:
            return  # 已知限制：未提交的 CHANGELOG 修改=合规进行中，放行
        lagged = _lagged(commits, changelog_sha)
        self.assertEqual(
            lagged, [],
            "以下 feat/fix 提交改动 tools/system 代码但晚于 CHANGELOG 末次提交——"
            "请在 CHANGELOG.md Unreleased 补条目（纯文档改动改用 docs( 前缀）：\n  "
            + "\n  ".join(f"{s[:12]} {subj}" for s, subj in lagged))


if __name__ == "__main__":
    unittest.main()
