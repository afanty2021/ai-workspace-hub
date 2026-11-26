# tests/test_check_commit_health.py
"""逐提交健康检查脚本的锁（2026-11-26 max 评审 r5 I-6）。

背景：按关注点事后拆分的提交没有逐笔验证过，2026-11-25 五笔里四笔 freshness 红、只有 HEAD 绿。
锁三件事：
① 结果解析：pytest / ruff 摘要;
② 编排：区间内任一笔红则 exit 1，全绿 exit 0，空区间不报错;
③ 真实链路：临时 git 仓库里「绿提交 + 红提交」，detached worktree 检出后确实能区分。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "system" / "scripts"))
import check_commit_health as cch  # noqa: E402


def test_pytest_and_ruff_summaries():
    assert cch.pytest_summary("noise\n1 failed, 7 passed in 0.08s\n") == "1 failed, 7 passed in 0.08s"
    assert cch.pytest_summary("") == "(无输出)"
    assert cch.ruff_summary(0, "All checks passed!") == "0 错"
    assert cch.ruff_summary(1, "Found 2 errors.\n") == "2 错"
    assert cch.ruff_summary(1, "[*] 6 fixable with the `--fix` option") == "rc=1"  # 无 Found 行时兜底为 rc


def test_main_exit_code_follows_worst_commit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cch, "list_commits",
                        lambda repo, base, head: [("aaa0001", "feat: a"), ("bbb0002", "fix: b"), ("ccc0003", "docs: c")])
    fake = {"aaa0001": {"pytest": "8 passed in 0.05s", "ruff": "—", "ok": True},
            "bbb0002": {"pytest": "1 failed, 7 passed in 0.08s", "ruff": "—", "ok": False},
            "ccc0003": {"pytest": "8 passed in 0.05s", "ruff": "—", "ok": True}}
    monkeypatch.setattr(cch, "check_commit", lambda sha, repo, tests, ruff=False: fake[sha])
    monkeypatch.setattr(cch, "_git", lambda repo, *a: str(tmp_path))
    assert cch.main(["--repo", str(tmp_path), "--base", "HEAD~3"]) == 1
    out = capsys.readouterr().out
    assert "红 1 笔：bbb0002" in out and "红    fix: b" in out

    fake["bbb0002"] = {"pytest": "8 passed in 0.05s", "ruff": "—", "ok": True}
    assert cch.main(["--repo", str(tmp_path), "--base", "HEAD~3"]) == 0
    assert "红 0 笔" in capsys.readouterr().out


def test_main_empty_range_is_not_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cch, "list_commits", lambda repo, base, head: [])
    monkeypatch.setattr(cch, "_git", lambda repo, *a: str(tmp_path))
    assert cch.main(["--repo", str(tmp_path), "--base", "HEAD~3"]) == 0
    assert "没有提交" in capsys.readouterr().out


def test_main_empty_default_range_warns_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    # I-5（2026-11-26 max 评审）：全部推送后缺省区间为空，静默 exit 0 = 假合规路径。
    # 未给 --base 且区间空 → 非零退出 + 提示；--allow-empty 或显式 --base 放行。
    monkeypatch.setattr(cch, "list_commits", lambda repo, base, head: [])
    monkeypatch.setattr(cch, "_git", lambda repo, *a: str(tmp_path))
    monkeypatch.setattr(cch, "default_base", lambda repo: "origin/main")

    assert cch.main(["--repo", str(tmp_path)]) == 2
    cap = capsys.readouterr()
    assert "缺省区间" in cap.out and "--base" in cap.out

    assert cch.main(["--repo", str(tmp_path), "--allow-empty"]) == 0
    assert "没有提交" in capsys.readouterr().out

    assert cch.main(["--repo", str(tmp_path), "--base", "HEAD~3"]) == 0
    assert "没有提交" in capsys.readouterr().out


def test_check_commit_distinguishes_green_and_red_commits_in_a_real_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-q", "-m", "chore: seed")
    (repo / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    git("add", "test_ok.py")
    git("commit", "-q", "-m", "feat: green")
    green = cch._git(repo, "rev-parse", "--short", "HEAD")
    (repo / "test_bad.py").write_text("def test_bad():\n    assert 1 + 1 == 3\n", encoding="utf-8")
    git("add", "test_bad.py")
    git("commit", "-q", "-m", "fix: red")
    red = cch._git(repo, "rev-parse", "--short", "HEAD")

    assert [sha for sha, _ in cch.list_commits(repo, "HEAD~2", "HEAD")] == [green, red]
    ok = cch.check_commit(green, repo, ["test_ok.py"])
    bad = cch.check_commit(red, repo, ["test_bad.py"])
    assert ok["ok"] is True and "1 passed" in ok["pytest"]
    assert bad["ok"] is False and "1 failed" in bad["pytest"]
    # worktree 已清理：仓库里只剩主工作树
    assert subprocess.run(["git", "worktree", "list"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.count("\n") == 1
