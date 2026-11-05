# tests/test_sr_models.py
import numpy as np
import pytest

pytest.importorskip("torch")

from sector_rotation.models import LinearModel, make_strategy, _prep  # noqa: E402
from sector_rotation.universe import Member, UniverseSpec  # noqa: E402

M2 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})
M3 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10),
      Member("C", "丙", ("EC.SH",), 0.10)]
SPEC3 = UniverseSpec(M3, {})


def toy_wf(T=160, seed=11):
    from sector_rotation.data import WeeklyFrame
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, 2)), axis=0)
    valid = np.ones((T, 2), bool)
    valid[-1] = False
    return WeeklyFrame([f"w{i}" for i in range(T)], idx,
                       [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                       1 + rng.normal(0, 0.03, (T, 2)), np.ones((T, 2)),
                       np.full((T, 2), 2e8), M2, SPEC, valid, valid.copy(),
                       np.full(T, 0.001))


def _frame(T, valid, etf_close, seed=3, *, idx=None, members=M2, spec=SPEC):
    from sector_rotation.data import WeeklyFrame
    L = len(members)
    if idx is None:
        rng = np.random.default_rng(seed)
        idx = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, L)), axis=0)
    codes = [[m.etf_candidates[0] for m in members]] * T
    return WeeklyFrame([f"w{i}" for i in range(T)], idx, codes, np.ones((T, L)),
                       etf_close, np.ones((T, L)), np.full((T, L), 2e8),
                       members, spec, valid, valid.copy(), np.full(T, 0.001))


def test_linear_model_learns_separable_signal():
    from sector_rotation.data import WeeklyFrame
    T = 160
    idx = np.zeros((T, 2))
    label_ret = np.zeros((T, 2))
    up = True
    for t in range(T):
        idx[t] = [110.0 if up else 90.0, 100.0]
        label_ret[t] = [0.05 if up else -0.05, 0.0]
        up = not up
    valid = np.ones((T, 2), bool)
    valid[-1] = False
    wf = WeeklyFrame([f"w{i}" for i in range(T)], idx,
                     [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                     1 + label_ret, np.ones((T, 2)), np.full((T, 2), 2e8),
                     M2, SPEC, valid, valid.copy(), np.full(T, 0.001))
    assert 0 in make_strategy("L1", k=1)(wf, T - 2)      # callable 协议（I11）


def test_l1_independent_variant_runs():
    """评审 I4：spec §3.4 L1 双版——每行业独立 sigmoid+BCE 也要实现并对照。"""
    strat = make_strategy("L1", k=1, l1_variant="independent")
    assert isinstance(strat(toy_wf(T=180), 178), dict)


def test_make_strategy_level_validation():
    with pytest.raises(ValueError, match="level"):
        make_strategy("L9")


def test_prep_trains_when_no_week_fully_valid():
    """结构修正回归（T12 carry Ruling）：训练行=指数特征可用周（window_blocks
    口径），不再要求 wf.valid[tj].all()——原口径在稀疏覆盖宇宙（416 成员峰值
    65%）下训练集恒空、策略恒返回 {}。"""
    wf = toy_wf(T=160)
    wf.valid[:, 1] = False          # 成员 B 全程 invalid → 没有任何一周全 valid
    picks = make_strategy("L1", k=1)(wf, 158)
    assert picks == {0: 1.0}        # 旧口径此处恒 {}（_prep 返回 None）


def test_masked_labels_do_not_leak():
    """per-asset invalid 周的标签必须被掩码：掩码外翻转价格不得改变任何
    学习结果（masked-mean BCE 零贡献 = 逐位一致）。决策周取奇数（B 可入
    M_t），偶数 invalid 周落在训练行内。"""
    T = 160
    rng = np.random.default_rng(7)
    close = 1 + rng.normal(0, 0.03, (T, 2))
    valid = np.ones((T, 2), bool)
    valid[-1] = False
    valid[::2, 1] = False                       # B 在偶数周 invalid（训练行内大量存在）
    wf1 = _frame(T, valid, close)
    garbage = np.where(close > 1.0, 0.5, 3.0)   # invalid 周翻出 ±50%/+200% 大收益
    wf2 = _frame(T, valid, np.where(~valid, garbage, close))
    prep1 = _prep(wf1, 157, window=13)
    prep2 = _prep(wf2, 157, window=13)
    m1 = LinearModel(window=13)
    m1.fit(*prep1[:3])
    m2 = LinearModel(window=13)
    m2.fit(*prep2[:3])
    np.testing.assert_array_equal(m1.probs_now(prep1[3]), m2.probs_now(prep2[3]))
    assert make_strategy("L1", k=1)(wf1, 157) == make_strategy("L1", k=1)(wf2, 157)


def test_model_handles_sparse_point_in_time_coverage():
    """结构修正第 2 层回归（v2 Ruling 扩展，2026-11-06 真实数据冒烟实证）：
    没有任何一行全体成员指数齐备（point-in-time 覆盖增长 + 成员缺席）时，
    全市场 window_blocks 口径 t_idx 恒空 → 策略恒 {}；修正后按 M_t 子集
    训练并正常出信号。"""
    T = 160
    rng = np.random.default_rng(5)
    idx = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, 3)), axis=0)
    idx[:80, 2] = np.nan            # 成员 C：前期缺席
    idx[120:, 1] = np.nan           # 成员 B：后期缺席 → 无任何一行三人齐备
    valid = np.ones((T, 3), bool)
    valid[-1] = False
    wf = _frame(T, valid, 1 + rng.normal(0, 0.03, (T, 3)), idx=idx,
                members=M3, spec=SPEC3)
    picks = make_strategy("L1", k=1)(wf, 158)
    assert picks                                    # 旧口径恒 {}（t_idx 空）
    assert set(picks) <= {0, 2}                     # M_158 = {A, C}，B 缺席剔除


def test_l1_seed_deterministic():
    """v2 预注册可复现性：同数据两次全新训练逐位一致（每次 fit 前重置种子）。"""
    wf = toy_wf(T=180, seed=11)
    s1 = make_strategy("L1", k=1)
    s2 = make_strategy("L1", k=1)
    assert s1(wf, 170) == s2(wf, 170)
    assert s1(wf, 178) == s2(wf, 178)
