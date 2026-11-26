# tests/test_knowledge_index_consistency.py
"""仓库级知识索引一致性（2026-11-26 max 评审 Q-20261126-15④）。

三类 `_index.md` 是自动生成的加载路由，preflight 靠它们路由加载；改卡不重建索引会让
后续研究读到过期路由——11-25 勘误② 改卡未重建，滞后到 ffa8c5c 才顺带修好，此前
`tests/` 没有任何测试断言真实仓库的索引与卡一致（现有相关测试全用合成根目录）。
本测试在真实仓库根目录跑 `knowledge_lifecycle.py rebuild-index`（缺省 dry-run，不写盘），
断言三类索引 changed 全为 false；已并入 `check_commit_health.py` 默认档。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_rebuild_index_dry_run_reports_no_drift():
    out = subprocess.run(
        [sys.executable, "system/scripts/knowledge_lifecycle.py", "rebuild-index"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180,
    )
    assert out.returncode == 0, f"rebuild-index dry-run 非零退出：\n{out.stderr}"
    entries = json.loads(out.stdout)
    drifted = [e["path"] for e in entries if e.get("changed")]
    assert not drifted, f"知识索引与卡不一致（先跑 rebuild-index --apply 再提交）：{drifted}"
    assert {e["type"] for e in entries} >= {"exploration", "pattern", "rule"}
