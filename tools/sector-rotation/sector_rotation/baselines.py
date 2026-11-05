# tools/sector-rotation/sector_rotation/baselines.py
"""对照组与 L0（spec §3.4/§3.8）。只选当周 valid（point-in-time 宇宙）成员。"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame


def _valid(wf: WeeklyFrame, t: int) -> list[int]:
    return [i for i in range(len(wf.members)) if wf.valid[t, i]]


class EqualWeightAnnual:
    """对照①（spec §3.8 + 评审 C5）：等权持有当周 valid 全体；**年再平衡 + 宇宙时变
    驱动**（成员集变化周被迫调仓），其余周返回上周权重原值——引擎按净换手计费，
    持有周成本 ≈ 0，不给对照制造幻影换手。"""

    def __init__(self) -> None:
        self.last: dict[int, float] | None = None
        self.last_year: int | None = None

    def __call__(self, wf: WeeklyFrame, t: int) -> dict[int, float]:
        cols = _valid(wf, t)
        year = int(wf.fridays[t][:4])
        if (self.last is None or year != self.last_year
                or set(self.last) != set(cols)):
            self.last = {i: 1.0 / len(cols) for i in cols} if cols else {}
            self.last_year = year
        return dict(self.last)


def _rank_topk(wf: WeeklyFrame, t: int, *, lookback: int, k: int,
               reverse: bool) -> dict[int, float]:
    cols = _valid(wf, t)
    rets = {i: wf.index_close[t, i] / wf.index_close[t - lookback, i] - 1.0
            for i in cols
            if t - lookback >= 0 and np.isfinite(wf.index_close[t - lookback, i])}
    ranked = sorted(rets, key=lambda i: rets[i], reverse=reverse)
    picked = ranked[:k]
    return {i: 1.0 / len(picked) for i in picked} if picked else {}


def momentum_topk(wf: WeeklyFrame, t: int, *, lookback: int = 1, k: int = 3
                  ) -> dict[int, float]:
    return _rank_topk(wf, t, lookback=lookback, k=k, reverse=True)


def reversal_topk(wf: WeeklyFrame, t: int, *, lookback: int = 1, k: int = 3
                  ) -> dict[int, float]:
    return _rank_topk(wf, t, lookback=lookback, k=k, reverse=False)


def random_k(wf: WeeklyFrame, t: int, *, k: int = 3, seed: int = 0
             ) -> dict[int, float]:
    cols = _valid(wf, t)
    if not cols:
        return {}
    rng = np.random.default_rng(seed * 10_000 + t)
    picked = list(rng.choice(cols, size=min(k, len(cols)), replace=False))
    return {i: 1.0 / len(picked) for i in picked}
