# -*- coding: utf-8 -*-
"""RPS（相对价格强度）核心计算：全市场横排名复现 + 检验基座。

口径对靶（陶博士2006 通达信四步）：
  ① EXTRS = (C - REF(C, N)) / REF(C, N)，N ∈ {50, 120, 250}（个股自身区间涨幅）
  ② .902 扩展数据 0-1000 归一化横排名（板块=上市一年以上），RPS = 值/10
     等价于 ret_N 的横截面百分位排名 ×100（文章 WorkBuddy rank(pct=True)*100 同口径）
  ③ RPS≥90 红线

实现差异（须在报告中声明）：
  - 价格：mootdx 不复权日线 + 板别阈值送转修复（价值中性近似，现金分红不加回=保守；
    与 R20261110-02 sleeve.py 同款）。通达信本地通常前复权、文章 akshare qfq。
  - 上市一年以上：数据集内 bar 数 ≥250 近似（缓存起点 2012-06，2013-06 前无 RPS250）。
  - 宇宙：当前在市票缓存（幸存者偏差，绝对收益高估、相对分层稳健——EXP-20261110-01 同款限制）。
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data/wyckoff/daily"
ETF_RE = re.compile(r"^(51|56|58)\d{4}\.(SH|SZ)$")   # 沪深 ETF 段（评审 M-8：56 段放宽 SH|SZ，
                                                    # 与 run_backtest.ETF_RE 口径不同，跨工具勿混用）
IDX_RE = re.compile(r"^8[08]\d{4}\.")               # 通达信 880/881 自编指数段


def board_lim(sym: str) -> float:
    """送转跳落识别阈值：创业板/科创板 22.5%，主板 12.5%（超板别跌停幅度的单日跳落）。"""
    return 0.225 if sym[:2] in ("30", "68") else 0.125


def adjust_close(sym: str, c: np.ndarray) -> np.ndarray:
    """板别阈值送转修复：跳落日按价格比累乘折算（K），c_adj = c/K。

    送转 10送10 价格减半 → 修复后涨幅≈0；现金分红（跳落<阈值）不修=保守低估涨幅。
    """
    retc = np.ones(len(c))
    retc[1:] = c[1:] / c[:-1]
    jump = np.zeros(len(c), dtype=bool)
    jump[1:] = retc[1:] < (1 - board_lim(sym))
    K = np.cumprod(np.where(jump, retc, 1.0))
    return c / K


def load_close_matrix(min_bars: int = 30):
    """全市场个股不复权 close 矩阵 (date × ticker) + 复权近似矩阵。

    返回 (close_raw, close_adj)：列 = 票代码，行 = 交易日（全集并集，票内缺失=NaN）。
    """
    cols_raw, cols_adj = {}, {}
    for path in sorted(DATA_DIR.glob("*.jsonl")):
        sym = path.stem
        if ETF_RE.match(sym) or IDX_RE.match(sym):
            continue
        dates, closes = [], []
        with open(path) as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                dates.append(row["date"])
                closes.append(row["close"])
        if len(closes) < min_bars:
            continue
        c = np.asarray(closes, float)
        cols_raw[sym] = pd.Series(c, index=pd.to_datetime(dates))
        cols_adj[sym] = pd.Series(adjust_close(sym, c), index=pd.to_datetime(dates))
    close_raw = pd.DataFrame(cols_raw).sort_index()
    close_adj = pd.DataFrame(cols_adj).sort_index()
    return close_raw, close_adj


def interval_ret(close_adj: pd.DataFrame, n: int) -> pd.DataFrame:
    """EXTRS：C_t / C_{t-n} - 1（复权近似口径）。"""
    return close_adj / close_adj.shift(n) - 1.0


def rps_from_ret(ret: pd.DataFrame, min_bars: int = 250) -> pd.DataFrame:
    """横截面百分位 ×100；min_bars=上市一年以上近似（≥250 根 bar 才入横截面）。"""
    eligible = ret.notna() & (close_count(ret) >= min_bars)
    r = ret.where(eligible).rank(axis=1, pct=True) * 100.0
    return r


def close_count(df: pd.DataFrame) -> pd.DataFrame:
    """截至每行、每列的累计有效 bar 数。"""
    return df.notna().cumsum()


def rps_main(periods=(50, 120, 250), cache: Path = None):
    """计算全部 RPS 矩阵；cache 给定则优先读缓存。"""
    if cache and cache.exists():
        return pd.read_pickle(cache)
    _, close_adj = load_close_matrix()
    out = {}
    for n in periods:
        out[n] = rps_from_ret(interval_ret(close_adj, n))
    bundle = {"close_adj": close_adj, **{f"rps{n}": v for n, v in out.items()}}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(bundle, cache)
    return bundle


if __name__ == "__main__":
    import time
    t0 = time.time()
    b = rps_main(cache=Path(__file__).resolve().parents[2] / "data/research/R20261110-04/rps_bundle.pkl")
    for n in (50, 120, 250):
        r = b[f"rps{n}"]
        last = r.index[-1].date()
        row = r.iloc[-1].dropna()
        print(f"RPS{n}: {r.shape[1]} 票 / 末日 {last} 横截面 {len(row)} 只 / "
              f">90: {(row > 90).sum()} / max {row.max():.1f}")
    print(f"耗时 {time.time()-t0:.0f}s")
