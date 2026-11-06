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
    # v2 评审 M-3：锁到概率逐位一致（picks 相等只是排序级，强度不足）
    X, y, r, x_now, cols = _prep(wf, 170, window=13)
    probs = []
    for _ in range(2):
        m = LinearModel()
        m.fit(X, y, r)
        probs.append(m.probs_now(x_now))
    assert np.array_equal(probs[0], probs[1])
    assert s1(wf, 178) == s2(wf, 178)


# ---- MIMOModel（L2 复活，R20261106-02 §3/§8）----

from sector_rotation.models import (  # noqa: E402
    MIMOModel, ROCState, _confident, _roc_threshold, thresholds_from_pairs)
from sector_rotation.weekly import (  # noqa: E402
    weekly_gross_returns, window_blocks)


def test_confident_rule_tighter_than_gaussian():
    """论文 §1.1：MC 样本 ≥80% 质量落在中位数 ±1σ 内才置信——高斯 ≈68% 不
    过，紧簇样本过（弃权机制的判定单位）。"""
    tight = np.full((20, 1), 0.5)
    tight[0, 0] = 0.9                       # 19/20 落带内 → 0.95 ≥ 0.8 → 置信
    assert _confident(tight)[0]
    wide = np.linspace(0, 1, 20)[:, None]   # ≈13/20 落带内 → 0.65 < 0.8 → 弃权
    assert not _confident(wide)[0]


def test_roc_threshold_separable_and_fallback():
    # ≥10 对可分样本才越过 len<10 早退、真实命中 Youden 主路径（复查轮 N5：
    # 4 样本会被 0.5 兜底凑巧通过断言，主路径零覆盖）。
    p = np.array([0.05, 0.1, 0.15, 0.2, 0.3, 0.7, 0.8, 0.85, 0.9, 0.95])
    y = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    thr = _roc_threshold(p, y)
    assert 0.3 < thr <= 0.75                # 完全可分：Youden J 主路径的分割点
    assert _roc_threshold(p, np.ones(10)) == 0.5   # 单类标签 → 回退 0.5


def test_thresholds_from_trailing_pairs():
    """偏差⑨（T13/评审 I5 口径，用户追认 I-7）：阈值来自 trailing 实际
    （预测,已实现标签）对——<26 对每资产回退 0.5；可分对阈值落在 (0,1)。"""
    rng = np.random.default_rng(4)
    L = 3
    pairs = []
    for _ in range(30):
        pred = rng.random(L)
        pairs.append((pred, (pred > 0.5).astype(float)))   # 完全可分
    th = thresholds_from_pairs(pairs, L)
    assert th.shape == (L,) and ((th > 0) & (th < 1)).all()
    assert (thresholds_from_pairs(pairs[:10], L) == 0.5).all()   # <26 回退
    st = ROCState()
    st.pairs.extend(pairs + pairs)                    # 60 对 → maxlen=52 截断
    assert len(st.pairs) == 52


def test_mimo_seed_deterministic():
    """可复现性：同数据两个全新实例 → 连续三周 select 输出逐位一致
    （含 ROC 状态演化的确定性）。"""
    wf = toy_wf(T=180, seed=11)
    m1 = MIMOModel(window=13).fit(wf, 170)
    m2 = MIMOModel(window=13).fit(wf, 170)
    assert ([m1.select(wf, t) for t in (171, 172, 173)]
            == [m2.select(wf, t) for t in (171, 172, 173)])


def test_mimo_feature_boundary_uses_decision_close():
    """I-3 修正的边界锁：决策 t 的特征块 = [t-window+1, t]——t 之后的数据
    翻转不影响 t 决策；翻转 t 自身收盘则特征块必变。"""
    T = 180
    rng = np.random.default_rng(9)
    idx1 = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, 2)), axis=0)
    idx1_late = idx1.copy()
    idx1_late[171:] = 1.0                            # t 之后全变垃圾
    idx3 = idx1.copy()
    idx3[170] = idx1[170] * 0.5                      # 只翻 t=170 收盘
    close = 1 + rng.normal(0, 0.03, (T, 2))
    v = np.ones((T, 2), bool)
    v[-1] = False
    wf1 = _frame(T, v, close, idx=idx1)
    wf1l = _frame(T, v, close, idx=idx1_late)
    wf3 = _frame(T, v, close, idx=idx3)
    m1 = MIMOModel(window=13).fit(wf1, 170)
    m1l = MIMOModel(window=13).fit(wf1l, 170)
    assert m1.select(wf1, 170) == m1l.select(wf1l, 170)     # 171+ 无关
    b3, t_idx3 = window_blocks(wf3, window=13, upto=171, include_t=True)
    b1, _ = window_blocks(wf1, window=13, upto=171, include_t=True)
    assert t_idx3[-1] == 170 and not np.allclose(b3[-1], b1[-1])  # x_now 含 t 收盘


def test_mimo_learns_alternating_regime():
    """可学习性冒烟（open→close 标签版，偏差⑦）：A 资产偶数周执行窗 +5%、
    奇数周 -5%，特征=交替收盘模式（偶 90/奇 110）——训练行 tj≤194 学到
    「特征末值 90 → 该行执行窗 +5%」，决策偶数周应选中 A 而非 B（B 平价
    标签恒 0）。"""
    T = 200
    idx = np.zeros((T, 2))
    lab_ret = np.zeros((T, 2))
    for t in range(T):
        idx[t] = [90.0 if t % 2 == 0 else 110.0, 100.0]
        lab_ret[t] = [0.05 if t % 2 == 0 else -0.05, 0.0]
    v = np.ones((T, 2), bool)
    v[-1] = False
    wf = _frame(T, v, 1 + lab_ret, idx=idx)   # _frame 的 etf_open=1 → 执行周收益=lab_ret
    m = MIMOModel(window=13).fit(wf, 195)
    sel = m.select(wf, 196)                   # 偶数周决策：行 196 执行窗 +5%
    assert 0 in sel and sel.get(1, 0.0) <= sel[0]


def test_mimo_fit_requires_min_history():
    wf = toy_wf(T=20)
    try:
        MIMOModel(window=13).fit(wf, 19)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_mimo_roc_backfill_stateful_and_shared():
    """偏差⑨回填协议：select(t) 先把上周 (预测, 已实现标签) 入缓冲——标签 =
    执行周 open→close（决策时点 t 已实现，无泄漏）；状态对象跨实例共享
    （年冻结模型跨年携带）。"""
    wf = toy_wf(T=180, seed=5)
    st = ROCState()
    m1 = MIMOModel(window=13).fit(wf, 170)
    m1.select(wf, 171, roc=st)
    assert len(st.pairs) == 0                 # 首周无上周可回填
    m1.select(wf, 172, roc=st)
    assert len(st.pairs) == 1                 # 回填 (171 的预测, 171 执行周标签)
    pred, lab = st.pairs[0]
    assert pred.shape == lab.shape == (2,)
    np.testing.assert_allclose(lab, (weekly_gross_returns(wf)[171] >= 0.01))
    m2 = MIMOModel(window=13).fit(wf, 170)    # 年冻结驱动模式：新实例接续同一缓冲
    m2.select(wf, 173, roc=st)
    assert len(st.pairs) == 2


def test_make_strategy_l2_protocol_error():
    """L2 不走 per-call 重训协议：年冻结模型由 repro_paper.py 驱动，
    make_strategy("L2") 构造时即报错指路（计划评审 I-3）。"""
    with pytest.raises(ValueError, match="MIMOModel"):
        make_strategy("L2")
