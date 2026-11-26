# tests/test_planted_calibrate.py
"""planted calibrate 的统计口径与 strict 注记路径（2026-11-26 max 评审 r5 I-5 / I-8）。

calibrate 按队列决定不进单测（测量工具不是闸门），但它的计数逻辑、CLI 参数处理与
「契约偏差注记」的触发路径应当有锁——此前注记触发路径零锁（删报警、删注记的变异全存活）：
① 样本不足的对照市场既不计入干净也不计入误报，分母是充足市场数；
② --calib-targets 为空直接报错，不静默空跑；
③ 落盘 JSON 不出现 NaN / Infinity 字面量；
④ event / rps 的契约偏差注记能被触发：默认只报不算（exit 0），--strict 返回 1。
全部假数据，不跑真实管道。
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

import run_check
import synth

CLEAN = {"n_eff": 35, "alpha_mean": 0.0, "alpha_t": 0.5}
FALSE_POSITIVE = {"n_eff": 35, "alpha_mean": 0.0, "alpha_t": 2.6}
INSUFFICIENT = {"n_eff": 3, "alpha_mean": 0.0, "alpha_t": 0.2}
EDGE = {"n_eff": 12, "alpha_mean": 0.01, "alpha_t": 8.0, "pos_ratio": 1.0, "n_sig": 500}


class _FakePipe:
    def __init__(self):
        self.stats = None

    def summarize(self, *args):
        return dict(self.stats)


def _install_fake_pipes(monkeypatch, noise_pairs, edge_stat=None):
    """noise_pairs：逐个对照市场的 (chuji 统计, jinniu 统计)；之后每次调用（埋边扫档）返回 edge_stat。"""
    sb, jn = _FakePipe(), _FakePipe()
    rows = [{"sym": s, "chuji_5_sig": 0.0, "chuji_5_base": 0.0, "chuji_5_n": 10,
             "d_buy_5_sig": 0.0, "d_buy_5_base": 0.0, "d_buy_5_n": 10}
            for s in list(synth.NOISE) + list(synth.EDGE_BOUNCE)]
    queue = list(noise_pairs)

    def fake_run(cache_root, *, verbose=False):
        if queue:
            sb.stats, jn.stats = queue.pop(0)
        else:
            sb.stats = jn.stats = dict(edge_stat or EDGE)
        return sb, jn, rows, rows

    monkeypatch.setattr(run_check, "_run_event_pipes", fake_run)
    monkeypatch.setattr(run_check.synth, "write_cache", lambda *a, **k: None)
    monkeypatch.setattr(run_check, "_jinniu_wiring_ok", lambda *a, **k: None)


def test_calibrate_event_counts_insufficient_as_neither_clean_nor_false_positive(tmp_path, monkeypatch):
    _install_fake_pipes(monkeypatch, [
        (CLEAN, CLEAN),                 # 1 干净
        (FALSE_POSITIVE, CLEAN),        # 2 chuji 误报
        (INSUFFICIENT, INSUFFICIENT),   # 3 双臂不足
        (CLEAN, INSUFFICIENT),          # 4 jinniu 不足
    ])
    result = run_check.calibrate_event(tmp_path, n_markets=4, edge_seeds=1)
    nz = result["noise"]
    assert (nz["chuji_sufficient"], nz["chuji_clean"]) == (3, 2)       # 误报 1/3（市场 3 不进分母）
    assert (nz["jinniu_sufficient"], nz["jinniu_clean"]) == (2, 2)     # 误报 0/2（市场 3、4 不进分母）
    assert (nz["both_sufficient"], nz["both_clean"]) == (2, 1)         # 市场 2 的 chuji 误报 → 双臂全干净只剩 1
    assert nz["insufficient"] == 2                                     # 任一臂不足的市场：3、4
    text = run_check.render_calibrate({"event": result})
    assert "chuji 臂 1/3" in text and "jinniu 臂 0/2" in text and "样本不足 2" in text


def test_render_calibrate_falls_back_to_market_count_for_old_json():
    old = {"event": {"n_markets": 50, "edge_seeds": 3, "edge": [],
                     "noise": {"markets": 50, "chuji_clean": 49, "jinniu_clean": 46,
                               "both_clean": 45, "insufficient": 0}}}
    text = run_check.render_calibrate(old)
    assert "chuji 臂 1/50" in text and "jinniu 臂 4/50" in text and "双臂全干净 45/50" in text


def test_empty_calib_targets_is_a_cli_error(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("targets 为空时不应进入 calibrate")

    monkeypatch.setattr(run_check, "calibrate", _boom)
    with pytest.raises(SystemExit) as e:
        run_check.main(["calibrate", "--calib-targets", " ", "--cache-root", str(tmp_path)])
    assert e.value.code == 2


def test_nan_to_none():
    v = {"a": float("nan"), "b": np.float64("inf"), "c": [float("-inf"), 1.5, "x"], "d": {"e": 0.25}}
    out = run_check._nan_to_none(v)
    assert out == {"a": None, "b": None, "c": [None, 1.5, "x"], "d": {"e": 0.25}}


def test_calibrate_out_json_never_writes_nan_literal(tmp_path, monkeypatch):
    edge = dict(EDGE, alpha_mean=math.nan, alpha_t=3.0, pos_ratio=0.5, n_sig=10)
    _install_fake_pipes(monkeypatch, [(CLEAN, CLEAN)], edge_stat=edge)
    out = tmp_path / "calib.json"
    assert run_check.main(["calibrate", "--calib-targets", "event", "--n-markets", "1",
                           "--edge-seeds", "1", "--out-json", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    data = json.loads(text)
    assert data["event"]["edge"][0]["stats"][0]["alpha_mean"] is None
    assert data["event"]["noise"]["chuji_clean"] == 1


def test_event_contract_note_is_reported_by_default_and_fails_strict(tmp_path, monkeypatch, capsys):
    leaky = {"stage-bottom": {run_check.EVENT_H: 0.95}, "jinniu": {run_check.EVENT_H: 0.95}}
    monkeypatch.setattr(run_check, "event_filter_retention", lambda *a, **k: leaky)
    assert run_check.main(["event", "--cache-root", str(tmp_path / "a")]) == 0
    out = capsys.readouterr().out
    assert "量具正常" in out and "⚠" in out and "停牌过滤" in out
    assert run_check.main(["event", "--cache-root", str(tmp_path / "b"), "--strict"]) == 1
    assert "⚠" in capsys.readouterr().out


def test_rps_warmup_contract_note_is_reported_by_default_and_fails_strict(tmp_path, monkeypatch, capsys):
    bad = {"documented_min_bars": run_check.RPS_DOCUMENTED_MIN_BARS, "ok": False,
           "first_bar": {"rps50": 300, "rps120": 370, "rps250": 500}}
    monkeypatch.setattr(run_check, "_warmup_contract", lambda bundle: bad)
    assert run_check.main(["rps", "--cache-root", str(tmp_path / "a")]) == 0
    out = capsys.readouterr().out
    assert "量具正常" in out and "⚠" in out and "rps_core 预热契约偏差" in out
    assert run_check.main(["rps", "--cache-root", str(tmp_path / "b"), "--strict"]) == 1
