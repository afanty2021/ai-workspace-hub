# -*- coding: utf-8 -*-
"""RPS 有效性检验（EXP-20261110-02 教训：组合级 null=同宇宙等权，非单票 BH/绝对收益）。

臂：
  A 十分位分层：RPS 本身=横截面 rank pct×100，天然均匀 → 按 0-10,...,90-100 十等分，
    前瞻 h∈{20,60,120,250} 复权收益 pooled 均值（同宇宙内相对比较，幸存者偏差同偏）。
  B 月度组合：月末 RPS≥90（及 ≥95、三线共红 RPS50/120/250 全≥90）等权持有下月，
    vs 同横截面宇宙等权（EW-universe null）。分年。
  C RankIC：RPS vs fwd20 逐日横截面 spearman（rank-rank pearson 向量化），全史+分年。
  D 动量崩溃段：暴跌窗口（2015-06/07、2015-08、2016-01、2024-09/10）高 RPS 组下月收益。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from rps_core import rps_main

OUT = Path(__file__).resolve().parents[2] / "output/research"
B = rps_main(cache=Path(__file__).resolve().parents[2] / "data/research/R20261110-04/rps_bundle.pkl")
close_adj = B["close_adj"]
rps250, rps120, rps50 = B["rps250"], B["rps120"], B["rps50"]

# 前瞻收益（全局行 shift；停牌缺日 NaN → dropna，退市票左尾被截=幸存者偏差，同偏标注）
fwd = {h: close_adj.shift(-h) / close_adj - 1.0 for h in (20, 60, 120, 250)}

print("=" * 72)
print("A. RPS250 十分位 × 前瞻收益（pooled 均值 %，2013-06 起全市场）")
print("=" * 72)
elig = rps250.notna()
for h in (20, 60, 120, 250):
    f = fwd[h].where(elig)
    r = rps250.where(elig)
    rows = []
    for lo in range(0, 100, 10):
        m = (r >= lo) & (r < lo + 10)
        vals = f[m].stack()
        rows.append((f"D{lo//10}", len(vals), vals.mean() * 100))
    print(f"\n-- fwd {h}d --")
    for d, n, mu in rows:
        print(f"  {d}: n={n:>9,}  mean={mu:+.3f}%")
    dm = pd.DataFrame(rows, columns=["d", "n", "mean"])["mean"]
    print(f"  单调性 D9-D0 spread = {dm.iloc[9]-dm.iloc[0]:+.3f}pp")

print()
print("=" * 72)
print("B. 月度组合：RPS 口径选股 vs 同宇宙 EW（等权 null）")
print("=" * 72)
# 月末行：全史交易日里每月最后一天
month_last = close_adj.index.to_series().groupby(close_adj.index.to_period("M")).max()
month_last = pd.DatetimeIndex(month_last)
# 月收益矩阵：mret.loc[dt] = 上月末→dt 月末（复权）。月末停牌容差：全矩阵先按日 ffill(5) 再取月末。
c_fill = close_adj.ffill(limit=5)
cm = c_fill.loc[month_last]
mret = cm / cm.shift(1) - 1.0
sel = {"RPS250>=90": rps250 >= 90, "RPS250>=95": rps250 >= 95,
       "三线共红(50/120/250全>=90)": (rps50 >= 90) & (rps120 >= 90) & (rps250 >= 90)}


def monthly_arm(sigs: dict):
    rows = []
    for k in range(1, len(month_last) - 1):              # dt 信号月末；ret = dt→下一个月末
        dt, dt_nxt = month_last[k], month_last[k + 1]
        nxt = mret.loc[dt_nxt]                           # 下月收益（信号之后，无前视）
        base_mask = rps250.loc[dt].notna()               # 同横截面资格（上市≥1年+当日有价）
        if base_mask.sum() < 500:
            continue
        ew = nxt[base_mask].mean()
        row = {"month": dt.strftime("%Y-%m"), "n": int(base_mask.sum()), "EW": ew}
        for name, sig in sigs.items():
            m = sig.loc[dt].fillna(False) & base_mask
            row[name] = nxt[m].mean() if m.sum() >= 5 else np.nan
            row[name + "_n"] = int(m.sum())
        rows.append(row)
    return pd.DataFrame(rows).set_index("month")


mf = monthly_arm(sel)
print(f"\n覆盖 {mf.index[0]} → {mf.index[-1]}，{len(mf)} 个月")

# 对靶冒烟（EXP-20261109-03 纪律）：2024-09 月末信号 → 10 月收益，独立重算对拍表值
_dt = pd.Timestamp("2024-09-30")
_dt_nxt = month_last[month_last > _dt][0]
_chk = rps250.loc[_dt]
_members = _chk[_chk >= 90].index
_r = (c_fill.loc[_dt_nxt, _members] / c_fill.loc[_dt, _members] - 1.0).dropna()
print(f"[对靶] 2024-09 月末 RPS>=90 n={len(_members)}，下月手工均值 {_r.mean()*100:+.2f}% "
      f"vs 表值 {mf.loc['2024-09','RPS250>=90']*100:+.2f}%  "
      f"{'OK' if abs(_r.mean()-mf.loc['2024-09','RPS250>=90'])<1e-9 else 'MISMATCH'}")
cols = list(sel.keys())
summary = []
for c in cols + ["EW"]:
    r = mf[c].dropna()
    ann = (1 + r).prod() ** (12 / len(r)) - 1
    dd = ((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()
    summary.append((c, len(r), mf[c + "_n"].mean() if c + "_n" in mf else np.nan, ann * 100, dd * 100))
print("\n组合 | 月数 | 平均持仓数 | 年化% | maxDD%（月频，未扣费）")
for c, n, k, a, d in summary:
    print(f"  {c:<24} {n:>4}  {k:>7.0f}  {a:+8.2f}  {d:8.1f}")
print("\n分年（各臂 − EW 年差 pp）：")
mf["year"] = mf.index.str[:4]
yr = mf.groupby("year").apply(
    lambda g: pd.Series({c: ((1 + g[c]).prod() - (1 + g["EW"]).prod()) * 100 for c in cols}))
print(yr.round(1).to_string())

print()
print("=" * 72)
print("C. RankIC：RPS vs fwd20（逐日横截面 spearman，向量化）")
print("=" * 72)
def row_ic(x: pd.DataFrame, y: pd.DataFrame) -> pd.Series:
    a = x.rank(axis=1)
    b = y.rank(axis=1)
    am = a.sub(a.mean(axis=1), axis=0)
    bm = b.sub(b.mean(axis=1), axis=0)
    cov = (am * bm).mean(axis=1)
    ic = cov / (am.std(axis=1) * bm.std(axis=1))
    return ic

for name, sig in [("RPS50", rps50), ("RPS120", rps120), ("RPS250", rps250)]:
    ic = row_ic(sig.where(sig.notna()), fwd[20].where(sig.notna())).dropna()
    t = ic.mean() / ic.std() * np.sqrt(len(ic))
    by = ic.groupby(ic.index.year).mean()
    print(f"\n{name}: 日均 IC {ic.mean()*100:+.2f}%  t={t:.1f}  正率 {(ic>0).mean()*100:.0f}%  月数 {len(ic)}")
    print("  分年 IC%:", " ".join(f"{y}:{v*100:+.1f}" for y, v in by.items()))

print()
print("=" * 72)
print("D. 动量崩溃段：暴跌窗口高 RPS 组（>=90）下月收益 vs EW")
print("=" * 72)
crash_windows = ["2015-06", "2015-07", "2015-08", "2016-01", "2024-09", "2024-10", "2026-02"]
for w in crash_windows:
    if w not in mf.index:
        continue
    r = mf.loc[w]
    print(f"  {w}: RPS>=90 {r['RPS250>=90']*100:+6.1f}% (n={int(r['RPS250>=90_n'])})  "
          f"三线 {r[cols[2]]*100:+6.1f}%  EW {r['EW']*100:+6.1f}%")

mf.to_csv(OUT / "R20261110-04-rps-monthly-arms.csv")
print(f"\n月度臂明细已存 {OUT/'R20261110-04-rps-monthly-arms.csv'}")
