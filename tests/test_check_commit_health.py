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


def _make_default_test_files(root: Path) -> None:
    # B-I6：main 现校验 --tests/缺省档路径在当前树存在（fake repo 也要造出这几份）
    for t in cch.DEFAULT_TESTS:
        p = root / t
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")


def test_main_exit_code_follows_worst_commit(tmp_path, monkeypatch, capsys):
    _make_default_test_files(tmp_path)
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

    # 复查 r2（席 A M-2）：`--base ""` 空串归一为未设，不得绕过缺省空区间守卫。
    assert cch.main(["--repo", str(tmp_path), "--base", ""]) == 2
    assert "缺省区间" in capsys.readouterr().out


def test_default_tests_locked_by_literals_and_exist():
    # B-I6：缺省档自身零锁（M187-M189/M27 同点）——删 registration 或 freshness
    # 条目、路径打错字，原全量绿。清单=字面量元组且逐个真实存在。
    assert cch.DEFAULT_TESTS == ["tests/test_changelog_freshness.py",
                                 "tests/test_knowledge_index_consistency.py",
                                 "tests/test_registration_contract.py"]
    for t in cch.DEFAULT_TESTS:
        assert (REPO_ROOT / t).exists(), f"缺省档路径不存在: {t}"


def test_missing_test_path_fails_fast(tmp_path, monkeypatch, capsys):
    # B-I6：--tests 打错字原被 check_commit 的「按存在性过滤」静默吞掉
    # （假合规路径）——main 对当前树缺失的路径非零退出。
    monkeypatch.setattr(cch, "list_commits",
                        lambda repo, base, head: [("aaa0001", "feat: a")])
    monkeypatch.setattr(cch, "_git", lambda repo, *a: str(tmp_path))
    code = cch.main(["--repo", str(tmp_path), "--base", "HEAD~1",
                     "--tests", "tests/bogus_missing_test.py"])
    assert code == 2
    assert "不存在" in capsys.readouterr().err


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
