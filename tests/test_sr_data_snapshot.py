"""data_snapshot 单测（Q-20261110-08 B 案）——hash 清单指纹=数据态绑定锚。"""

from __future__ import annotations

import json
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401

import data_snapshot as ds  # noqa: E402


def _make_tree(root: Path) -> Path:
    data = root / "us-sector"
    (data / "market" / "series").mkdir(parents=True)
    (data / "market" / "series" / "SPY.jsonl").write_text(
        '{"date": "2026-11-10", "close": 680.0}\n', encoding="utf-8")
    (data / "market" / "series" / "XLK.jsonl").write_text(
        '{"date": "2026-11-10", "close": 140.0}\n', encoding="utf-8")
    (data / ".locks").mkdir()
    (data / ".locks" / "us-SPY.lock").write_text("123", encoding="utf-8")
    return data


def test_fingerprint_stable_and_manifest_written(tmp_path: Path) -> None:
    data = _make_tree(tmp_path)
    m1 = tmp_path / "m1.json"
    m2 = tmp_path / "m2.json"
    s1 = ds.snapshot_data_paths([data], m1)
    s2 = ds.snapshot_data_paths([data], m2)
    assert s1["fingerprint"] == s2["fingerprint"]  # 内容态唯一，与输出路径无关
    assert s1["files"] == 2                         # .locks 点前缀目录跳过
    manifest = json.loads(m1.read_text(encoding="utf-8"))
    assert manifest["fingerprint"] == s1["fingerprint"]
    assert [e["path"] for e in manifest["entries"]] == [
        "us-sector/market/series/SPY.jsonl",
        "us-sector/market/series/XLK.jsonl",       # 目录条目带 base.name 前缀
    ]


def test_single_byte_change_alters_fingerprint(tmp_path: Path) -> None:
    data = _make_tree(tmp_path)
    fp0 = ds.snapshot_data_paths([data], tmp_path / "m.json")["fingerprint"]
    f = data / "market" / "series" / "SPY.jsonl"
    f.write_text(f.read_text(encoding="utf-8").replace("680.0", "680.1"),
                 encoding="utf-8")
    fp1 = ds.snapshot_data_paths([data], tmp_path / "m.json")["fingerprint"]
    assert fp0 != fp1


def test_file_add_remove_alters_fingerprint(tmp_path: Path) -> None:
    data = _make_tree(tmp_path)
    fp0 = ds.snapshot_data_paths([data], tmp_path / "m.json")["fingerprint"]
    (data / "market" / "series" / "XLE.jsonl").write_text("{}", encoding="utf-8")
    fp1 = ds.snapshot_data_paths([data], tmp_path / "m.json")["fingerprint"]
    assert fp0 != fp1
    (data / "market" / "series" / "XLE.jsonl").unlink()
    fp2 = ds.snapshot_data_paths([data], tmp_path / "m.json")["fingerprint"]
    assert fp2 == fp0                              # 回到原态=回到原指纹


def test_mixed_dir_and_single_file(tmp_path: Path) -> None:
    data = _make_tree(tmp_path)
    log = tmp_path / "track-log.jsonl"
    log.write_text('{"t": 1}\n', encoding="utf-8")
    snap = ds.snapshot_data_paths([data, log], tmp_path / "m.json")
    manifest = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    paths = [e["path"] for e in manifest["entries"]]
    assert "track-log.jsonl" in paths               # 单文件=裸名无前缀
    assert snap["files"] == 3
    # 单文件内容变化同样改指纹（hold_crash_check 的状态载体门依赖）
    fp0 = snap["fingerprint"]
    log.write_text('{"t": 2}\n', encoding="utf-8")
    fp1 = ds.snapshot_data_paths([data, log], tmp_path / "m.json")["fingerprint"]
    assert fp0 != fp1


def test_report_line_contains_short_fp_and_manifest(tmp_path: Path) -> None:
    data = _make_tree(tmp_path)
    m = tmp_path / "sub" / "m.json"
    snap = ds.snapshot_data_paths([data], m)
    line = ds.snapshot_report_line(snap)
    assert snap["fingerprint"][:16] in line        # 短指纹
    assert str(m) in line                          # manifest 路径
    assert "2 文件" in line                        # 文件数
