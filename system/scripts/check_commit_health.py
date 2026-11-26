"""逐提交健康检查：对一段提交区间里的每一笔，在 detached worktree 里跑指定检查，出健康度表。

为什么需要它：按关注点事后拆分出来的提交是「最终树的一个切面」，中间任何一笔的树都没有被
单独跑过。2026-11-25 的五笔里四笔的 CHANGELOG freshness 测试是红的，只有 HEAD 绿（max 评审
r5 I-6）；同族前科见 friction-log 2026-11-11 / 11-12 / 11-14。CI 只跑 HEAD，拦不住这种红。

用法：
    python system/scripts/check_commit_health.py                  # <上游>..HEAD（未推送区间）
    python system/scripts/check_commit_health.py --base HEAD~5    # 任意基点
    python system/scripts/check_commit_health.py --ruff           # 每笔再跑 ruff（需已安装）
    python system/scripts/check_commit_health.py --full           # 每笔再跑全量测试（慢）

每笔默认跑 tests/test_changelog_freshness.py（CHANGELOG 契约）与
tests/test_knowledge_index_consistency.py（知识索引一致性，Q-20261126-15④）。
任一笔红则 exit 1。缺省区间为空（通常=已全部推送）时非零退出并提示用 --base，
确属无需检查用 --allow-empty 放行（I-5：静默 exit 0 是假合规路径）。
只读：worktree 建在系统临时目录，退出时删除；不改任何分支、索引或工作树。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TESTS = ["tests/test_changelog_freshness.py", "tests/test_knowledge_index_consistency.py"]

# Windows 本地裸跑、非 UTF-8 模式下读中文提交信息会 cp1252 解码炸（与 CI 首跑 Windows
# 腿编码族同根，ce88e74 修根同款；2026-11-26 max 评审 M-14）——所有 text 子进程显式 utf-8。
_TEXT_KWARGS = dict(capture_output=True, text=True, encoding="utf-8", errors="replace")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, **_TEXT_KWARGS).stdout.strip()


def default_base(repo: Path) -> str:
    """HEAD 的上游分支；没有上游（从未推送）时退回 origin/main，再不行退回 HEAD~1。"""
    try:
        return _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except subprocess.CalledProcessError:
        return "origin/main" if _git(repo, "rev-parse", "--verify", "--quiet", "origin/main") else "HEAD~1"


def list_commits(repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    """区间 base..head 里的提交（旧→新），返回 [(短 sha, 标题首行)]。"""
    out = _git(repo, "log", "--reverse", "--format=%h%x09%s", f"{base}..{head}")
    rows = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\t")
        if sha:
            rows.append((sha, subject))
    return rows


def pytest_summary(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "(无输出)"


def ruff_summary(rc: int, text: str) -> str:
    if rc == 0:
        return "0 错"
    m = re.search(r"Found (\d+) errors?", text)
    return f"{m.group(1)} 错" if m else f"rc={rc}"


def check_commit(sha: str, repo: Path, tests: list[str], *, ruff: bool = False) -> dict:
    """在 detached worktree 里检出 sha，跑 tests（与可选 ruff），返回 {"pytest": 摘要, "ruff": 摘要, "ok": bool}。"""
    tmp = Path(tempfile.mkdtemp(prefix="commit-health-"))
    wt = tmp / "wt"
    try:
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), sha], cwd=repo,
                       check=True, **_TEXT_KWARGS)
        # 缺省档里较新的测试文件在历史提交的树上还不存在——按存在性过滤（全缺则跳过），
        # 否则逐提交检查会被「文件不存在」的收集错误整体打红（Q-20261126-15④）。
        existing = [t for t in tests if (wt / t).exists()]
        if not existing:
            return {"pytest": f"（指定测试在该提交尚不存在，跳过：{' '.join(tests)}）", "ruff": "—", "ok": True}
        cmd = [sys.executable, "-m", "pytest", *existing, "-q", "-p", "no:cacheprovider", "--tb=line"]
        run = subprocess.run(cmd, cwd=wt, **_TEXT_KWARGS)
        out = {"pytest": pytest_summary(run.stdout + "\n" + run.stderr), "ruff": "—", "ok": run.returncode == 0}
        if ruff:
            if shutil.which("ruff") is None:
                out["ruff"] = "未安装"
            else:
                rr = subprocess.run(["ruff", "check", "system", "tools", "tests"], cwd=wt, **_TEXT_KWARGS)
                out["ruff"] = ruff_summary(rr.returncode, rr.stdout + rr.stderr)
                out["ok"] = out["ok"] and rr.returncode == 0
        return out
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, **_TEXT_KWARGS)
        shutil.rmtree(tmp, ignore_errors=True)


def render(rows: list[tuple[str, str, dict]]) -> str:
    lines = [f"{'提交':<10}{'pytest':<44}{'ruff':<10}判定  标题"]
    for sha, subject, res in rows:
        lines.append(f"{sha:<10}{res['pytest'][:42]:<44}{res['ruff']:<10}{'绿' if res['ok'] else '红'}    {subject[:60]}")
    red = [sha for sha, _, res in rows if not res["ok"]]
    lines.append(f"\n共 {len(rows)} 笔；红 {len(red)} 笔{'：' + ' '.join(red) if red else ''}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="逐提交健康检查（detached worktree，只读）")
    ap.add_argument("--base", default=None, help="区间基点；缺省=HEAD 的上游，没有上游则 origin/main")
    ap.add_argument("--head", default="HEAD", help="区间终点，默认 HEAD")
    ap.add_argument("--tests", nargs="*", default=DEFAULT_TESTS, help="每笔跑的测试路径")
    ap.add_argument("--full", action="store_true", help="每笔跑全量测试（tests/）")
    ap.add_argument("--ruff", action="store_true", help="每笔再跑 ruff check system tools tests")
    ap.add_argument("--allow-empty", action="store_true",
                    help="显式放行空区间（缺省区间为空通常=已全部推送，确属无需检查时用）")
    ap.add_argument("--repo", default=None, type=Path, help="仓库路径，缺省=当前目录所在仓库")
    args = ap.parse_args(argv)
    # 复查 r2（2026-11-26 席 A M-2）：`--base ""` 空串此前走 default_base 解析出缺省基点、
    # 但下方 args.base is None 判不住空串，空区间绕过 exit-2 守卫——空串归一为未设。
    args.base = args.base or None
    try:
        repo = (args.repo or Path(_git(Path.cwd(), "rev-parse", "--show-toplevel"))).resolve()
    except subprocess.CalledProcessError:
        ap.error("当前目录不在 git 仓库里")
    base = args.base or default_base(repo)
    commits = list_commits(repo, base, args.head)
    if not commits:
        if args.base is None and not args.allow_empty:
            # I-5（2026-11-26 max 评审）：全部推送后缺省区间为空，一笔都没查却 exit 0
            # 是假合规路径——非零退出并提示显式指定区间。
            print(f"缺省区间 {base}..{args.head} 为空（通常=已全部推送）：本命令一笔都没有检查。\n"
                  f"请用 --base 显式指定要查的区间（如 --base HEAD~3 或评审头 sha）；\n"
                  f"确属无需检查时用 --allow-empty 放行。")
            return 2
        print(f"区间 {base}..{args.head} 内没有提交")
        return 0
    tests = ["tests"] if args.full else list(args.tests)
    rows = []
    for sha, subject in commits:
        res = check_commit(sha, repo, tests, ruff=args.ruff)
        rows.append((sha, subject, res))
        print(f"  {sha} {'绿' if res['ok'] else '红'}  {res['pytest'][:60]}", file=sys.stderr)
    print(f"逐提交健康检查 {base}..{args.head}（每笔跑：{' '.join(tests)}{' + ruff' if args.ruff else ''}）")
    print(render(rows))
    return 1 if any(not res["ok"] for _, _, res in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
