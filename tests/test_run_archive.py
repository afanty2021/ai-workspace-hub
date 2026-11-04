"""run_archive 运行账本单测：六行型记账 + 尾行哈希链 + 行锚定哈希 + 两步 amend + verify 四清单。

全部用 tmp_path 账本（<tmp>/data/.state/run-log.jsonl），不碰真实 data/、不发网络。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _test_paths import REPO_ROOT  # noqa: F401


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RA = load_module("run_archive", REPO_ROOT / "system" / "scripts" / "run_archive.py")

# 固定时刻（+08:00），run_id 可预测且不受测试执行时刻影响
NOW = datetime(2026, 11, 4, 16, 30, tzinfo=timezone(timedelta(hours=8)))
LATER = NOW + timedelta(hours=1)  # 24h 内：孤儿闸门不触发


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    """tmp 账本布局：<tmp>/data/.state/run-log.jsonl（仓库根 = tmp）。"""
    root = tmp_path / "data"
    root.mkdir()
    return root


def ledger_lines(root: Path) -> list[str]:
    return (root / ".state" / "run-log.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)


def write_series(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def write_report(tmp_path: Path, rel: str = "output/r.md", text: str = "report v1\n") -> Path:
    report = tmp_path / rel
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text, encoding="utf-8")
    return report


def test_open_data_close_close_full_chain(data_root: Path, tmp_path: Path) -> None:
    """全链记账：open → data-close → close 三行，prev_sha256 链逐行重算一致，verify 干净。"""
    series = tmp_path / "data" / "market" / "series" / "300476.SZ.jsonl"
    write_series(series, [{"date": "2026-11-03", "close": 122.71, "source": "mootdx"}])
    report = write_report(tmp_path, "output/daily-watch/2026-11/2026-11-03.md")

    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    assert run_id == "RUN-20261104-1630-watch"
    RA.append_data_close(
        data_root, run_id,
        [{"path": "data/market/series/300476.SZ.jsonl", "anchor_date": "2026-11-03"}],
        ["mootdx"], [])
    RA.append_close(data_root, run_id, "output/daily-watch/2026-11/2026-11-03.md", [])

    lines = ledger_lines(data_root)
    assert [json.loads(line)["type"] for line in lines] == ["open", "data-close", "close"]
    prev_digest = None
    for line in lines:  # 尾行哈希链：prev = 前一原始行（含换行）的 sha256，首行 null
        row = json.loads(line)
        assert row["prev_sha256"] == prev_digest
        prev_digest = hashlib.sha256(line.encode("utf-8")).hexdigest()

    dc = json.loads(lines[1])  # series 目标 = 行锚定三元组，哈希可独立重算
    assert dc["data_targets"][0] == {
        "path": "data/market/series/300476.SZ.jsonl",
        "anchor_date": "2026-11-03",
        "sha256": RA.row_anchor_hash(series, "2026-11-03")}
    close = json.loads(lines[2])  # 报告整文件哈希
    assert close["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert close["evidence_registered"] == []
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True


def test_row_anchor_append_clean_rewrite_flagged(data_root: Path, tmp_path: Path) -> None:
    """行锚定语义：追加 date>anchor 的新行 verify 仍干净；改 date≤anchor 的旧行报未申报。"""
    series = tmp_path / "data" / "s.jsonl"
    write_series(series, [
        {"date": "2026-11-01", "close": 10.0},
        {"date": "2026-11-02", "close": 11.0},
        {"date": "2026-11-03", "close": 12.0},
    ])
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_data_close(data_root, run_id,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-02"}], [], [])
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True

    with series.open("a", encoding="utf-8") as fh:  # 追加第 4 行（date > anchor）
        fh.write(json.dumps({"date": "2026-11-04", "close": 13.0}) + "\n")
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True

    lines = series.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = json.dumps({"date": "2026-11-01", "close": 99.0}) + "\n"  # 改第 1 行
    series.write_text("".join(lines), encoding="utf-8")
    result = RA.verify_ledger(data_root, now=LATER)
    flagged = [u for u in result["undeclared"] if u["kind"] == "series"]
    assert len(flagged) == 1 and flagged[0]["target"] == "data/s.jsonl"
    assert result["clean"] is False


def test_two_step_amend_intent_then_done(data_root: Path, tmp_path: Path) -> None:
    """两步 amend：intent 后 verify 列未完成修订；--done 补改后哈希后干净。"""
    write_report(tmp_path)
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_close(data_root, run_id, "output/r.md", [])
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True

    RA.append_amend(data_root, run_id, "output/r.md", "盘前快照错行，按官方收盘修正")
    mid = RA.verify_ledger(data_root, now=LATER)
    assert [u["target"] for u in mid["unfinished_amends"]] == ["output/r.md"]

    write_report(tmp_path, text="report v2 修正后\n")
    RA.append_amend(data_root, run_id, "output/r.md", done=True)
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True
    done_row = json.loads(ledger_lines(data_root)[-1])
    assert done_row["type"] == "amend-done"
    assert done_row["post_sha256"] == hashlib.sha256(
        (tmp_path / "output" / "r.md").read_bytes()).hexdigest()


def test_same_minute_collision_gets_r2_r3(data_root: Path) -> None:
    """同分钟同 kind 重开：前一 run 未终结 → 追加 -r2，再撞 → -r3。"""
    first = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    second = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    third = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    assert first == "RUN-20261104-1630-watch"
    assert second == first + "-r2"
    assert third == first + "-r3"


def test_orphan_open_listed_after_25h(data_root: Path) -> None:
    """孤儿 open：open 后 >24h 无 data-close/close/abort → verify 列出；24h 内不列。"""
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    assert RA.verify_ledger(data_root, now=NOW + timedelta(hours=23))["orphan_opens"] == []
    result = RA.verify_ledger(data_root, now=NOW + timedelta(hours=25))
    assert [o["run_id"] for o in result["orphan_opens"]] == [run_id]
    assert result["clean"] is False


def test_abort_terminates_without_close(data_root: Path) -> None:
    """abort 显式收口：verify 不追其 close（不列孤儿、不要求报告哈希）。"""
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_abort(data_root, run_id, "fetch 半途失败")
    result = RA.verify_ledger(data_root, now=NOW + timedelta(hours=30))
    assert result["orphan_opens"] == []
    assert result["clean"] is True


def test_chain_break_on_deleted_middle_line(data_root: Path, tmp_path: Path) -> None:
    """哈希链防篡改：删中间行 → 断链，verify 报当前文件里的断链行号。"""
    write_series(tmp_path / "data" / "s.jsonl", [{"date": "2026-11-03", "close": 1.0}])
    write_report(tmp_path)
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_data_close(data_root, run_id,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-03"}], [], [])
    RA.append_close(data_root, run_id, "output/r.md", [])

    ledger = data_root / ".state" / "run-log.jsonl"
    lines = ledger_lines(data_root)
    del lines[1]  # 删 data-close 行
    ledger.write_text("".join(lines), encoding="utf-8")

    result = RA.verify_ledger(data_root, now=LATER)
    assert result["chain_breaks"] == [2]  # 现文件第 2 行（close）的 prev 对不上
    assert result["clean"] is False


def test_invalid_kind_rejected(data_root: Path) -> None:
    """kind 六值校验：库抛 ValueError；CLI argparse 直接拒（exit 2，不落盘）。"""
    with pytest.raises(ValueError, match="kind"):
        RA.append_open(data_root, "bogus", "2026-11-03", now=NOW)
    with pytest.raises(SystemExit) as excinfo:
        RA.main(["--data-root", str(data_root), "open",
                 "--kind", "bogus", "--trade-date", "2026-11-03"])
    assert excinfo.value.code == 2
    assert not (data_root / ".state" / "run-log.jsonl").exists()


def test_evidence_status_migration_exempt_body_change_flagged(
        data_root: Path, tmp_path: Path) -> None:
    """I4 豁免 + 归一化哈希：状态字段迁移后 verify 仍干净；改正文则报未申报；显式 sha 透传。"""
    evidence = tmp_path / "evidence" / "2026-11" / "E-20261103-mover-300476-sz-h1.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        "---\n"
        "id: E-20261103-mover-300476-sz-h1\n"
        "review_status: pending\n"
        "direction: pending\n"
        "confidence: pending\n"
        "---\n\n# 证据\n\n## 观察\n\n收盘 -9.12%。\n",
        encoding="utf-8")
    write_report(tmp_path)

    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    assert RA.main(["--data-root", str(data_root), "close", "--run-id", run_id,
                    "--report", "output/r.md",
                    "--evidence", "E-20261103-mover-300476-sz-h1"]) == 0
    close_row = json.loads(ledger_lines(data_root)[-1])
    assert close_row["evidence_registered"][0]["id"] == "E-20261103-mover-300476-sz-h1"
    assert close_row["evidence_registered"][0]["sha256"] == RA.normalized_evidence_sha256(evidence)

    # 状态字段合法生命周期迁移（I4 豁免）：归一化后哈希不变，verify 仍干净
    text = evidence.read_text(encoding="utf-8")
    evidence.write_text(
        text.replace("review_status: pending", "review_status: confirmed")
            .replace("direction: pending", "direction: strengthen"),
        encoding="utf-8")
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True

    # 改正文（观察段数值）：不属于豁免范围，verify 报未申报
    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace("收盘 -9.12%。", "收盘 -1.00%。"),
        encoding="utf-8")
    result = RA.verify_ledger(data_root, now=LATER)
    flagged = [u for u in result["undeclared"] if u["kind"] == "evidence"]
    assert len(flagged) == 1
    assert flagged[0]["target"] == "E-20261103-mover-300476-sz-h1"

    # 显式 E-ID:sha256 透传，不重算
    assert RA.main(["--data-root", str(data_root), "close", "--run-id", run_id,
                    "--report", "output/r.md",
                    "--evidence", "E-20261103-mover-300476-sz-h1:deadbeef"]) == 0
    passthrough = json.loads(ledger_lines(data_root)[-1])
    assert passthrough["evidence_registered"][0]["sha256"] == "deadbeef"


def test_sentinel_file_listed_by_verify(data_root: Path) -> None:
    """写失败 sentinel：存在 run-log.error 即列出，verify 退出码 1。"""
    RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    sentinel = data_root / ".state" / "run-log.error"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("2026-11-04T16:31:00+08:00 append_open failed: boom\n", encoding="utf-8")
    result = RA.verify_ledger(data_root, now=LATER)
    assert len(result["sentinel"]) == 1
    assert "boom" in result["sentinel"][0]["content"]
    assert result["clean"] is False
    assert RA.main(["--data-root", str(data_root), "verify"]) == 1


def test_series_amend_done_inherits_intent_anchor(data_root: Path, tmp_path: Path) -> None:
    """series 两步修订：intent 声明 path#date，--done 自动按该锚算行锚定哈希，改后 verify 干净。"""
    series = tmp_path / "data" / "s.jsonl"
    write_series(series, [
        {"date": "2026-11-01", "close": 10.0},
        {"date": "2026-11-02", "close": 11.0},
    ])
    run_id = RA.append_open(data_root, "watch", "2026-11-02", now=NOW)
    RA.append_data_close(data_root, run_id,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-02"}], [], [])

    assert RA.main(["--data-root", str(data_root), "amend", "--run-id", run_id,
                    "--target", "data/s.jsonl", "--reason", "错行修正",
                    "--data-target", "data/s.jsonl#2026-11-02"]) == 0
    assert RA.verify_ledger(data_root, now=LATER)["unfinished_amends"]

    lines = series.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = json.dumps({"date": "2026-11-01", "close": 10.5}) + "\n"  # 改 anchor 内旧行
    series.write_text("".join(lines), encoding="utf-8")
    assert RA.main(["--data-root", str(data_root), "amend", "--done",
                    "--run-id", run_id, "--target", "data/s.jsonl"]) == 0

    done_row = json.loads(ledger_lines(data_root)[-1])
    assert done_row["anchor_date"] == "2026-11-02"
    assert done_row["post_sha256"] == RA.row_anchor_hash(series, "2026-11-02")
    result = RA.verify_ledger(data_root, now=LATER)
    assert result["unfinished_amends"] == []
    assert result["undeclared"] == []


def test_data_close_cli_targets_sources_missing(data_root: Path, tmp_path: Path,
                                                capsys) -> None:
    """CLI data-close：path#anchor 行锚定目标、sources 逗号拆分、missing 数组透传。"""
    write_series(tmp_path / "data" / "s.jsonl", [{"date": "2026-11-03", "close": 5.0}])
    assert RA.main(["--data-root", str(data_root), "open",
                    "--kind", "watch", "--trade-date", "2026-11-03"]) == 0
    run_id = capsys.readouterr().out.strip()
    assert run_id.startswith("RUN-") and run_id.endswith("-watch")

    missing = [{"item": "VIX", "reason": "FMP key 未配置"}]
    assert RA.main(["--data-root", str(data_root), "data-close", "--run-id", run_id,
                    "--data-target", "data/s.jsonl#2026-11-03",
                    "--sources", "mootdx,nasdaq",
                    "--missing-json", json.dumps(missing, ensure_ascii=False)]) == 0
    row = json.loads(ledger_lines(data_root)[-1])
    assert row["sources_used"] == ["mootdx", "nasdaq"]
    assert row["missing"] == missing
    assert row["data_targets"] == [{
        "path": "data/s.jsonl", "anchor_date": "2026-11-03",
        "sha256": RA.row_anchor_hash(tmp_path / "data" / "s.jsonl", "2026-11-03")}]
