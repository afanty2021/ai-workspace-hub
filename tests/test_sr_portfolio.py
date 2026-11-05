# tests/test_sr_portfolio.py
import numpy as np

from sector_rotation.cost import CostModel
from sector_rotation.data import WeeklyFrame
from sector_rotation.portfolio import RiskState, simulate_week
from sector_rotation.universe import Member, UniverseSpec

M4 = [Member("A1", "光伏", ("E1.SH",), 0.10), Member("A2", "风电", ("E2.SH",), 0.10),
      Member("A3", "储能", ("E3.SH",), 0.10), Member("B1", "银行", ("E4.SH",), 0.10)]
SPEC = UniverseSpec(M4, {2019: {"A1": "s", "A2": "s", "A3": "s", "B1": "o"}})


def _wf(open_, close_, prev_close, week_amount=None, valid=None, fridays=None):
    # 默认 friday 取 ≥2021 年（评审 C8：2019 代簇 2021 年起可用，cap 测试才成立）
    T, L = open_.shape
    v = np.ones((T, L), bool) if valid is None else valid
    return WeeklyFrame(
        fridays=fridays or ["2021-06-04"] * T, index_close=np.ones((T, L)),
        etf_symbols=[["E1.SH", "E2.SH", "E3.SH", "E4.SH"]] * T,
        etf_open=open_, etf_close=close_, etf_prev_close=prev_close,
        etf_week_amount=week_amount if week_amount is not None
        else np.full((T, L), 2e8),
        members=M4, spec=SPEC, valid=v, dvalid=v.copy(),
        bench_300=np.full(T, 0.0))


def test_cluster_cap_holds_cash_not_renormalized():
    rs = RiskState(SPEC)
    wf = _wf(np.full((1, 4), 1.0), np.full((1, 4), 1.01), np.full((1, 4), 0.99))
    got = rs.apply(0, wf, {0: 1 / 3, 1: 1 / 3, 2: 1 / 3}, None)
    same = [i for i in got if SPEC.clusters[2019][f"A{i + 1}"] == "s"]
    assert len(same) == 2 and rs.binds == 1
    assert sum(got.values()) < 1.0 - 1e-9      # 截断资金持币（每权 1/3，剩 2/3）


def test_no_cluster_generation_skips_constraint():
    rs = RiskState(SPEC)
    wf = _wf(np.full((1, 4), 1.0), np.full((1, 4), 1.01), np.full((1, 4), 0.99),
             fridays=["2018-06-01"])           # 2019 代 2021 年才可用
    got = rs.apply(0, wf, {0: 0.25, 1: 0.25, 2: 0.25}, None)
    assert len(got) == 3 and rs.binds == 0


def test_limit_up_blocks_buy_and_weekly_liquidity_gate():
    wf = _wf(np.array([[1.10, 1.0]]), np.array([[1.10, 1.02]]),
             np.array([[1.0, 1.0]]),
             week_amount=np.array([[2e8, 3e7]]))    # 2 号周内均额 3000 万 <5000 万
    net, pos, detail = simulate_week(wf, 0, {}, {0: 0.5, 1: 0.5}, CostModel.base())
    assert 0 not in pos and detail["blocked"][0] == "limit_up"
    assert 1 not in pos and detail["blocked"][1] == "liquidity"


def test_missing_open_blocks_buy():
    """执行注：etf_open 为 nan 的 missing 情形单独记 blocked='missing'。"""
    wf = _wf(np.array([[np.nan]]), np.array([[1.02]]), np.array([[1.0]]))
    _, pos, detail = simulate_week(wf, 0, {}, {0: 1.0}, CostModel.base())
    assert 0 not in pos and detail["blocked"][0] == "missing"


def test_simulate_week_net_turnover_costs():
    """评审 C1+C5：建仓只付单边 11bp；持有过周末（同权重再入选）成本 ≈ 0。"""
    wf = _wf(np.array([[1.0]]), np.array([[1.10]]), np.array([[0.99]]))
    net, pos, detail = simulate_week(wf, 0, {}, {0: 1.0}, CostModel.base())
    assert abs(pos[0] - 0.10) < 1e-12
    assert abs(detail["costs"] - CostModel.base().side_bps() / 1e4) < 1e-12
    assert abs(net - (0.10 - CostModel.base().side_bps() / 1e4)) < 1e-9
    wf2 = _wf(np.array([[1.0]]), np.array([[1.05]]), np.array([[0.99]]))
    _, _, detail2 = simulate_week(wf2, 0, {0: 1.0}, {0: 1.0}, CostModel.base())
    assert detail2["costs"] == 0.0


def test_drawdown_halves_and_absolute_loss_halts():
    """评审 I2：§3.6 风控表六条补全——回撤 ≥8% 降半仓、绝对亏损 ≥10% 全停。"""
    rs = RiskState(SPEC)
    wf = _wf(np.full((3, 4), 1.0), np.full((3, 4), 1.01), np.full((3, 4), 1.0),
             fridays=["2021-01-08", "2021-06-04", "2021-12-31"])
    assert rs.apply(0, wf, {0: 0.5}, None, nav=1.0) == {0: 0.5}
    got = rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.91)   # 回撤 9% → 半仓
    assert got == {0: 0.25} and rs.halved
    got = rs.apply(2, wf, {0: 0.5}, {0: 0.01}, nav=0.89)   # 绝对亏损 11% → 全停
    assert got == {} and rs.halted


def test_consecutive_loss_weeks_pause():
    rs = RiskState(SPEC)
    wf = _wf(np.full((5, 4), 1.0), np.full((5, 4), 0.99), np.full((5, 4), 1.0),
             fridays=[f"2020-01-{i:02d}" for i in range(1, 6)])
    out = {0: 0.5}
    for t in range(4):
        out = rs.apply(t, wf, {0: 0.5}, {0: -0.01})
    assert out == {}


# ---- S6-A 探针重启（spec v1.2.3 §3.6：全停从吸收态改滞回态）----

FRIDAYS16 = [f"2021-01-{d:02d}" for d in range(1, 10)] + [f"2021-01-{d:02d}" for d in range(10, 17)]


def _wf16():
    return _wf(np.full((16, 4), 1.0), np.full((16, 4), 1.01), np.full((16, 4), 1.0),
               fridays=FRIDAYS16)


def test_halt_probe_restart_confirms():
    """触发 → N=8 周持币 → f=0.5 探针 M=4 周 → 探针期收益 ≥0 确认。
    确认后回到常规风控域：仍低于年内高点 → 回撤减半规则接手（0.5 仓），
    创新高后恢复满仓（§3.6 级联）。"""
    rs = RiskState(SPEC, halt_wait_weeks=8, probe_frac=0.5, probe_confirm_weeks=4)
    wf = _wf16()
    assert rs.apply(0, wf, {0: 0.5}, None, nav=1.00) == {0: 0.5}      # 正常
    assert rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.89) == {}       # 触发（当周计入持币 1/8）
    for t in range(2, 9):                                             # 持币 2..8/8 周
        assert rs.apply(t, wf, {0: 0.5}, None, nav=0.88) == {}
    got = rs.apply(9, wf, {0: 0.5}, None, nav=0.88)                   # 第 9 周 = 探针第 1 周
    assert got == {0: 0.25} and rs.probing                            # f=0.5 缩放（探针期不看绝对线）
    for t, nav in ((10, 0.885), (11, 0.89), (12, 0.90)):              # 探针 2..4 周（滞回态）
        assert rs.apply(t, wf, {0: 0.5}, None, nav=nav) == {0: 0.25}
    got = rs.apply(13, wf, {0: 0.5}, None, nav=0.93)                  # 探针期 0.88→0.93 ≥0 确认
    assert got == {0: 0.25} and not rs.halted and not rs.probing      # 停机解除；减半规则接手
    assert rs.halved
    got = rs.apply(14, wf, {0: 0.5}, None, nav=1.01)                  # 创年内新高 → 满仓
    assert got == {0: 0.5} and not rs.halved
    assert rs.halt_events == ["2021-01-02"]                           # 触发日志恰一条


def test_halt_probe_restart_rejects_and_recycles():
    """探针 M 周收益 <0 → 否决回停机，重走 N 周等待后可再次探针（循环不限次）。"""
    rs = RiskState(SPEC, halt_wait_weeks=4, probe_frac=0.5, probe_confirm_weeks=2)
    wf = _wf16()
    rs.apply(0, wf, {0: 0.5}, None, nav=1.00)
    rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.85)                    # 触发
    for t in range(2, 5):                                             # 持币 2..4/4
        rs.apply(t, wf, {0: 0.5}, None, nav=0.85)
    assert rs.apply(5, wf, {0: 0.5}, None, nav=0.85) == {0: 0.25}     # 探针 1/2
    assert rs.apply(6, wf, {0: 0.5}, None, nav=0.84) == {0: 0.25}     # 探针 2/2（跌）
    got = rs.apply(7, wf, {0: 0.5}, None, nav=0.83)                   # 0.85→0.83 <0 否决
    assert got == {} and rs.halted and not rs.probing and rs.halt_rejects == 1
    for t in range(8, 11):                                            # 第二轮持币
        rs.apply(t, wf, {0: 0.5}, None, nav=0.83)
    assert rs.apply(11, wf, {0: 0.5}, None, nav=0.83) == {0: 0.25}    # 再次探针（循环不限次）


def test_probe_params_invariant_when_never_halted():
    """从未触发的路径与 (N, f, M) 参数无关——网格选择只对触发格有区分度。"""
    wf = _wf(np.full((6, 4), 1.0), np.full((6, 4), 1.01), np.full((6, 4), 1.0),
             fridays=[f"2021-02-{d:02d}" for d in range(1, 7)])
    outs = []
    for kwargs in ({}, dict(halt_wait_weeks=4, probe_frac=0.25, probe_confirm_weeks=2)):
        rs = RiskState(SPEC, **kwargs)
        outs.append([rs.apply(t, wf, {0: 0.4, 3: 0.6}, None, nav=1.0 + 0.001 * t)
                     for t in range(6)])
    assert outs[0] == outs[1]
