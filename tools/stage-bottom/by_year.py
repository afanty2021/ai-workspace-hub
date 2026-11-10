"""「阶段底部出击」分年度 pooled alpha：chuji 与 rsi_up20 两臂 h=5（除权过滤），按信号年分桶。

对照设计：chuji（2×RSI5+ADX−WR10 合成）vs rsi_up20（裸 RSI5 上穿 20）——
「合成是否比最简构件强」的分年度读数。基础率同窗同截尾（复用 run_backtest 口径）。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_backtest import (CACHE, GAP_DAYS, UNIVERSE_RE, WARMUP, event_returns, ex_div_mask,  # noqa: E402
                          load_symbol)
from stage_bottom import stage_bottom_signals  # noqa: E402

H = 5


def pooled_by_year(di, o, sig, h, gap, exdiv):
    si, sr = event_returns(di, o, sig, h, gap, exdiv=exdiv)
    years_sig = di[si] // 10000
    n_all = np.ones(len(di), dtype=bool)
    ai, ar = event_returns(di, o, n_all, h, gap, exdiv=exdiv)
    years_all = di[ai] // 10000
    out = defaultdict(lambda: ([], []))
    for k in range(len(si)):
        out[int(years_sig[k])][0].append(sr[k])
    for k in range(len(ai)):
        out[int(years_all[k])][1].append(ar[k])
    return out


def main() -> int:
    aggs = {a: defaultdict(lambda: [[], []]) for a in ("chuji", "rsi_up20")}
    files = sorted(p for p in CACHE.glob("*.jsonl") if UNIVERSE_RE.match(p.stem))  # 评审 M-8：宇宙白名单
    for k, path in enumerate(files):
        try:
            di, o, hgh, low, c = load_symbol(path)
        except Exception:
            continue
        if len(c) < 120:
            continue
        sigs = stage_bottom_signals(hgh, low, c)
        ex = ex_div_mask(c)
        for arm in aggs:
            sig = sigs[arm]
            sig[:WARMUP] = False
            for y, (ss, bb) in pooled_by_year(di, o, sig, H, GAP_DAYS, ex).items():
                aggs[arm][y][0].extend(ss)
                aggs[arm][y][1].extend(bb)
        if (k + 1) % 1000 == 0:
            print(f"..{k+1}/{len(files)}", file=sys.stderr)

    years = sorted(set(aggs["chuji"]) | set(aggs["rsi_up20"]))
    print(f"\n==== 分年度 pooled alpha（h={H}d，除权过滤）：chuji vs rsi_up20 ====")
    print(f"{'年':<6}{'N信号':>8}{'chuji信号':>10}{'基础率':>9}{'alpha':>9}{'胜率':>7}   |"
          f"{'N信号':>8}{'rsi信号':>10}{'alpha':>9}{'胜率':>7}")
    for y in years:
        parts = []
        for arm in ("chuji", "rsi_up20"):
            ss, bb = aggs[arm][y]
            if len(ss) < 100:
                parts.append(f"{'-':>8}{'-':>10}{'-':>9}{'-':>7}")
                continue
            ss, bb = np.array(ss), np.array(bb)
            parts.append(f"{len(ss):>8}{ss.mean():>9.2%}{bb.mean():>9.2%}"
                         f"{ss.mean()-bb.mean():>+8.2%}{(ss>0).mean():>7.1%}")
        print(f"{y:<6}{parts[0]}   |{parts[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
