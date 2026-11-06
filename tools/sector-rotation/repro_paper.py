# tools/sector-rotation/repro_paper.py
"""SSRN 4280640 论文复现驱动（R20261106-02 §9 U7；预注册先行，spec §6.3）。

Tier-1 引擎锚：L0 动量对照（论文缺失的对照组）+ 等权年再平衡 + 3 周帧手验
切面（etf_open/close vs 原始 jsonl 逐位）——锚全绿才继续。
Tier-2 主跑：MIMOModel 三格（window∈{13,26,52}）× 2012-2022，年模型冻结 +
跨年共享 ROC 状态（偏差⑨），毛口径（0 成本）主判定 + 2bp 净参考行（同信号
双跑、独立 ROC 状态——ROC 对与成本无关，净行只差成本），vs 论文 Table 3
并排对照 + 判定域 A/B/C 归类（无 p 值闸门——探索性诊断定性）。

自检（提案 §9）：config 注入断言、三格不全等、SPY 锚点带、全窗 valid==11
（设计评审 C-1 教训——缩宇宙须硬警报，计划评审 I-4）。

窗口纪律：消费区间硬编码 2012-01-01:2022-12-31；尾段 2023+ 处女——
--limit-weeks 只缩短不改终点，代码 assert 终点周 ≤ 2022-12-31。

用法：python repro_paper.py [--limit-weeks N] [--force-out]——OUT 已存在时
默认拒绝覆盖（归档 C 判定证据防确定性复查误毁），--force-out 才显式覆盖。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.baselines import EqualWeightAnnual, momentum_topk  # noqa: E402
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import _week_key, build_weekly_frame  # noqa: E402
from sector_rotation.models import MIMOModel, ROCState  # noqa: E402
from sector_rotation.portfolio import RiskState  # noqa: E402
from sector_rotation.universe import load_universe  # noqa: E402
from sector_rotation.walkforward import run_walkforward  # noqa: E402
from us_backfill import SPY_ANCHORS, annual_close_returns, check_anchors  # noqa: E402

YEARS = list(range(2012, 2023))
N_GRID = [13, 26, 52]
WIN_START, WIN_END = "2012-01-01", "2022-12-31"
US_CONFIG = REPO_ROOT / "config" / "sector-rotation-us-universe.md"
US_DATA = REPO_ROOT / "data" / "us-sector"
OUT = REPO_ROOT / "output" / "sector-rotation" / "2026-11" / "us-repro-2026-11-06.md"
CROSS_WEEKS = ["2012-01-06", "2016-11-04", "2020-03-20"]
PAPER = {"mean_alpha": 0.1263, "median_alpha": 0.0763, "alpha_2012": -0.0075,
         "alpha_2022": 0.284, "cagr_mean": 0.2661, "spx_cagr": 0.1397,
         "sharpe_mean": 1.39, "maxdd_mean": 0.10, "win_rate": 0.606,
         "avg_positions": 2.25}
ZERO = CostModel(commission_bps=0.0, spread_bps=0.0)
REF2BP = CostModel(commission_bps=0.0, spread_bps=2.0)
PREREG_CONFIG = ("US-复现-L2 预注册（与 spec §6.3 2026-11-06 行同源，R20261106-02）："
                 "MIMOModel · N∈{13,26,52} 三格全披露 · 训练=前 104 周年冻结"
                 "（训练行 tj≤t-1） · 标签=执行窗 open→close ≥1%（偏差⑦） · "
                 "特征=[t-N+1,t] 含决策周五（偏差⑥） · 置信=MC dropout T=20 · "
                 "中位±1SD ≥80% 质量 · ROC=trailing 52 对实际预测-标签 Youden J"
                 "（<26 回退 0.5，偏差⑨） · 等权（论文加权公式损坏，偏差①） · "
                 "损失=masked BCE+λ0.1 金融项（实现方口径，偏差⑤） · "
                 "seed=20261106 · CPU · 零成本主判定+2bp 参考行 · RiskState 关"
                 "（enabled=False，裸路径=唯一路径） · 窗口 2012-01-01:2022-12-31"
                 "（尾段 2023+ 处女） · 基准 SPY 复权（TR 代理） · α 判定=同周 "
                 "open→close 合成、日历年口径并排 · 年归属=执行周 ISO 年 · "
                 "判定域 A/B/C 预声明无 p 值闸门 · 最强格=α 均值→正年数→N 小")
DISCLOSURES = [
    "周定义：ISO 周内最后交易日决策、执行=次周首日 open→末日 close；Good Friday 等"
    "休市周自动退为周四决策（提案 §3 评审 M-5 注记）。",
    "MC dropout T=20：论文未给 T，较 T13 默认 100 降档（算力/方差折衷），边界敏感"
    "性提案 §3 评审 M-6 披露。",
    "A/B 边界 8% = 论文 12.63% 的锚定折扣（非推导）；7/11 正年 = 论文 10/11 正年"
    "的容差（提案 §5 评审 M-2/M-1）。",
    "ROC 阈值：年首回退期（<26 对 → 0.5）与缓冲跨年模型混用为实现方选择（偏差⑨，"
    "提案 §4，2026-11-06 用户追认）。",
    "α 双口径：判定列 = 同周 open→close 合成（引擎 bench 原生）；SPY 日历年 "
    "close-to-close 并排披露供论文对照（提案 §3 评审 I-8）。",
    "标签 = 执行窗 open→close ≥1%（偏差⑦，与执行 PnL 同口径，2026-11-06 用户"
    "追认）；净参考行基准为毛口径 SPY（指数无交易成本）。",
    "窗界过滤（复查轮 N3）：决策周五 ∈ 2012-01-01..2022-12-31 且执行周 ISO 年 "
    "≤2022——2012 年不含 W01 执行周（属窗外决策 2011-12-30）、末决策 2022-12-30 "
    "的执行周 2023-W01 已弃，尾段 2023+ 零触及。",
    "胜率/Sharpe 的分母含空仓周（本轮 458/573 周空仓）——与论文 60.6% 可比的"
    "是持仓周内条件胜率（由归档数字推导：win_rate×n_weeks/weeks_with_positions，"
    "N=13 ≈61%）；空仓周同时压缩 Sharpe 均值与标准差。",
]


def build_frame():
    spec = load_universe(US_CONFIG)
    return build_weekly_frame(US_DATA, spec, bench_symbol="SPY",
                              corrupt_threshold=1e9, pick_bypass_single=True)


def exec_iso_year(friday: str) -> int:
    """年归属 = 执行周 ISO 年（提案 §5 评审 M-3，计划评审 I-7）：决策 ISO 周
    的下一周——其周一 = _week_key(friday)+7，取该周 ISO 年（跨年 W52/W53
    决策周归下一年）。"""
    return date.fromordinal(_week_key(friday) + 7).isocalendar()[0]


def year_bounds(wf) -> tuple[int, int]:
    """消费窗（GC 6 + 复查轮 N3）：决策周五 ∈ 2012-01-01..2022-12-31 且执行周
    ISO 年 ≤ 2022——末决策周五 2022-12-30 的执行周是 2023-W01，必须弃（尾段
    2023+ 处女零触及；α 字典保持 2012..2022 十一键，与 ≥7/11 判据对齐）。"""
    idx = [t for t, f in enumerate(wf.fridays)
           if WIN_START <= f <= WIN_END and exec_iso_year(f) <= 2022]
    assert idx, "2012-2022 无决策周——数据未回补？"
    assert exec_iso_year(wf.fridays[idx[-1]]) <= 2022   # GC-6：末消费决策的执行周不出窗
    return idx[0], idx[-1] + 1


def annual_group_returns(keys: list[int], weekly: np.ndarray) -> dict[int, float]:
    """按执行周 ISO 年复合周收益（keys 与 weekly 一一对应）。"""
    out: dict[int, float] = {}
    for y, r in zip(keys, weekly):
        out.setdefault(int(y), 1.0)
        out[int(y)] *= (1.0 + float(r))
    return {y: v - 1.0 for y, v in out.items()}


def alpha_vs_paper(annual: dict[int, float],
                   bench: dict[int, float]) -> dict[int, float]:
    return {y: annual[y] - bench[y] for y in annual if y in bench}


def _paper_cell(pv, fmt: str) -> str:
    """论文列渲染（终审修复波）：None 才是「论文无此口径」；格式串一律可格式化
    ——旧守卫 `"{}" in fmt` 对 "{:+.2%}" 恒 False，报告 7/9 行误渲染为「—」。"""
    return fmt.format(pv) if pv is not None else "—"


def verdict(mean_alpha: float, pos_years: int) -> str:
    if mean_alpha >= 0.08 and pos_years >= 7:
        return "A（域内复现成功——引擎验证通过 + 论文方向可复现）"
    if mean_alpha > 0:
        return ("B（方向复现——引擎通过、幅度/一致性未达 A；归因待分：偏差①②③"
                " 消融 vs 论文全样本调参嫌疑，并列记录不预指派）")
    return "C（复现失败——引擎/数据单元核对后再下结论）"


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def manual_cross_check(wf, data_root: Path, weeks: list[str]) -> list[str]:
    """3 周帧手验：wf.etf_open/close vs 原始 jsonl 逐位（friction-log 教训——
    真实数据冒烟是任何网格的前置闸门）。"""
    errors = []
    for wk in weeks:
        t = wf.fridays.index(wk)
        for li, m in enumerate(wf.members):
            rows = _read_rows(data_root / "market" / "series"
                              / f"{m.etf_candidates[0]}.jsonl")
            by_wk: dict[int, list[dict]] = {}
            for r in rows:
                by_wk.setdefault(_week_key(r["date"]), []).append(r)
            nxt = next((c for c in (_week_key(wk) + 7, _week_key(wk) + 14)
                        if c in by_wk), None)
            if nxt is None:
                errors.append(f"{wk} {m.index_code}: 执行周缺数据")
                continue
            first, last = by_wk[nxt][0], by_wk[nxt][-1]
            if abs(wf.etf_open[t, li] - float(first["open"])) > 1e-9 \
                    or abs(wf.etf_close[t, li] - float(last["close"])) > 1e-9:
                errors.append(f"{wk} {m.index_code}: 帧价与原始行不符")
    return errors


def _run(wf, strategy, start, end, *, cost: CostModel):
    # min_universe 不传（复查轮 N7）：恒传显式 start 时 coverage_start 不被
    # 调用、该参数是死参——防坍缩语义由 Task 1 测试在 start=None 路径锁定
    return run_walkforward(wf, strategy, cost=cost,
                           risk=RiskState(wf.spec, enabled=False),
                           start=start, end=end, min_amount_wan=None)


def tier1(wf, start, end, data_root) -> tuple[list[str], list[str]]:
    errors = manual_cross_check(wf, data_root, CROSS_WEEKS)
    lines = ["## Tier-1 引擎锚（描述性，不判定）", "",
             "| 策略 | 逐年 α vs SPY（毛口径，执行周归年） | 均值 |",
             "|---|---|---|"]
    t_rows = list(range(start, end))
    bench_annual = annual_group_returns(
        [exec_iso_year(wf.fridays[t]) for t in t_rows],
        np.array([wf.bench_300[t] for t in t_rows]))
    for name, strat in [("L0 动量 k=3/lb=1", momentum_topk),
                        ("等权年再平衡", EqualWeightAnnual())]:
        res = _run(wf, strat, start, end, cost=ZERO)
        ann = annual_group_returns(
            [exec_iso_year(wf.fridays[t]) for t in res.t_rows], res.weekly)
        al = alpha_vs_paper(ann, bench_annual)
        mean_a = float(np.mean(list(al.values())))
        lines.append(f"| {name} | " + " ".join(f"{y}:{al[y]:+.1%}" for y in sorted(al))
                     + f" | {mean_a:+.1%} |")
    lines.append("")
    lines.append("SPY（TR 代理，执行周归年）逐年: "
                 + " ".join(f"{y}:{v:+.1%}" for y, v in sorted(bench_annual.items())))
    return errors, lines


def mimo_cell(wf, window: int, start, end, limit_weeks=None) -> dict:
    stop = end if limit_weeks is None else min(end, start + limit_weeks)
    years_run = sorted({int(wf.fridays[t][:4]) for t in range(start, stop)})
    models: dict[int, MIMOModel] = {}
    for y in years_run:
        # 计划评审 C-3：训练集扫全帧（受 stop 约束兼容 --limit-weeks）——start
        # 是 2012 首周，y-1（如 2011）的训练周在 start 之前，必须向前扫
        train_ts = [t for t in range(0, stop)
                    if int(wf.fridays[t][:4]) == y - 1]
        if train_ts:
            models[y] = MIMOModel(window=window).fit(wf, train_ts[-1])

    def make_strat():
        # 计划评审 I-8：毛/净两次运行各持独立 ROCState——ROC 对 =
        # (预测, 已实现标签) 与成本无关，独立状态保证两跑信号逐位一致
        roc = ROCState()

        def strat(wf_, t):
            y = int(wf_.fridays[t][:4])
            return models[y].select(wf_, t, roc=roc) if y in models else {}

        return strat

    res = _run(wf, make_strat(), start, stop, cost=ZERO)
    res_net = _run(wf, make_strat(), start, stop, cost=REF2BP)
    years = [exec_iso_year(wf.fridays[t]) for t in res.t_rows]
    ann = annual_group_returns(years, res.weekly)
    ann_net = annual_group_returns(years, res_net.weekly)
    bench_annual = annual_group_returns(
        years, np.array([wf.bench_300[t] for t in res.t_rows]))
    al = alpha_vs_paper(ann, bench_annual)
    al_net = alpha_vs_paper(ann_net, bench_annual)
    by_year: dict[int, list[float]] = {}
    for y, r in zip(years, res.weekly):
        by_year.setdefault(y, []).append(float(r))
    sharpe_years = {y: (float(np.mean(v)) / float(np.std(v)) * np.sqrt(52)
                        if np.std(v) > 0 else float("nan"))
                    for y, v in by_year.items()}
    return {
        "annual": ann, "alpha": al,
        "mean_alpha": float(np.mean(list(al.values()))),
        "median_alpha": float(np.median(list(al.values()))),
        "pos_years": sum(1 for v in al.values() if v > 0),
        "net_alpha_mean": float(np.mean(list(al_net.values()))),
        "net_cagr": res_net.metrics["cagr"],
        "sharpe_years": sharpe_years,
        "sharpe_mean": float(np.nanmean(list(sharpe_years.values()))),
        "cagr": res.metrics["cagr"], "maxdd": res.metrics["max_dd"],
        "win_rate": res.metrics["win_rate"],
        "avg_positions": (sum(len(tr["holdings"]) for tr in res.trades)
                          / max(len(res.trades), 1)),
        "weeks_with_positions": sum(1 for tr in res.trades if tr["holdings"]),
        "n_weeks": len(res.trades),
    }


def main(argv: list[str]) -> int:
    limit = None
    if "--limit-weeks" in argv:
        limit = int(argv[argv.index("--limit-weeks") + 1])
    # 覆盖保护（终审修复波）：OUT 是归档 C 判定证据——确定性复查重跑不得静默
    # 重写，须 --force-out 显式覆盖
    if OUT.exists() and "--force-out" not in argv:
        print(f"[FAIL] 报告已存在：{OUT}——防误覆盖归档证据，确认覆盖请传 --force-out")
        return 1
    wf = build_frame()
    start, end = year_bounds(wf)
    # 自检（提案 §9，计划评审 I-4）：全窗 valid==11 + SPY 锚点带——缩宇宙/数据
    # 漂移必须硬警报，静默通过即重演设计评审 C-1
    assert (wf.valid[start:end].sum(axis=1) == 11).all(), "宇宙缩水：valid≠11"
    spy_annual = annual_close_returns(
        _read_rows(US_DATA / "market" / "series" / "SPY.jsonl"))
    anchor_errs = check_anchors(spy_annual, SPY_ANCHORS)
    assert not anchor_errs, anchor_errs
    report = ["# US 复现报告（SSRN 4280640 × 自研引擎）",
              "", f"预注册配置：{PREREG_CONFIG}", ""]
    errors, t1 = tier1(wf, start, end, US_DATA)
    report += t1
    if errors:
        report += ["", "## [FAIL] Tier-1 锚未过，终止", ""] + errors
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
        print("\n".join(errors))
        return 1
    cells = {n: mimo_cell(wf, n, start, end, limit) for n in N_GRID}
    # 自检：三格不全等（sweep 纪律——window 必须真实注入）
    sigs = [tuple(sorted(round(v, 6) for v in c["alpha"].values()))
            for c in cells.values()]
    if sigs[0] == sigs[1] == sigs[2]:
        print("[FAIL] 三格结果全等——window 未生效")
        return 1
    # 最强格三级链（提案 §5 评审 I-4，计划评审 I-6）：α 均值 → 正年数 → N 小
    best = max(cells, key=lambda n: (cells[n]["mean_alpha"],
                                     cells[n]["pos_years"], -n))
    report += ["", "## Tier-2 MIMO 三格（毛口径主判定 + 2bp 净参考行）", "",
               "| 指标 | 论文 | " + " | ".join(f"N={n}" for n in N_GRID) + " |",
               "|---|---|" + "---|" * len(N_GRID)]
    rows = [("α 均值", "mean_alpha", PAPER["mean_alpha"], "{:+.2%}"),
            ("α 中位", "median_alpha", PAPER["median_alpha"], "{:+.2%}"),
            ("α 正年数", "pos_years", 10, "{}/11"),
            ("Sharpe 均值", "sharpe_mean", PAPER["sharpe_mean"], "{:.2f}"),
            ("CAGR", "cagr", PAPER["cagr_mean"], "{:+.2%}"),
            ("MaxDD", "maxdd", PAPER["maxdd_mean"], "{:.2%}"),
            ("胜率", "win_rate", PAPER["win_rate"], "{:.1%}"),
            ("周均持仓数", "avg_positions", PAPER["avg_positions"], "{:.2f}"),
            ("净α均值(2bp)", "net_alpha_mean", None, "{:+.2%}")]
    for label, key, pv, fmt in rows:
        paper_cell = _paper_cell(pv, fmt)
        report.append(f"| {label} | {paper_cell} | "
                      + " | ".join(fmt.format(c[key]) for c in cells.values()) + " |")
    for n in N_GRID:
        c = cells[n]
        report.append(f"\n**N={n}** 逐年 α（执行周 ISO 年）: "
                      + " ".join(f"{y}:{v:+.1%}" for y, v in sorted(c["alpha"].items())))
        report.append(f"N={n} 净口径(2bp)：α 均值 {c['net_alpha_mean']:+.2%} · "
                      f"CAGR {c['net_cagr']:+.2%} · 有持仓周 "
                      f"{c['weeks_with_positions']}/{c['n_weeks']} · 逐年 Sharpe "
                      + " ".join(f"{y}:{c['sharpe_years'][y]:.2f}"
                                 for y in sorted(c["sharpe_years"])))
        report.append(f"N={n} 判定: {verdict(c['mean_alpha'], c['pos_years'])}")
    report += ["", "## 总判定（最强格 N={best}，三级链 α 均值→正年数→N 小，三格全披露）".format(best=best),
               "", verdict(cells[best]["mean_alpha"], cells[best]["pos_years"]),
               "", "SPY 日历年 close-to-close（论文对照口径，评审 I-8）: "
               + " ".join(f"{y}:{spy_annual[y]:+.1%}" for y in YEARS if y in spy_annual),
               "", "## 口径与披露", ""]
    report += [f"- {d}" for d in DISCLOSURES]
    report += ["", "偏差清单与边界见提案 §4/§5（R20261106-02）。"]
    # 自检：config 注入断言
    text = "\n".join(report)
    assert PREREG_CONFIG in text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    print(f"best N={best}: {verdict(cells[best]['mean_alpha'], cells[best]['pos_years'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
