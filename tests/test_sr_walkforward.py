# tests/test_sr_walkforward.py
from datetime import date, timedelta

import numpy as np
import pytest

from sector_rotation.baselines import EqualWeightAnnual, momentum_topk
from sector_rotation.cost import CostModel
from sector_rotation.data import WeeklyFrame
from sector_rotation.permtest import paired_block_bootstrap, perm_test_vs_random
from sector_rotation.universe import Member, UniverseSpec
from sector_rotation.walkforward import coverage_start, run_walkforward

M2 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})
_T0 = date(2024, 1, 5)      # ISO 周五：RiskState/EqualWeightAnnual 依赖 YYYY 前缀


def _fridays(T: int) -> list[str]:
    return [(_T0 + timedelta(weeks=i)).isoformat() for i in range(T)]


def _wf(T=30, seed=5, valid=None):
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.002, 0.02, (T, 2)), axis=0)
    v = np.ones((T, 2), bool) if valid is None else valid
    v[-1, :] = False
    return WeeklyFrame(_fridays(T), idx,
                       [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                       1 + rng.normal(0.001, 0.02, (T, 2)), np.ones((T, 2)),
                       np.full((T, 2), 2e8), M2, SPEC, v, v.copy(), np.full(T, 0.001))


def test_coverage_start_finds_first_week_meeting_min_universe():
    v = np.zeros((20, 2), bool)
    v[10:, :] = True                        # 第 10 周起 2 行业全部可用
    assert coverage_start(_wf(T=20, valid=v), min_universe=2) == 10


def test_walkforward_runs_real_path_with_iso_fridays():
    """修复轮1：显式 start=0 走真实路径（默认 min_universe=50 对 2 成员回退末行
    空转），ISO fridays 供 RiskState.apply 解年份。"""
    wf = _wf()
    res = run_walkforward(wf, momentum_topk, cost=CostModel.base(), start=0)
    assert res.nav[0] == 1.0 and len(res.nav) == len(res.weekly) + 1
    assert len(res.weekly) > 0                    # 修复轮1：锁非零周数，非空洞通过
    assert len(res.t_rows) == len(res.weekly)     # 评审 C4：行号账本等长
    assert all(set(tr["holdings"]) <= {0, 1} for tr in res.trades)


def test_drift_update_skips_blocked_member_no_keyerror():
    """修复轮1 Critical：blocked（missing 闸门）成员不在 gross_pos（executed）里，
    漂移更新必须按 gross_pos 键迭代——旧实现按 weights_new 迭代即 KeyError。
    价格取确定性 +1%/周，避开 RiskState 的 halved/banned 随机分支。"""
    T = 3
    open_ = np.ones((T, 2))
    open_[0, 0] = np.nan                      # 第 0 周成员 0 触发 missing 拦截
    close = np.full((T, 2), 1.01)             # 每成员每周 open→close +1%
    wf = WeeklyFrame(_fridays(T), np.full((T, 2), 100.0),
                     [["EA.SH", "EB.SH"]] * T, open_, close, np.ones((T, 2)),
                     np.full((T, 2), 2e8), M2, SPEC,
                     np.ones((T, 2), bool), np.ones((T, 2), bool), np.full(T, 0.001))
    res = run_walkforward(wf, lambda w, t: {0: 0.5, 1: 0.5},
                          cost=CostModel.base(), start=0)
    assert res.trades[0]["blocked"] == {0: "missing"}
    assert len(res.weekly) == 3 and res.nav[0] == 1.0
    assert 0.0 < res.weekly[0] < 0.01         # 第 0 周照常出收益（仅成员 1 的 1% 的一半）
    # 漂移只含 executed 键：成员 0 第 1 周全额重新建仓 → 换手 ≥ 其权重
    assert res.trades[1]["detail"]["turnover"] > 0.49


@pytest.mark.filterwarnings("ignore:Mean of empty slice:RuntimeWarning")
@pytest.mark.filterwarnings("ignore:invalid value encountered in divide:RuntimeWarning")
@pytest.mark.filterwarnings("ignore:invalid value encountered in scalar divide:RuntimeWarning")
@pytest.mark.filterwarnings("ignore:Degrees of freedom <= 0 for slice:RuntimeWarning")
def test_min_universe_passthrough_prevents_collapse():
    """R20261106-02 §7：11 成员宇宙下默认 min_universe=50 令 coverage_start 回退
    末行（空转）；透传 min_universe=1 后从首个有效周正常起跑。
    默认档空转走 metrics 空数组路径，4 类 RuntimeWarning 为该档预期输出，
    就地屏蔽（GC 2 输出干净）——断言与既有行为锁不动。"""
    wf = _wf(T=30)                                   # 2 成员全 valid（末行除外）
    res_def = run_walkforward(wf, momentum_topk, cost=CostModel.base(),
                              min_universe=50)       # 回退 start=29 → 第 29 周无 valid → 空转
    assert len(res_def.t_rows) == 0
    res = run_walkforward(wf, momentum_topk, cost=CostModel.base(), min_universe=1)
    assert len(res.t_rows) == 29


def test_paired_block_bootstrap_positive_and_negative():
    """评审 C2：重定心版——正效应 p<0.1、负效应 p 接近 1（未重定心版两者都 ≈0.5）。"""
    rng = np.random.default_rng(1)
    assert paired_block_bootstrap(rng.normal(0.002, 0.01, 300),
                                  block=4, n=500) < 0.1
    assert paired_block_bootstrap(rng.normal(-0.002, 0.01, 300),
                                  block=4, n=500) > 0.9


def test_perm_test_p_in_range():
    wf = _wf(T=40)
    res = run_walkforward(wf, EqualWeightAnnual(), cost=CostModel.base(), start=0)
    assert len(res.weekly) > 0                # 修复轮1：锁 EqualWeightAnnual 真被调用
    out = perm_test_vs_random(wf, CostModel.base(), k=1, n=30,
                              strategy=EqualWeightAnnual(), start=0)
    assert 0 <= out["p_value"] <= 1 and out["n_random"] == 30
