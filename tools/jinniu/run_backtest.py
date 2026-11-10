"""金牛决策系统全量回测：事件研究 + 交替持仓，日线/周线。

用法：
    python tools/jinniu/run_backtest.py [--limit N] [--out /tmp/jinniu-out]

数据：data/wyckoff/daily/*.jsonl（威科夫深历史缓存，mootdx 不复权）。

口径要点（对齐 [[baseline-comparison-same-window]] 教训）：
- 事件研究与基础率同窗同截尾：同一票内，凡存在 i+1 与 i+1+h 的 i 全部计入基础率，
  信号样本是其子集；两口径共用同一可交易日集合。
- 前瞻收益基准 = 次日开盘进 / h 期后开盘出，全程开盘口径（信号收盘后可执行）。
- 停牌跳空过滤：i+1 距 i 超 10 个日历日（日线）/ 21 天（周线）的样本剔除（信号组与基础率同规则）。
- 除权过滤（对照版）：样本窗内出现 |C/C_prev|>12% 的疑似除权跳空则剔除该样本。
- 交替回测：空仓遇笑脸次日开盘买、持仓遇哭脸次日开盘卖，期末强平；
  成本买 0.075% / 卖 0.125%（佣金万2.5+印花税0.05%+滑点5bp）；同时报零成本档。
- 幸存者偏差：缓存为当前在市股票（mootdx 可拉取），对信号组与基础率同向，
  相对比较（alpha）受影响有限，绝对收益水平有偏——报告口径中注明。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jinniu import icon_signals  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "wyckoff" / "daily"
# 复查 I-B 修根：宇宙白名单（与 stage-bottom UNIVERSE_RE 同口径——缓存混有 16 段 LOF
# 344 只、52 段基金 4 只、跨资产序列 10 只、881.TDX 板块指数 2 只，原裸 glob 全部落入个股臂）
UNIVERSE_RE = re.compile(r"^(?:(?:60|68|51|56|58)\d{4}\.SH|(?:00|30|15)\d{4}\.SZ)$")
WARMUP = 60          # 每票前 N 根不取信号（次新/数据头）
GAP_DAYS = 10        # 日线停牌跳空阈值（日历日）
GAP_WEEKS = 21       # 周线停牌跳空阈值（日历日）
DAILY_H = [1, 3, 5, 10, 20]
WEEKLY_H = [1, 2, 4, 8]
COST_BUY, COST_SELL = 0.00075, 0.00125


def d2i(s: str) -> int:
    return int(s.replace("-", ""))


def load_symbol(path: Path):
    dates, o, c = [], [], []
    with open(path) as fh:
        for line in fh:
            b = json.loads(line)
            dates.append(d2i(b["date"]))
            o.append(b["open"])
            c.append(b["close"])
    return np.array(dates, dtype=np.int64), np.array(o, float), np.array(c, float)


def _days_from_civil(y, m, d):
    """Hinnant days_from_civil 向量化：公历日期 → 自 1970-01-01 的天数。"""
    y = y - (m <= 2)
    era = np.where(y >= 0, y, y - 399) // 400
    yoe = y - era * 400
    doy = (153 * np.where(m > 2, m - 3, m + 9) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _ymd_days(d):
    """YYYYMMDD int → 天数标量封装（复查 I-B：年化一律历法日 /365.25，YYYYMMDD 差不是天数）。"""
    return int(_days_from_civil(d // 10000, d // 100 % 100, d % 100))


def resample_weekly(di, o, c):
    """周线重采样：按自然周（周一）分组，返回 (周序号, 周open=first, 周close=last)。

    周键 = (days+4)//7 对齐周一（1970-01-01 是周四）。纯向量化；
    节前提前收周与 W-FRI 等价（周五收盘=周末前最后收盘）。
    """
    days = _days_from_civil(di // 10000, di // 100 % 100, di % 100)
    weeks = (days + 3) // 7
    bounds = np.nonzero(np.diff(weeks))[0] + 1
    starts = np.concatenate([[0], bounds])
    ends = np.concatenate([bounds, [len(di)]]) - 1
    return weeks[starts], o[starts], c[ends]


def ex_div_mask(di, c, thresh=0.12):
    """疑似除权跳空日：|C/C_prev-1|>thresh（主板/创业/科创涨停幅之外）。"""
    m = np.zeros(len(c), dtype=bool)
    m[1:] = np.abs(c[1:] / c[:-1] - 1.0) > thresh
    return m


def event_returns(di, o, sig, h, gap, exdiv=None):
    """信号 i 的前瞻收益 = O[i+1+h]/O[i+1]-1；返回有效样本（索引, 收益）。

    同一函数对全量索引调用即得基础率（同窗同截尾）。
    """
    n = len(o)
    idx = np.nonzero(sig)[0]
    idx = idx[(idx + 1 + h < n) & (idx >= 1)]
    if not len(idx):
        return idx, np.array([])
    nxt = idx + 1
    ok = (di[nxt] - di[idx]) <= gap  # i→i+1 间隔（停牌复牌跳空剔除）
    ok &= (di[idx + 1 + h] - di[nxt]) <= h * 5 + 20  # 前瞻窗跨长期停牌剔除
    idx = idx[ok]
    if exdiv is not None:
        cum = np.cumsum(exdiv)
        bad = cum[idx + 1 + h] - cum[idx] > 0
        idx = idx[~bad]
    if not len(idx):
        return idx, np.array([])
    ret = o[idx + 1 + h] / o[idx + 1] - 1.0
    return idx, ret


def run_backtest(di, o, sigb, sigs, warmup=WARMUP):
    """交替持仓：空仓遇买入信号次日开盘进，持仓遇卖出信号次日开盘出。

    返回 (spans=[(入场i, 出场i)], 持仓根数)。出场价=下一 span 入场 open 或末根 close。
    """
    n = len(o)
    spans = []
    pos = 0
    cur = -1
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


def summarize(name, rows):
    """rows: 每票 {alpha, n_sig}；票根数门槛在入库前已过滤（日线>=120/周线>=60）。"""
    al = np.array([r["alpha"] for r in rows if r["n_sig"] > 0])
    n_sig = sum(r["n_sig"] for r in rows)
    out = {
        "n_stock": len(rows),
        "n_stock_with_sig": int((np.array([r["n_sig"] for r in rows]) > 0).sum()),
        "n_sig": n_sig,
    }
    if len(al):
        t = al.mean() / (al.std(ddof=1) / np.sqrt(len(al))) if len(al) > 2 else float("nan")
        out.update(alpha_mean=al.mean(), alpha_median=np.median(al),
                   alpha_t=float(t), pos_ratio=float((al > 0).mean()), n_eff=len(al))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--symbols", default="", help="逗号分隔股票代码（用户池子样本），如 600276.SH,000858.SZ")
    ap.add_argument("--out", default="/tmp/jinniu-out")
    args = ap.parse_args(argv)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in CACHE.glob("*.jsonl") if UNIVERSE_RE.match(p.stem))  # 复查 I-B：宇宙白名单
    if args.symbols:
        want = {s.strip() for s in args.symbols.split(",") if s.strip()}
        files = [p for p in files if p.stem in want]
    elif args.limit:
        files = files[: args.limit]

    per_stock = []
    for k, path in enumerate(files):
        try:
            di, o, c = load_symbol(path)
        except Exception as e:
            print(f"skip {path.name}: {e}", file=sys.stderr)
            continue
        if len(c) < 120:
            continue
        sym = path.stem
        # ---- 日线 ----
        ib, is_ = icon_signals(c)
        ib[:WARMUP] = False
        is_[:WARMUP] = False
        ex = ex_div_mask(di, c)
        row = {"sym": sym, "start": int(di[0]), "end": int(di[-1]), "n": len(c)}
        base_all = np.ones(len(c), dtype=bool)
        base_cache: dict = {}

        def base_mean(h, xd=False):
            if (h, xd) not in base_cache:
                _, br = event_returns(di, o, base_all, h, GAP_DAYS, exdiv=ex if xd else None)
                base_cache[(h, xd)] = float(br.mean()) if len(br) else None
            return base_cache[(h, xd)]

        for tag, sig in (("buy", ib), ("sell", is_)):
            for h in DAILY_H:
                si, sr = event_returns(di, o, sig, h, GAP_DAYS)
                row[f"d_{tag}_{h}_sig"] = float(sr.mean()) if len(sr) else None
                row[f"d_{tag}_{h}_n"] = len(sr)
                row[f"d_{tag}_{h}_base"] = base_mean(h)
            for h in (5, 10):  # 除权过滤对照
                si, sr = event_returns(di, o, sig, h, GAP_DAYS, exdiv=ex)
                row[f"d_{tag}_{h}_sigxd"] = float(sr.mean()) if len(sr) else None
                row[f"d_{tag}_{h}_basexd"] = base_mean(h, xd=True)
        # 日线交替回测：span=(买入执行i, 卖出执行i)，出场价即 span 尾 open
        spans, hold = run_backtest(di, o, ib, is_)
        trades = []
        for a, b in spans:
            if o[a] > 0:
                trades.append(o[b] / o[a] - 1.0)
        yrs = max((_ymd_days(int(di[-1])) - _ymd_days(int(di[spans[0][0]]))) / 365.25, 1e-9) if spans else 0
        gross = float(np.prod([1 + t for t in trades])) if trades else 1.0
        net = float(np.prod([(1 + t) * (1 - COST_BUY) * (1 - COST_SELL) for t in trades])) if trades else 1.0
        bh = float(o[-1] / o[spans[0][0]]) if spans else None
        row.update(d_trades=len(trades), d_hold=hold / len(c) if spans else 0.0,
                   d_gross=gross, d_net=net, d_bh=bh,
                   d_win=float(np.mean([t > 0 for t in trades])) if trades else None,
                   d_avg_trade=float(np.mean(trades)) if trades else None)
        # ---- 周线 ----
        wd, wo, wc = resample_weekly(di, o, c)
        if len(wc) >= 60:
            wb, ws = icon_signals(wc)
            wb[:12] = False
            ws[:12] = False
            exw = ex_div_mask(wd, wc)
            wbase_all = np.ones(len(wc), dtype=bool)
            wbase_cache: dict = {}

            def wbase_mean(h, xd=False):
                if (h, xd) not in wbase_cache:
                    _, br = event_returns(wd, wo, wbase_all, h, GAP_WEEKS, exdiv=exw if xd else None)
                    wbase_cache[(h, xd)] = float(br.mean()) if len(br) else None
                return wbase_cache[(h, xd)]

            for tag, sig in (("buy", wb), ("sell", ws)):
                for h in WEEKLY_H:
                    si, sr = event_returns(wd, wo, sig, h, GAP_WEEKS)
                    row[f"w_{tag}_{h}_sig"] = float(sr.mean()) if len(sr) else None
                    row[f"w_{tag}_{h}_n"] = len(sr)
                    row[f"w_{tag}_{h}_base"] = wbase_mean(h)
                for h in (2, 4):
                    si, sr = event_returns(wd, wo, sig, h, GAP_WEEKS, exdiv=exw)
                    row[f"w_{tag}_{h}_sigxd"] = float(sr.mean()) if len(sr) else None
                    row[f"w_{tag}_{h}_basexd"] = wbase_mean(h, xd=True)
            wspans, whold = run_backtest(wd, wo, wb, ws, warmup=12)
            wtrades = []
            for a, b in wspans:
                if wo[a] > 0:
                    wtrades.append(wo[b] / wo[a] - 1.0)
            wgross = float(np.prod([1 + t for t in wtrades])) if wtrades else 1.0
            wnet = float(np.prod([(1 + t) * (1 - COST_BUY) * (1 - COST_SELL) for t in wtrades])) if wtrades else 1.0
            wbh = float(wo[-1] / wo[wspans[0][0]]) if wspans else None
            row.update(w_n=len(wc), w_trades=len(wtrades), w_hold=whold / len(wc) if wspans else 0.0,
                       w_gross=wgross, w_net=wnet, w_bh=wbh,
                       w_win=float(np.mean([t > 0 for t in wtrades])) if wtrades else None,
                       w_avg_trade=float(np.mean(wtrades)) if wtrades else None)
        per_stock.append(row)
        if (k + 1) % 500 == 0:
            print(f"..{k+1}/{len(files)}", file=sys.stderr)

    with open(outdir / "per_stock.jsonl", "w") as fh:
        for r in per_stock:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- 汇总 ----
    def agg(freq, tag, h, xd=False):
        rows = []
        sfx = "_sigxd" if xd else "_sig"
        bsfx = "_basexd" if xd else "_base"
        for r in per_stock:
            s, b, n = r.get(f"{freq}_{tag}_{h}{sfx}"), r.get(f"{freq}_{tag}_{h}{bsfx}"), r.get(f"{freq}_{tag}_{h}_n", 0)
            if s is None or b is None:
                continue
            rows.append({"alpha": s - b, "n_sig": n})
        return summarize(f"{freq}_{tag}_{h}", rows), sum(r["n_sig"] for r in rows)

    print("\n==== 事件研究：信号前瞻收益 - 同票基础率（分票 alpha 横截面） ====")
    hdr = f"{'口径':<22}{'N票':>6}{'N信号':>8}{'alpha均值':>10}{'中位':>10}{'t':>8}{'alpha>0占比':>12}"
    print(hdr)
    lines = [hdr]
    for freq, hs in (("d", DAILY_H), ("w", WEEKLY_H)):
        for tag in ("buy", "sell"):
            for h in hs:
                s, nsig = agg(freq, tag, h)
                if "alpha_mean" in s:
                    l = (f"{freq}_{tag}_{h:<3}{'xd' if False else '':<3}{s['n_eff']:>6}{nsig:>8}"
                         f"{s['alpha_mean']*100:>9.3f}%{s['alpha_median']*100:>9.3f}%{s['alpha_t']:>8.1f}{s['pos_ratio']:>11.1%}")
                    print(l)
                    lines.append(l)
    print("\n---- 除权过滤对照（h=5d/2w） ----")
    for freq, hs, tag in (("d", [5, 10], "buy"), ("w", [2, 4], "buy")):
        for h in hs:
            s, nsig = agg(freq, tag, h, xd=True)
            if "alpha_mean" in s:
                l = (f"{freq}_buy_{h}_xd        {s['n_eff']:>6}{nsig:>8}"
                     f"{s['alpha_mean']*100:>9.3f}%{s['alpha_median']*100:>9.3f}%{s['alpha_t']:>8.1f}{s['pos_ratio']:>11.1%}")
                print(l)
                lines.append(l)

    def strat_table(freq):
        key_g, key_n, key_b, key_t = f"{freq}_gross", f"{freq}_net", f"{freq}_bh", f"{freq}_trades"
        rs = [r for r in per_stock if r.get(key_b) and r.get(key_t, 0) >= 5]
        if not rs:
            return
        g = np.array([r[key_g] for r in rs])
        n_ = np.array([r[key_n] for r in rs])
        b = np.array([r[key_b] for r in rs])
        hold = np.array([r[f"{freq}_hold"] for r in rs])
        win = np.array([r[f"{freq}_win"] for r in rs if r.get(f"{freq}_win") is not None])
        # 年化（跨度用各自数据长度）
        yrs = np.array([max((_ymd_days(r["end"]) - _ymd_days(r["start"])) / 365.25, 0.5) for r in rs])  # 复查 I-B 修根
        cagr_s = np.sign(n_) * np.abs(n_) ** (1 / yrs) - 1
        cagr_b = np.sign(b) * np.abs(b) ** (1 / yrs) - 1
        lab = "日线" if freq == "d" else "周线"
        t = (cagr_s - cagr_b).mean() / ((cagr_s - cagr_b).std(ddof=1) / np.sqrt(len(rs)))
        print(f"\n==== {lab} 交替持仓 vs 买入持有（{len(rs)} 票，>=5 笔） ====")
        for name, arr in (("策略毛收益中位", g), ("策略净收益中位", n_), ("买入持有中位", b),
                          ("策略年化中位", cagr_s), ("BH年化中位", cagr_b), ("年化差 策略-BH 中位", cagr_s - cagr_b)):
            print(f"  {name:<14} {np.median(arr):>9.2%}   均值 {arr.mean():>9.2%}")
        print(f"  年化差均值 { (cagr_s-cagr_b).mean():.2%}  t={t:.1f}  持仓占比中位 {np.median(hold):.0%}  单笔胜率中位 {np.median(win):.0%}")

    strat_table("d")
    strat_table("w")

    with open(outdir / "summary.txt", "w") as fh:
        fh.write("\n".join(lines))
    print(f"\n明细 → {outdir}/per_stock.jsonl（{len(per_stock)} 票）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
