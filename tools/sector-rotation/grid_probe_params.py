#!/usr/bin/env python3
"""S6-A 探针参数网格扫描（spec v1.2.3 §3.8 v2 协议第 4/5 条；§6.3 实施记录）。

背景：v2 步骤 0 实证选择窗 halt 大量触发 → N/f 走选择窗网格冻结（先验 N=8 作废）。
判据（事前声明，spec §6.3）：12 策略格（k∈{2,3,4} × 方向 × lb∈{1,4}）× 两档
（基准/压力）净 CAGR 的均值；平手取 Sharpe 均值。M=4 固定不扫。
冻结结果（2026-11-05 首跑）：N=13 / f=0.5 / M=4（净 CAGR 均值 +2.86%，
Sharpe 均值 0.20；先验 N=8 为 +1.34%）。

本脚本入库动机（评审 I-4）：首跑脚本是一次性 /tmp 脚本未落库，参数冻结的
可复现性断点——重跑本脚本应复现 §6.3 数字（确定性：同数据、同 seed）。

用法（仓库根目录）：
    python tools/sector-rotation/grid_probe_params.py            # 汇总表
    python tools/sector-rotation/grid_probe_params.py --verbose  # 附 12 格×两档明细

自检（friction-log 2026-11-05 教训：sweep 必须先验证 sweep 本身有效）：
六组合结果若全等 → 报错退出（参数未注入的签名）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from sector_rotation.baselines import momentum_topk, reversal_topk  # noqa: E402
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import build_weekly_frame  # noqa: E402
from sector_rotation.portfolio import RiskState  # noqa: E402
from sector_rotation.universe import load_universe  # noqa: E402
from sector_rotation.walkforward import coverage_start, run_walkforward  # noqa: E402

TIERS = {"base": CostModel.base, "stress": CostModel.stress}
GRID = [(n, f) for n in (4, 8, 13) for f in (0.25, 0.5)]   # M=4 固定（spec §6.3）
CELLS = [(k, d, lb) for k in (2, 3, 4)
         for d in ("momentum", "reversal") for lb in (1, 4)]   # v1 阶段 A 同款 12 格


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--oos-start", default="2019-06-01",
                    help="样本外起点标称值（实际起点 = max(此值首周, 可用行业数≥50 首周)，"
                         "选择窗 = [首个可用周, 实际起点)）")
    ap.add_argument("--verbose", action="store_true", help="打印 12 格×两档明细")
    args = ap.parse_args(argv)

    spec = load_universe(REPO_ROOT / "config/sector-rotation-universe.md")
    wf = build_weekly_frame(REPO_ROOT / "data", spec)
    oos_row = next(t for t, f in enumerate(wf.fridays) if f >= args.oos_start)
    oos_start = max(coverage_start(wf), oos_row)               # S5：≥50 首周取大
    sel = {"start": int(np.flatnonzero(wf.valid.any(axis=1))[0]), "end": oos_start}
    print(f"选择窗 {wf.fridays[sel['start']]} → {wf.fridays[sel['end'] - 1]}"
          f"（{sel['end'] - sel['start']} 周），OOS 起点 {wf.fridays[oos_start]}")

    rows = {}
    for n, f in GRID:
        cagrs, sharpes = [], []
        detail = []
        for tier, cost_fn in TIERS.items():
            for k, d, lb in CELLS:
                strat = (momentum_topk if d == "momentum" else reversal_topk)
                res = run_walkforward(
                    wf, lambda w, t, s=strat, k=k, lb=lb: s(w, t, lookback=lb, k=k),
                    cost=cost_fn(), start=sel["start"], end=sel["end"],
                    risk=RiskState(spec, halt_wait_weeks=n, probe_frac=f))
                cagrs.append(res.metrics["cagr"])
                sharpes.append(res.metrics["sharpe"])
                detail.append((tier, k, d, lb, res.metrics["cagr"], res.metrics["sharpe"]))
        rows[(n, f)] = {"cagr": float(np.mean(cagrs)), "sharpe": float(np.mean(sharpes)),
                        "detail": detail}

    if len({round(r["cagr"], 12) for r in rows.values()}) == 1:   # sweep 自检
        raise SystemExit("六组合净 CAGR 全等——参数未注入（friction-log 2026-11-05 教训），结果不可信")

    print("\n| N | f | 净 CAGR 均值（12 格×两档） | Sharpe 均值 |")
    print("|---|---|---|---|")
    for (n, f), r in sorted(rows.items(), key=lambda kv: -kv[1]["cagr"]):
        print(f"| {n} | {f} | {r['cagr']:+.2%} | {r['sharpe']:.2f} |")
    best = max(rows, key=lambda kk: rows[kk]["cagr"])
    print(f"\n冻结判据胜出：N={best[0]}/f={best[1]}/M=4"
          f"（均值 {rows[best]['cagr']:+.2%}/{rows[best]['sharpe']:.2f}；"
          "spec §6.3 冻结值 N=13/f=0.5/M=4，重跑应复现）")

    if args.verbose:
        for (n, f), r in rows.items():
            print(f"\n## N={n} f={f}")
            for tier, k, d, lb, c, s in r["detail"]:
                print(f"  {tier:6s} k={k} {d:8s} lb={lb}  CAGR {c:+.2%}  Sharpe {s:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
