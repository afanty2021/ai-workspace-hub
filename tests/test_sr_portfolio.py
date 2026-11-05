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


def test_probe_defaults_frozen():
    """评审 I-4：引擎默认 = spec §6.3 选择窗网格冻结值（N=13/f=0.5/M=4）。
    默认值即预注册参数载体（对照/压力档走 run_walkforward 内部默认构造），
    改动必须随 spec 预注册行同步，本断言防静默漂移。"""
    rs = RiskState(SPEC)
    assert (rs.halt_wait_weeks, rs.probe_frac,
            rs.probe_confirm_weeks) == (13, 0.5, 4)


def test_probe_frac_distinct_from_halved_scale():
    """评审 I-6（M4 变异存活）：探针敞口与回撤减半是两个独立状态。
    f=0.25 且探针周 halved=True（避开与 f=0.5 的数值碰撞盲区）——
    探针周仓位必须 0.5×0.25=0.125；若探针优先级被删（退化成 halved
    的 0.5），将得 0.25 → 本用例红。"""
    rs = RiskState(SPEC, halt_wait_weeks=4, probe_frac=0.25, probe_confirm_weeks=2)
    wf = _wf16()
    rs.apply(0, wf, {0: 0.5}, None, nav=1.00)
    rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.89)        # 触发（0.89 ≤ 0.90）
    for t in range(2, 5):                                 # 持币 2..4/4
        rs.apply(t, wf, {0: 0.5}, None, nav=0.89)
    got = rs.apply(5, wf, {0: 0.5}, None, nav=0.89)       # 探针 1/2
    assert got == {0: 0.125} and rs.probing and rs.halved  # 探针优先级 > halved


def test_probe_confirm_boundary_exact_zero():
    """评审 I-6（M5 变异存活）：判据周 nav == probe_nav0（探针期累计收益恰为 0）
    → 按 spec §3.6「≥0」语义确认恢复；若判据变异成严格 >，此路径错否决。"""
    rs = RiskState(SPEC, halt_wait_weeks=4, probe_frac=0.5, probe_confirm_weeks=2)
    wf = _wf16()
    rs.apply(0, wf, {0: 0.5}, None, nav=1.00)
    rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.85)        # 触发（probe_nav0 将取 0.85）
    for t in range(2, 5):
        rs.apply(t, wf, {0: 0.5}, None, nav=0.85)         # 持币 2..4/4
    assert rs.apply(5, wf, {0: 0.5}, None, nav=0.85) == {0: 0.25}   # 探针 1/2
    rs.apply(6, wf, {0: 0.5}, None, nav=0.85)             # 探针 2/2（持平）
    got = rs.apply(7, wf, {0: 0.5}, None, nav=0.85)       # 收益恰 0 → 确认
    assert got == {0: 0.25} and not rs.halted and not rs.probing


def test_confirm_below_line_disarms_until_recover():
    """Q-20261105-05 拍板 A（边沿触发）：探针确认时 NAV 仍 ≤0.9×锚点 →
    绝对线解除武装（次周不再触发，恢复持续活跃）；NAV 重上锚点线 → 重新武装；
    此后再跌破 → 才再停。替代 level 触发（确认次周即再停的 18 周循环，
    深熊中「恢复满仓」只活 1 周——评审 I-1 实测对靶复现后用户拍板弃用）。"""
    rs = RiskState(SPEC, halt_wait_weeks=4, probe_frac=0.5, probe_confirm_weeks=2)
    wf = _wf(np.full((11, 4), 1.0), np.full((11, 4), 1.01), np.full((11, 4), 1.0),
             fridays=[f"2021-04-{d:02d}" for d in range(1, 12)])
    rs.apply(0, wf, {0: 0.5}, None, nav=1.00)             # start_nav=1.00，线=0.90
    rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.80)        # 触发 #1
    for t in range(2, 5):
        rs.apply(t, wf, {0: 0.5}, None, nav=0.80)         # 持币 2..4/4
    assert rs.apply(5, wf, {0: 0.5}, None, nav=0.80) == {0: 0.25}   # 探针 1/2
    rs.apply(6, wf, {0: 0.5}, None, nav=0.81)             # 探针 2/2
    got = rs.apply(7, wf, {0: 0.5}, None, nav=0.82)       # 0.80→0.82 ≥0 确认（仍 <0.90）
    assert got == {0: 0.25} and not rs.halted and not rs.armed   # 解除武装
    got = rs.apply(8, wf, {0: 0.5}, None, nav=0.82)       # 次周仍在线下 → 不再停
    assert got == {0: 0.25} and not rs.halted and len(rs.halt_events) == 1
    got = rs.apply(9, wf, {0: 0.5}, None, nav=0.95)       # 收复锚点线 → 重新武装
    assert got == {0: 0.25} and rs.armed and not rs.halted  # 0.95<年内高点 1.00 仍半仓；armed 已 True
    got = rs.apply(10, wf, {0: 0.5}, None, nav=0.88)      # 此后再跌破 → 再停 #2
    assert got == {} and rs.halted and len(rs.halt_events) == 2


def test_ytd_high_resets_across_year_during_halt():
    """评审 Minor：停机期跨年 ytd_high 重置——新年首周 nav 成为年内高点基准，
    确认周 nav ≥ 新 ytd_high 时直接满仓（而非被旧年高点的减半规则接手）。"""
    fridays = ["2021-12-17", "2021-12-24", "2021-12-31",
               "2022-01-07", "2022-01-14", "2022-01-21"]
    wf = _wf(np.full((6, 4), 1.0), np.full((6, 4), 1.01), np.full((6, 4), 1.0),
             fridays=fridays)
    rs = RiskState(SPEC, halt_wait_weeks=2, probe_frac=0.5, probe_confirm_weeks=2)
    rs.apply(0, wf, {0: 0.5}, None, nav=1.00)             # 2021 高点 1.00
    rs.apply(1, wf, {0: 0.5}, {0: 0.01}, nav=0.85)        # 触发
    rs.apply(2, wf, {0: 0.5}, None, nav=0.85)             # 持币 2/2
    assert rs.apply(3, wf, {0: 0.5}, None, nav=0.85) == {0: 0.25}   # 探针 1/2（跨年首周）
    assert rs.ytd_year == 2022 and rs.ytd_high == 0.85    # ytd_high 已按新年重置
    rs.apply(4, wf, {0: 0.5}, None, nav=0.86)             # 探针 2/2
    got = rs.apply(5, wf, {0: 0.5}, None, nav=0.86)       # 0.85→0.86 ≥0 确认
    assert got == {0: 0.5} and not rs.halved              # 0.86 ≥ 新高点 0.86 → 满仓
