# tools/sector-rotation/repro_paper_ablation.py
"""SSRN 4280640 论文原文消融驱动（提案 §12.9；EXP-04 候选改进逐一实施轮，
2026-11-07 用户指令「候选改进清单逐一进行实现，一定要严格完整实现论文原文」）。

与 repro_paper.py 的关系：窗口/锚/口径全部复用（import，不改归档驱动一行）；
本驱动只做探索性消融——五个候选逐项 + 严格论文口径全组合，判定无关（C 判定
属归档轮，本轮只问「单项/组合能否接近论文 operating point」）。

候选 → 变体（每格相对 V0 只动一项，V6 全开）：
  V0 基线        默认参数——锚定：必须与归档 us-repro-2026-11-06.md 位级一致
                 （N=13/26/52 α 均值 -11.14%/-12.07%/-11.15%，容差 6e-5）
  V1 volume      use_volume=True（偏差⑫：输入 N×2L，论文脚注「N × (2l+m)
                 if ETF volumes are used」最终配置）
  V2 4 隐层      hidden=L2_HIDDEN_PAPER=(64,32,16,8)（偏差⑬：论文「four
                 fully connected internal layers」+独立线性输出=5 层 dense）
  V3 T=100       mc_samples=100（论文「a large number of predictions」，未给 T）
  V4 加权 p1     WeightState p1（偏差①：OCR 损坏公式默认读法
                 1+wins·streaks/buys+wins/(streaks+1)；信号不变只动权重）
  V4p2/V4p3      公式另两种读法（p2/p3，读法敏感性行）
  V5 增量续训    update_epochs=1（偏差②：周级 warm-start 微调「week just
                 ended」；对照已测全量重训 trailing104 α -15.26%）
  V6 全组合      V1+V2+V3+V4+V5——严格论文口径单配置（N 仍缺失 → 三格）

实现方读法披露（论文未披露处的最优读法，非论文原文）：
  volume=决策周最后交易日成交量（论文「filtered to exclude all but Friday
  close prices」→ 周五单日 volume，与价格同一数据行；周合计口径未测）；
  层宽 (64,32,16,8)=漏斗延伸推定；T=100=引擎 T13 默认档；update_epochs=1=
  单 pass 单行、标准化统计冻结年模型训练切片；加权公式三读法见 WeightState。

窗口纪律：与归档轮同窗 2012-01-01:2022-12-31（已消费窗内的探索性消融），
尾段 2023+ 处女不触及（year_bounds 同源断言）。

用法：python repro_paper_ablation.py [--force-out]——OUT 已存在默认拒覆盖。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.models import (  # noqa: E402
    L2_HIDDEN, L2_HIDDEN_PAPER, MIMOModel, ROCState, WeightState)
from sector_rotation.weekly import weekly_gross_returns  # noqa: E402
from repro_paper import (  # noqa: E402
    N_GRID, US_DATA, ZERO, _run, annual_group_returns, alpha_vs_paper,
    build_frame, exec_iso_year, year_bounds)
from data_snapshot import snapshot_data_paths, snapshot_report_line  # noqa: E402

OUT = (REPO_ROOT / "output" / "sector-rotation" / "2026-11"
       / "us-repro-ablation-2026-11-07.md")
# V0 位级锚（归档 us-repro-2026-11-06.md：α 均值 2dp + 持仓周；容差按 2dp
# 舍入半宽 5e-5 放宽至 6e-5）
V0_ANCHOR = {13: (-0.1114, 115), 26: (-0.1207, 118), 52: (-0.1115, 155)}

VARIANTS = [
    ("V0 基线", {}),
    ("V1 volume⑫", {"use_volume": True}),
    ("V2 4隐层⑬", {"hidden": L2_HIDDEN_PAPER}),
    ("V3 T=100", {"mc_samples": 100}),
    ("V4 加权p1", {"weight_parse": "p1"}),
    ("V4p2 加权", {"weight_parse": "p2"}),
    ("V4p3 加权", {"weight_parse": "p3"}),
    ("V5 增量续训", {"update_epochs": 1}),
    ("V6 全组合", {"use_volume": True, "hidden": L2_HIDDEN_PAPER,
                  "mc_samples": 100, "weight_parse": "p1", "update_epochs": 1}),
]


def cell(wf, window: int, start, end, *,
         use_volume=False, hidden=L2_HIDDEN, mc_samples=20,
         weight_parse=None, update_epochs=0) -> dict:
    """单格（毛口径零成本——消融只对毛 α；净参考行属归档轮）。
    年模型协议与 repro_paper.mimo_cell 同构：y-1 年末决策周五冻结 fit，
    年内 select 只换特征；V4/V5 状态（WeightState/增量微调）在同构回填
    协议下挂接——决策时点 t 先回填上周已实现行，再产生当周信号/权重。"""
    years_run = sorted({int(wf.fridays[t][:4]) for t in range(start, end)})
    models: dict[int, MIMOModel] = {}
    for y in years_run:
        train_ts = [t for t in range(0, end) if int(wf.fridays[t][:4]) == y - 1]
        if train_ts:
            models[y] = MIMOModel(
                window=window,
                hidden=hidden, mc_samples=mc_samples,
                use_volume=use_volume, update_epochs=update_epochs
            ).fit(wf, train_ts[-1])
    rets_all = weekly_gross_returns(wf)

    def make_strat():
        roc = ROCState()
        wstate = (WeightState(len(wf.members), parse=weight_parse)
                  if weight_parse else None)
        last = {"t": None, "buy": []}

        def strat(wf_, t):
            y = int(wf_.fridays[t][:4])
            if y not in models:
                return {}
            fresh = last["t"] is not None and t > last["t"]
            if fresh and update_epochs:
                models[y].update(wf_, last["t"])       # 偏差②：week just ended
            sel = models[y].select(wf_, t, roc=roc)
            if fresh and wstate is not None:
                wstate.record(last["buy"], rets_all[last["t"]])   # 偏差①
            last["t"], last["buy"] = t, sorted(sel)
            if wstate is not None:
                return wstate.weights(list(sel))
            return sel

        return strat

    res = _run(wf, make_strat(), start, end, cost=ZERO)
    years = [exec_iso_year(wf.fridays[t]) for t in res.t_rows]
    ann = annual_group_returns(years, res.weekly)
    bench = annual_group_returns(
        years, np.array([wf.bench_300[t] for t in res.t_rows]))
    al = alpha_vs_paper(ann, bench)
    by_year: dict[int, list[float]] = {}
    for y, r in zip(years, res.weekly):
        by_year.setdefault(y, []).append(float(r))
    sharpe_years = {y: (float(np.mean(v)) / float(np.std(v)) * np.sqrt(52)
                        if np.std(v) > 0 else float("nan"))
                    for y, v in by_year.items()}
    n_pos = sum(1 for tr in res.trades if tr["holdings"])
    wins = sum(1 for r in res.weekly if r > 0)
    return {
        "alpha": al,
        "mean_alpha": float(np.mean(list(al.values()))),
        "median_alpha": float(np.median(list(al.values()))),
        "pos_years": sum(1 for v in al.values() if v > 0),
        "cagr": res.metrics["cagr"], "maxdd": res.metrics["max_dd"],
        "sharpe_mean": float(np.nanmean(list(sharpe_years.values()))),
        "win_rate": res.metrics["win_rate"],
        "avg_positions": (sum(len(tr["holdings"]) for tr in res.trades)
                          / max(len(res.trades), 1)),
        "weeks_with_positions": n_pos,
        "n_weeks": len(res.trades),
        # 条件胜率（持仓周内）——与论文 60.6% 可比口径（归档轮披露行公式）
        "cond_win_rate": (wins / n_pos) if n_pos else float("nan"),
    }


def main(argv: list[str]) -> int:
    if OUT.exists() and "--force-out" not in argv:
        print(f"[FAIL] 报告已存在：{OUT}——防误覆盖消融证据，确认覆盖传 --force-out")
        return 1
    # 数据态绑定（Q-20261110-08 B）：消融锚定行对拍归档数字，数据态漂移须显形
    snap = snapshot_data_paths([US_DATA],
                               OUT.with_name(OUT.stem + "-data-manifest.json"))
    wf = build_frame()
    start, end = year_bounds(wf)
    # 消融前置自检：volume 特征在消费窗+暖机段全齐备（否则 V1 的 ok 过滤会
    # 静默缩块——设计评审 C-1 教训的 volume 版）
    vol = wf.etf_volume
    assert vol is not None, "etf_volume 未构造"
    warm = max(0, start - 60)
    assert np.isfinite(vol[warm:end]).all(), "volume 特征存在缺失周"
    report = ["# US 复现消融报告——论文原文五候选逐一实施（提案 §12.9）", "",
              f"窗口与锚：与归档轮同源（year_bounds {wf.fridays[start]}.."
              f"{wf.fridays[end - 1]}，尾段 2023+ 零触及）；volume 特征 "
              f"{warm}:{end} 全齐备断言通过。", "",
              snapshot_report_line(snap), ""]
    rows_by_variant: dict[str, dict[int, dict]] = {}
    t0 = time.time()
    for name, kw in VARIANTS:
        rows_by_variant[name] = {}
        for n in N_GRID:
            c = cell(wf, n, start, end, **kw)
            rows_by_variant[name][n] = c
            if name.startswith("V0"):
                a_ma, a_pos = V0_ANCHOR[n]
                assert abs(c["mean_alpha"] - a_ma) < 6e-5, (
                    f"V0 N={n} 锚不符：{c['mean_alpha']:.6f} vs 归档 {a_ma}"
                    "——引擎默认行为被改动？")
                assert c["weeks_with_positions"] == a_pos, (
                    f"V0 N={n} 持仓周 {c['weeks_with_positions']}"
                    f" ≠ 归档 {a_pos}")
            print(f"[{time.time() - t0:7.1f}s] {name} N={n}: "
                  f"α {c['mean_alpha']:+.4f} 正年 {c['pos_years']}/11 "
                  f"持仓 {c['avg_positions']:.3f}/wk", flush=True)
    header = ("| 变体 | N | α均值 | α中位 | 正年 | CAGR | Sharpe | 周均持仓 | "
              "持仓周 | 条件胜率 |")
    report += [header, "|" + "---|" * 7 + "---|" + "---|" + "---|"]
    for name, _ in VARIANTS:
        for n in N_GRID:
            c = rows_by_variant[name][n]
            report.append(
                f"| {name} | {n} | {c['mean_alpha']:+.2%} | "
                f"{c['median_alpha']:+.2%} | {c['pos_years']}/11 | "
                f"{c['cagr']:+.2%} | {c['sharpe_mean']:.2f} | "
                f"{c['avg_positions']:.2f} | "
                f"{c['weeks_with_positions']}/{c['n_weeks']} | "
                f"{c['cond_win_rate']:.1%} |")
    report += ["", "论文对照：α 均值 +12.63% · 正年 10/11 · 周均持仓 2.25 · "
               "胜率 60.6%（条件口径同位）。", "", "## 逐年 α（执行周 ISO 年）", ""]
    for name, _ in VARIANTS:
        for n in N_GRID:
            c = rows_by_variant[name][n]
            report.append(f"- **{name} N={n}**: " + " ".join(
                f"{y}:{v:+.1%}" for y, v in sorted(c["alpha"].items())))
    report += ["", "## 实现方读法披露（论文未披露处的最优读法）", "",
               "- volume = 决策周最后交易日成交量（论文「exclude all but Friday",
               "  close prices」→ 周五单日 volume，与价格同一数据行；周合计口径未测）。",
               "- 4 隐层层宽 (64,32,16,8)：论文未披露层宽，漏斗延伸推定。",
               "- T=100：论文「a large number」未给数，引擎 T13 默认档。",
               "- 增量续训：单行单 pass（update_epochs=1）、标准化统计冻结年模型",
               "  训练切片、同自定义损失、种子 L2_SEED+t_train；对照=已测全量重训",
               "  trailing104（α -15.26%）。",
               "- 加权公式 OCR 损坏（偏差①），三读法 p1/p2/p3 见 WeightState；",
               "  信号（买入集）与 V0 位级一致——权重只影响买入集内资金分配。",
               "- N 论文未披露（偏差④），三格 {13,26,52} 全披露不择优。",
               "- 全部为已消费窗 2012-2022 内的探索性消融，不改 C 判定；尾段",
               "  2023+ 处女零触及（spec §3.8 第 10 条）。"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
