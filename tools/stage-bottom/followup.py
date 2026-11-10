"""R20261110-01 遗留项验证三合一：合成减分消融 + rsi_up20 费后可交易性 + 2026 体制月度序列。

用法：
    python tools/stage-bottom/followup.py [--symbols 600276.SH,...] [--out /tmp/sb-followup]

三项设计（口径全部继承 run_backtest.py：同窗同截尾基础率、停牌跳空剔除、除权 |ΔC|>12% 过滤、
次日开盘进/h 后开盘出、warmup 60）：

A. 合成减分消融——不做公式手术（对和式剔除组件需引入任意中性常数），改事件条件化：
   A1 出击事件按信号日 RSI5 分桶 [0,10)/[10,20)/[20,40)/[40,100]：
      机制假设=合成的有效阈值 (WR10−ADX)/2 高度离散，把事件散到「接刀区」（RSI<10，
      跌势未止）与「追高区」（RSI>40，反转已耗），好区间 [10,20) 应≈裸 RSI 基线 alpha。
   A2 裸 RSI 上穿 20 事件按信号日 ADX / WR10 三分位分桶：哪一层的状态携带负信息。
   （两桶表均 pooled 均值 + 臂内对比；基础率同口径参照。）

B. rsi_up20 费后可交易性——每票单仓非重叠固定持有（h=10/20），费率敏感性 0/0.2%/0.5% 单往返，
   净 CAGR − BH CAGR 分票横截面（个股/ETF/指定池三宇宙）。

C. 2026 体制——rsi_up20 h=20（附 h=5）月度 pooled alpha（信号月−同月基础率），2025-01 起全列。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_backtest import (CACHE, ETF_RE, GAP_DAYS, UNIVERSE_RE, event_returns, ex_div_mask,  # noqa: E402
                          load_symbol)
from stage_bottom import civil_days, stage_bottom_indicators, stage_bottom_signals  # noqa: E402

H_LIST = (5, 20)
RSI_BUCKETS = [(0.0, 10.0), (10.0, 20.0), (20.0, 40.0), (40.0, 100.0)]
POOL_SET: set[str] = set()


def nonoverlap_trades(di, o, sig, h):
    """每票单仓非重叠：信号 i 次日开盘进，h 后开盘出；持有期内新信号忽略。
    返回 (entry_idx 列表, 毛单笔收益列表)；尾部窗口不足的事件丢弃（与事件研究同截尾）。"""
    n = len(o)
    si, sr = event_returns(di, o, sig, h, GAP_DAYS)
    trades, entries, last_exit = [], [], -1
    for k in range(len(si)):
        i, r = int(si[k]), float(sr[k])
        if i + 1 > last_exit:  # 入场时上一仓已平（出场执行点 = i+1+h）
            trades.append(r)
            entries.append(i + 1)
            last_exit = i + 1 + h
    return entries, trades


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--out", default="/tmp/sb-followup")
    args = ap.parse_args(argv)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    if args.symbols:
        POOL_SET.update(s.strip() for s in args.symbols.split(",") if s.strip())

    files = sorted(p for p in CACHE.glob("*.jsonl") if UNIVERSE_RE.match(p.stem))  # 评审 M-8：宇宙白名单
    if POOL_SET:
        files = [p for p in files if p.stem in POOL_SET]

    # A 桶累积：bucket -> {h: [ret...]}；出击事件元组（rsi/adx/wr/thr, ret5, ret20）
    chuji_buckets = {b: {h: [] for h in H_LIST} for b in RSI_BUCKETS}
    chuji_feats = {"rsi": [], "thr": [], "adx": [], "wr": [], "ret5": [], "ret20": []}
    rsi_ev = {"adx": [], "wr": [], "ret5": [], "ret20": []}
    base_by_month = {h: defaultdict(lambda: [0.0, 0]) for h in H_LIST}
    sig_by_month = {h: defaultdict(lambda: [0.0, 0]) for h in H_LIST}
    base_pooled = {h: [] for h in H_LIST}
    # B 可交易性
    trade_rows = []
    COSTS = [(0.0, 0.0), (0.00075, 0.00125), (0.0025, 0.0025)]

    for k, path in enumerate(files):
        try:
            di, o, hgh, low, c = load_symbol(path)
        except Exception:
            continue
        if len(c) < 120:
            continue
        ind = stage_bottom_indicators(hgh, low, c)
        sigs = stage_bottom_signals(hgh, low, c)
        ex = ex_div_mask(c)
        sym = path.stem
        n_all = np.ones(len(c), dtype=bool)

        # 基础率（全量日）pooled + 月度
        for h in H_LIST:
            ai, ar = event_returns(di, o, n_all, h, GAP_DAYS, exdiv=ex)
            base_pooled[h].extend(ar.tolist())
            for m, r in zip((di[ai] // 100).tolist(), ar.tolist()):
                base_by_month[h][m][0] += r
                base_by_month[h][m][1] += 1

        # A1 出击：以 h=20 事件集为基准（双期限收益同集可比，尾部截尾略严于主表）
        si, sr20 = event_returns(di, o, sigs["chuji"], 20, GAP_DAYS, exdiv=ex)
        sr5 = o[si + 6] / o[si + 1] - 1.0  # si+21<n 已保证 si+6 有效
        rsi_at = ind["rsi5"][si]
        thr_at = (ind["wr10"][si] - ind["adx"][si]) / 2.0
        chuji_feats["rsi"].extend(rsi_at.tolist())
        chuji_feats["thr"].extend(thr_at.tolist())
        chuji_feats["adx"].extend(ind["adx"][si].tolist())
        chuji_feats["wr"].extend(ind["wr10"][si].tolist())
        chuji_feats["ret5"].extend(sr5.tolist())
        chuji_feats["ret20"].extend(sr20.tolist())
        for b in RSI_BUCKETS:
            m = (rsi_at >= b[0]) & (rsi_at < b[1])
            chuji_buckets[b][5].extend(sr5[m].tolist())
            chuji_buckets[b][20].extend(sr20[m].tolist())

        # A2 + C：rsi_up20 同样以 h=20 事件集为基准
        si, sr20 = event_returns(di, o, sigs["rsi_up20"], 20, GAP_DAYS, exdiv=ex)
        sr5 = o[si + 6] / o[si + 1] - 1.0
        for m, r in zip((di[si] // 100).tolist(), sr20.tolist()):
            sig_by_month[20][m][0] += r
            sig_by_month[20][m][1] += 1
        for m, r5 in zip((di[si] // 100).tolist(), sr5.tolist()):
            sig_by_month[5][m][0] += r5
            sig_by_month[5][m][1] += 1
        rsi_ev["adx"].extend(ind["adx"][si].tolist())
        rsi_ev["wr"].extend(ind["wr10"][si].tolist())
        rsi_ev["ret5"].extend(sr5.tolist())
        rsi_ev["ret20"].extend(sr20.tolist())

        # B 非重叠固定持有
        for h in (10, 20):
            entries, trades = nonoverlap_trades(di, o, sigs["rsi_up20"], h)
            if not entries:
                continue
            yrs = max((civil_days(di[-1]) - civil_days(di[entries[0]])) / 365.25, 0.5)  # 评审 I-1 修根：历法日，原 /10000 年化偏 5-11%
            bh = o[-1] / o[entries[0]]
            row = {"sym": sym, "type": "etf" if ETF_RE.match(sym) else "stock",
                   "h": h, "n": len(trades), "yrs": yrs,
                   "expo": len(trades) * h / len(o),
                   "win": float(np.mean([t > 0 for t in trades])),
                   "bh_cagr": float(np.sign(bh) * np.abs(bh) ** (1 / yrs) - 1)}
            for ci, (cb, cs) in enumerate(COSTS):
                net = float(np.prod([(1 + t) * (1 - cb) * (1 - cs) for t in trades]))
                row[f"cagr_{ci}"] = float(np.sign(net) * np.abs(net) ** (1 / yrs) - 1)
            trade_rows.append(row)
        if (k + 1) % 1000 == 0:
            print(f"..{k+1}/{len(files)}", file=sys.stderr)

    out_lines = []

    def P(s=""):
        print(s)
        out_lines.append(s)

    # ---- A1 ----
    P("\n==== A1 出击事件按信号日 RSI5 分桶（pooled 前瞻收益，除权过滤） ====")
    base20 = float(np.mean(base_pooled[20]))
    base5 = float(np.mean(base_pooled[5]))
    P(f"基础率 pooled：h=5 {base5:.3%} / h=20 {base20:.3%}")
    P(f"{'RSI 桶':<12}{'N(h20)':>8}{'ret5':>9}{'ret20':>9}{'alpha20':>9}")
    for b in RSI_BUCKETS:
        r5 = chuji_buckets[b][5]
        r20 = chuji_buckets[b][20]
        if len(r20) < 100:
            P(f"[{b[0]:.0f},{b[1]:.0f})    {len(r20):>8}  样本不足")
            continue
        P(f"[{b[0]:.0f},{b[1]:.0f})    {len(r20):>8}  {np.mean(r5):>8.3%}  {np.mean(r20):>8.3%}"
          f"  {np.mean(r20)-base20:>+8.3%}")
    rsi_a = np.array(chuji_feats["rsi"])
    thr_a = np.array(chuji_feats["thr"])
    P(f"出击日 RSI5 分布：p10/25/50/75/90 = {np.percentile(rsi_a,[10,25,50,75,90]).round(1)}")
    P(f"有效阈值 (WR10−ADX)/2 分布：p10/50/90 = {np.percentile(thr_a,[10,50,90]).round(1)}"
      f"（裸基线固定 20）")

    # ---- A2 ----
    P("\n==== A2 裸 RSI 上穿 20 事件按 ADX / WR10 三分位分桶（臂内对比，h=20） ====")
    adx_a = np.array(rsi_ev["adx"])
    wr_a = np.array(rsi_ev["wr"])
    ret20_a = np.array(rsi_ev["ret20"])
    ret5_a = np.array(rsi_ev["ret5"])
    ok = ~(np.isnan(adx_a) | np.isnan(wr_a))
    P(f"全臂 pooled：h=5 {np.mean(ret5_a):.3%} / h=20 {np.mean(ret20_a):.3%}（n={len(ret20_a)}，"
      f"剔 NaN(ADX/WR10) {int((~ok).sum())} 条后分桶）")
    adx_a, wr_a, ret20_a, ret5_a = adx_a[ok], wr_a[ok], ret20_a[ok], ret5_a[ok]
    for name, vals in (("ADX", adx_a), ("WR10", wr_a)):
        q1, q2 = np.percentile(vals, [100 / 3, 200 / 3])
        P(f"{name} 三分位切点：{q1:.1f} / {q2:.1f}")
        for lab, m in (("低 1/3", vals <= q1), ("中 1/3", (vals > q1) & (vals <= q2)), ("高 1/3", vals > q2)):
            if m.sum() < 100:
                continue
            P(f"  {name} {lab}：n={m.sum():>7}  ret5 {np.mean(ret5_a[m]):>8.3%}  "
              f"ret20 {np.mean(ret20_a[m]):>8.3%}")

    # ---- C ----
    P("\n==== C rsi_up20 月度 pooled alpha（信号月 − 同月基础率，2025-01 起） ====")
    months = sorted(set(sig_by_month[20]) | set(base_by_month[20]))
    P(f"{'月':<8}{'n信号':>7}{'sig20':>9}{'base20':>9}{'alpha20':>9}{'alpha5':>9}")
    for m in months:
        if m < 202501:
            continue
        s20, n20 = sig_by_month[20][m]
        b20, nb20 = base_by_month[20][m]
        s5, n5 = sig_by_month[5][m]
        b5, nb5 = base_by_month[5][m]
        if n20 < 100:
            P(f"{m:<8}{n20:>7}  样本不足")
            continue
        a20 = s20 / n20 - b20 / nb20
        a5 = s5 / n5 - b5 / nb5
        P(f"{m:<8}{n20:>7}{s20/n20:>9.2%}{b20/nb20:>9.2%}{a20:>+9.2%}{a5:>+9.2%}")

    # ---- B ----
    P("\n==== B rsi_up20 非重叠固定持有费后可交易性（净 CAGR − BH CAGR，分票横截面） ====")
    P("费率档：c0 零费 / c1 买 0.075%+卖 0.125% / c2 单边 0.25%")
    with open(outdir / "trades.jsonl", "w") as fh:
        for r in trade_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for h in (10, 20):
        rows = [r for r in trade_rows if r["h"] == h and r["n"] >= 5]
        for uni, pred in (("个股", lambda r: r["type"] == "stock"),
                          ("ETF", lambda r: r["type"] == "etf"),
                          ("指定池", lambda r: r["sym"] in POOL_SET) if POOL_SET else (None, None)):
            if pred is None:
                continue
            rs = [r for r in rows if pred(r)]
            if len(rs) < 5:
                continue
            for ci in range(len(COSTS)):
                d = np.array([r[f"cagr_{ci}"] - r["bh_cagr"] for r in rs])
                t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 2 else float("nan")
                tag = "净" if ci > 0 else "毛"
                P(f"  h={h} {uni:<4} {tag}(c{ci})：N={len(rs):>5} 年化差中位 {np.median(d):>+7.2%} "
                  f"均值 {d.mean():>+7.2%} t={t:>6.1f} | 绝对年化中位 {np.median([r[f'cagr_{ci}'] for r in rs]):>+7.2%}"
                  f"（BH {np.median([r['bh_cagr'] for r in rs]):>+7.2%}） 持仓 {np.median([r['expo'] for r in rs]):.0%} "
                  f"胜率 {np.median([r['win'] for r in rs]):.0%} 笔/年 {np.median([r['n']/r['yrs'] for r in rs]):.1f}")
    with open(outdir / "summary.txt", "w") as fh:
        fh.write("\n".join(out_lines))
    P(f"\n明细 → {outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
