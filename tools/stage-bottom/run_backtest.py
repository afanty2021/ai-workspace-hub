"""「阶段底部出击」全量回测：事件研究（5 信号臂 × 5 前瞻窗）+ 交替持仓（出击进/KD 死叉出）。

用法：
    python tools/stage-bottom/run_backtest.py [--limit N] [--symbols 600276.SH,...] [--out /tmp/sb-out]

数据：data/wyckoff/daily/*.jsonl（威科夫深历史缓存，mootdx 不复权，7482 票 2012-2026）。
宇宙边界（评审 M-8 声明）：白名单过滤——个股 60/68.SH、00/30.SZ + ETF 51/56/58.SH、15.SZ；
缓存内 881xxx.TDX 板块指数等非标的文件剔除；北交所票当前缓存无（若有会落入个股臂按
主板 12.5% 送转阈值处理）。与 rps_core.ETF_RE（56 段放宽 SH|SZ）口径不同，跨工具复用勿混。

口径（复用 tools/jinniu 的已验证框架，对齐 [[baseline-comparison-same-window]]）：
- 事件研究与基础率同窗同截尾：同一票内凡存在 i+1 与 i+1+h 的 i 全部计入基础率，
  信号样本是其子集；停牌跳空（i→i+1 超 10 日历日）与前瞻窗跨长停牌同规则剔除。
- 前瞻收益 = O[i+1+h]/O[i+1]-1，全程开盘口径（信号收盘后次日开盘可执行）。
- 除权过滤对照：样本窗内 |C/C_prev|>12% 的疑似除权跳空剔除该样本（主信号与裸 RSI 基线各做 h=5/10）。
- 交替回测：空仓遇出击次日开盘买、持仓遇 KD 死叉次日开盘卖，期末强平；
  成本买 0.075%/卖 0.125%（佣金万2.5+印花税0.05%+滑点5bp，与金牛同口径），另报零成本档。
- 幸存者偏差：缓存为当前在市股票，信号组与基础率同向，alpha 相对结论稳健、绝对水平有偏。

信号臂（见 stage_bottom.py 对靶映射）：
- chuji    出击（主信号）
- chuji_yr 出击 + 年线过滤（C>MA250 才启用——「护栏能否救活」检验）
- zhunbei  准备状态第一天（左侧提醒）
- kd_gold  KD 金叉（二级确认）
- rsi_dn20 裸 RSI5 下穿 20（超卖基线）
- rsi_up20 裸 RSI5 上穿 20（超卖修复基线 = 出击的最简近似）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_bottom import civil_days, roll_mean, stage_bottom_signals  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "wyckoff" / "daily"
WARMUP = 60
GAP_DAYS = 10
HORIZONS = [1, 3, 5, 10, 20]
ARMS = ["chuji", "chuji_yr", "zhunbei", "kd_gold", "rsi_dn20", "rsi_up20"]
EXDIV_ARMS = ["chuji", "rsi_up20"]
COST_BUY, COST_SELL = 0.00075, 0.00125
ETF_RE = re.compile(r"^(51|56|58)\d{4}\.SH$|^15\d{4}\.SZ$")
# 评审 M-8 修根：宇宙白名单（本目录各脚本共用）——缓存混有 16 段 LOF 344 只、
# 52 段沪基金 4 只、跨资产序列（HG/NQ/XAU 等）10 只、881.TDX 板块指数 2 只，
# 原裸 glob *.jsonl 时全部落入「个股」臂
UNIVERSE_RE = re.compile(r"^(?:(?:60|68|51|56|58)\d{4}\.SH|(?:00|30|15)\d{4}\.SZ)$")


def d2i(s: str) -> int:
    return int(s.replace("-", ""))


def load_symbol(path: Path):
    dates, o, h, l, c = [], [], [], [], []
    with open(path) as fh:
        for line in fh:
            b = json.loads(line)
            dates.append(d2i(b["date"]))
            o.append(b["open"])
            h.append(b["high"])
            l.append(b["low"])
            c.append(b["close"])
    return (np.array(dates, dtype=np.int64), np.array(o, float), np.array(h, float),
            np.array(l, float), np.array(c, float))


def ex_div_mask(c: np.ndarray, thresh=0.12) -> np.ndarray:
    m = np.zeros(len(c), dtype=bool)
    m[1:] = np.abs(c[1:] / c[:-1] - 1.0) > thresh
    return m


def event_returns(di, o, sig, h, gap, exdiv=None):
    """信号 i 的前瞻收益 = O[i+1+h]/O[i+1]-1；对全量索引调用即基础率（同窗同截尾）。"""
    n = len(o)
    idx = np.nonzero(sig)[0]
    idx = idx[(idx + 1 + h < n) & (idx >= 1)]
    if not len(idx):
        return idx, np.array([])
    nxt = idx + 1
    ok = (di[nxt] - di[idx]) <= gap
    ok &= (di[idx + 1 + h] - di[nxt]) <= h * 5 + 20
    idx = idx[ok]
    if exdiv is not None:
        cum = np.cumsum(exdiv)
        bad = cum[idx + 1 + h] - cum[idx] > 0
        idx = idx[~bad]
    if not len(idx):
        return idx, np.array([])
    ret = o[idx + 1 + h] / o[idx + 1] - 1.0
    return idx, ret


def alt_spans(o, sigb, sigs, warmup=WARMUP):
    """交替持仓：空仓遇买入信号次日开盘进，持仓遇卖出信号次日开盘出，期末强平。"""
    n = len(o)
    spans, pos, cur = [], 0, -1
    for i in range(warmup, n - 1):
        if pos == 0 and sigb[i]:
            pos, cur = 1, i + 1
        elif pos == 1 and sigs[i]:
            spans.append((cur, i + 1))
            pos, cur = 0, -1
    if pos == 1:
        spans.append((cur, n - 1))
    hold = sum(b - a for a, b in spans)
    return spans, hold


def summarize(rows):
    """rows: 每票 {alpha, n_sig}；alpha 横截面 t 统计（票为独立单元）。"""
    al = np.array([r["alpha"] for r in rows if r["n_sig"] > 0])
    n_sig = sum(r["n_sig"] for r in rows)
    out = {"n_stock": len(rows), "n_sig": n_sig}
    if len(al):
        t = al.mean() / (al.std(ddof=1) / np.sqrt(len(al))) if len(al) > 2 else float("nan")
        out.update(alpha_mean=al.mean(), alpha_median=np.median(al), alpha_t=float(t),
                   pos_ratio=float((al > 0).mean()), n_eff=len(al))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--symbols", default="", help="逗号分隔代码（用户池），如 600276.SH,512000.SH")
    ap.add_argument("--out", default="/tmp/sb-out")
    args = ap.parse_args(argv)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # 评审 M-8 修根：宇宙白名单过滤（定义见 UNIVERSE_RE）
    files = sorted(p for p in CACHE.glob("*.jsonl") if UNIVERSE_RE.match(p.stem))
    if args.symbols:
        want = {s.strip() for s in args.symbols.split(",") if s.strip()}
        files = [p for p in files if p.stem in want]
    elif args.limit:
        files = files[: args.limit]

    per_stock, pooled = [], {a: {h: [] for h in HORIZONS} for a in ARMS}
    for k, path in enumerate(files):
        try:
            di, o, hgh, low, c = load_symbol(path)
        except Exception as e:
            print(f"skip {path.name}: {e}", file=sys.stderr)
            continue
        if len(c) < 120:
            continue
        sym = path.stem
        sigs = stage_bottom_signals(hgh, low, c)
        ma250 = roll_mean(c, 250)
        sigs["chuji_yr"] = sigs["chuji"] & (c > ma250)  # 年线过滤臂（MA250 NaN 头自动 False）
        ex = ex_div_mask(c)
        row = {"sym": sym, "type": "etf" if ETF_RE.match(sym) else "stock",
               "start": int(di[0]), "end": int(di[-1]), "n": len(c)}
        base_all = np.ones(len(c), dtype=bool)
        base_cache: dict = {}

        def base_mean(hh, xd=False):
            if (hh, xd) not in base_cache:
                _, br = event_returns(di, o, base_all, hh, GAP_DAYS, exdiv=ex if xd else None)
                base_cache[(hh, xd)] = float(br.mean()) if len(br) else None
            return base_cache[(hh, xd)]

        for arm in ARMS:
            sig = sigs[arm]
            for hh in HORIZONS:
                si, sr = event_returns(di, o, sig, hh, GAP_DAYS)
                row[f"{arm}_{hh}_sig"] = float(sr.mean()) if len(sr) else None
                row[f"{arm}_{hh}_n"] = len(sr)
                row[f"{arm}_{hh}_base"] = base_mean(hh)
                if len(sr):
                    pooled[arm][hh].extend(sr.tolist())
                    row[f"{arm}_{hh}_win"] = float((sr > 0).mean())
            if arm in EXDIV_ARMS:
                for hh in (5, 10):
                    si, sr = event_returns(di, o, sig, hh, GAP_DAYS, exdiv=ex)
                    row[f"{arm}_{hh}_sigxd"] = float(sr.mean()) if len(sr) else None
                    row[f"{arm}_{hh}_basexd"] = base_mean(hh, xd=True)

        spans, hold = alt_spans(o, sigs["chuji"], sigs["kd_dead"])
        trades = [o[b] / o[a] - 1.0 for a, b in spans if o[a] > 0]
        gross = float(np.prod([1 + t for t in trades])) if trades else 1.0
        net = float(np.prod([(1 + t) * (1 - COST_BUY) * (1 - COST_SELL) for t in trades])) if trades else 1.0
        bh = float(o[-1] / o[spans[0][0]]) if spans else None
        row.update(trades=len(trades), hold=hold / len(c) if spans else 0.0,
                   gross=gross, net=net, bh=bh,
                   win=float(np.mean([t > 0 for t in trades])) if trades else None,
                   avg_trade=float(np.mean(trades)) if trades else None)
        per_stock.append(row)
        if (k + 1) % 500 == 0:
            print(f"..{k+1}/{len(files)}", file=sys.stderr)

    with open(outdir / "per_stock.jsonl", "w") as fh:
        for r in per_stock:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- 汇总：分票 alpha 横截面 + pooled 描述 ----
    def agg(arm, hh, xd=False):
        sfx = "_sigxd" if xd else "_sig"
        bsfx = "_basexd" if xd else "_base"
        rows = []
        for r in per_stock:
            s, b, n = r.get(f"{arm}_{hh}{sfx}"), r.get(f"{arm}_{hh}{bsfx}"), r.get(f"{arm}_{hh}_n", 0)
            if s is None or b is None:
                continue
            rows.append({"alpha": s - b, "n_sig": n})
        return summarize(rows)

    print("\n==== 事件研究：信号前瞻收益 − 同票基础率（分票 alpha 横截面） ====")
    hdr = f"{'臂':<10}{'h':>3}{'N票':>6}{'N信号':>8}{'alpha均值':>10}{'中位':>9}{'t':>8}{'alpha>0':>9}{'pooled均值':>11}{'pooled胜率':>11}"
    print(hdr)
    lines = [hdr]
    for arm in ARMS:
        for hh in HORIZONS:
            s = agg(arm, hh)
            pv = np.array(pooled[arm][hh])
            if "alpha_mean" in s and len(pv):
                l = (f"{arm:<10}{hh:>3}{s['n_eff']:>6}{s['n_sig']:>8}"
                     f"{s['alpha_mean']*100:>9.3f}%{s['alpha_median']*100:>8.3f}%{s['alpha_t']:>8.1f}"
                     f"{s['pos_ratio']:>9.1%}{pv.mean()*100:>10.3f}%{(pv>0).mean()*100:>10.1f}%")
                print(l)
                lines.append(l)
    print("\n---- 除权过滤对照（h=5/10） ----")
    for arm in EXDIV_ARMS:
        for hh in (5, 10):
            s = agg(arm, hh, xd=True)
            if "alpha_mean" in s:
                l = (f"{arm}_{hh}_xd  {s['n_eff']:>6}{s['n_sig']:>8}"
                     f"{s['alpha_mean']*100:>9.3f}%{s['alpha_median']*100:>8.3f}%{s['alpha_t']:>8.1f}{s['pos_ratio']:>9.1%}")
                print(l)
                lines.append(l)

    def strat_table(rows, label):
        rs = [r for r in rows if r.get("bh") and r.get("trades", 0) >= 5]
        if not rs:
            return
        g = np.array([r["gross"] for r in rs]); n_ = np.array([r["net"] for r in rs])
        b = np.array([r["bh"] for r in rs]); hold = np.array([r["hold"] for r in rs])
        win = np.array([r["win"] for r in rs if r.get("win") is not None])
        at = np.array([r["avg_trade"] for r in rs if r.get("avg_trade") is not None])
        yrs = np.array([max((civil_days(r["end"]) - civil_days(r["start"])) / 365.25, 0.5) for r in rs])  # 评审 I-1 修根：历法日，原 /10000 年化偏 5-11%
        cagr_s = np.sign(n_) * np.abs(n_) ** (1 / yrs) - 1
        cagr_b = np.sign(b) * np.abs(b) ** (1 / yrs) - 1
        t = (cagr_s - cagr_b).mean() / ((cagr_s - cagr_b).std(ddof=1) / np.sqrt(len(rs)))
        print(f"\n==== 交替持仓（出击进/KD死叉出）vs 买入持有：{label}（{len(rs)} 票，>=5 笔） ====")
        for name, arr in (("毛收益中位", g), ("净收益中位", n_), ("BH中位", b),
                          ("净年化中位", cagr_s), ("BH年化中位", cagr_b), ("年化差中位", cagr_s - cagr_b)):
            print(f"  {name:<10} {np.median(arr):>9.2%}   均值 {arr.mean():>9.2%}")
        print(f"  年化差均值 {(cagr_s-cagr_b).mean():.2%}  t={t:.1f}  持仓占比中位 {np.median(hold):.0%}  "
              f"单笔胜率中位 {np.median(win):.0%}  单笔均值中位 {np.median(at):.2%}")

    strat_table(per_stock, "全部")
    strat_table([r for r in per_stock if r["type"] == "stock"], "个股")
    strat_table([r for r in per_stock if r["type"] == "etf"], "ETF")

    with open(outdir / "summary.txt", "w") as fh:
        fh.write("\n".join(lines))
    print(f"\n明细 → {outdir}/per_stock.jsonl（{len(per_stock)} 票）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
