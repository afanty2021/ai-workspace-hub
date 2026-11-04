"""evidence_lint 三时点巡检单测：合法/单调性违反/无时区/未核实/双类型归一/空目录。

全部用 tmp_path 证据树（<tmp>/evidence/YYYY-MM/*.md），不碰真实 evidence/。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EL = load_module("evidence_lint", REPO_ROOT / "system" / "scripts" / "evidence_lint.py")


def make_evidence(root: Path, month: str, name: str, fm_fields: str) -> Path:
    """在 <root>/<month>/<name>.md 写一个最小证据文件，fm_fields 是 frontmatter 正文行。"""
    d = root / month
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(f"---\n{fm_fields}\n---\n\n正文。\n", encoding="utf-8")
    return p


BASE_QUOTED = (
    "id: E-20261103-x-h1\n"
    "type: evidence\n"
    "observed_at: '2026-11-03'\n"
    "available_at: '2026-11-03T05:00:00+08:00'\n"
    "recorded_at: '2026-11-03T18:00:00+08:00'"
)

BASE_BARE = (
    "id: E-20261103-x-h1\n"
    "type: evidence\n"
    "observed_at: 2026-11-03\n"
    "available_at: 2026-11-03T05:00:00+08:00\n"
    "recorded_at: 2026-11-03T18:00:00+08:00"
)


def test_valid_file_passes(tmp_path: Path):
    make_evidence(tmp_path, "2026-11", "ok", BASE_QUOTED)
    result = EL.lint_tree(tmp_path)
    assert result == {"scanned": 1, "errors": [], "unverified": []}


def test_observed_after_available_is_error(tmp_path: Path):
    fm = BASE_QUOTED.replace("observed_at: '2026-11-03'", "observed_at: '2026-11-04'")
    make_evidence(tmp_path, "2026-11", "bad-obs", fm)
    result = EL.lint_tree(tmp_path)
    assert len(result["errors"]) == 1
    e = result["errors"][0]
    assert e["field"] == "observed_at/available_at"
    assert "单调性" in e["reason"]


def test_available_after_recorded_is_error(tmp_path: Path):
    fm = BASE_QUOTED.replace("recorded_at: '2026-11-03T18:00:00+08:00'",
                             "recorded_at: '2026-11-02T18:00:00+08:00'")
    make_evidence(tmp_path, "2026-11", "bad-rec", fm)
    result = EL.lint_tree(tmp_path)
    assert [e["field"] for e in result["errors"]] == ["available_at/recorded_at"]


def test_available_without_timezone_is_error(tmp_path: Path):
    fm = BASE_QUOTED.replace("available_at: '2026-11-03T05:00:00+08:00'",
                             "available_at: '2026-11-03T05:00:00'")
    make_evidence(tmp_path, "2026-11", "naive-av", fm)
    result = EL.lint_tree(tmp_path)
    assert len(result["errors"]) == 1
    assert result["errors"][0]["field"] == "available_at"
    assert "时区" in result["errors"][0]["reason"]
    # 无时区时刻不进单调性比较，也不算未核实
    assert result["unverified"] == []


def test_missing_available_is_unverified_not_error(tmp_path: Path):
    fm = "\n".join(line for line in BASE_QUOTED.splitlines() if not line.startswith("available_at"))
    make_evidence(tmp_path, "2026-11", "old", fm)
    result = EL.lint_tree(tmp_path)
    assert result["errors"] == []
    assert len(result["unverified"]) == 1


def test_bare_date_and_quoted_string_equivalent(tmp_path: Path):
    """YAML 双类型归一：裸 date 与引号串解析结果一致。"""
    make_evidence(tmp_path, "2026-11", "quoted", BASE_QUOTED)
    make_evidence(tmp_path, "2026-11", "bare", BASE_BARE)
    result = EL.lint_tree(tmp_path)
    assert result["scanned"] == 2
    assert result["errors"] == []
    assert result["unverified"] == []


def test_bare_recorded_date_normalized_to_plus8_midnight(tmp_path: Path):
    """recorded_at 裸日期按当日 00:00+08:00 归一：available 同日(+08)仍合法（等号允许）。"""
    fm = BASE_QUOTED.replace("recorded_at: '2026-11-03T18:00:00+08:00'", "recorded_at: '2026-11-03'")
    make_evidence(tmp_path, "2026-11", "bare-rec", fm)
    result = EL.lint_tree(tmp_path)
    assert result["errors"] == []


def test_timezone_conversion_uses_plus8_day(tmp_path: Path):
    """available 2026-11-03T20:00-05:00 换算 +08:00 是 11-04：observed 11-03 合法，11-04 也合法；
    但 recorded（+08 的 11-04 之前，即 11-03 23:00+08）会违反单调性。"""
    fm = (
        "observed_at: '2026-11-03'\n"
        "available_at: '2026-11-03T20:00:00-05:00'\n"  # → +08:00 的 2026-11-04 09:00
        "recorded_at: '2026-11-03T23:00:00+08:00'"
    )
    make_evidence(tmp_path, "2026-11", "tz-cross", fm)
    result = EL.lint_tree(tmp_path)
    assert [e["field"] for e in result["errors"]] == ["available_at/recorded_at"]


def test_empty_tree_is_clean(tmp_path: Path):
    result = EL.lint_tree(tmp_path)
    assert result == {"scanned": 0, "errors": [], "unverified": []}
    # 不存在的根目录同样干净（降级不报错口径）
    result2 = EL.lint_tree(tmp_path / "nope")
    assert result2["scanned"] == 0


def test_cli_exit_codes_and_json(tmp_path, capsys):
    make_evidence(tmp_path, "2026-11", "ok", BASE_QUOTED)
    fm_naive = BASE_QUOTED.replace("available_at: '2026-11-03T05:00:00+08:00'",
                                   "available_at: '2026-11-03T05:00:00'")
    make_evidence(tmp_path, "2026-11", "naive", fm_naive)
    fm_old = "\n".join(line for line in BASE_QUOTED.splitlines() if not line.startswith("available_at"))
    make_evidence(tmp_path, "2026-11", "old", fm_old)

    # 人类可读模式：有 error → 退出码 1
    code = EL.main(["--evidence-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "[error]" in out and "[unverified]" in out

    # --json 模式：结构完整，退出码同口径
    code2 = EL.main(["--evidence-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code2 == 1
    assert payload["scanned"] == 3
    assert len(payload["errors"]) == 1
    assert len(payload["unverified"]) == 1

    # 仅未核实 → 退出码 0
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    make_evidence(clean_root, "2026-11", "old2", fm_old)
    assert EL.main(["--evidence-root", str(clean_root)]) == 0


def test_frontmatter_reader_scalar_only(tmp_path: Path):
    """列表值 / 缩进行 / 无 frontmatter 的文件：reader 只取顶层标量。"""
    p = tmp_path / "list.md"
    p.write_text(
        "---\n"
        "observed_at: '2026-11-03'\n"
        "linked_hypotheses:\n"
        "- H1\n"
        "note: 嵌套:\n"
        "available_at: '2026-11-03T05:00:00+08:00'\n"
        "recorded_at: '2026-11-03'\n"
        "---\n",
        encoding="utf-8",
    )
    fields = EL.parse_frontmatter(p.read_text(encoding="utf-8"))
    assert fields["observed_at"] == "2026-11-03"
    assert "linked_hypotheses" not in fields and "- H1" not in fields
    assert "available_at" in fields

    no_fm = tmp_path / "plain.md"
    no_fm.write_text("没有 frontmatter 的普通笔记。\n", encoding="utf-8")
    assert EL.parse_frontmatter(no_fm.read_text(encoding="utf-8")) == {}


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
