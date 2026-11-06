# tools/sector-rotation/sector_rotation/weekly.py
"""特征窗口与标签（spec §3.3，v1.2 I-4：标准化只进训练窗统计）。"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame


def weekly_gross_returns(wf: WeeklyFrame) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        r = wf.etf_close / wf.etf_open - 1.0
    return np.where(np.isfinite(r), r, np.nan)


def window_blocks(wf: WeeklyFrame, *, window: int = 13, cols=None, upto=None,
                  include_t: bool = False
                  ) -> tuple[np.ndarray, np.ndarray]:
    """cols：资产子集（None=全体）；upto：只取 tj < upto（None=全帧）；
    include_t：特征块含决策周 t 自身收盘（[t-window+1, t]，R20261106-02 论文
    「周五收盘后采样」口径，修 v2 评审 I-3 滞后一档）——默认 False 保持
    [t-window, t) 原口径，L1 既有行为零变化。

    v2（R20261105-02）子集口径：全市场口径在 point-in-time 覆盖增长宇宙
    （416 成员 10→416 增长、峰值 65%）下无任何一行全体齐备 → t_idx 恒空
    → L1 策略恒 {}（真实数据冒烟实测）——消费端按当周 M_t 子集调用。"""
    mat = wf.index_close if cols is None else wf.index_close[:, cols]
    ok = np.isfinite(mat).all(axis=1)
    stop = len(wf.fridays) if upto is None else upto
    first = window - 1 if include_t else window
    feats, t_index = [], []
    for t in range(first, stop):
        rows = (np.arange(t - window + 1, t + 1) if include_t
                else np.arange(t - window, t))
        if ok[rows].all():
            feats.append(mat[rows, :].reshape(-1))
            t_index.append(t)
    return np.array(feats, dtype=float), np.array(t_index, dtype=int)


def standardize_fit_apply(blocks_train: np.ndarray, blocks_now: np.ndarray
                          ) -> np.ndarray:
    mu = blocks_train.mean(axis=0)
    sd = blocks_train.std(axis=0)
    sd = np.where((~np.isfinite(sd)) | (sd == 0), 1.0, sd)
    return (blocks_now - mu) / sd
