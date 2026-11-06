# tools/sector-rotation/sector_rotation/walkforward.py
"""walk-forward 引擎（spec §3.8 + 补钉 S5：可用行业数 ≥50 起点，起点晚于 2019-06 功效重估）。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .cost import CostModel
from .data import WeeklyFrame
from .metrics import compute_metrics
from .portfolio import RiskState, WEEKLY_MIN_AMOUNT_WAN, simulate_week


@dataclass
class WalkResult:
    nav: np.ndarray
    nav_gross: np.ndarray
    weekly: np.ndarray
    t_rows: list[int] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)


def coverage_start(wf: WeeklyFrame, *, min_universe: int = 50) -> int:
    counts = wf.valid.sum(axis=1)
    hits = np.flatnonzero(counts >= min_universe)
    return int(hits[0]) if len(hits) else len(wf.fridays) - 1


def run_walkforward(wf: WeeklyFrame, strategy, *, cost: CostModel,
                    start: int | None = None, end: int | None = None,
                    oos_start: int | None = None,
                    risk: RiskState | None = None,
                    min_universe: int = 50,
                    min_amount_wan: float | None = WEEKLY_MIN_AMOUNT_WAN
                    ) -> WalkResult:
    risk = risk or RiskState(wf.spec)
    start = (coverage_start(wf, min_universe=min_universe)
             if start is None else start)
    if oos_start is not None:
        start = max(start, oos_start)
    stop = len(wf.fridays) if end is None else end
    nav, nav_g = [1.0], [1.0]
    weekly, trades, t_rows = [], [], []
    weights_prev: dict[int, float] = {}
    last_pos_returns: dict[int, float] | None = None
    turnover_acc = cost_acc = gross_acc = 0.0
    for t in range(start, stop):
        if not wf.valid[t].any():
            continue
        desired = strategy(wf, t)                    # 评审 I11：callable 协议
        weights_new = risk.apply(t, wf, desired, last_pos_returns, nav=nav[-1])
        net, gross_pos, detail = simulate_week(wf, t, weights_prev, weights_new, cost, min_amount_wan=min_amount_wan)
        weekly.append(net)
        nav.append(nav[-1] * (1 + net))
        nav_g.append(nav_g[-1] * (1 + detail["gross"]))
        turnover_acc += detail["turnover"]
        cost_acc += detail["costs"]
        gross_acc += detail["gross"]
        last_pos_returns = gross_pos or None
        total = 1 + detail["gross"]                  # 评审 C5：上周权重漂移调整
        # 修复轮1（Critical）：漂移只对 executed（gross_pos）成员计——blocked 成员
        # （涨停/低流动/缺数）不在 gross_pos，下周 weights_prev 不含它、按全额买卖
        # 计换手（T9 裁定口径）；total≤0（≤-100% 周）病理情形等价全灭。
        weights_prev = ({i: weights_new[i] * (1 + gross_pos[i]) / total
                         for i in gross_pos} if total > 0 else {})
        t_rows.append(t)
        trades.append({"friday": wf.fridays[t], "holdings": sorted(weights_new),
                       "blocked": detail["blocked"], "detail": detail})
    nav_a, weekly_a = np.array(nav), np.array(weekly)
    metrics = compute_metrics(
        nav_a, weekly_a, turnover=turnover_acc,
        cost_drag=(cost_acc / gross_acc) if gross_acc > 0 else float("nan"),
        cluster_binds=risk.binds)                    # 评审 M7：毛收益 ≤0 时记 nan
    return WalkResult(nav_a, np.array(nav_g), weekly_a, t_rows, metrics, trades)
