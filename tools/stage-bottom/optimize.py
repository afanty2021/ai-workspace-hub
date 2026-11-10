"""「阶段底部出击」优化层验证：消融指向的 4 个闸门/阈值变体 vs 裸 RSI 基线。

预注册（先于结果锁定，变体全部由 followup.py 消融读数推导，非扫参）：
- base20  = CROSS(RSI5, 20)                        基线（已证最优最简）
- adx44   = base20 & ADX>43.6                      ADX 闸门（A2：事件内 ADX 三分位 1.23/1.61/2.28 单调升）
- adx67   = base20 & ADX>67.3                      ADX 高位闸门
- wr72    = base20 & WR10<71.6                     WR10 低闸门（A2：低 2.02 vs 高 1.35）
- deep10  = CROSS(RSI5, 10)                        深度阈值（A1：[0,10) 桶 alpha +3.36% 最肥）

判据（先于结果声明）：
- 闸门「有效」= alpha@20d 相对基线提升 ≥20% 且事件数 ≥ 基线 1/3（密度不可塌）；
- deep10 预期每事件 alpha 更高、密度必然下降，只报读数不做优劣裁决（样本量级差）；
- 切点沿用全市场事件分布三分位（43.6/67.3/71.6），池内不重切，防结果导向。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_backtest import (CACHE, GAP_DAYS, UNIVERSE_RE, WARMUP, event_returns, ex_div_mask,  # noqa: E402
                          load_symbol, summarize)
from stage_bottom import cross_up, stage_bottom_indicators, stage_bottom_signals  # noqa: E402

H_LIST = (5, 10, 20)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    files = sorted(p for p in CACHE.glob("*.jsonl") if UNIVERSE_RE.match(p.stem))  # 评审 M-8：宇宙白名单
    if args.symbols:
        want = {s.strip() for s in args.symbols.split(",") if s.strip()}
        files = [p for p in files if p.stem in want]
    elif args.limit:
        files = files[: args.limit]

    ARMS = ["base20", "adx44", "adx67", "wr72", "deep10"]
    # rows[arm][h] = list of per-stock {"alpha","n_sig"}；pooled[arm][h] = [ret...]
    rows = {a: {h: [] for h in H_LIST} for a in ARMS}
    pooled = {a: {h: [] for h in H_LIST} for a in ARMS}
    n_stock = 0
    for k, path in enumerate(files):
        try:
            di, o, hgh, low, c = load_symbol(path)
        except Exception:
            continue
        if len(c) < 120:
            continue
        n_stock += 1
        ind = stage_bottom_indicators(hgh, low, c)
        sigs = stage_bottom_signals(hgh, low, c)
        rsi5, adx, wr10 = ind["rsi5"], ind["adx"], ind["wr10"]
        base = sigs["rsi_up20"]
        deep = cross_up(rsi5, 10.0)
        deep[:WARMUP] = False
        arms = {
            "base20": base,
            "adx44": base & (adx > 43.6),
            "adx67": base & (adx > 67.3),
            "wr72": base & (wr10 < 71.6),
            "deep10": deep,
        }
        ex = ex_div_mask(c)
        n_all = np.ones(len(c), dtype=bool)
        for h in H_LIST:
            ai, ar = event_returns(di, o, n_all, h, GAP_DAYS, exdiv=ex)
            bmean = float(ar.mean()) if len(ar) else None
            if bmean is None:
                continue
            for a in ARMS:
                si, sr = event_returns(di, o, arms[a], h, GAP_DAYS, exdiv=ex)
                if len(sr):
                    rows[a][h].append({"alpha": float(sr.mean()) - bmean, "n_sig": len(sr)})
                    pooled[a][h].extend(sr.tolist())
                else:
                    rows[a][h].append({"alpha": None, "n_sig": 0})
        if (k + 1) % 1000 == 0:
            print(f"..{k+1}/{len(files)}", file=sys.stderr)

    print(f"\n==== 优化闸门变体 vs 裸 RSI 基线（{n_stock} 票，除权过滤，预注册判据见 docstring） ====")
    hdr = f"{'臂':<8}{'h':>3}{'N信号':>9}{'alpha均值':>10}{'中位':>9}{'t':>8}{'alpha>0':>9}{'pooled':>9}{'判据':>8}"
    print(hdr)
    for h in H_LIST:
        for a in ARMS:
            s = summarize([r for r in rows[a][h] if r["alpha"] is not None])
            pv = np.array(pooled[a][h])
            if "alpha_mean" not in s or not len(pv):
                continue
            if a == "base20":
                verdict = "基线"
            elif a == "deep10":
                verdict = "报读数"
            else:
                base_s = summarize([r for r in rows["base20"][h] if r["alpha"] is not None])
                lift = s["alpha_mean"] / base_s["alpha_mean"] if base_s.get("alpha_mean") else float("nan")
                ok = lift >= 1.2 and s["n_sig"] >= base_s["n_sig"] / 3
                verdict = ("有效" if ok else "不过") + f" x{lift:.1f}"
            print(f"{a:<8}{h:>3}{s['n_sig']:>9}{s['alpha_mean']*100:>9.3f}%"
                  f"{s['alpha_median']*100:>8.3f}%{s['alpha_t']:>8.1f}{s['pos_ratio']:>9.1%}"
                  f"{pv.mean()*100:>8.3f}%{verdict:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
