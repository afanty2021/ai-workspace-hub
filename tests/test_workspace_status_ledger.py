"""四模块序号账本体检测试（Q-20261114-04 修根 B）。

覆盖 friction-log 2026-11-14 两案：漏记（报告声明但 profile 缺行）与
撞号（多报告同序号，无人值守批次旁路）；preflight 回执引用豁免回归
（真实冒烟 2026-11-14：18/19/31 撞号均为回执引用误报）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "system" / "scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from workspace_status import check_module_number_ledger, find_workspace_root  # noqa: E402


def _make_ws(tmp_path: Path, reports: dict[str, str], profile_section: str) -> Path:
    """构造最小工作区：output/research/*.md + workspace/research-profile.md。"""
    research = tmp_path / "output" / "research"
    research.mkdir(parents=True)
    for name, text in reports.items():
        (research / name).write_text(text, encoding="utf-8")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "research-profile.md").write_text(
        "# Research Profile\n\n## 本轮观察\n" + profile_section + "\n## 待确认调整\n",
        encoding="utf-8",
    )
    return tmp_path


def test_ok_when_all_declared_numbers_have_profile_rows(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {
            "a.md": "# A\n四模块第 46 次应用。\n",
            "b.md": "# B\n四模块第 47 次应用。\n",
        },
        "- 2026-11-14（R1）：四模块第 46 次——x\n- 2026-11-14（R2）：四模块第 47 次——y\n",
    )
    result = check_module_number_ledger(root)
    assert result["ok"] is True
    assert result["missing_in_profile"] == []
    assert result["duplicate_across_reports"] == {}


def test_missing_report_declaration_fails(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {
            "a.md": "# A\n四模块第 48 次应用。\n",
        },
        "- 2026-11-13（R0）：四模块第 47 次——y\n",
    )
    result = check_module_number_ledger(root)
    assert result["ok"] is False
    assert result["missing_in_profile"] == [48]


def test_duplicate_across_reports_fails(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {
            "a.md": "# A\n四模块第 46 次应用。\n",
            "b.md": "# B\n四模块第 46 次应用（另一票误抄）。\n",
        },
        "- 2026-11-14（R1）：四模块第 46 次——x\n",
    )
    result = check_module_number_ledger(root)
    assert result["ok"] is False
    assert "46" in result["duplicate_across_reports"]
    assert len(result["duplicate_across_reports"]["46"]) == 2


def test_slash_and_range_compound_rows_expand(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {
            "a.md": "# A\n四模块第 20/21 次应用。\n",
        },
        "- 2026-11-11（双票）：四模块第 20/21 次应用\n- 2026-11-12（四票）：四模块第 33~36 次应用\n",
    )
    result = check_module_number_ledger(root)
    assert result["ok"] is True
    assert result["profile_rows"] == 6  # {20, 21} + {33, 34, 35, 36}


def test_preflight_receipts_are_not_report_bodies(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {
            "a.md": "# A\n四模块第 18 次应用。\n",
        },
        "- 2026-11-11（R）：四模块第 18 次——x\n",
    )
    # 回执目录引用另一票的序号（真实误报案例：18/19/31）不应进入对账。
    receipt_dir = root / "output" / "research" / "preflight"
    receipt_dir.mkdir()
    (receipt_dir / "PF-xxx.md").write_text(
        "# 回执\n命中：output/research/R20261111-09.md（四模块第 19 次）\n",
        encoding="utf-8",
    )
    result = check_module_number_ledger(root)
    assert result["ok"] is True
    assert 19 not in result["duplicate_across_reports"]
    assert result["missing_in_profile"] == []


def test_reports_without_declaration_are_not_flagged(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {
            "a.md": "# A\n正文无序号声明（报告侧不强制）。\n",
        },
        "- 2026-11-13（R0）：四模块第 41 次——x\n",
    )
    result = check_module_number_ledger(root)
    assert result["ok"] is True


def test_duplicate_profile_rows_fail(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {"a.md": "# A\n四模块第 46 次应用。\n"},
        "- 2026-11-14（R1）：四模块第 46 次——x\n- 2026-11-14（R1 补录重复）：四模块第 46 次——x\n",
    )
    result = check_module_number_ledger(root)
    assert result["ok"] is False
    assert result["duplicate_in_profile"] == [46]


def test_real_repo_ledger_is_balanced() -> None:
    """真实数据冒烟：当前仓库账本应对账平衡（漏记/撞号出现即红，防回归）。"""
    root = find_workspace_root(Path(__file__))
    result = check_module_number_ledger(root)
    assert result["ok"] is True, f"真实账本异常：{result}"
