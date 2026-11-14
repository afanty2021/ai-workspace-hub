# tools/sector-rotation/repro_hold_confirm.py
"""R20261107-03 沉默持有方案族——2023+ 尾段确认窗单次消费驱动（预注册先行）。

冻结载体：workspace/proposals/2026-11-07-sector-rotation-hold-confirm.md
（commit 先于本文件任何确认窗运行——沿 R20261106-02 预注册 9f980ee 先例）。

方案族（§2.1 冻结）：MIMOModel 默认参数三格 N∈{13,26,52} 整族 + 持有规则
（gate 集空=沉默=持有上一期组合）+ 等权 + 冷启动（ROC/持仓空）。
窗口（§2.2 冻结）：决策周五 2023-01-01..2026-10-23 ∧ 执行周 ISO 年 ≥2023
∧ 当周 valid==11；末界=最后一个完整 exec 周（2026-10-30 决策的 W45 缺
周五行 2026-11-06，残缺弃）；决策 2022-12-30（exec 2023-W01）对称永久弃。
判定（§2.3 预声明）：族中位（三格毛 α 均值）>0 弱正 / 全正且 ≥3% 强正 /
≤0 证伪。单次消费：报告一经写出尾段转已消费，不得重跑。

用法：python repro_hold_confirm.py [--force-out]——OUT 已存在默认拒覆盖。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.models import MIMOModel, ROCState  # noqa: E402
from repro_paper import (  # noqa: E402
    N_GRID, REF2BP, US_DATA, ZERO, _run, annual_group_returns, alpha_vs_paper,
    build_frame, exec_iso_year, year_bounds)
from data_snapshot import snapshot_data_paths, snapshot_report_line  # noqa: E402

OUT = (REPO_ROOT / "output" / "sector-rotation" / "2026-11"
       / "us-hold-confirm-2026-11-07.md")
TAIL_START, TAIL_END = "2023-01-01", "2026-10-23"
EXPECT_WEEKS = (198, 199, 200)          # 数据被动更新即越界终止
FROZEN = ("R20261107-03 沉默持有确认（冻结于运行前，提案 2026-11-07-sector-"
          "rotation-hold-confirm.md）：MIMOModel 默认参数（hidden 64,32,16 · "
          "dropout 0.2 · epochs 200 · MC T=20 · λ_fin 0.1 · seed 20261106 · "
          "训练 104 周 tj≤t_train−1）· 纯价格 N∈{13,26,52} 三格整族 · 持有规则="
          "gate 集空→持有上一期组合（等权） · 冷启动 ROC/持仓空 · 毛 α 主判定"
          "+2bp 净参考 · 窗口 2023-01-01:2026-10-23 执行周 ISO 年 ≥2023 · "
          "族级判定=三格 α 均值中位：全正且 ≥3% 强正 / >0 弱正 / ≤0 证伪 · "
          "单次消费（报告写出即消费，不得重跑）")


def tail_bounds(wf) -> tuple[int, int]:
    """尾段窗口（镜像 year_bounds 结构）：决策周五 ∈ [TAIL_START, TAIL_END]
    ∧ 执行周 ISO 年 ≥2023 ∧ 当周 valid==11。断言与消费窗零重叠相接、周数
    落在冻结预期带（数据被动更新即终止）。"""
    idx = [t for t in range(len(wf.fridays))
           if TAIL_START <= wf.fridays[t] <= TAIL_END
           and exec_iso_year(wf.fridays[t]) >= 2023
           and bool(wf.valid[t].all())]
    assert idx, "2023+ 无决策周——数据未回补？"
    assert list(range(idx[0], idx[-1] + 1)) == idx, "尾段周不连续（数据缺口）"
    return idx[0], idx[-1] + 1


def make_hold_strat(models: dict, roc: ROCState):
    """沉默持有协议（冻结核）：gate 集非空=发声→组合=该集（等权，来自
    select 输出）；集空=沉默→持有上一期组合与权重；无历史→现金。闭包状态
    只在本窗口内演化（冷启动），不携带消费窗任何状态。"""
    last = {"w": None}

    def strat(wf_, t):
        y = int(wf_.fridays[t][:4])
        if y not in models:
            return {}
        sel = models[y].select(wf_, t, roc=roc)
        if sel:
            last["w"] = sel
            return sel
        return last["w"] or {}

    return strat


def family_verdict(mean_alphas: dict[int, float]) -> str:
    """§2.3 预声明判定域（机械归类）。"""
    vals = list(mean_alphas.values())
    med = float(np.median(vals))
    if all(v > 0 for v in vals) and med >= 0.03:
        return ("强正——OOS 方向+幅度初证成立，进入产品化评估"
                "（净口径复核+A 股域迁移评估）")
    if med > 0:
        return "弱正——方向未证伪但幅度不足以行动；归档待更长窗"
    return "证伪——该方案族本窗方向不成立（连同 §12.9/§12.10 构成同构负结果链）"


def hold_cell(wf, window: int, start, end) -> dict:
    """单格：年模型（y−1 年末决策周五 fit，训练数据全部 ≤已消费窗）+ 冷启动
    沉默持有；毛（主判定）+2bp 净（参考行）双跑，独立 ROCState（同 R20261106-02
    I-8：ROC 对与成本无关，独立状态保证两跑信号逐位一致）。"""
    years_run = sorted({int(wf.fridays[t][:4]) for t in range(start, end)})
    models: dict[int, MIMOModel] = {}
    for y in years_run:
        train_ts = [t for t in range(len(wf.fridays))
                    if wf.fridays[t][:4] == str(y - 1)]
        assert train_ts, f"{y} 无前年训练锚（数据缺口）"
        models[y] = MIMOModel(window=window).fit(wf, train_ts[-1])

    def run(cost):
        return _run(wf, make_hold_strat(models, ROCState()),
                    start, end, cost=cost)

    res, res_net = run(ZERO), run(REF2BP)
    years = [exec_iso_year(wf.fridays[t]) for t in res.t_rows]
    ann = annual_group_returns(years, res.weekly)
    ann_net = annual_group_returns(years, res_net.weekly)
    bench = annual_group_returns(
        years, np.array([wf.bench_300[t] for t in res.t_rows]))
    al, al_net = alpha_vs_paper(ann, bench), alpha_vs_paper(ann_net, bench)
    n_pos = sum(1 for tr in res.trades if tr["holdings"])
    wins = sum(1 for r in res.weekly if r > 0)
    return {
        "alpha": al, "net_alpha": al_net,
        "mean_alpha": float(np.mean(list(al.values()))),
        "net_mean_alpha": float(np.mean(list(al_net.values()))),
        "median_alpha": float(np.median(list(al.values()))),
        "pos_years": sum(1 for v in al.values() if v > 0),
        "n_years": len(al),
        "cagr": res.metrics["cagr"], "net_cagr": res_net.metrics["cagr"],
        "maxdd": res.metrics["max_dd"],
        "avg_positions": (sum(len(tr["holdings"]) for tr in res.trades)
                          / max(len(res.trades), 1)),
        "weeks_with_positions": n_pos, "n_weeks": len(res.trades),
        "cond_win_rate": (wins / n_pos) if n_pos else float("nan"),
        "turnover": res.metrics.get("turnover", float("nan")),
    }


def main(argv: list[str]) -> int:
    if OUT.exists() and "--force-out" not in argv:
        print(f"[FAIL] 报告已存在：{OUT}——单次消费证据防覆盖，确认传 --force-out")
        return 1
    # 数据态绑定（Q-20261110-08 B）：消费跑读数前落依赖数据 hash 清单
    snap = snapshot_data_paths([US_DATA],
                               OUT.with_name(OUT.stem + "-data-manifest.json"))
    wf = build_frame()
    _, c_end = year_bounds(wf)
    start, end = tail_bounds(wf)
    # 自检（提案 §2.2）：与消费窗零重叠——间隔恰为永久弃的 2022-12-30 决策
    # （消费窗 N3 弃其 exec 2023-W01；本窗弃其决策日 <2023-01-01；对称永久弃）
    assert start == c_end + 1, (
        f"尾段首周 {start} ≠ 消费窗末 {c_end}+1（重叠或意外缺口）")
    assert wf.fridays[c_end] == "2022-12-30", (
        f"消费窗末后应恰为永久弃决策 2022-12-30，实际 {wf.fridays[c_end]}")
    assert end - start in EXPECT_WEEKS, (
        f"尾段周数 {end - start} 越出冻结带 {EXPECT_WEEKS}——数据被更新过，终止")
    assert (wf.valid[start:end].sum(axis=1) == 11).all(), "尾段宇宙缩水"
    cells = {n: hold_cell(wf, n, start, end) for n in N_GRID}
    sigs = [tuple(sorted(round(v, 6) for v in c["alpha"].values()))
            for c in cells.values()]
    assert not (sigs[0] == sigs[1] == sigs[2]), "三格全等——window 未注入"
    verdict = family_verdict({n: cells[n]["mean_alpha"] for n in N_GRID})
    report = ["# US 持有制方案族——2023+ 尾段确认窗（R20261107-03）", "",
              f"预注册冻结配置：{FROZEN}", "",
              snapshot_report_line(snap), "",
              f"窗口：决策 {wf.fridays[start]}..{wf.fridays[end - 1]} 共 "
              f"{end - start} 周（执行周 ISO 年 2023-2026）· 与消费窗 "
              f"[..{wf.fridays[c_end - 1]}] 零重叠（间隔恰为永久弃决策 "
              f"2022-12-30）· valid==11 全窗。", "",
              "| 指标 | N=13 | N=26 | N=52 |", "|" + "---|" * 4]
    keys = [("α 均值（毛，主判定）", "mean_alpha", "{:+.2%}"),
            ("α 中位（毛）", "median_alpha", "{:+.2%}"),
            ("α 正年数", "pos_years", "{}/" + str(cells[13]["n_years"])),
            ("净 α 均值（2bp）", "net_mean_alpha", "{:+.2%}"),
            ("CAGR（毛/净）", None, None),
            ("MaxDD", "maxdd", "{:.1%}"),
            ("周均持仓", "avg_positions", "{:.2f}"),
            ("持仓周", None, None),
            ("条件胜率", "cond_win_rate", "{:.1%}"),
            ("换手 Σ", "turnover", "{:.0f}")]
    for label, key, fmt in keys:
        if key:
            report.append(f"| {label} | "
                          + " | ".join(fmt.format(c[key]) for c in cells.values()) + " |")
        elif label == "CAGR（毛/净）":
            report.append("| " + label + " | " + " | ".join(
                f"{c['cagr']:+.2%} / {c['net_cagr']:+.2%}" for c in cells.values()) + " |")
        else:
            report.append("| " + label + " | " + " | ".join(
                f"{c['weeks_with_positions']}/{c['n_weeks']}" for c in cells.values()) + " |")
    for n in N_GRID:
        c = cells[n]
        report.append(f"\n**N={n}** 逐年 α（执行周 ISO 年）: " + " ".join(
            f"{y}:{v:+.1%}" for y, v in sorted(c["alpha"].items())))
    spy = annual_group_returns(
        [exec_iso_year(wf.fridays[t]) for t in range(start, end)],
        np.array([wf.bench_300[t] for t in range(start, end)]))
    report += ["", "SPY 同口径逐年: " + " ".join(f"{y}:{v:+.1%}" for y, v in sorted(spy.items())),
               "", "## 族级判定（预声明域，机械归类）", "",
               f"三格 α 均值 {{13: {cells[13]['mean_alpha']:+.2%}, "
               f"26: {cells[26]['mean_alpha']:+.2%}, 52: {cells[52]['mean_alpha']:+.2%}}} "
               f"→ 族中位 {float(np.median([cells[n]['mean_alpha'] for n in N_GRID])):+.2%}",
               "", f"**{verdict}**", "",
               "## 披露", "",
               "- 单次消费：本报告写出即尾段转已消费（spec §3.8 第 10 条状态变更随结果落档）；",
               "  运行后不得以任何理由重跑或改判。",
               "- 冷启动期（ROC<26 对回退 0.5）如实计入；前段可能长期空仓属诚实结果。",
               "- 功效：~199 周窗单格 α 均值 se ≈9%/年量级——只对大效应有功效，弱正档天然脆弱。",
               "- 窗内含 2026-11 前夜美股崩盘段（SOX -12% 级）与 2023-2024 强牛，两端压力测试。",
               "- 训练数据全部 ≤2022 年末（已消费窗），尾段零泄漏；模型/门参数/等权零新自由度。"]
    text = "\n".join(report)
    assert FROZEN in text, "冻结配置未注入报告"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    for n in N_GRID:
        print(f"N={n}: 毛 α {cells[n]['mean_alpha']:+.2%} · 净 α "
              f"{cells[n]['net_mean_alpha']:+.2%} · CAGR {cells[n]['cagr']:+.2%} · "
              f"持仓周 {cells[n]['weeks_with_positions']}/{cells[n]['n_weeks']}")
    print(f"族级判定: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
