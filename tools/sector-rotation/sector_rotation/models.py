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

from collections import deque

import numpy as np

from .data import WeeklyFrame
from .weekly import standardize_fit_apply, weekly_gross_returns, window_blocks

TRAIN_WEEKS = 104
LAMBDA_FIN = 0.1
SEED = 20261105
# L2 复刻常量（R20261106-02 §10 预注册；论文 N 缺失 → 网格在消费端声明）
L2_SEED = 20261106
L2_TRAIN_WEEKS = 104                  # 论文「前 2 年历史训练」→ 年模型 104 周冻结
L2_HIDDEN = (64, 32, 16)              # 3 隐层 + 线性输出 = 论文「4 层全连接」
L2_DROPOUT = 0.2
L2_EPOCHS = 200
L2_LR = 1e-3
L2_MC_SAMPLES = 20


def _torch(seed: int = SEED):
    import torch
    torch.manual_seed(seed)            # 每次 fit/推断前重置（v2 可复现性口径）
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


def _roc_threshold(probs: np.ndarray, labels: np.ndarray) -> float:
    """纯函数：数组上的 Youden J 最优分位点；单类/样本过少 → 回退 0.5。
    trailing 对口径经 thresholds_from_pairs 调用（偏差⑨）。"""
    m = np.isfinite(probs) & np.isfinite(labels)
    p, y = probs[m], labels[m]
    if len(p) < 10 or len(np.unique(y)) < 2:
        return 0.5
    best, thr = -1.0, 0.5
    for q in np.unique(np.quantile(p, np.linspace(0.05, 0.95, 19))):
        tpr = float(((p >= q) & (y == 1)).mean())
        fpr = float(((p >= q) & (y == 0)).mean())
        if tpr - fpr > best:
            best, thr = tpr - fpr, float(q)
    return thr


def _confident(samples: np.ndarray, *, mass: float = 0.80) -> np.ndarray:
    """MC dropout 置信（论文 §1.1）：某资产 (T,) 概率样本 ≥80% 落在
    中位数 ±1 总体标准差（ddof=0）内 → 置信。高斯 ≈68% 不过——只有紧于
    高斯的预测分布才可买（论文周均仅买 2.25/11 的机制来源）。"""
    med = np.median(samples, axis=0)
    sd = samples.std(axis=0)
    return (np.abs(samples - med) <= sd).mean(axis=0) >= mass


def thresholds_from_pairs(pairs, n_assets: int, *, min_pairs: int = 26
                          ) -> np.ndarray:
    """T13/评审 I5 口径（R20261106-02 §4 偏差⑨，2026-11-06 用户追认）：
    每资产买入阈值 = trailing 实际（预测, 已实现标签）对的 Youden J；
    有效对 < min_pairs 回退 0.5（年首回退期）。禁用训练窗 in-sample
    拟合概率充数。"""
    out = np.full(n_assets, 0.5)
    if len(pairs) < min_pairs:
        return out
    P = np.stack([p for p, _ in pairs])              # (n, L) 预测（MC 中位）
    Y = np.stack([lb for _, lb in pairs])            # (n, L) 已实现标签（含 NaN）
    for j in range(n_assets):
        m = np.isfinite(P[:, j]) & np.isfinite(Y[:, j])
        if m.sum() >= min_pairs:
            out[j] = _roc_threshold(P[m, j], Y[m, j])
    return out


class ROCState:
    """L2 跨年共享 ROC 状态（R20261106-02 §4 偏差⑨）：trailing 实际
    （预测, 已实现标签）对环形缓冲（maxlen=52）+ 上周预测暂存。年冻结模型
    逐年换实例，同一状态对象跨年携带（缓冲跨年模型混用，提案 §4 已披露）；
    毛/净两次运行各持独立实例（ROC 对与成本无关，独立状态保证两跑信号
    逐位一致——repro_paper.make_strat）。

    回填协议（T13 评审 I5/I11）：select(t) 先把上周 (last_pred, 已实现标签)
    入缓冲——标签 = weekly_gross_returns[last_t]（执行周 open→close），决策
    时点 t 已实现，无泄漏。"""

    def __init__(self, maxlen: int = 52):
        self.pairs: deque = deque(maxlen=maxlen)
        self.last_t: int | None = None
        self.last_pred: np.ndarray | None = None


class MIMOModel:
    """L2 论文复刻（spec §1.1；R20261106-02 §3/§8，T13 复活）。

    与 L1 的差异：①特征块含决策周五收盘（window_blocks include_t=True，
    论文「周五收盘后采样」，修 v2 评审 I-3 滞后一档，偏差⑥）；②标签 =
    执行周 open→close ≥1%（weekly_gross_returns 引擎原生，与执行 PnL 同
    口径，偏差⑦——2026-11-06 用户追认 A）；③MIMO 联合 4 层 FC（3 隐层
    ReLU+dropout + 线性 11 输出）；④推断 MC dropout T 采样——中位数 ±1σ
    含 ≥80% 样本质量才置信；⑤买入 = 置信 ∧ 中位数 ≥ ROC 阈值，阈值 =
    trailing 52 对实际（预测,已实现标签）的 Youden J（<26 回退 0.5，偏差⑨
    ——论文「周周重估」的机制落地，2026-11-06 用户追认 A）；等权（论文
    win-rate/streak 加权公式排版损坏，偏差①）。年模型协议（偏差②）：fit
    在交易年前最后一个决策周五调用后冻结，年内 select 只换特征不换参，
    ROC 状态跨年共享（驱动见 repro_paper.py）。"""

    def __init__(self, *, window: int = 13, epochs: int = L2_EPOCHS,
                 lr: float = L2_LR, hidden: tuple[int, ...] = L2_HIDDEN,
                 dropout: float = L2_DROPOUT, mc_samples: int = L2_MC_SAMPLES,
                 lambda_fin: float = LAMBDA_FIN, roc: ROCState | None = None):
        self.window, self.epochs, self.lr = window, epochs, lr
        self.hidden, self.dropout, self.mc_samples = hidden, dropout, mc_samples
        self.lambda_fin = lambda_fin
        self.net = None
        self.roc = roc if roc is not None else ROCState()
        self._train_blocks: np.ndarray | None = None

    def _build_net(self, torch, D: int, L: int):
        layers, d = [], D
        for h in self.hidden:
            layers += [torch.nn.Linear(d, h), torch.nn.ReLU(),
                       torch.nn.Dropout(self.dropout)]
            d = h
        layers.append(torch.nn.Linear(d, L))
        return torch.nn.Sequential(*layers)

    def fit(self, wf: WeeklyFrame, t_train: int) -> "MIMOModel":
        blocks, t_idx = window_blocks(wf, window=self.window,
                                      upto=t_train + 1, include_t=True)
        lab = [k for k, tj in enumerate(t_idx) if tj + 1 <= t_train]
        if len(lab) < self.window + 2:
            raise ValueError(f"训练行不足：{len(lab)} < window+2={self.window + 2}")
        take = lab[-L2_TRAIN_WEEKS:]
        tj_all = t_idx[take]
        train = blocks[take]
        # 标签 = 执行周 open→close（偏差⑦）：weekly_gross_returns 行 tj 即
        # 决策 tj 的执行周收益；tj ≤ t_train-1 保证至决策周五收盘已实现
        rets = weekly_gross_returns(wf)
        sub_r = rets[tj_all]
        lab_ok = wf.valid[tj_all] & np.isfinite(sub_r)   # per-asset 掩码
        r = np.where(lab_ok, sub_r, np.nan).astype(np.float32)
        y = np.where(lab_ok, sub_r >= 0.01, np.nan).astype(np.float32)
        X = standardize_fit_apply(train, train)
        torch = _torch(L2_SEED)
        self.net = self._build_net(torch, X.shape[1], y.shape[1])
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr)
        bce = torch.nn.BCEWithLogitsLoss(reduction="none")
        Xt = torch.tensor(X, dtype=torch.float32)
        mask = torch.tensor(np.isfinite(y) & np.isfinite(r), dtype=torch.float32)
        Yt = torch.nan_to_num(torch.tensor(y), nan=0.0)
        Rt = torch.nan_to_num(torch.tensor(r), nan=0.0)
        denom = mask.sum().clamp(min=1.0)
        for _ in range(self.epochs):
            opt.zero_grad()
            logits = self.net(Xt)
            loss = ((bce(logits, Yt) * mask).sum() / denom
                    - self.lambda_fin * (torch.sigmoid(logits) * Rt * mask).sum() / denom)
            loss.backward()
            opt.step()
        self._train_blocks = train
        return self

    def _mc_stats(self, x_now: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        torch = _torch(L2_SEED)          # 推断前重置种子：dropout 采样可复现
        self.net.train()                 # MC dropout：推断时开 dropout
        samples = []
        with torch.no_grad():
            xt = torch.tensor(x_now[None, :], dtype=torch.float32)
            for _ in range(self.mc_samples):
                samples.append(torch.sigmoid(self.net(xt))[0].numpy())
        self.net.eval()
        s = np.stack(samples)            # (T, L)
        return np.median(s, axis=0), _confident(s)

    def select(self, wf: WeeklyFrame, t: int, *,
               roc: ROCState | None = None) -> dict[int, float]:
        if self.net is None:
            return {}
        roc = roc if roc is not None else self.roc
        blocks, t_idx = window_blocks(wf, window=self.window,
                                      upto=t + 1, include_t=True)
        if len(t_idx) == 0 or t_idx[-1] != t:
            return {}
        x_now = standardize_fit_apply(self._train_blocks, blocks[-1:])[0]
        med, conf = self._mc_stats(x_now)
        # 偏差⑨回填协议：先入上周 (预测, 已实现标签) 对再取阈值——标签 =
        # 执行周 open→close，决策时点 t 已实现无泄漏；t > last_t 即可回填
        # （跳周时上周标签同样已实现）
        if roc.last_t is not None and t > roc.last_t:
            rets = weekly_gross_returns(wf)
            lab = np.where(np.isfinite(rets[roc.last_t]),
                           rets[roc.last_t] >= 0.01, np.nan)
            roc.pairs.append((roc.last_pred, lab))
        thr = thresholds_from_pairs(roc.pairs, len(med))
        buy = [j for j in range(len(med)) if conf[j] and med[j] >= thr[j]]
        roc.last_t, roc.last_pred = t, med
        return {j: 1.0 / len(buy) for j in buy} if buy else {}


def make_strategy(level: str, *, k: int = 3, window: int = 13,
                  lambda_fin: float = LAMBDA_FIN, mc_dropout: bool = True,
                  roc: bool = True, l1_variant: str = "joint") -> object:
    # window = 特征窗 N（spec §3.3 网格 {8,13,26,52}，I3）；≠ L0 的 lookback（排名回看）。
    if level == "L1":
        strat = LinearModel(window=window, variant=l1_variant)
        return lambda wf, t: strat.select(wf, t, k=k)  # type: ignore[return-value]
    if level == "L2":
        raise ValueError("L2=MIMOModel 年冻结协议（R20261106-02 §3），由 "
                         "repro_paper.py 驱动，不走 per-call 重训的 make_strategy")
    raise ValueError(f"未知 level: {level}")
