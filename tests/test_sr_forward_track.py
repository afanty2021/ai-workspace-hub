# tests/test_sr_forward_track.py
"""前向纸面跟踪器回归测试（产品化评估基础设施，2026-11-07）。

覆盖：ROCState 序列化往返（52 对环形缓冲语义）、step() 沉默持有+状态外置
演化（发声→照单、沉默→持有上期名单）、log 幂等去重（log_dates）。
真实数据路径（fetch/bootstrap 重放）由 CLI 首跑验收，不进单测。"""
import json

import numpy as np
import pytest

pytest.importorskip("torch")

from sector_rotation.data import WeeklyFrame  # noqa: E402
from sector_rotation.models import ROCState  # noqa: E402
from sector_rotation.universe import Member, UniverseSpec  # noqa: E402
from forward_track import log_dates, roc_from_json, roc_to_json, step  # noqa: E402

M2 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def _wf(fridays):
    T = len(fridays)
    v = np.ones((T, 2), bool)
    return WeeklyFrame(fridays, np.full((T, 2), 100.0), [["EA.SH", "EB.SH"]] * T,
                       np.ones((T, 2)), np.full((T, 2), 1.01), np.ones((T, 2)),
                       np.full((T, 2), 2e8), M2, SPEC, v, v.copy(), np.full(T, 0.001))


def test_roc_state_json_roundtrip_preserves_pairs_and_maxlen():
    roc = ROCState()
    rng = np.random.default_rng(3)
    for k in range(60):                      # 超 52 → 环形截断
        roc.pairs.append((rng.random(2), rng.random(2)))
    roc.last_t, roc.last_pred = 41, np.array([0.4, 0.6])
    out = roc_from_json(json.loads(json.dumps(roc_to_json(roc))))
    assert out.last_t == 41 and np.allclose(out.last_pred, [0.4, 0.6])
    assert len(out.pairs) == 52              # deque maxlen 保持
    assert np.allclose(out.pairs[-1][0], roc.pairs[-1][0])
    fresh = roc_from_json({"last_t": None, "last_pred": None, "pairs": []})
    assert fresh.last_t is None and len(fresh.pairs) == 0


class _Stub:
    def __init__(self, seq):
        self.seq, self.i = list(seq), 0

    def select(self, wf_, t, roc=None):
        out = dict(self.seq[min(self.i, len(self.seq) - 1)])
        self.i += 1
        return out


def test_step_hold_semantics_and_state_evolution():
    wf = _wf([f"2026-w{i:02d}" for i in range(4)])
    st = {"last_decision": None, "per_n": {}}
    m = _Stub([{0: 0.5, 1: 0.5}, {}, {1: 1.0}])
    r0 = step(wf, 13, 0, st, {2026: m})
    assert r0["spoke"] and r0["members"] == ["EA.SH", "EB.SH"]
    assert st["per_n"]["13"]["roster"] == [0, 1]
    r1 = step(wf, 13, 1, st, {2026: m})
    assert not r1["spoke"] and r1["members"] == ["EA.SH", "EB.SH"]   # 沉默持有
    r2 = step(wf, 13, 2, st, {2026: m})
    assert r2["spoke"] and r2["members"] == ["EB.SH"]                # 换仓卖出 A
    assert st["per_n"]["13"]["roster"] == [1]
    r3 = step(wf, 13, 3, st, {})       # 年模型缺失 → {} 但名单外置保留
    assert not r3["spoke"] and r3["members"] == ["EB.SH"]


def test_log_dates_dedup(tmp_path):
    from forward_track import LOG
    import forward_track as ft
    LOG.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "x").touch()
    ft.LOG = tmp_path / "track-log.jsonl"      # 重定向到临时路径
    ft.LOG.write_text(json.dumps({"friday": "2026-10-30", "n": 13}) + "\n",
                      encoding="utf-8")
    assert log_dates() == {"2026-10-30"}
