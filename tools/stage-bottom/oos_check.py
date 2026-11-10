"""优化变体 OOS 复核：时间切分 IS(<2020-01-01) / OOS(>=2020-01-01)。

背景：optimize.py 的闸门切点（43.6/67.3）取自全样本事件分布且检验同一样本——本脚本做严格版：
1) Pass1：仅用 IS 段 rsi_up20 事件的 ADX 分布重切三分位（OOS 零信息）；
2) Pass2：base20 / adx44_is / adx67_is / deep10 / chuji(参照) 在两窗的事件研究
   （h=5/10/20，除权过滤，同 h20 事件集三收益口径，分票 alpha 横截面）；
3) OOS 费后可交易性：base20 与 adx67_is 非重叠固定持有 h=20，仅计 OOS 入场，
   净 CAGR−BH CAGR 分票横截面（个股/ETF/指定池）。

判读（先于结果声明）：闸门 OOS 有效 = OOS alpha 提升仍 ≥1.2× 且密度 ≥1/3 基线；
base20 对 chuji 的优势若在 OOS 维持（符号+幅度级），主结论无需全样本依赖。
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_backtest import (CACHE, ETF_RE, GAP_DAYS, UNIVERSE_RE, WARMUP, event_returns, ex_div_mask,  # noqa: E402
                          load_symbol, summarize)
from stage_bottom import (civil_days, companion_valid_events, cross_up,  # noqa: E402
                          stage_bottom_indicators, stage_bottom_signals)

IS_CUT = 20200101
H_LIST = (5, 10, 20)
POOL_SET: set[str] = set()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--pass1-only", action="store_true")
    ap.add_argument("--cuts", default="", help="跳过 pass1，直接传 'a44,a67' 两个切点")
    args = ap.parse_args(argv)
    files = sorted(p for p in CACHE.glob("*.jsonl") if UNIVERSE_RE.match(p.stem))  # 评审 M-8：宇宙白名单
    if args.symbols:
        want = {s.strip() for s in args.symbols.split(",") if s.strip()}
        files = [p for p in files if p.stem in want]

    # ---- Pass 1：IS 段 ADX 三分位 ----
    if args.cuts:
        a44, a67 = (float(x) for x in args.cuts.split(","))
        print(f"[pass1 skipped] 使用外部切点 adx44={a44} adx67={a67}")
    else:
        isx_adx = []
        for k, path in enumerate(files):
            try:
                di, o, hgh, low, c = load_symbol(path)
            except Exception:
                continue
            if len(c) < 120:
                continue
            ind = stage_bottom_indicators(hgh, low, c)
            sigs = stage_bottom_signals(hgh, low, c)
            si, _ = event_returns(di, o, sigs["rsi_up20"], 20, GAP_DAYS, exdiv=ex_div_mask(c))
            si = companion_valid_events(si, ind)  # ADX/WR10 无效事件不进切点分布
            m = di[si] < IS_CUT
            isx_adx.extend(ind["adx"][si][m].tolist())
            if (k + 1) % 1000 == 0:
                print(f"..p1 {k+1}/{len(files)}", file=sys.stderr)
        isx = np.array(isx_adx)
        a44, a67 = (float(x) for x in np.percentile(isx, [100 / 3, 200 / 3]))
        print(f"[pass1] IS 段 rsi_up20 事件 n={len(isx_adx)} → ADX 三分位切点 "
              f"adx44={a44:.1f} adx67={a67:.1f}（全样本切点为 43.6/67.3）")
        if args.pass1_only:
            return 0

    # ---- Pass 2 ----
    ARMS = ["base20", "adx44_is", "adx67_is", "deep10", "chuji"]
    ev = {a: {"is": [], "oos": []} for a in ARMS}       # 每事件 ret5/ret10/ret20
    base = {"is": [], "oos": []}                         # 每票 {h5,h10,h20 均值}
    trade_rows = []
    COST_BUY, COST_SELL = 0.00075, 0.00125

    for k, path in enumerate(files):
        try:
            di, o, hgh, low, c = load_symbol(path)
        except Exception:
            continue
        if len(c) < 120:
            continue
        sym = path.stem
        ind = stage_bottom_indicators(hgh, low, c)
        sigs = stage_bottom_signals(hgh, low, c)
        rsi5, adx = ind["rsi5"], ind["adx"]
        deep = cross_up(rsi5, 10.0)
        deep[:WARMUP] = False
        ex = ex_div_mask(c)
        arms = {"base20": sigs["rsi_up20"],
                "adx44_is": sigs["rsi_up20"] & (adx > a44),
                "adx67_is": sigs["rsi_up20"] & (adx > a67),
                "deep10": deep,
                "chuji": sigs["chuji"]}
        per = (di < IS_CUT).astype(int)  # 0=IS 1=OOS

        # 基础率（h20 事件集三收益，每窗均值）
        ai, ab20 = event_returns(di, o, np.ones(len(c), dtype=bool), 20, GAP_DAYS, exdiv=ex)
        ab5 = o[ai + 6] / o[ai + 1] - 1.0
        ab10 = o[ai + 11] / o[ai + 1] - 1.0
        for w, key in ((0, "is"), (1, "oos")):
            m = per[ai] == w
            if m.sum():
                base[key].append({"sym": sym, "n": int(m.sum()),
                                  "h5": float(ab5[m].mean()), "h10": float(ab10[m].mean()),
                                  "h20": float(ab20[m].mean())})

        arm_rows = {}
        for a in ARMS:
            si, sr20 = event_returns(di, o, arms[a], 20, GAP_DAYS, exdiv=ex)
            sr5 = o[si + 6] / o[si + 1] - 1.0
            sr10 = o[si + 11] / o[si + 1] - 1.0
            rows = [(sym, float(sr5[i]), float(sr10[i]), float(sr20[i])) for i in range(len(si))]
            arm_rows[a] = (si, rows)
            for w, key in ((0, "is"), (1, "oos")):
                ev[a][key].extend([r for r, p in zip(rows, per[si] == w) if p])

        # OOS 可交易性：base20 与 adx67_is 非重叠固定 h=20，仅 OOS 入场
        for a in ("base20", "adx67_is"):
            si, rows = arm_rows[a]
            oos_ev = [(int(si[j]), rows[j][3]) for j in range(len(si)) if per[si[j]] == 1]
            trades, entries, last = [], [], -1
            for i, r in oos_ev:
                if i + 1 > last:
                    trades.append(r)
                    entries.append(i + 1)
                    last = i + 1 + 20
            if len(trades) < 3:
                continue
            yrs = max((civil_days(di[-1]) - civil_days(di[entries[0]])) / 365.25, 0.5)  # 评审 I-1 修根：历法日，原 /10000 年化偏 5-11%
            bh = o[-1] / o[entries[0]]
            net = float(np.prod([(1 + t) * (1 - COST_BUY) * (1 - COST_SELL) for t in trades]))
            trade_rows.append({"sym": sym, "arm": a,
                               "type": "etf" if ETF_RE.match(sym) else "stock",
                               "n": len(trades), "yrs": yrs,
                               "cagr": float(np.sign(net) * np.abs(net) ** (1 / yrs) - 1),
                               "bh_cagr": float(np.sign(bh) * np.abs(bh) ** (1 / yrs) - 1)})
        if (k + 1) % 1000 == 0:
            print(f"..p2 {k+1}/{len(files)}", file=sys.stderr)

    bm = {key: {r["sym"]: r for r in base[key]} for key in ("is", "oos")}

    def agg(a, key, h):
        """按票聚合事件 alpha 后做横截面（与 run_backtest 口径一致）。"""
        per_stock = defaultdict(list)
        for r in ev[a][key]:
            b = bm[key].get(r[0])
            if b:
                per_stock[r[0]].append(r[{"h5": 1, "h10": 2, "h20": 3}[h]] - b[h])
        rows = [{"alpha": float(np.mean(v)), "n_sig": len(v)} for v in per_stock.values()]
        s = summarize(rows)
        s["n_event"] = len(ev[a][key])
        return s

    print(f"\n==== IS(<2020) / OOS(>=2020) 事件研究（h=20 主读数，除权过滤，IS 切点闸门） ====")
    print(f"{'臂':<10}{'窗':<4}{'N事件':>8}{'a_h5':>9}{'a_h10':>9}{'a_h20':>9}{'t20':>8}{'a>0':>7}")
    for key, lab in (("is", "IS"), ("oos", "OOS")):
        for a in ARMS:
            s5, s10, s20 = agg(a, key, "h5"), agg(a, key, "h10"), agg(a, key, "h20")
            if "alpha_mean" not in s20:
                print(f"{a:<10}{lab:<4}{s20['n_event']:>8}  无事件")
                continue
            print(f"{a:<10}{lab:<4}{s20['n_event']:>8}{s5['alpha_mean']*100:>8.3f}%"
                  f"{s10['alpha_mean']*100:>8.3f}%{s20['alpha_mean']*100:>8.3f}%"
                  f"{s20['alpha_t']:>8.1f}{s20['pos_ratio']:>7.1%}")

    print("\n==== OOS 费后可交易性（非重叠固定 h=20，仅 OOS 入场，净 c1=0.075%/0.125%） ====")
    for a in ("base20", "adx67_is"):
        for uni, pred in (("个股", lambda r: r["type"] == "stock"), ("ETF", lambda r: r["type"] == "etf"),
                          ("指定池", lambda r: r["sym"] in POOL_SET) if POOL_SET else (None, None)):
            if pred is None:
                continue
            rs = [r for r in trade_rows if r["arm"] == a and pred(r)]
            if len(rs) < 5:
                print(f"  {a} {uni}: N={len(rs)} 样本不足")
                continue
            d = np.array([r["cagr"] - r["bh_cagr"] for r in rs])
            t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 2 else float("nan")
            print(f"  {a:<9}{uni:<4}：N={len(rs):>5} 年化差中位 {np.median(d):>+7.2%} 均值 {d.mean():>+7.2%} "
                  f"t={t:>6.1f} | 绝对净年化中位 {np.median([r['cagr'] for r in rs]):>+7.2%}"
                  f"（BH {np.median([r['bh_cagr'] for r in rs]):>+7.2%}） 笔数中位 {np.median([r['n'] for r in rs]):.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
