"""金牛决策系统（通达信公式）信号翻译。

对靶源：用户 2026-11-09 提供的通达信公式原文。只翻译可回测的信号部分；
O1/O2/O3 均线、MMM 星号、压力/支撑线、STICKLINE 全部是画图装饰，不影响信号。
`卖空:=REF(压力,1)&&O<=压力&&C>压力` 定义后未被任何输出语句引用，不回测。

核心信号链：
- VAR1  = C>REF(C,1) AND C>REF(C,2)              上涨启动（两连突破）
- VAR2..VARC = REF(前一环,1) AND C 在前两日收盘区间内（含边界）——11 环延续
  （原文 VAR2~VARC 的涨跌条件交替出现，但全部化简为同一区间条件）
- VARD  = C<REF(C,1) AND C<REF(C,2)              下跌启动
- VARE..VAR18 = 同构下跌延续 11 环
- VAR19 = REF(DOWN链任一,1) AND VAR1   → 买入（原式 DRAWICON 图标1 笑脸）
- VAR1A = REF(UP链任一,1) AND VARD    → 卖出（原式 DRAWICON 图标2 哭脸）
- 图标信号带 FILTER(X,5)：信号后 5 根内不重复（间隔 >= 6 根）

链长上限 12 环是原文结构（VAR1 + VAR2..VARC 共 12 天），超过后链断，
只能由新的 VAR1/VARD 重新点火——本翻译保留该行为，不做无限延续状态机。
"""
from __future__ import annotations

import numpy as np

CHAIN_LINKS = 11  # VAR2..VARC / VARE..VAR18 的延续环数


def _shift1(x: np.ndarray) -> np.ndarray:
    """布尔序列右移一位，首位填 False（REF(x,1) 因果语义）。"""
    out = np.zeros_like(x)
    out[1:] = x[:-1]
    return out


def _shift_k(arr: np.ndarray, k: int) -> np.ndarray:
    """数值序列右移 k 位，头部用 arr[0] 占位；调用方只用 [k:] 切片。"""
    out = np.empty_like(arr)
    out[:k] = arr[0]
    out[k:] = arr[:-k]
    return out


def chain_signals(close: np.ndarray):
    """返回 (var1, up_chain, vard, down_chain)，全部与 close 等长，头部 False。

    up_chain = VAR1 OR VAR2 OR ... OR VARC（上涨状态机）；down_chain 同构。
    """
    n = len(close)
    var1 = np.zeros(n, dtype=bool)
    vard = np.zeros(n, dtype=bool)
    in_range = np.zeros(n, dtype=bool)
    up_chain = np.zeros(n, dtype=bool)
    down_chain = np.zeros(n, dtype=bool)
    if n < 3:
        return var1, up_chain, vard, down_chain
    c1 = _shift_k(close, 1)
    c2 = _shift_k(close, 2)
    var1[2:] = (close[2:] > c1[2:]) & (close[2:] > c2[2:])
    vard[2:] = (close[2:] < c1[2:]) & (close[2:] < c2[2:])
    lo = np.minimum(c1, c2)
    hi = np.maximum(c1, c2)
    in_range[2:] = (close[2:] >= lo[2:]) & (close[2:] <= hi[2:])

    up_chain |= var1
    down_chain |= vard
    prev_up = var1.copy()
    prev_dn = vard.copy()
    for _ in range(CHAIN_LINKS):
        prev_up = _shift1(prev_up) & in_range
        up_chain |= prev_up
        prev_dn = _shift1(prev_dn) & in_range
        down_chain |= prev_dn
    return var1, up_chain, vard, down_chain


def jinniu_signals(close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """VAR19（买入原始）/ VAR1A（卖出原始），未做 FILTER。"""
    var1, up_chain, vard, down_chain = chain_signals(close)
    buy = _shift1(down_chain) & var1    # VAR19
    sell = _shift1(up_chain) & vard     # VAR1A
    buy[:3] = False
    sell[:3] = False
    return buy, sell


def tdx_filter(x: np.ndarray, n: int) -> np.ndarray:
    """通达信 FILTER(X,N)：X 满足后其后 N 根内置 0，即相邻两信号间隔 >= N+1 根。"""
    out = np.zeros(len(x), dtype=bool)
    last = -10**9
    for i in np.nonzero(x)[0]:
        if i > last + n:
            out[i] = True
            last = i
    return out


def icon_signals(close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """图表上实际打出的图标信号：FILTER(VAR19,5) 笑脸买入 / FILTER(VAR1A,5) 哭脸卖出。"""
    buy, sell = jinniu_signals(close)
    return tdx_filter(buy, 5), tdx_filter(sell, 5)
