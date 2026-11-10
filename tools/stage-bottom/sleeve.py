"""弱势票反转 sleeve 执行层：组合级回测（R20261110-02）。

上游信号（R20261110-01 已严格 OOS 验证）：gate70 = CROSS(RSI5,20) AND ADX>70；
对照臂 base20 = CROSS(RSI5,20)。本脚本预注册执行层规则并组合级检验。

== 预注册规则（先于结果锁定） ==

宇宙过滤（信号 bar i 判定，全部因果）：
  U1  i >= 250（上市约一年，次新排除）
  U2  入场价 o[i+1] >= 2.0 元（仙股/退市区排除；不复权价）
  U3  amt20 = 20 日均成交额（bar i）>= 3000 万元
  U4  di[i+1]-di[i] <= 10 日历日（复牌跳空不追）
  U5  开盘涨停不追：o[i+1]/c[i] > 1.095（主板 60/00）或 > 1.195（创业 30/科创 68）→ 弃
  U6  ETF 排除（宇宙=个股）；ST 不可从缓存判定=执行边界（实盘用 tushare namechange 排除）

组合构造：
  N=20 槽（敏感性 40 报读数不选优）；每仓 f=1/N 当前净值；现金 0 收益
  每票同持 1 仓；溢出取信号日 RSI5 最低者（最深超卖优先，A1 深度单调的机制延伸）
  入场：信号次日开盘；出场：入场后第 20 根 bar 开盘（个股自身序列，停牌顺延）
  主设计无止损；S3 描述性变体：收盘 <= 0.9×入场价 → 次日开盘出（EXP-20261106-03：
  防守规则的滞后成本须对账，只报读数不入选）
  成本：买 0.075% / 卖 0.125%；日频 MTM（NAV=现金+持仓×收盘）

基准：
  现金 0；EW-universe = 同过滤宇宙日频等权组合（close-close 均值复利）
  ——锚对照（EXP-20261107-05 教训：正结果须排除等权效应）

成功判据（OOS=2020+ 段，预注册）：
  净 CAGR >= EW-universe 同窗 CAGR + 3pp，且 OOS maxDD <= 35%。
窗口报告：全样本 / IS(<2020) / OOS(>=2020)。

== 幸存者边界（口径声明） ==
缓存为当前在市票：退市票的反转事件缺席，绝对收益水平有偏（弱票退市=左尾被截）；
EW 基准同偏，相对差稳健性高于绝对值；实盘上桌前须以含退市样本复核绝对水平。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_backtest import CACHE, ETF_RE, UNIVERSE_RE  # noqa: E402
from stage_bottom import civil_days, cross_up, roll_sum, stage_bottom_indicators, stage_bottom_signals  # noqa: E402

WARMUP = 60
MIN_BARS = 250          # U1
MIN_PRICE = 2.0         # U2
MIN_AMT = 3e7           # U3：3000 万元
GAP_DAYS = 10           # U4
N_SLOTS = 20
COST_BUY, COST_SELL = 0.00075, 0.00125
IS_CUT = 20200101
F = 1.0 / N_SLOTS


def load_full(path: Path):
    dates, o, h, l, c, amt = [], [], [], [], [], []
    with open(path) as fh:
        for line in fh:
            b = json.loads(line)
            dates.append(int(b["date"].replace("-", "")))
            o.append(b["open"]); h.append(b["high"]); l.append(b["low"]); c.append(b["close"])
            amt.append(b.get("amount") or 0.0)
    return (np.array(dates, dtype=np.int64), np.array(o, float), np.array(h, float),
            np.array(l, float), np.array(c, float), np.array(amt, float))


def board_limit(sym: str) -> float:
    return 1.195 if sym[:2] in ("30", "68") else 1.095


def collect(files, gate_cut=70.0):
    """Pass1：收集两臂事件（含 21 根路径收盘/开盘/日期）+ EW 基准累积。"""
    ev_gate, ev_base = [], []
    ew_sum, ew_cnt = defaultdict(float), defaultdict(int)
    for k, path in enumerate(files):
        try:
            di, o, hgh, low, c, amt = load_full(path)
        except Exception:
            continue
        if len(c) < 300:
            continue
        sym = path.stem
        if ETF_RE.match(sym):
            continue
        # 复权近似（执行层必需）：超板别涨停幅度的跳落=送转除权，穿越日的价格比按
        # 价值中性修正（K=跳落比累乘，adj=raw/K）；现金分红（<阈值跳落）不计入=保守。
        # 事件研究可用「两侧同规则剔除除权事件」，组合级持仓穿越除权日不可剔除——
        # 不复权则送转跳落被当真实亏损（冒烟实测单笔均值 +0.65% vs 事件研究 +2.4%）。
        # 信号/指标用原始价（与 R20261110-01 已验证口径一致），仅经济口径复权。
        retc = np.ones(len(c))
        retc[1:] = c[1:] / c[:-1]
        lim = 0.225 if sym[:2] in ("30", "68") else 0.125
        jump = np.zeros(len(c), dtype=bool)
        jump[1:] = retc[1:] < (1 - lim)
        K = np.cumprod(np.where(jump, retc, 1.0))
        c_adj, o_adj = c / K, o / K

        ind = stage_bottom_indicators(hgh, low, c)
        sigs = stage_bottom_signals(hgh, low, c)
        rsi5, adx = ind["rsi5"], ind["adx"]
        base = sigs["rsi_up20"]
        gate = base & (adx > gate_cut)
        amt20 = roll_sum(amt, 20) / 20.0

        # EW 基准：合格日（U1/U2/U3），复权收益
        ret = np.full(len(c), np.nan)
        ret[1:] = c_adj[1:] / c_adj[:-1] - 1.0
        okb = (np.arange(len(c)) >= MIN_BARS) & (c >= MIN_PRICE) & (amt20 >= MIN_AMT)
        okb &= ~np.isnan(ret)
        for j in np.nonzero(okb)[0]:
            d = int(di[j])
            ew_sum[d] += float(ret[j])
            ew_cnt[d] += 1

        limit = board_limit(sym)
        for arm, sig, out in (("gate", gate, ev_gate), ("base", base, ev_base)):
            for i in np.nonzero(sig)[0]:
                if i < MIN_BARS or i + 21 >= len(c) or np.isnan(amt20[i]):
                    continue
                e = i + 1
                if di[e] - di[i] > GAP_DAYS:                      # U4
                    continue
                if o[e] < MIN_PRICE or amt20[i] < MIN_AMT:        # U2/U3
                    continue
                if o[e] / c[i] > limit:                           # U5
                    continue
                out.append({
                    "sym": sym, "rsi": float(rsi5[i]), "adx": float(adx[i]),
                    "e_di": int(di[e]), "x_di": int(di[e + 20]),
                    "o_in": float(o_adj[e]), "o_out": float(o_adj[e + 20]),
                    "amt20": float(amt20[i]),
                    "pd": di[e:e + 21].copy(),                            # 路径日期
                    "pc": (c_adj[e:e + 21]).astype(np.float32).copy(),    # 路径收盘（MTM，复权）
                    "po": (o_adj[e:e + 21]).astype(np.float32).copy(),    # 路径开盘（止损次日出，复权）
                })
        if (k + 1) % 1000 == 0:
            print(f"..collect {k+1}/{len(files)}", file=sys.stderr)
    return ev_gate, ev_base, ew_sum, ew_cnt


def simulate(events, n_slots=N_SLOTS, stop=None, f=None, fill="deepest", seed=7):
    """日频 MTM 组合模拟。fill: deepest=预注册（已证有毒）/ sym=符号序中性 / random=种子随机。
    返回 (日期数组, NAV 数组, 统计 dict)。"""
    f = f or 1.0 / n_slots
    rng = np.random.default_rng(seed)
    rk = {id(e): rng.random() for e in events}
    keymap = {"deepest": lambda e: (e["e_di"], e["rsi"]),
              "sym": lambda e: (e["e_di"], e["sym"]),
              "random": lambda e: (e["e_di"], rk[id(e)])}
    events = sorted(events, key=keymap[fill])
    calendar = sorted({int(d) for e in events for d in (e["e_di"], e["x_di"])})
    # 全交易日历（用路径内日期补齐，保证 MTM 连续）
    all_days = sorted({int(d) for e in events for d in e["pd"]} | set(calendar))
    by_entry = defaultdict(list)
    for e in events:
        by_entry[e["e_di"]].append(e)
    sec = {"deepest": lambda e: e["rsi"], "sym": lambda e: e["sym"], "random": lambda e: rk[id(e)]}
    for d in by_entry:
        by_entry[d].sort(key=sec[fill])                    # 当日槽位竞争次序

    nav, cash, navs = 1.0, 1.0, []
    pos = []                                               # 每仓 {units,o_in,stop_px?,pi,exit_di,exit_px,e}
    held = set()
    trades, wins = [], []
    expo_sum, expo_n = 0.0, 0
    day_idx = {d: i for i, d in enumerate(all_days)}
    exits_by_day = defaultdict(list)

    for d in all_days:
        # 1) 到期/止损出场（开盘执行）
        for p in exits_by_day.pop(d, []):
            if p in pos:
                pos.remove(p); held.discard(p["e"]["sym"])
                cash += p["units"] * p["o_out"] * (1 - COST_SELL)
                r = p["o_out"] / p["o_in"] - 1.0
                trades.append(r)
                wins.append(r > 0)
        # 2) MTM：推进每仓路径指针，检查止损
        for p in pos:
            while p["pi"] < 21 and int(p["e"]["pd"][p["pi"]]) <= d:
                p["last_c"] = float(p["e"]["pc"][p["pi"]])
                if (stop is not None and not p.get("stopped") and p["pi"] < 20
                        and p["last_c"] <= p["o_in"] * (1 - stop)):
                    # 收盘触发 → 次日开盘出（路径下一根开盘）
                    p["stopped"] = True
                    p["o_out"] = float(p["e"]["po"][p["pi"] + 1])
                    p["exit_di"] = int(p["e"]["pd"][p["pi"] + 1])
                    exits_by_day[p["exit_di"]].append(p)
                p["pi"] += 1
        # 3) 入场（先出后进；最深优先）
        for e in by_entry.get(d, ()):
            if len(pos) >= n_slots or e["sym"] in held:
                continue
            units = (nav * f) / (e["o_in"] * (1 + COST_BUY))
            cash -= units * e["o_in"] * (1 + COST_BUY)
            p = {"e": e, "units": units, "o_in": e["o_in"], "pi": 0,
                 "last_c": e["o_in"], "o_out": e["o_out"], "exit_di": e["x_di"]}
            pos.append(p); held.add(e["sym"])
            exits_by_day[e["x_di"]].append(p)
        invested = sum(p["units"] * p["last_c"] for p in pos)
        nav = cash + invested
        navs.append(nav)
        expo_sum += invested / nav if nav > 0 else 0.0
        expo_n += 1

    stats = {"n_trades": len(trades), "win": float(np.mean(wins)) if wins else None,
             "avg_trade": float(np.mean(trades)) if trades else None,
             "exposure": expo_sum / max(expo_n, 1),
             "avg_pos": None}
    return np.array(all_days), np.array(navs), stats


def window_metrics(days, nav, lo=None, hi=None):
    m = np.ones(len(days), dtype=bool)
    if lo is not None:
        m &= days >= lo
    if hi is not None:
        m &= days < hi
    d, n = days[m], nav[m]
    if len(d) < 30:
        return None
    yrs = max((civil_days(d)[-1] - civil_days(d)[0]) / 365.25, 1 / 365)
    rets = n[1:] / n[:-1] - 1.0
    cagr = float(np.sign(n[-1]) * np.abs(n[-1] / n[0]) ** (1 / yrs) - 1)
    vol = float(rets.std(ddof=1) * np.sqrt(244)) if len(rets) > 2 else float("nan")
    dd = float((n / np.maximum.accumulate(n) - 1).min())
    return {"cagr": cagr, "vol": vol, "sharpe": cagr / vol if vol > 0 else float("nan"),
            "maxdd": dd, "days": len(d)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="/tmp/sb-sleeve")
    args = ap.parse_args(argv)
    files = sorted(p for p in CACHE.glob("*.jsonl") if UNIVERSE_RE.match(p.stem))  # 评审 M-8：宇宙白名单（原跑为裸 glob，双臂同宇宙故相对结论不受影响）
    if args.limit:
        files = files[: args.limit]
    ev_gate, ev_base, ew_sum, ew_cnt = collect(files)
    print(f"事件：gate70 {len(ev_gate)} / base20 {len(ev_base)}", file=sys.stderr)

    # EW 基准 NAV（首日锚 1.0，与 sleeve NAV 同口径；薄覆盖日 n<30 剔除——
    # 2012-2013 早期仅个位数票过 250 根暖机，n=1 日均即该票单日收益）
    ew_days = np.array(sorted(d for d in ew_sum if ew_cnt[d] >= 30))
    ew_nav = np.concatenate([[1.0], np.cumprod([1.0 + (ew_sum[d] / ew_cnt[d] if ew_cnt[d] else 0.0)
                                                for d in ew_days])])
    ew_days = np.concatenate([[ew_days[0]], ew_days])

    def report(name, days, nav, stats):
        print(f"\n---- {name} ----")
        print(f"  交易 {stats['n_trades']}  单笔胜率 {stats['win']:.1%}  单笔均值 {stats['avg_trade']:+.2%}"
              f"  平均敞口 {stats['exposure']:.0%}" if stats["n_trades"] else "  无交易")
        for lab, lo, hi in (("全样本", None, None), ("IS<2020", None, IS_CUT), ("OOS>=2020", IS_CUT, None)):
            m = window_metrics(days, nav, lo, hi)
            if m:
                print(f"  {lab:<9} CAGR {m['cagr']:>+8.2%}  vol {m['vol']:>6.1%}  "
                      f"Sharpe {m['sharpe']:>5.2f}  maxDD {m['maxdd']:>7.1%}")

    print("\n==== 基准 ====")
    print("  现金：CAGR 0%")
    ew = window_metrics(np.array(ew_days), ew_nav)
    print(f"  EW-universe：CAGR {ew['cagr']:+.2%}  maxDD {ew['maxdd']:.1%}")
    for lab, lo, hi in (("IS<2020", None, IS_CUT), ("OOS>=2020", IS_CUT, None)):
        m = window_metrics(np.array(ew_days), ew_nav, lo, hi)
        if m:
            print(f"  EW {lab:<9} CAGR {m['cagr']:>+8.2%}  maxDD {m['maxdd']:>7.1%}")

    d, n, s = simulate(ev_gate)
    report("S1 预注册主设计：gate70 × N=20 × deepest-first（无止损）", d, n, s)
    d2, n2, s2 = simulate(ev_base)
    report("S2 预注册对照：base20 × N=20 × deepest-first", d2, n2, s2)
    d3, n3, s3 = simulate(ev_gate, stop=0.10)
    report("S3 预注册描述性：gate70 × N=20 × 止损-10%", d3, n3, s3)
    d4, n4, s4 = simulate(ev_gate, n_slots=40)
    report("S4 预注册敏感性：gate70 × N=40 × deepest-first", d4, n4, s4)
    # ---- post-hoc 机制分解（S1 失败后追加，非预注册，只作归因）----
    d5, n5, s5 = simulate(ev_gate, fill="sym")
    report("V1 post-hoc：gate70 × N=20 × 符号序中性填充", d5, n5, s5)
    d6, n6, s6 = simulate(ev_gate, fill="random")
    report("V2 post-hoc：gate70 × N=20 × 随机填充", d6, n6, s6)
    d7, n7, s7 = simulate(ev_gate, n_slots=150, fill="sym")
    report("V3 post-hoc：gate70 × N=150 × 符号序（高分散）", d7, n7, s7)
    d8, n8, s8 = simulate(ev_gate, n_slots=150, fill="random")
    report("V4 post-hoc：gate70 × N=150 × 随机（高分散）", d8, n8, s8)

    # 分年度：S1 vs EW
    print("\n==== S1 分年度 vs EW-universe ====")
    print(f"{'年':<6}{'S1':>9}{'EW':>9}{'差':>8}")
    for y in range(2012, 2027):
        lo, hi = y * 10000, (y + 1) * 10000
        m1 = window_metrics(d, n, lo, hi)
        m2 = window_metrics(np.array(ew_days), ew_nav, lo, hi)
        if m1 and m2:
            print(f"{y:<6}{m1['cagr']:>9.1%}{m2['cagr']:>9.1%}{m1['cagr']-m2['cagr']:>8.1%}")

    # 容量（描述性）：单票仓位 <= 2% × amt20
    amts = np.array([e["amt20"] for e in ev_gate])
    cap_per_name = 0.02 * amts
    print(f"\n==== 容量估算（单票 <=2%×20日均额，×{N_SLOTS} 仓） ====")
    print(f"  amt20 分布：p10 {np.percentile(amts,10)/1e8:.2f} 亿 / 中位 {np.median(amts)/1e8:.2f} 亿 / p90 {np.percentile(amts,90)/1e8:.2f} 亿")
    print(f"  单票容量中位 {np.median(cap_per_name)/1e4:.0f} 万 → 组合容量中位 ~{np.median(cap_per_name)*N_SLOTS/1e8:.2f} 亿"
          f"（p10 口径 ~{np.percentile(cap_per_name,10)*N_SLOTS/1e4:.0f} 万）")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    np.savez(Path(args.out) / "navs.npz", days=d, s1=n, s2=n2, s3=n3, s4=n4,
             ew_days=np.array(ew_days), ew=ew_nav)
    print(f"\nNAV 序列 → {args.out}/navs.npz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
