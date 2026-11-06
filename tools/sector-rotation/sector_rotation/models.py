# tools/sector-rotation/sector_rotation/models.py
"""L1（torch 线性）与 L2（MIMO 复刻）策略（spec §3.4；v2 复活 T12 设计）。

结构修正两层（T12 carry Ruling 2026-11-05 + v2 扩展 2026-11-06 真实数据
冒烟实证）：①训练行不要求全成员 valid；②资产子集 M_t = 当周窗口特征齐备
且 valid 的成员——全市场 window_blocks 口径在 point-in-time 覆盖增长宇宙
（416 成员、无任何一行全体齐备）下 t_idx 恒空、策略恒 {}。标签按当周
per-asset valid 掩码（masked-mean BCE）。

口径注：①训练=决策帧向前 104 周全量重训（论文为增量更新；小模型成本等价
更干净）；②标准化 mu/sd 只来自训练切片（v1.2 I-4）；③金融损失 = masked
BCE + λ·masked(-(sigmoid·下周收益))——论文未给公式（spec §8-2 待验证），
实现方口径，λ 消融验证；④训练强制 CPU + 每次 fit 前重置全局 seed（v2
预注册可复现性，R20261105-02）；⑤L2 占位（仅 L1 过闸后实现，spec §5）；
⑥特征窗 [t-window, t) 不含决策周五收盘 t——比 L0 动量（index_close[t]/
index_close[t-1]）与论文「周五收盘后采样」口径滞后一档；训练/推断一致故
非泄漏，但 vs L0 对照中 L1 信息集结构性少一周（v2 评审 I-3；v2 已按此口径
结案，v3 重启需重钉边界）；⑦M_t 联合齐备约束：新成员入集把联合齐备训练史
拖到自身起点，宇宙扩张周训练行坍缩——实测 OOS 尾部 2026-08-28→11-05 连续
12 周不足 window+2 门槛转持币（v2 评审 I-4 实测；v3 需成员最短历史门槛或
per-member 特征可得性设计）。
"""
from __future__ import annotations

import numpy as np

from .data import WeeklyFrame
from .weekly import standardize_fit_apply, weekly_gross_returns, window_blocks

TRAIN_WEEKS = 104
LAMBDA_FIN = 0.1
SEED = 20261105


def _torch():
    import torch
    torch.manual_seed(SEED)              # v2 可复现性：每次取 torch 前重置种子
    return torch


def _modelable(wf: WeeklyFrame, t: int, *, window: int) -> np.ndarray:
    """决策周 t 的 point-in-time 资产子集 M_t：指数窗口特征齐备且当周 valid。"""
    if t < window:
        return np.zeros(len(wf.members), bool)
    feat_ok = np.isfinite(wf.index_close[t - window:t]).all(axis=0)
    return feat_ok & wf.valid[t]


def _prep(wf: WeeklyFrame, t: int, *, window: int):
    """→ (X_train_std, y_train, r_train, x_now_std, cols) | None。

    结构修正两层（T12 carry Ruling + v2 扩展，2026-11-06 真实数据冒烟实证）：
    ①训练行不要求全成员 valid（原 wf.valid[tj].all() 在稀疏覆盖下恒空）；
    ②资产子集 M_t = 当周窗口特征齐备且 valid 的成员——全市场 window_blocks
    口径在 point-in-time 覆盖增长宇宙（416 成员峰值 65%）下 t_idx 恒空、
    策略恒 {}。训练行 = M_t 固定子集上整窗齐备的历史周（市场快照无 NaN），
    向前至多 TRAIN_WEEKS 周；标签/收益在 per-asset invalid 或缺失周置 NaN
    （fit 内 masked-mean，零贡献）；标准化只来自训练切片。
    """
    m = _modelable(wf, t, window=window)
    if not m.any():
        return None
    cols = np.flatnonzero(m)
    blocks, t_idx = window_blocks(wf, window=window, cols=cols, upto=t)
    if len(t_idx) < window + 2:
        return None
    take = t_idx[-TRAIN_WEEKS:]
    sub_r = weekly_gross_returns(wf)[np.ix_(take, cols)]
    lab_ok = wf.valid[np.ix_(take, cols)] & np.isfinite(sub_r)
    y = np.where(lab_ok, sub_r >= 0.01, np.nan).astype(np.float32)
    r = np.where(lab_ok, sub_r, np.nan).astype(np.float32)
    train = blocks[-len(take):]                    # blocks 行序与 t_idx 一一对应
    X_train = standardize_fit_apply(train, train)
    x_now = standardize_fit_apply(
        train, wf.index_close[t - window:t][:, cols].reshape(-1)[None, :])[0]
    return (X_train, y, r, x_now, cols)


class LinearModel:
    def __init__(self, *, window: int = 13, epochs: int = 100, lr: float = 1e-2,
                 variant: str = "joint"):           # 评审 I4："joint" | "independent"
        self.window, self.epochs, self.lr, self.variant = window, epochs, lr, variant

    def fit(self, blocks: np.ndarray, y: np.ndarray, r: np.ndarray) -> None:
        torch = _torch()
        Xt = torch.tensor(blocks, dtype=torch.float32)
        mask = torch.tensor(np.isfinite(y) & np.isfinite(r), dtype=torch.float32)
        Yt = torch.nan_to_num(torch.tensor(y), nan=0.0)
        Rt = torch.nan_to_num(torch.tensor(r), nan=0.0)
        D, L = blocks.shape[1], y.shape[1]
        if self.variant == "joint":                 # 联合 multi-label 版
            self.nets = [torch.nn.Linear(D, L)]
        else:                                       # I4：每行业独立 sigmoid+BCE
            self.nets = [torch.nn.Linear(D, 1) for _ in range(L)]
        opt = torch.optim.Adam([p for n in self.nets for p in n.parameters()],
                               lr=self.lr)
        bce = torch.nn.BCEWithLogitsLoss(reduction="none")
        denom = mask.sum().clamp(min=1.0)           # masked-mean：无效标签零贡献
        for _ in range(self.epochs):
            opt.zero_grad()
            logits = torch.cat([n(Xt) for n in self.nets], dim=1)
            loss = ((bce(logits, Yt) * mask).sum() / denom
                    - LAMBDA_FIN * (torch.sigmoid(logits) * Rt * mask).sum() / denom)
            loss.backward()
            opt.step()

    def probs_now(self, x: np.ndarray) -> np.ndarray:
        torch = _torch()
        with torch.no_grad():
            z = torch.cat([n(torch.tensor(x, dtype=torch.float32))
                           for n in self.nets], dim=0).numpy()
        return 1.0 / (1.0 + np.exp(-z))

    def select(self, wf: WeeklyFrame, t: int, *, k: int = 3) -> dict[int, float]:
        prep = _prep(wf, t, window=self.window)
        if prep is None:
            return {}
        X, y, r, x_now, cols = prep
        self.fit(X, y, r)
        probs = self.probs_now(x_now)
        order = sorted(range(len(probs)), key=lambda j: -probs[j])[:k]
        return {int(cols[j]): 1.0 / len(order) for j in order} if order else {}


def make_strategy(level: str, *, k: int = 3, window: int = 13,
                  lambda_fin: float = LAMBDA_FIN, mc_dropout: bool = True,
                  roc: bool = True, l1_variant: str = "joint") -> object:
    # window = 特征窗 N（spec §3.3 网格 {8,13,26,52}，I3）；≠ L0 的 lookback（排名回看）。
    if level == "L1":
        strat = LinearModel(window=window, variant=l1_variant)
        return lambda wf, t: strat.select(wf, t, k=k)  # type: ignore[return-value]
    if level == "L2":
        from functools import partial
        return partial(_l2_select, k=k, window=window,
                       lambda_fin=lambda_fin, mc_dropout=mc_dropout, roc=roc)
    raise ValueError(f"未知 level: {level}")


def _l2_select(wf: WeeklyFrame, t: int, *, k: int, window: int,
               lambda_fin: float, mc_dropout: bool, roc: bool) -> dict[int, float]:
    raise NotImplementedError("Task 13 实现（T13 落地为有状态 L2Strategy；仅 L1 过闸后解锁）")
