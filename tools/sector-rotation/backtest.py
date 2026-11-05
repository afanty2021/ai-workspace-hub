# tools/sector-rotation/backtest.py
"""检验矩阵回测 CLI（spec §3.8 v1.2 + 评审 C4/C6/C9/I1/I3/I10/I12 修正）。

预注册两段式（I1/C9+S5 裁定）：--pre-oos 在样本外前窗口（首个有可用行业周 →
确认窗起点）跑探索性网格 → 预注册行写 spec 实施记录并单独 commit →
不带 --pre-oos 跑确认性检验（start = max(可用行业数 ≥50 首周（S5）,
oos_start 行)，选择窗与确认窗不相交）。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.baselines import (EqualWeightAnnual, momentum_topk,  # noqa: E402
                                       random_k, reversal_topk)
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import build_weekly_frame  # noqa: E402
from sector_rotation.portfolio import RiskState  # noqa: E402
from sector_rotation.permtest import paired_block_bootstrap, perm_test_vs_random  # noqa: E402
from sector_rotation.universe import load_universe  # noqa: E402
from sector_rotation.walkforward import WalkResult, coverage_start, run_walkforward  # noqa: E402

TIERS = {"base": CostModel.base, "stress": CostModel.stress}


def power_note(n_oos: int) -> str:
    """评审 C9 + spec 补钉 S3：按实际样本外周数动态生成（370 周基准 ≈5-7%）。"""
    scale = (370 / n_oos) ** 0.5 if n_oos > 0 else float("nan")
    lo, hi = 0.05 * scale, 0.07 * scale
    return (f"功效边界：样本外 {n_oos} 周，单侧 p<0.1 稳定检出的年化 α ≈ "
            f"{lo:.1%}-{hi:.1%}（spec §3.8 补钉 S3：随 √(370/n) 缩放，粗估）；"
            f"证伪结论是「未检出 ≥{lo:.0%}/年的 α」，弱边际可能被错杀。")


def render_report(results: dict[str, WalkResult],
                  tests: dict[tuple[str, str, str], float], *, level: str,
                  tag: str, tier_notes: dict[str, str], prereg: str,
                  exploratory: bool = False,
                  n_oos: int | None = None,
                  diag: dict[str, float] | None = None) -> str:
    lines = [f"# 板块轮动回测报告：{tag}", "",
             f"- 生成：{date.today().isoformat()} · 配置：{prereg}",
             f"- 点差档：基准 {tier_notes['base']} / 压力 {tier_notes['stress']}"
             "（单边口径，含佣金后单边 11/21bp；α 全部成本后）", "",
             "| 策略 | CAGR | Sharpe | MaxDD | 胜率 | 换手 | 成本拖累(基准) | 成本拖累(压力) | 同簇截断 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, res in results.items():                        # M7/M8：nan 记 —，两档各一列
        m = res.metrics

        def _drag(key):
            mm = results.get(key).metrics if key in results else m
            v = mm.get("cost_drag", float("nan"))
            return f"{v:.1%}" if isinstance(v, float) and np.isfinite(v) else "—"
        lines.append(f"| {name} | {m['cagr']:.2%} | {m['sharpe']:.2f} | "
                     f"{m['max_dd']:.2%} | {m['win_rate']:.1%} | {m['turnover']:.1f} | "
                     f"{_drag(name)} | {_drag(f'{name}·压力档')} | {int(m['cluster_binds'])} |")
    lines += ["", "## 检验矩阵（单侧 p<0.1 判定，两档都须过）", "",
              "| 检验 | 基准档 p | 基准档 | 压力档 p | 压力档 |", "|---|---|---|---|---|"]
    for row in ("vs 随机", "vs 等权", "vs 沪深300", "vs L0"):
        cells = [row]                                        # C6：键用 level 参数
        for tier in ("base", "stress"):
            p = tests.get((level, row, tier))
            cells += ["—" if p is None else f"{p:.3f}",
                      "—" if p is None else ("过" if p < 0.1 else "未过")]
        lines.append("| " + " | ".join(cells) + " |")
    if exploratory:                                          # I10：探索性不判定
        # 2026-11-05 机械适配：brief 脚注原文含「闸门」二字，与 brief 测试
        # `"闸门" not in text2` 互斥；改为同义表述，探索性文本不出现闸门字样。
        lines += ["", "> **探索性变体——只报告不判定**（spec §3.8 变体协议，不构成任何晋级判定）。"]
    else:
        rows = ["vs 随机", "vs 等权", "vs 沪深300"] + ([] if level == "L0" else ["vs L0"])
        ok = all(tests.get((level, r, t), 1.0) < 0.1
                 for r in rows for t in ("base", "stress"))
        lines += ["", f"> {level} 闸门："
                  f"{'**通过，可进下一级**' if ok else '**未通过，按 spec §5 停止并写结案报告**'}"]
    if n_oos:
        lines += ["", power_note(n_oos), ""]
    if diag:                                            # S6-C：裸信号诊断（不判定）
        lines += ["## 裸信号诊断（S6-C，RiskState 关闭；只诊断不判定，spec v1.2.3）", "",
                  f"- 裸路径 CAGR {diag['bare_cagr']:+.2%} / Sharpe {diag['bare_sharpe']:.2f}"
                  f" / MaxDD {diag['bare_max_dd']:.2%}——归因用：裸路径差 = 信号无边际；"
                  "裸路径好而闸门路径差 = 风控侵蚀边际。",
                  f"- 闸门路径 halt 统计：触发 {diag['halt_events']} 次"
                  f" / 探针否决 {diag['halt_rejects']} 次（S6-A 滞回态）。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", choices=["L0", "L1", "L2"], default="L0")
    ap.add_argument("--direction", choices=["momentum", "reversal"],
                    default="momentum")                      # I12
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--lookback", type=int, default=1, choices=[1, 4])
    ap.add_argument("--window", type=int, default=13, choices=[8, 13, 26, 52])
    ap.add_argument("--tier", choices=["base", "stress", "both"], default="both")
    ap.add_argument("--oos-start", default="2019-06-01",    # C9
                    help="样本外起点（实际起点 = max(此值首周, 可用行业数≥50 首周（S5）)）")
    ap.add_argument("--pre-oos", action="store_true",
                    help="预注册选择窗：只跑 oos_start 之前（I1 阶段 A）")
    ap.add_argument("--slice", default=None, metavar="FROM:TO",
                    help="稳健切片，如 2024-09-01:2024-12-31（I7）")
    ap.add_argument("--exploratory", action="store_true",
                    help="探索性变体：只报告不判定（I10）")
    ap.add_argument("--universe", type=Path,
                    default=REPO_ROOT / "config/sector-rotation-universe.md")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "output/sector-rotation")
    args = ap.parse_args(argv)
    spec = load_universe(args.universe)
    wf = build_weekly_frame(REPO_ROOT / "data", spec)

    oos_row = next(t for t, f in enumerate(wf.fridays) if f >= args.oos_start)
    start = max(coverage_start(wf), oos_row)                 # C9：样本外边界
    if args.slice:                                           # I7：稳健切片
        lo, hi = args.slice.split(":")
        run_kw = {"start": next(t for t, f in enumerate(wf.fridays) if f >= lo),
                  "end": next((t for t, f in enumerate(wf.fridays) if f > hi),
                              len(wf.fridays))}
    elif args.pre_oos:  # I1+S5 裁定：选择窗=[首个有可用行业周, 确认窗起点)，防 start>end 恒空
        run_kw = {"start": int(np.flatnonzero(wf.valid.any(axis=1))[0]), "end": start}
    else:
        run_kw = {"start": start}
    tiers = ["base", "stress"] if args.tier == "both" else [args.tier]

    def _l0(w, t):
        fn = momentum_topk if args.direction == "momentum" else reversal_topk
        return fn(w, t, lookback=args.lookback, k=args.k)

    def _l0_anti(w, t):
        fn = reversal_topk if args.direction == "momentum" else momentum_topk
        return fn(w, t, lookback=args.lookback, k=args.k)

    tests: dict[tuple[str, str, str], float] = {}
    results: dict[str, WalkResult] = {}
    n_oos = 0
    main_strat = _l0 if args.level == "L0" else None      # S6-C：裸诊断用主策略引用
    gate_risk = None                                      # S6-C：基准档主策略 halt 统计
    for tier in tiers:
        cost = TIERS[tier]()
        strategies = {
            f"L0-{args.direction}-lb{args.lookback}": _l0,
            "L0-反向": _l0_anti,
            "等权持有": EqualWeightAnnual(),                 # C5：年再平衡
            f"随机k{args.k}": (lambda w, t: random_k(w, t, k=args.k, seed=0)),
        }
        if args.level in ("L1", "L2"):
            from sector_rotation.models import make_strategy
            strategies[args.level] = make_strategy(args.level, k=args.k,
                                                   window=args.window)
        main_name = args.level if args.level in ("L1", "L2") \
            else f"L0-{args.direction}-lb{args.lookback}"
        tier_res = {}
        for n, s in strategies.items():
            if n == main_name and tier == "base":         # S6-C：自持 RiskState 读 halt 统计
                gate_risk = RiskState(spec)
                tier_res[n] = run_walkforward(wf, s, cost=cost, risk=gate_risk, **run_kw)
            else:
                tier_res[n] = run_walkforward(wf, s, cost=cost, **run_kw)
        main_strat = strategies[main_name]
        main_res = tier_res[main_name]
        n_oos = len(main_res.weekly)                         # C9：实际样本外周数
        if not args.exploratory:  # 2026-11-05 裁定：探索性跳过 1001 次置换（只按净指标选配置）
            tests[(args.level, "vs 随机", tier)] = perm_test_vs_random(
                wf, cost, k=args.k, n=1000, strategy=strategies[main_name],
                start=run_kw.get("start"), end=run_kw.get("end"))["p_value"]
        eq_weekly = tier_res["等权持有"].weekly
        bench_weekly = np.array([wf.bench_300[t]              # C4：t_rows 对齐
                                 for t in main_res.t_rows])
        tests[(args.level, "vs 等权", tier)] = paired_block_bootstrap(
            main_res.weekly - eq_weekly)
        tests[(args.level, "vs 沪深300", tier)] = paired_block_bootstrap(
            main_res.weekly - bench_weekly)
        if args.level in ("L1", "L2"):
            tests[(args.level, "vs L0", tier)] = paired_block_bootstrap(
                main_res.weekly - tier_res[f"L0-{args.direction}-lb{args.lookback}"].weekly)
        if tier == "base":
            results = tier_res
        else:
            results.update({f"{n}·压力档": r for n, r in tier_res.items()})
    diag = None
    if "base" in tiers and main_strat is not None and gate_risk is not None:
        # S6-C：裸信号诊断（RiskState 关闭，spec v1.2.3 §3.8 v2 协议第 2 条）——
        # 只诊断不判定；裸路径差=信号无边际，裸路径好而闸门路径差=风控侵蚀边际。
        bare = run_walkforward(wf, main_strat, cost=CostModel.base(),
                               risk=RiskState(spec, enabled=False), **run_kw)
        diag = {"bare_cagr": bare.metrics["cagr"], "bare_sharpe": bare.metrics["sharpe"],
                "bare_max_dd": bare.metrics["max_dd"],
                "halt_events": len(gate_risk.halt_events),
                "halt_rejects": gate_risk.halt_rejects}
    # 修根（2026-11-05，阶段 A 实测）：tag 必须含 direction——momentum/reversal 同
    # k·lb 的两格会写同一文件名互相覆盖（brief 原 tag 只到 lb）。方向维度进文件名。
    tag = f"{args.level}-{args.direction}-k{args.k}-lb{args.lookback}"
    if args.slice:
        tag += f"-slice-{args.slice.replace(':', '_')}"
    if args.pre_oos:
        tag += "-preoos"
    prereg = (f"k={args.k} / 方向={args.direction} / lookback={args.lookback} / "
              f"window={args.window} / 判定档=基准+压力双档"
              if not args.exploratory else "探索性变体——只报告不判定")
    text = render_report(results, tests, level=args.level, tag=tag,
                         tier_notes={"base": "10bp", "stress": "20bp"},
                         prereg=prereg, exploratory=args.exploratory,
                         n_oos=None if args.pre_oos else n_oos, diag=diag)
    start_row = run_kw.get("start", start)
    if args.pre_oos:  # 终审 Should-fix 2：选择窗不是 OOS，功效注释不适用
        oos_note = (f"选择窗 {wf.fridays[start_row]} → {wf.fridays[run_kw['end'] - 1]}"
                    f"（pre-oos，S5 裁定：确认窗起点前全部可用数据），共 {n_oos} 周"
                    "——选择窗行业数 1-49 薄覆盖，仅探索性选配置，不判定")
    else:
        oos_note = (f"OOS 起点 {wf.fridays[start_row]}（oos-start={args.oos_start} 与"
                    f"可用行业数 ≥50 首周取大（S5），评审 C9），样本外 {n_oos} 周")
    out = args.out / f"{date.today():%Y-%m}" / f"backtest-{tag}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n\n" + oos_note + "\n", encoding="utf-8")
    print(text, f"\n{oos_note}", f"\n已写入 {out}", sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
