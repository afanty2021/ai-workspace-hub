"""弱票反转观察清单前瞻评估（R20261110-07，预注册读数）。

消费 weak_scan.py 台账，对成熟信号（入场后 h 根 bar 已存在）计算：

  fwd_h = O[t+1+h] / O[t+1] − 1        （t=信号日，次日开盘入场，h 日后开盘出）
  alpha_h = fwd_h(信号) − fwd_h(同日 U 过滤宇宙均值)   （配对到信号当日基础率）

预注册读数（先于数据积累锁定）：
  主读数 = gate70 非重叠事件 pooled alpha_20 均值（每票前信号 20 日窗未了结则跳过
  后信号——对靶 R20261110-01 可交易性口径）；
  参考读数 = alpha_5（研究已证 5 日腿弱化，预期接近 0 或负——若 5 日腿显著为正
  反而要警惕口径漂移）；
  对照期望 = 事件级毛 +2.0%/20 日（OOS +2.59%@adx67 切点口径，评审重算）；
  判定规则 = 积累 ≥3 个月、非重叠事件 ≥300 后读 pooled alpha_20：≥+1% 观察清单
  维持、[0,+1%) 降密度观察、<0 纳入失效候选（连弱 2 个月撤线）。
  单月/小样本只报读数不判定——20 日持有窗意味着首组成熟信号在启动后 1 个月才出现。

用法：python weak_eval.py [--horizons 5,20] [--kinds gate70,deep10]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from weak_scan import CACHE, LEDGER, MIN_AMT, MIN_BARS, MIN_PRICE, load_rows, stock_files  # noqa: E402


def load_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    events = {}
    for r in load_rows(LEDGER):
        events[(r["date"], r["sym"], r["kind"])] = r
    return sorted(events.values(), key=lambda e: (e["date"], e["sym"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default="5,20")
    ap.add_argument("--kinds", default="gate70,deep10")
    args = ap.parse_args(argv)
    hs = [int(x) for x in args.horizons.split(",")]
    kinds = set(args.kinds.split(","))

    events = [e for e in load_ledger() if e["kind"] in kinds]
    if not events:
        print("台账为空——尚未积累信号。")
        return 0
    hmax = max(hs)
    dates = sorted({e["date"] for e in events})
    print(f"台账 {len(events)} 事件（{dates[0]}..{dates[-1]}），评估窗 {hs}")

    # 单遍全市场扫描：每个 ledger 日期 × 每票 的 U 过滤与 fwd_h
    # per_date[kind=None]: {date: {h: [fwd,...]}} —— 同日宇宙基础率（无信号条件）
    sig_rows = {(e["date"], e["sym"]): e for e in events}
    base = {d: {h: [] for h in hs} for d in dates}
    # 信号事件的前瞻：{(date,sym): {h: fwd}}
    fwd = {k: {} for k in sig_rows}

    files = stock_files(CACHE)   # 复查 I-A 修根：原 p.name 带 .jsonl 后缀恒不匹配 → 评估器静默空转
    if not files:
        print("[abort] 缓存白名单命中 0 个文件（CACHE 配置或过滤有误）——拒绝静默空评估")
        return 1
    for path in files:
        try:
            rows = load_rows(path)
        except Exception:                           # noqa: BLE001
            continue
        if len(rows) < MIN_BARS + 1:
            continue
        sym = path.name.removesuffix(".jsonl")
        d2i = {r["date"]: i for i, r in enumerate(rows)}
        c = np.array([r["close"] for r in rows], float)
        o = np.array([r["open"] for r in rows], float)
        amt = np.array([r.get("amount") or 0.0 for r in rows], float)
        from numpy.lib.stride_tricks import sliding_window_view
        if len(amt) >= 20:
            w = sliding_window_view(amt, 20)
            amt20 = np.full(len(amt), np.nan)
            amt20[19:] = w.mean(axis=1)
        else:
            amt20 = np.full(len(amt), np.nan)
        for d in dates:
            i = d2i.get(d)
            if i is None or i + 1 >= len(rows):
                continue
            if c[i] < MIN_PRICE or np.isnan(amt20[i]) or amt20[i] < MIN_AMT:
                continue                            # 同款 U1-U3 过滤
            key = (d, sym)
            is_sig = key in sig_rows
            for h in hs:
                j = i + 1 + h
                if j >= len(rows):
                    continue
                r = o[j] / o[i + 1] - 1.0
                if is_sig:
                    fwd[key][h] = r
                base[d][h].append(r)

    # 非重叠去重（每票，按时间序；前信号 h=20 窗未了结则跳过后信号）
    def nonoverlap(kind: str, h: int) -> list[dict]:
        out, last_exit = [], {}
        for e in sorted(events, key=lambda x: (x["date"], x["sym"])):
            if e["kind"] != kind or h not in fwd.get((e["date"], e["sym"]), {}):
                continue
            le = last_exit.get(e["sym"])
            # 评审 M-6：20 交易日持有窗 ≈ 28 日历日，未了结则跳过（原「同月去重」近似
            # 在跨月边界重叠/漏删，判定窗 2027-02 启动前修正）
            if le and (date.fromisoformat(e["date"]) - date.fromisoformat(le)).days < 28:
                continue
            last_exit[e["sym"]] = e["date"]
            out.append(e)
        return out

    for kind in sorted(kinds):
        n_all = sum(1 for e in events if e["kind"] == kind)
        print(f"\n==== {kind}（台账 {n_all}）====")
        for h in hs:
            evs = nonoverlap(kind, h)
            vals, alphas = [], []
            for e in evs:
                f = fwd[(e["date"], e["sym"])][h]
                vals.append(f)
                b = base[e["date"]][h]
                if b:
                    alphas.append(f - float(np.mean(b)))
            matured = len(vals)
            if not matured:
                print(f"  h={h}: 无成熟事件（20 日窗首组成熟需启动后 1 个月）")
                continue
            vals_a, alphas_a = np.array(vals), np.array(alphas)
            print(f"  h={h}: 成熟 {matured}  毛 {vals_a.mean():+.2%}（中位 "
                  f"{np.median(vals_a):+.2%}、胜率 {(vals_a > 0).mean():.0%}）"
                  f"  alpha {alphas_a.mean():+.2%}（n={len(alphas_a)}）")
        by_month = defaultdict(list)
        for e in events:
            if e["kind"] == kind and 20 in fwd.get((e["date"], e["sym"]), {}):
                by_month[e["date"][:7]].append(fwd[(e["date"], e["sym"])][20])
        if by_month:
            print("  月度毛 fwd20: " + " ".join(
                f"{m}:{np.mean(v):+.1%}(n={len(v)})" for m, v in sorted(by_month.items())))
    print("\n判定规则（预注册）：≥3 个月且非重叠事件 ≥300 后读 pooled alpha_20——"
          "≥+1% 维持 / [0,+1%) 降密度 / <0 连弱 2 个月撤线；此前只报读数不判定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
