# tests/test_sr_paper_faithful.py
"""论文原文核对轮消融实现的回归测试（2026-11-07，提案 §12.9）。

覆盖五个候选：⑫ volume 输入（data.py etf_volume + window_blocks with_volume
+ MIMOModel use_volume）、⑬ 4 隐层（L2_HIDDEN_PAPER）、MC T 档位
（mc_samples 透传）、偏差① win/streak 加权（WeightState 三读法）、偏差②
周级增量续训（MIMOModel.update）。默认参数=归档行为位级不变（V0 锚由
repro_paper_ablation.py 在真实数据上再验）。"""
import numpy as np
import pytest

pytest.importorskip("torch")

from sector_rotation.data import WeeklyFrame, build_weekly_frame  # noqa: E402
from sector_rotation.models import (  # noqa: E402
    L2_HIDDEN_PAPER, MIMOModel, WeightState)
from sector_rotation.universe import Member, UniverseSpec  # noqa: E402
from sector_rotation.weekly import window_blocks  # noqa: E402

M2 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def toy_wf(T=180, seed=11, *, with_volume=True):
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, 2)), axis=0)
    valid = np.ones((T, 2), bool)
    valid[-1] = False
    vol = (np.abs(rng.normal(5e6, 2e6, (T, 2)))).round() if with_volume else None
    return WeeklyFrame([f"w{i}" for i in range(T)], idx,
                       [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                       1 + rng.normal(0, 0.03, (T, 2)), np.ones((T, 2)),
                       np.full((T, 2), 2e8), M2, SPEC, valid, valid.copy(),
                       np.full(T, 0.001), etf_volume=vol)


# ---- ⑫ volume：window_blocks 列拼接与齐备过滤 ----

def test_window_blocks_volume_layout_and_default_unchanged():
    wf = toy_wf(T=12, seed=5)
    b_pure, ti_pure = window_blocks(wf, window=3, upto=8, include_t=True)
    b_vol, ti_vol = window_blocks(wf, window=3, upto=8, include_t=True,
                                  with_volume=True)
    # 维度 = N×2L（论文脚注 N×(2l+m) 的 2l 读法）；t_idx 不变（volume 全齐备）
    assert b_vol.shape == (len(ti_vol), 3 * 2 * 2)
    assert np.array_equal(ti_pure, ti_vol)
    # 拼接序 = [价格窗展平, volume 窗展平]（weekly.py 展平口径逐块核对）
    for k, t in enumerate(ti_vol):
        rows = np.arange(t - 2, t + 1)
        expect = np.concatenate([wf.index_close[rows, :].reshape(-1),
                                 wf.etf_volume[rows, :].reshape(-1)])
        assert np.allclose(b_vol[k], expect)
        assert np.allclose(b_pure[k], wf.index_close[rows, :].reshape(-1))


def test_window_blocks_volume_gap_excludes_week():
    wf = toy_wf(T=12, seed=5)
    wf.etf_volume[3, 0] = np.nan           # 第 3 周 volume 缺失 → 特征不齐备
    _, ti_vol = window_blocks(wf, window=3, upto=8, include_t=True,
                              with_volume=True)
    _, ti_pure = window_blocks(wf, window=3, upto=8, include_t=True)
    assert 3 in ti_pure and 3 not in ti_vol
    with pytest.raises(ValueError, match="etf_volume"):
        window_blocks(toy_wf(T=12, seed=5, with_volume=False), window=3,
                      upto=8, include_t=True, with_volume=True)


def test_mimo_use_volume_changes_input_dim_and_runs():
    wf = toy_wf(T=180, seed=7)
    m = MIMOModel(window=13, epochs=5, use_volume=True).fit(wf, 170)
    d_in = m.net[0].in_features
    assert d_in == 13 * 2 * 2               # 13 周 × (价格+volume) × 2 资产
    sel = m.select(wf, 171)
    assert all(0 <= w <= 1 for w in sel.values())


# ---- ⑬ 4 隐层（L2_HIDDEN_PAPER = 论文「four internal layers」+线性输出） ----

def test_hidden_paper_builds_five_dense_layers():
    torch = __import__("torch")
    wf = toy_wf(T=180, seed=7)
    m = MIMOModel(window=13, epochs=1, hidden=L2_HIDDEN_PAPER).fit(wf, 170)
    linears = [mod for mod in m.net if isinstance(mod, torch.nn.Linear)]
    assert len(linears) == len(L2_HIDDEN_PAPER) + 1      # 4 隐层 + 1 输出
    assert [lin.out_features for lin in linears] == list(L2_HIDDEN_PAPER) + [2]
    # 默认档保持归档 4 层 dense（3 隐层+输出）——V0 位级锚的前提
    m0 = MIMOModel(window=13, epochs=1).fit(wf, 170)
    assert len([mod for mod in m0.net if isinstance(mod, torch.nn.Linear)]) == 4


# ---- MC T 档位透传（论文「a large number」→ 消融 T=100） ----

def test_mc_samples_passthrough():
    wf = toy_wf(T=180, seed=7)
    m = MIMOModel(window=13, epochs=5, mc_samples=100).fit(wf, 170)
    x = np.zeros(13 * 2)
    med, conf = m._mc_stats(x)
    assert med.shape == (2,) and conf.shape == (2,)


# ---- 偏差① WeightState：buys/wins/streaks 追踪与三读法公式 ----

def test_weight_state_tracking_and_streak_semantics():
    w = WeightState(3)
    r = np.array([0.02, -0.01, 0.03])
    w.record([0, 1, 2], r)                  # 赢/输/赢
    assert list(w.buys) == [1, 1, 1] and list(w.wins) == [1, 0, 1]
    assert list(w.streaks) == [1, 0, 1]
    w.record([0], np.array([0.05, np.nan, np.nan]))   # 只买 0；1/2 未买不重置
    assert list(w.streaks) == [2, 0, 1] and list(w.buys) == [2, 1, 1]
    w.record([0, 1], np.array([-0.02, 0.01, np.nan]))  # 0 输 → streak 归零
    assert list(w.streaks) == [0, 1, 1]
    w.record([2], np.array([np.nan, np.nan, np.nan]))  # 无效收益不计 buys
    assert w.buys[2] == 1


def test_weight_state_formulas_and_normalization():
    w = WeightState(2, parse="p1")
    w.buys, w.wins, w.streaks = np.array([4, 2]), np.array([3, 0]), np.array([2, 0])
    # p1: 1 + 3·2/4 + 3/(2+1) = 3.5；未买资产 w=1.0
    assert w.raw(0) == pytest.approx(3.5)
    assert w.raw(1) == pytest.approx(1.0)
    w2 = WeightState(2, parse="p2")
    w2.buys, w2.wins, w2.streaks = (np.array([4]), np.array([3]),
                                     np.array([2]))
    assert w2.raw(0) == pytest.approx(1 + (3 + 2) / 4 + 3 / 3)
    w3 = WeightState(2, parse="p3")
    w3.buys, w3.wins, w3.streaks = (np.array([4]), np.array([3]),
                                     np.array([2]))
    assert w3.raw(0) == pytest.approx(1 + 3 * 2 / 4 + 3 / 5)
    ws = w.weights([0, 1])                  # 买入集内归一（引擎 Σw=1 约束）
    assert sum(ws.values()) == pytest.approx(1.0)
    assert ws[0] == pytest.approx(3.5 / 4.5) and ws[1] == pytest.approx(1 / 4.5)
    assert w.weights([]) == {}
    with pytest.raises(ValueError, match="parse"):
        WeightState(2, parse="p9")


# ---- 偏差② MIMOModel.update：周级增量 warm-start 微调 ----

def _params(m):
    return [p.detach().clone() for p in m.net.parameters()]


def test_update_warm_start_changes_weights_and_is_deterministic():
    wf = toy_wf(T=180, seed=7)
    m1 = MIMOModel(window=13, epochs=5, update_epochs=1).fit(wf, 170)
    m2 = MIMOModel(window=13, epochs=5, update_epochs=1).fit(wf, 170)
    before = _params(m1)
    m1.update(wf, 170)                      # 微调刚实现的训练行 t=170
    m2.update(wf, 170)
    assert any(not np.allclose(a.numpy(), b.numpy())
               for a, b in zip(before, _params(m1)))
    assert all(np.allclose(a.detach().numpy(), b.detach().numpy())
               for a, b in zip(_params(m1), _params(m2)))   # 确定性（种子 t_train）


def test_update_disabled_and_missing_cases_are_noop():
    wf = toy_wf(T=180, seed=7)
    m = MIMOModel(window=13, epochs=5, update_epochs=0).fit(wf, 170)
    snap = _params(m)
    m.update(wf, 170)                       # update_epochs=0 → 原样返回
    assert all(np.allclose(a.numpy(), b.numpy()) for a, b in zip(snap, _params(m)))
    m3 = MIMOModel(window=13, epochs=5, update_epochs=1).fit(wf, 170)
    snap3 = _params(m3)
    m3.update(wf, 0)                        # t=0 无齐备特征块（first=window-1）→ 跳过
    assert all(np.allclose(a.numpy(), b.numpy()) for a, b in zip(snap3, _params(m3)))


# ---- data.py：etf_volume 从 sector 序列周五行构造 ----

def test_build_weekly_frame_populates_etf_volume(tmp_path):
    import json
    def wr(p, rows):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    # 3 个决策周（周五 11-06/13/20），每日行含 volume；sector 序列同源带 volume
    sec = [{"date": "2026-11-06", "close": 100.0, "volume": 1.5e6},
           {"date": "2026-11-13", "close": 101.0, "volume": 2.5e6},
           {"date": "2026-11-20", "close": 102.0, "volume": 3.5e6}]
    wr(tmp_path / "sector/series/A.jsonl", sec)
    daily = [{"date": f"2026-11-{d:02d}", "open": 1.0, "close": 1.01,
              "amount": 3e8} for d in range(2, 21)]
    wr(tmp_path / "market/series/EA.SH.jsonl", daily)
    wr(tmp_path / "market/series/510300.SH.jsonl",
       [{"date": f"2026-11-{d:02d}", "open": 1.0, "close": 1.02, "amount": 1e9}
        for d in range(2, 21)])
    wf = build_weekly_frame(tmp_path, SPEC)
    assert np.allclose(wf.etf_volume[:, 0], [1.5e6, 2.5e6, 3.5e6])
    # sector 行缺 volume 字段 → NaN（A 股域现状），with_volume 消费端自筛
    sec_novol = [{k: v for k, v in r.items() if k != "volume"} for r in sec]
    wr(tmp_path / "sector/series/A.jsonl", sec_novol)
    wf2 = build_weekly_frame(tmp_path, SPEC)
    assert np.isnan(wf2.etf_volume).all()
