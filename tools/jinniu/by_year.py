"""金牛决策系统分年度 alpha：买入信号 h 期前瞻收益 - 基础率，按信号年分桶。

日线 h=5 与周线 h=4 两个关键口径。pooled 口径（全部事件按年聚合）+
分票-分年 cell 中位数（防高频票权重偏置）。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jinniu import icon_signals  # noqa: E402
from run_backtest import (CACHE, WARMUP, GAP_DAYS, GAP_WEEKS, ex_div_mask,
                          event_returns, load_symbol, resample_weekly)


def pooled_by_year(di, o, sig, h, gap, exdiv=None, year_arr=None):
    """返回 {年: (信号收益列表, 当年全部可采样日收益列表)}。

    信号年份必须用 event_returns 过滤后的 idx 取（gap/exdiv 会剔除部分信号）。
    year_arr：显式年份数组（周线时传入，di 是周序号无法直接取年）。
    """
    si, sr = event_returns(di, o, sig, h, gap, exdiv=exdiv)
    years_sig = year_arr[si] if year_arr is not None else di[si] // 10000
    n_all = np.ones(len(di), dtype=bool)
    ai, ar = event_returns(di, o, n_all, h, gap, exdiv=exdiv)
    years_all = year_arr[ai] if year_arr is not None else di[ai] // 10000
    out = defaultdict(lambda: ([], []))
    for k in range(len(si)):
        out[int(years_sig[k])][0].append(sr[k])
    for k in range(len(ai)):
        out[int(years_all[k])][1].append(ar[k])
    return out


def main() -> int:
    agg_d = defaultdict(lambda: [[], []])   # 年 -> [信号收益们, 基础收益们]
    agg_w = defaultdict(lambda: [[], []])
    files = sorted(CACHE.glob("*.jsonl"))
    for k, path in enumerate(files):
        try:
            di, o, c = load_symbol(path)
        except Exception:
            continue
        if len(c) < 120:
            continue
        ib, _ = icon_signals(c)
        ib[:WARMUP] = False
        ex = ex_div_mask(di, c)
        for y, (ss, bb) in pooled_by_year(di, o, ib, 5, GAP_DAYS, exdiv=ex).items():
            agg_d[y][0].extend(ss)
            agg_d[y][1].extend(bb)
        wd, wo, wc = resample_weekly(di, o, c)
        if len(wc) >= 60:
            wb, _ = icon_signals(wc)
            wb[:12] = False
            exw = ex_div_mask(wd, wc)
            # 周序号 → 周一年份：days = week*7 - 3（resample 对齐），再转公历年
            wyear = ((wd * 7 - 3).astype("datetime64[D]").astype("datetime64[Y]").astype(int) + 1970)
            for y, (ss, bb) in pooled_by_year(wd, wo, wb, 4, GAP_WEEKS, exdiv=exw, year_arr=wyear).items():
                agg_w[y][0].extend(ss)
                agg_w[y][1].extend(bb)
        if (k + 1) % 1000 == 0:
            print(f"..{k+1}/{len(files)}", file=sys.stderr)

    for name, agg in (("日线 buy h=5（除权过滤）", agg_d), ("周线 buy h=4（除权过滤）", agg_w)):
        print(f"\n==== {name} 分年度 pooled alpha ====")
        print(f"{'年':<6}{'N信号':>8}{'信号均值':>10}{'基础率':>10}{'alpha':>9}{'信号胜率':>9}")
        for y in sorted(agg):
            ss, bb = agg[y]
            if len(ss) < 50:
                continue
            ss, bb = np.array(ss), np.array(bb)
            print(f"{y:<6}{len(ss):>8}{ss.mean():>9.2%}{bb.mean():>9.2%}"
                  f"{ss.mean()-bb.mean():>8.2%}{(ss>0).mean():>9.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
