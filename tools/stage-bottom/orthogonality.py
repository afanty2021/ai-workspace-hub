"""rsi_up20 信号与 EXP-20261109-03 时间点划分因子（F1/F2/F3）的正交性检验。

数据：data/research/R20261109-02/（500 票抽样，2024-11→2026-11，
factors_A.parquet = A 臂 5min 因子日面板，daily.parquet = tushare 日线）。

问题：弱势票反转 sleeve 的 alpha 是否只是重新买入了 F 因子暴露（尤其 F3，正收益因子）？

设计（先于结果声明）：
1. 暴露倾斜：信号日的 F 横截面百分位均值 vs 0.5——信号是否系统性选到高 F 票；
2. 条件 alpha：rsi_up20 事件按信号日 F3 三分位（逐日横截面切）分桶，
   前瞻 20 日开盘-开盘收益 vs 同桶全日基础率——**低 F3 桶若仍有 alpha = 增量边**，
   alpha 只在高 F3 桶 = 与 F3 冗余；F1/F2 同法各出一张小表；
3. 读数口径：非重叠不做（事件研究口径），样本 490 票 2 年，桶内 n 会小——
   只报 pooled 均值与 n，不做 t（横截面单元不足），判定看方向一致性。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from stage_bottom import cross_up, stage_bottom_indicators

ROOT = Path(__file__).resolve().parents[2] / "data" / "research" / "R20261109-02"


def main() -> int:
    daily = pd.read_parquet(ROOT / "daily.parquet")
    fac = pd.read_parquet(ROOT / "factors_A.parquet")
    fac["date"] = pd.to_datetime(fac["date"])
    fac["ymd"] = fac["date"].dt.strftime("%Y%m%d").astype(int)
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    sig_rows, base_rows = [], []
    for code, g in daily.groupby("ts_code"):
        if len(g) < 120:
            continue
        o = g["open"].to_numpy(float)
        h = g["high"].to_numpy(float)
        l = g["low"].to_numpy(float)
        c = g["close"].to_numpy(float)
        ymd = g["trade_date"].to_numpy(int)
        n = len(c)
        # 尾部不足 20 日的日期不能算前瞻收益
        ind = stage_bottom_indicators(h, l, c)
        sig = cross_up(ind["rsi5"], 20.0)
        sig[:60] = False
        fwd = np.full(n, np.nan)
        ok = np.arange(n) + 21 < n
        idx = np.nonzero(ok)[0]
        fwd[idx] = o[idx + 21] / o[idx + 1] - 1.0  # 评审 I-2 修正：次日开盘进 / 20 根后开盘出（原 idx+6 为复制残留）
        for i in np.nonzero(sig & ~np.isnan(fwd))[0]:
            sig_rows.append((code, ymd[i], float(fwd[i])))
        for i in idx:
            base_rows.append((code, ymd[i], float(fwd[i])))

    sig = pd.DataFrame(sig_rows, columns=["ts_code", "ymd", "fwd"])
    base = pd.DataFrame(base_rows, columns=["ts_code", "ymd", "fwd"])
    print(f"样本：日线 {daily['ts_code'].nunique()} 票；rsi_up20 事件 {len(sig)}；基础日 {len(base)}")

    f = fac[["ts_code", "ymd", "F1", "F2", "F3"]].dropna(subset=["ymd"])
    # 逐日横截面百分位（3 因子各自）
    for col in ("F1", "F2", "F3"):
        f[col + "_pct"] = f.groupby("ymd")[col].rank(pct=True)

    merged = sig.merge(f, on=["ts_code", "ymd"], how="inner")
    merged_base = base.merge(f, on=["ts_code", "ymd"], how="inner")
    print(f"事件匹配因子面板：{len(merged)}（F3 非空 {merged['F3'].notna().sum()}）")

    print("\n==== 1) 暴露倾斜：信号日 F 横截面百分位均值（0.5=无倾斜） ====")
    for col in ("F1", "F2", "F3"):
        m = merged[col + "_pct"].dropna()
        print(f"  {col}: mean={m.mean():.3f}  n={len(m)}")

    print("\n==== 2) 条件 alpha：事件按信号日 F 三分位（逐日切）分桶，fwd20 − 同桶基础率 ====")
    for col in ("F3", "F1", "F2"):
        pc = col + "_pct"
        mm = merged.dropna(subset=[pc])
        bb = merged_base.dropna(subset=[pc])
        if len(mm) < 60:
            print(f"  {col}: 事件 {len(mm)} 不足，跳过")
            continue
        print(f"  {col}（事件 {len(mm)} / 基础 {len(bb)}）")
        for lab, mask_s in (("低 1/3", lambda d: d[pc] <= 1 / 3),
                            ("中 1/3", lambda d: (d[pc] > 1 / 3) & (d[pc] <= 2 / 3)),
                            ("高 1/3", lambda d: d[pc] > 2 / 3)):
            ms, bs = mm[mask_s(mm)], bb[mask_s(bb)]
            if len(ms) < 20:
                print(f"    {lab}: n={len(ms)} 不足")
                continue
            print(f"    {lab}: n={len(ms):>5}  事件 {ms['fwd'].mean():>+8.3%}  "
                  f"基础 {bs['fwd'].mean():>+8.3%}  alpha {ms['fwd'].mean()-bs['fwd'].mean():>+8.3%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
