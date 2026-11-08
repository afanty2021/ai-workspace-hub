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
                  include_t: bool = False,
                  with_volume: bool = False
                  ) -> tuple[np.ndarray, np.ndarray]:
    """cols：资产子集（None=全体）；upto：只取 tj < upto（None=全帧）；
    include_t：特征块含决策周 t 自身收盘（[t-window+1, t]，R20261106-02 论文
    「周五收盘后采样」口径，修 v2 评审 I-3 滞后一档）——默认 False 保持
    [t-window, t) 原口径，L1 既有行为零变化。

    with_volume（偏差⑫，2026-11-07 论文原文核对轮）：特征块追加 volume 列
    （wf.etf_volume，与 index_close 同一数据行）——行块展平为
    [price 窗展平, volume 窗展平]，维度 N×2L = 论文脚注「N × (2l+m) if ETF
    volumes are used」的 2l 读法；volume 缺失周视为特征不齐备（与价格同
    ok 判定）。默认 False 纯价格，既有行为位级不变。

    v2（R20261105-02）子集口径：全市场口径在 point-in-time 覆盖增长宇宙
    （416 成员 10→416 增长、峰值 65%）下无任何一行全体齐备 → t_idx 恒空
    → L1 策略恒 {}（真实数据冒烟实测）——消费端按当周 M_t 子集调用。"""
    mat = wf.index_close if cols is None else wf.index_close[:, cols]
    ok = np.isfinite(mat).all(axis=1)
    vol = None
    if with_volume:
        if wf.etf_volume is None:
            raise ValueError("with_volume 需要 wf.etf_volume（build_weekly_frame "
                             "构造；美股域 sector/series 含 volume 字段）")
        vol = wf.etf_volume if cols is None else wf.etf_volume[:, cols]
        ok = ok & np.isfinite(vol).all(axis=1)
    stop = len(wf.fridays) if upto is None else upto
    first = window - 1 if include_t else window
    feats, t_index = [], []
    for t in range(first, stop):
        rows = (np.arange(t - window + 1, t + 1) if include_t
                else np.arange(t - window, t))
        if ok[rows].all():
            block = mat[rows, :].reshape(-1)
            if vol is not None:
                block = np.concatenate([block, vol[rows, :].reshape(-1)])
            feats.append(block)
            t_index.append(t)
    return np.array(feats, dtype=float), np.array(t_index, dtype=int)


def standardize_fit_apply(blocks_train: np.ndarray, blocks_now: np.ndarray
                          ) -> np.ndarray:
    mu = blocks_train.mean(axis=0)
    sd = blocks_train.std(axis=0)
    sd = np.where((~np.isfinite(sd)) | (sd == 0), 1.0, sd)
    return (blocks_now - mu) / sd
