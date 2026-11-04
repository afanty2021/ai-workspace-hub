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


def test_evidence_amend_done_updates_evidence_auth(data_root: Path, tmp_path: Path) -> None:
    """evidence 两步修订端到端：close 注册 → amend intent → 改正文 → amend --done → verify
    干净（evidence_auth 被同步更新，post_sha256 为归一化口径）；对照面：不走 amend 改正文仍被抓。"""
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

    # 第一步：amend intent（target = evidence 文件，仓库根相对路径）
    ev_target = "evidence/2026-11/E-20261103-mover-300476-sz-h1.md"
    assert RA.main(["--data-root", str(data_root), "amend", "--run-id", run_id,
                    "--target", ev_target, "--reason", "观察段数值勘误"]) == 0
    mid = RA.verify_ledger(data_root, now=LATER)
    assert [u["target"] for u in mid["unfinished_amends"]] == [ev_target]
    # intent 未 done 且正文尚未改：evidence_auth 仍是 close 时哈希，verify 干净
    assert mid["undeclared"] == []

    # 改正文，然后 amend --done
    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace("收盘 -9.12%。", "收盘 -9.1%。"),
        encoding="utf-8")
    assert RA.main(["--data-root", str(data_root), "amend", "--done",
                    "--run-id", run_id, "--target", ev_target]) == 0
    done_row = json.loads(ledger_lines(data_root)[-1])
    assert done_row["type"] == "amend-done"
    assert done_row["post_sha256"] == RA.normalized_evidence_sha256(evidence)
    result = RA.verify_ledger(data_root, now=LATER)
    assert result["unfinished_amends"] == []
    assert [u for u in result["undeclared"] if u["kind"] == "evidence"] == []
    assert result["clean"] is True

    # 对照面：再改正文但不走 amend → evidence 归一化哈希对不上，报未申报
    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace("收盘 -9.1%。", "收盘 -1.0%。"),
        encoding="utf-8")
    flagged = RA.verify_ledger(data_root, now=LATER)
    ev_flagged = [u for u in flagged["undeclared"] if u["kind"] == "evidence"]
    assert len(ev_flagged) == 1
    assert ev_flagged[0]["target"] == "E-20261103-mover-300476-sz-h1"
    assert flagged["clean"] is False


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


# ---------------------------------------------------------------------------
# ledger 子命令（Task 5）：三段汇总 + 坏行降级 + 假设过滤
# ---------------------------------------------------------------------------

EV_TMPL = """---
id: {eid}
type: evidence
observed_at: '{observed}'
available_at: '{observed}T15:30:00+08:00'
recorded_at: '{recorded}'
source_type: daily-watch
direction: {direction}
confidence: pending
review_status: {review}
linked_hypotheses:
- {hyp}
---

# {eid}

正文。
"""

HYP_TMPL = """---
id: {hid}
type: hypothesis
status: 新建
---

# {hid}

{body}
"""


def append_raw(data_root: Path, row: dict) -> None:
    """直接追加一行到 tmp 账本（时间戳固定，不依赖真实时钟），prev_sha256 链按口径接上。"""
    ledger = data_root / ".state" / "run-log.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    raws = [ln for ln in ledger.read_text(encoding="utf-8").splitlines(keepends=True)
            if ln.strip()] if ledger.exists() else []
    row = dict(row)
    row["prev_sha256"] = (hashlib.sha256(raws[-1].encode("utf-8")).hexdigest()
                          if raws else None)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_evidence(tmp_path: Path, eid: str, recorded: str, hyp: str,
                   direction: str = "+", review: str = "pending") -> None:
    path = tmp_path / "evidence" / recorded[:7] / f"{eid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EV_TMPL.format(eid=eid, observed=recorded, recorded=recorded,
                                   direction=direction, review=review, hyp=hyp),
                    encoding="utf-8")


def write_hypothesis(tmp_path: Path, hid: str, body_lines: list[str]) -> None:
    path = tmp_path / "hypothesis" / f"{hid}-demo.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HYP_TMPL.format(hid=hid, body="\n".join(body_lines)),
                    encoding="utf-8")


def _seed_ledger_rows(data_root: Path) -> None:
    append_raw(data_root, {"type": "open", "run_id": "R1", "kind": "watch",
                           "trade_date": "2026-11-03", "started_at": "2026-11-03T16:00:00+08:00"})
    append_raw(data_root, {
        "type": "data-close", "run_id": "R1", "at": "2026-11-03T18:00:00+08:00",
        "data_targets": [], "sources_used": ["mootdx"],
        "missing": [  # 股票侧 / 宏观侧两种键形并存（T4 评审遗留约定）
            {"ticker": "300476.SZ", "source_tried": "mootdx", "reason": "停牌",
             "fallback": "eod"},
            {"item": "VIX", "reason": "FMP key 未配置"},
        ]})
    append_raw(data_root, {"type": "close", "run_id": "R1",
                           "finished_at": "2026-11-03T19:00:00+08:00",
                           "report": "output/daily-watch/2026-11/2026-11-03.md"})
    append_raw(data_root, {"type": "amend", "run_id": "R1",
                           "at": "2026-11-02T10:00:00+08:00",
                           "target": "output/daily-watch/2026-11/2026-11-03.md",
                           "reason": "修正数字"})
    append_raw(data_root, {"type": "close", "run_id": "R0",  # 区间外，应被排除
                           "finished_at": "2026-10-15T19:00:00+08:00",
                           "report": "output/old.md"})


def test_ledger_three_sections(data_root: Path, tmp_path: Path, capsys) -> None:
    """三段输出齐全：运行与修订（两种 missing 键形可读）/ 证据增量 / 判定变化；区间外剔除。"""
    _seed_ledger_rows(data_root)
    write_evidence(tmp_path, "E-20261103-demo-h1", "2026-11-03", "H1")
    write_evidence(tmp_path, "E-20261001-old-h1", "2026-10-01", "H1")  # 区间外
    write_hypothesis(tmp_path, "H1", [
        "- 2026-11-03 | check: sox-break | verdict: warn | as_of: 2026-11-03T09:00:00+08:00 | reading: 4200 | evidence: —",
        "- 2026-10-15 | check: old-check | verdict: normal | as_of: 2026-10-15 | reading: 1 | evidence: —",
    ])

    argv = ["--data-root", str(data_root), "ledger",
            "--from", "2026-11-01", "--to", "2026-11-04"]
    assert RA.main(argv) == 0
    out = capsys.readouterr().out

    assert "## 运行与修订" in out
    assert "close R1 -> output/daily-watch/2026-11/2026-11-03.md" in out
    assert "amend intent R1" in out and "修正数字" in out
    assert "close R0" not in out  # 区间外
    assert "数据缺口（2）" in out
    assert "300476.SZ" in out and "源 mootdx" in out and "降级 eod" in out  # 股票侧键形
    assert "VIX" in out and "FMP key 未配置" in out                          # 宏观侧键形

    assert "## 证据增量" in out
    assert "E-20261103-demo-h1" in out and "direction=+" in out
    assert "review_status=pending" in out and "recorded_at=2026-11-03" in out
    assert "E-20261001-old-h1" not in out

    assert "## 判定变化" in out
    assert "[H1] 2026-11-03 check=sox-break verdict=warn reading=4200" in out
    assert "old-check" not in out  # 区间外判定行
    assert "无法解析的行" not in out  # 本例无坏行


def test_ledger_json_output(data_root: Path, tmp_path: Path, capsys) -> None:
    """--json 输出结构化结果，键与库返回一致。"""
    _seed_ledger_rows(data_root)
    write_evidence(tmp_path, "E-20261103-demo-h1", "2026-11-03", "H1")
    assert RA.main(["--data-root", str(data_root), "ledger", "--json",
                    "--from", "2026-11-01", "--to", "2026-11-04"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"runs", "amends", "missing", "evidence", "verdicts", "unparseable"}
    assert payload["missing"][0]["entry"]["ticker"] == "300476.SZ"
    assert payload["missing"][1]["entry"]["item"] == "VIX"


def test_ledger_bad_verdict_line_degrades(data_root: Path, tmp_path: Path,
                                          capsys) -> None:
    """文法坏行显式报错降级：打印无法解析的行清单，好行照常输出，退出码仍 0。"""
    _seed_ledger_rows(data_root)
    write_hypothesis(tmp_path, "H1", [
        "- 2026-11-02 | check: good-check | verdict: trigger | as_of: 2026-11-02 | reading: 9 | evidence: E-1",
        "- 2026-11-02 | check: bad-verdict | verdict: maybe",
        "- 2026-11-02 | foo: bar | check: bad-key | verdict: normal",
        "- 2026-11-02 | check: bad-missing | verdict: missing | as_of: —",
    ])
    assert RA.main(["--data-root", str(data_root), "ledger",
                    "--from", "2026-11-01", "--to", "2026-11-04"]) == 0
    out = capsys.readouterr().out
    assert "无法解析的行（3" in out
    assert "verdict 非四值：'maybe'" in out
    assert "未知键 'foo'" in out
    assert "缺 reason" in out
    assert "check=good-check verdict=trigger" in out  # 好行不被坏行中断


def test_ledger_hypothesis_filter(data_root: Path, tmp_path: Path, capsys) -> None:
    """--hypothesis H1：只看 H1 文件判定行 + linked_hypotheses 含 H1 的证据（不受日期约束）。"""
    _seed_ledger_rows(data_root)
    write_evidence(tmp_path, "E-20261102-a-h1", "2026-11-02", "H1")
    write_evidence(tmp_path, "E-20261020-b-h2", "2026-10-20", "H2")
    write_evidence(tmp_path, "E-20261015-c-h1", "2026-10-15", "H1")  # 区间外但 linked 命中
    write_hypothesis(tmp_path, "H1", [
        "- 2026-11-02 | check: h1-check | verdict: normal | as_of: 2026-11-02 | reading: 1 | evidence: —"])
    write_hypothesis(tmp_path, "H2", [
        "- 2026-11-02 | check: h2-check | verdict: normal | as_of: 2026-11-02 | reading: 2 | evidence: —"])

    assert RA.main(["--data-root", str(data_root), "ledger", "--hypothesis", "H1",
                    "--from", "2026-11-01", "--to", "2026-11-04"]) == 0
    out = capsys.readouterr().out
    assert "h1-check" in out and "[H1]" in out
    assert "h2-check" not in out
    assert "E-20261102-a-h1" in out
    assert "E-20261015-c-h1" in out   # linked 命中，不受 recorded_at 区间约束
    assert "E-20261020-b-h2" not in out


def test_ledger_hypothesis_not_found(data_root: Path, capsys) -> None:
    """--hypothesis 指向不存在的假设：报参数错误（SystemExit 2），不静默。"""
    with pytest.raises(SystemExit) as exc:
        RA.main(["--data-root", str(data_root), "ledger", "--hypothesis", "H9",
                 "--from", "2026-11-01", "--to", "2026-11-04"])
    assert exc.value.code == 2
    assert "H9" in capsys.readouterr().err


# ---------------------------------------------------------------- 实施评审修复回归

def test_anchor_shrink_regression_backfill_keeps_later_anchor(data_root: Path, tmp_path: Path) -> None:
    """C1 回归：run2 只回填迟到旧行（新锚 11-01 < 历史锚 11-03）时权威锚不收缩。

    评审实证场景：两轮 data-close 锚 11-03 → 11-01（回填），随后篡改 11-03 行——
    修复前 verify 对同 path 的 series 权威无条件覆盖 → 11-01 锚生效 → 篡改脱离
    保护、verify clean；修复后取锚更晚的条目，篡改必须报未申报。
    """
    series = tmp_path / "data" / "s.jsonl"
    write_series(series, [
        {"date": "2026-11-01", "close": 10.0},
        {"date": "2026-11-03", "close": 12.0},
    ])
    run1 = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_data_close(data_root, run1,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-03"}], [], [])
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True

    # run2：只回填迟到的 11-01 旧行（本轮最大写入行日期 = 11-01，新锚早于历史锚）
    run2 = RA.append_open(data_root, "watch", "2026-11-01", now=NOW + timedelta(minutes=1))
    RA.append_data_close(data_root, run2,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-01"}], [], [])
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True  # 无篡改时干净

    # 篡改 11-03 行（处于历史锚 11-03 的保护区间内、在回填锚 11-01 之外）
    lines = series.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1] = json.dumps({"date": "2026-11-03", "close": 99.0}) + "\n"
    series.write_text("".join(lines), encoding="utf-8")
    result = RA.verify_ledger(data_root, now=LATER)
    flagged = [u for u in result["undeclared"] if u["kind"] == "series"]
    assert len(flagged) == 1 and flagged[0]["target"] == "data/s.jsonl"
    assert result["clean"] is False


def test_series_authority_same_anchor_takes_later_row(data_root: Path, tmp_path: Path) -> None:
    """C1 修法补充：同锚两条权威取后写（amend-done 刷新同锚哈希时生效）。"""
    series = tmp_path / "data" / "s.jsonl"
    write_series(series, [{"date": "2026-11-01", "close": 10.0}])
    run1 = RA.append_open(data_root, "watch", "2026-11-01", now=NOW)
    RA.append_data_close(data_root, run1,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-01"}], [], [])
    # 合法修订：amend intent → 改行 → amend-done 补同锚新哈希
    RA.append_amend(data_root, run1, "data/s.jsonl", reason="订正 11-01 收盘价",
                    data_targets=["data/s.jsonl#2026-11-01"])
    write_series(series, [{"date": "2026-11-01", "close": 10.5}])
    RA.append_amend(data_root, run1, "data/s.jsonl", done=True,
                    data_targets=["data/s.jsonl#2026-11-01"])
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True


def test_amend_done_missing_drops_authority(data_root: Path, tmp_path: Path) -> None:
    """#2a：close 指向的产物已消亡 → intent + amend-done --missing 收口。

    verify 遇 missing-done 把该 target 从权威表摘除（行保留，append-only 不破），
    不再对其做「文件缺失」的未申报判定。
    """
    write_report(tmp_path)  # output/r.md
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_close(data_root, run_id, "output/r.md", [])
    (tmp_path / "output" / "r.md").unlink()  # 产物消亡

    result = RA.verify_ledger(data_root, now=LATER)
    flagged = [u for u in result["undeclared"] if u.get("target") == "output/r.md"]
    assert len(flagged) == 1 and flagged[0]["detail"] == "文件缺失"

    RA.append_amend(data_root, run_id, "output/r.md", reason="产物已消亡（冒烟跑误入）")
    mid = RA.verify_ledger(data_root, now=LATER)
    assert mid["unfinished_amends"] and not mid["clean"]  # intent 未完成仍报

    RA.append_amend(data_root, run_id, "output/r.md", done=True, missing=True,
                    reason="产物已消亡（冒烟跑误入）")
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True

    rows = [json.loads(line) for line in ledger_lines(data_root)]
    assert rows[-1]["type"] == "amend-done" and rows[-1]["missing"] is True
    assert "post_sha256" not in rows[-1]  # 消亡收口不算哈希


def test_amend_done_missing_requires_reason(data_root: Path) -> None:
    """--missing 不带 reason 拒绝（消亡原因必须可追溯）。"""
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    with pytest.raises(ValueError, match="reason"):
        RA.append_amend(data_root, run_id, "output/r.md", done=True, missing=True)


def test_amend_missing_cli_roundtrip(data_root: Path, tmp_path: Path, capsys) -> None:
    """CLI：amend --done --missing 全链 exit 0，verify 回干净。"""
    write_report(tmp_path)
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_close(data_root, run_id, "output/r.md", [])
    (tmp_path / "output" / "r.md").unlink()
    assert RA.main(["--data-root", str(data_root), "amend", "--run-id", run_id,
                    "--target", "output/r.md", "--reason", "冒烟跑误入真实账本"]) == 0
    assert RA.main(["--data-root", str(data_root), "amend", "--done", "--missing",
                    "--run-id", run_id, "--target", "output/r.md",
                    "--reason", "冒烟跑误入真实账本"]) == 0
    assert "amend-done 已记账" in capsys.readouterr().out
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True


# ------------------------------------------------------- 延后项收口：amend 锚 / flock

def test_amend_done_earlier_anchor_fails_loud(data_root: Path, tmp_path: Path, capsys) -> None:
    """amend-done 锚早于账本权威锚 → fail-loud：库抛 ValueError，CLI exit 1 + stderr，
    账本不写入会被权威表丢弃 post_sha256 的坏行（否则 verify 误报未申报修订）。"""
    series = tmp_path / "data" / "s.jsonl"
    write_series(series, [
        {"date": "2026-11-01", "close": 10.0},
        {"date": "2026-11-02", "close": 11.0},
        {"date": "2026-11-03", "close": 12.0},
    ])
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_data_close(data_root, run_id,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-03"}], [], [])

    # 本次 amend 的锚 11-02 < 权威锚 11-03：库 API 抛 ValueError
    with pytest.raises(ValueError, match="权威锚"):
        RA.append_amend(data_root, run_id, "data/s.jsonl", done=True,
                        data_targets=["data/s.jsonl#2026-11-02"])
    # CLI 路径：exit 1 + stderr 提示
    assert RA.main(["--data-root", str(data_root), "amend", "--done", "--run-id", run_id,
                    "--target", "data/s.jsonl", "--data-target", "data/s.jsonl#2026-11-02"]) == 1
    assert "更晚锚" in capsys.readouterr().err

    # 账本未被写入坏行：仍是 open + data-close 两行，verify 干净
    rows = [json.loads(line) for line in ledger_lines(data_root)]
    assert [r["type"] for r in rows] == ["open", "data-close"]
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True


def test_amend_done_earlier_anchor_guard_rechecks_under_lock(
        data_root: Path, tmp_path: Path, monkeypatch) -> None:
    """锁内复检（TOCTOU）：锁外读到的旧账本没有更晚权威锚 → 外层检查放行，
    但锁内最新账本已有更晚 data-close → guard 必须抛错且不写行。"""
    series = tmp_path / "data" / "s.jsonl"
    write_series(series, [
        {"date": "2026-11-02", "close": 11.0},
        {"date": "2026-11-03", "close": 12.0},
    ])
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_data_close(data_root, run_id,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-03"}], [], [])

    # 构造锁外旧视图：抹掉那条 data-close（模拟读取与追加之间账本被并发推进）
    real_read = RA._read_rows_strict
    def _stale_read(ledger):
        rows, raws = real_read(ledger)
        return [r for r in rows if r["type"] != "data-close"], raws
    monkeypatch.setattr(RA, "_read_rows_strict", _stale_read)

    # 外层检查看到旧视图（无权威锚）放行；锁内 _append 读到真实账本 → guard 抛错
    with pytest.raises(ValueError, match="权威锚"):
        RA.append_amend(data_root, run_id, "data/s.jsonl", done=True,
                        data_targets=["data/s.jsonl#2026-11-02"])

    # 账本未被写入坏行（open + data-close 两行），verify 干净
    rows = [json.loads(line) for line in ledger_lines(data_root)]
    assert [r["type"] for r in rows] == ["open", "data-close"]
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True


def test_amend_done_same_or_later_anchor_unchanged(data_root: Path, tmp_path: Path) -> None:
    """锚相同或更晚：行为不变（回归）——同锚 amend-done 刷新哈希、更晚锚正常记账。"""
    series = tmp_path / "data" / "s.jsonl"
    write_series(series, [{"date": "2026-11-03", "close": 12.0}])
    run_id = RA.append_open(data_root, "watch", "2026-11-03", now=NOW)
    RA.append_data_close(data_root, run_id,
                         [{"path": "data/s.jsonl", "anchor_date": "2026-11-03"}], [], [])

    # 同锚：改行后 amend-done 补新哈希（与既有 test_series_authority_same_anchor 同路径）
    write_series(series, [{"date": "2026-11-03", "close": 12.5}])
    RA.append_amend(data_root, run_id, "data/s.jsonl", reason="订正收盘价",
                    data_targets=["data/s.jsonl#2026-11-03"])
    RA.append_amend(data_root, run_id, "data/s.jsonl", done=True,
                    data_targets=["data/s.jsonl#2026-11-03"])
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True

    # 更晚锚：追加新行后以新锚记账，verify 干净
    with series.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"date": "2026-11-04", "close": 13.0}) + "\n")
    RA.append_amend(data_root, run_id, "data/s.jsonl", reason="补 11-04 行",
                    data_targets=["data/s.jsonl#2026-11-04"])
    RA.append_amend(data_root, run_id, "data/s.jsonl", done=True,
                    data_targets=["data/s.jsonl#2026-11-04"])
    done_rows = [json.loads(line) for line in ledger_lines(data_root)
                 if json.loads(line)["type"] == "amend-done"]
    assert [r["anchor_date"] for r in done_rows] == ["2026-11-03", "2026-11-04"]
    assert RA.verify_ledger(data_root, now=LATER)["clean"] is True


def test_concurrent_appends_keep_chain_intact(data_root: Path) -> None:
    """flock 并发防护：多线程并发追加 N 行后尾链完整（无丢行 / 无断链），verify 通过。"""
    from concurrent.futures import ThreadPoolExecutor

    def _append_one(i: int) -> None:
        RA.append_open(data_root, "watch", "2026-11-03", now=NOW + timedelta(seconds=i))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_append_one, range(16)))

    lines = [ln for ln in ledger_lines(data_root) if ln.strip()]
    assert len(lines) == 16  # 无丢行
    prev_digest = None
    for line in lines:  # 尾链逐行重算完整
        assert json.loads(line)["prev_sha256"] == prev_digest
        prev_digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    # verify：同 run 互不背锅——16 个 open 均无下文且 <24h，不触发孤儿；链完整即干净
    result = RA.verify_ledger(data_root, now=NOW + timedelta(hours=1))
    assert result["chain_breaks"] == []
    assert result["clean"] is True
