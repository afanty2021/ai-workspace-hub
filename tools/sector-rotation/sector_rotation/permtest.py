# tools/sector-rotation/sector_rotation/permtest.py
"""检验矩阵实现（spec §3.8）：置换检验 + block bootstrap 配对。"""
from __future__ import annotations

import numpy as np

from .baselines import random_k
from .cost import CostModel
from .data import WeeklyFrame
from .walkforward import run_walkforward


def perm_test_vs_random(wf: WeeklyFrame, cost: CostModel, *, k: int, n: int = 1000,
                        strategy=None, start: int | None = None,
                        end: int | None = None) -> dict:
    obs = run_walkforward(wf, strategy or (lambda w, t: random_k(w, t, k=k, seed=0)),
                          cost=cost, start=start, end=end)
    rand = np.array([
        run_walkforward(wf, lambda w, t, s=seed: random_k(w, t, k=k, seed=s),
                        cost=cost, start=start, end=end).metrics["cagr"]
        for seed in range(n)])
    p = float((1 + (rand >= obs.metrics["cagr"]).sum()) / (1 + n))
    return {"observed_cagr": obs.metrics["cagr"], "p_value": p,
            "random_cagr_mean": float(rand.mean()),
            "random_cagr_p95": float(np.percentile(rand, 95)), "n_random": n}


def paired_block_bootstrap(diff: np.ndarray, *, block: int = 4, n: int = 1000,
                           seed: int = 0) -> float:
    """H0: 配对周差均值 ≤ 0。评审 C2：必须在 H0 下**重定心**——对 diff − obs_mean
    重抽，p = P(boot_mean ≥ obs_mean)；未重定心版 p 数学收敛 ~0.5，检验矩阵第
    2-4 行全体失效（数值验证：正效应数据 plan_p≈0.5 / 重定心版 p≈0.01）。"""
    diff = np.asarray(diff, dtype=float)
    diff = diff[np.isfinite(diff)]
    if len(diff) < block:
        return float("nan")
    rng = np.random.default_rng(seed)
    centered = diff - diff.mean()
    obs_mean = diff.mean()
    n_blocks = int(np.ceil(len(diff) / block))
    count = 0
    for _ in range(n):
        idx = rng.integers(0, len(diff) - block + 1, size=n_blocks)
        sample = np.concatenate([centered[i:i + block] for i in idx])[:len(diff)]
        if sample.mean() >= obs_mean:
            count += 1
    return float((1 + count) / (1 + n))
