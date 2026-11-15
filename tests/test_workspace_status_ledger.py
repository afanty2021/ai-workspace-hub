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

from workspace_status import (  # noqa: E402
    check_module_number_ledger,
    check_profile_trigger_ledger,
    find_workspace_root,
)


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

def test_trigger_ok_reference_style_covers_report(tmp_path: Path) -> None:
    # 引用式 T1-T3 覆盖报告触发器表；节外 T80 噪音不进集合。
    root = _make_ws(
        tmp_path,
        {
            "2026-11-15-x-600000.md": (
                "## 研究问题\n四模块第 62 次应用。\n"
                "## 观察哨事件表（T1-T3）\n- T1 回踩\n- T2 年报\n- T3 毛利率\n\n"
                "## 附注\n技术上 T80 波段（行文噪音）。\n"
            ),
        },
        "- 2026-11-15（R20261115-01 X 600000）：四模块第 62 次——样本。触发器 T1-T3（全表见报告）。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert result["ok"] is True
    assert result["issues"] == []


def test_trigger_missing_section_flagged(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {
            "2026-11-15-x-600000.md": "四模块第 62 次应用。\n**观察哨事件表**：\n- T1 回踩\n- T2 年报\n",
        },
        "- 2026-11-15（R20261115-01 X 600000）：四模块第 62 次——样本。待观察：第二样本。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert result["ok"] is False
    assert any("报告有触发器表 T1-T2 但行未列" in i for i in result["issues"])


def test_trigger_m1_sparse_compression_flagged(tmp_path: Path) -> None:
    # 巨星案：行仅散提 T8、报告 T1-T8——max 相同但集合不覆盖。
    root = _make_ws(
        tmp_path,
        {
            "R20261112-08-x-603477.md": (
                "四模块第 29 次应用。\n## 观察哨事件表\n- T1 现价 10.5\n- T2 8.0\n"
                "- T3 能繁\n- T4 成本\n- T5 现金流\n- T6 负债\n- T7 转债\n- T8 拐点分歧\n"
            ),
        },
        "- 2026-11-12（R20261112-08 X 603477）：四模块第 29 次——触发器=重检线、T8 拐点分歧窗。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert result["ok"] is False
    assert any("行缺 T1" in i for i in result["issues"])


def test_trigger_filename_key_digit_boundary_no_collision(tmp_path: Path) -> None:
    # 2026-11-15 评审 I-2：4 位 HK 头注码（0700）不得吞文件名含 5 位
    # 官方码（00700）的报告触发器表——子串 glob 会把两票对上账，产出
    # 「行缺 T2、3」假异常（968↔968176 数字相邻碰撞同理）。行与报告
    # 序号互不连接（63≠62）、报告无 preflight 自指纹，只剩通道②。
    root = _make_ws(
        tmp_path,
        {
            "2026-11-15-x-00700.md": (
                "四模块第 62 次应用。\n## 观察哨事件表\n"
                "- T1 回踩\n- T2 年报\n- T3 毛利率\n"
            ),
        },
        "- 2026-11-15（R20261115-01 X 0700）：四模块第 63 次——样本。触发器 T1 回踩。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert result["ok"] is True
    assert result["issues"] == []
    assert result["reconciled"] == 0  # 未对上任何报告=零异常（旧子串 glob 时为 1+假异常）


def test_trigger_detached_ids_without_keyword_flagged(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {},
        "- 2026-11-12（R20261112-18 X 023350）：四模块第 38 次——纪律线（T1 经理离任=清仓）。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert any("未挂「触发器」段" in i for i in result["issues"])


def test_trigger_unnumbered_keyword_flagged(tmp_path: Path) -> None:
    root = _make_ws(
        tmp_path,
        {},
        "- 2026-11-14（R20261114-09 X 688825）：四模块第 54 次——主触发器=合约价环比。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert any("行含「触发器」但无 T 编号" in i for i in result["issues"])


def test_trigger_non_research_row_exempt(tmp_path: Path) -> None:
    # 无「四模块第」声明的惯例/收尾行不参与对账（首跑「收尾」行误报案）；
    # lint 仍全行适用（散嵌 T 一律点名），行内不提 T 即零违规。
    root = _make_ws(
        tmp_path,
        {"R20261111-12-x-002463.md": "## 观察哨事件表\n- T1 a\n- T2 b\n"},
        "- 2026-11-11（R20261111-12/13 收尾）：惯例确认行。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert result["issues"] == []


def test_trigger_preflight_id_self_key(tmp_path: Path) -> None:
    # 通道③：frontmatter preflight_id 自指纹（头注无码、文件名无 R-id）。
    root = _make_ws(
        tmp_path,
        {
            "2026-11-13-smic-x.md": (
                "---\npreflight_id: PF-R20261113-01-31f01b9f\n---\n"
                "## 观察哨事件表\n- T1 供给潮\n- T2 折旧\n"
            ),
        },
        "- 2026-11-13（R20261113-01 中芯国际）：四模块第 40 次——双高型。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert any("但行未列" in i for i in result["issues"])


def test_trigger_date_in_header_not_code(tmp_path: Path) -> None:
    # 头注「补录 2026-11-14」的年份不得当 code glob 全年报告（三全案）。
    root = _make_ws(
        tmp_path,
        {
            "2026-11-14-a-999999.md": "## 观察哨事件表\n- T1 x\n",
            "2026-11-15-b-888888.md": "## 观察哨事件表\n- T1 y\n- T2 z\n",
        },
        "- 2026-11-13（R20261113-02 三全 002216，补录 2026-11-14）：四模块第 41 次——双低×DV。\n",
    )
    result = check_profile_trigger_ledger(root)
    assert result["issues"] == []
