"""回测指标（spec §3.8；sharpe 零波动约定 nan）。"""
from __future__ import annotations

import numpy as np


def compute_metrics(nav: np.ndarray, weekly_ret: np.ndarray, *,
                    benchmark_nav: np.ndarray | None = None,
                    turnover: float = 0.0, cost_drag: float = 0.0,
                    cluster_binds: int = 0, weeks_per_year: int = 52) -> dict[str, float]:
    years = len(weekly_ret) / weeks_per_year
    cagr = float(nav[-1] / nav[0]) ** (1 / years) - 1 if years > 0 else 0.0
    if benchmark_nav is not None:
        bench = float(benchmark_nav[-1] / benchmark_nav[0]) ** (1 / years) - 1
        alpha = cagr - bench
    else:
        alpha = 0.0
    mu, sd = float(np.mean(weekly_ret)), float(np.std(weekly_ret, ddof=1))
    sharpe = float(mu / sd * np.sqrt(weeks_per_year)) if sd > 0 else float("nan")
    peak = np.maximum.accumulate(nav)
    return {"cagr": cagr, "alpha": alpha, "sharpe": sharpe,
            "max_dd": float((nav / peak - 1.0).min()),
            "win_rate": float((weekly_ret > 0).mean()),
            "turnover": turnover, "cost_drag": cost_drag,
            "cluster_binds": float(cluster_binds)}
