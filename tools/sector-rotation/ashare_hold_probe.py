# tools/sector-rotation/ashare_hold_probe.py
"""R20261107-05 A 股沉默持有方案族探索性测试（spec §3.8 第 8 条纯探索）。

用户指令「在A股测试一下」：美股 R20261107-03 强正方案族（MIMO 默认参数 +
沉默持有）向 A 股域的移植测试 + A 股归档引擎 L1 持有变体收口（EXP-20261107-05
遗留项）。**只报告不判定、不消费任何确认性窗口**（I10 语义）。

窗口纪律（提案 §1）：决策周五 ∈ [2020-07-10（S5 OOS 锚）, 2026-11-06（第 9 条
最后消费周）]；2026-11-13 起为 v3 确认窗处女段，帧内出现越界周五即终止。

Part 1：L1 归档预注册配置（w8/independent/k3/momentum）裸路径——沉默持有
（select()=={} → 持有上期组合）vs 同窗全平；复现锚=归档裸路径（基准档）
CAGR -14.65% / Sharpe -0.43 / MaxDD -80.88%，数据快照未变则逐位一致。

Part 2：美股冻结族移植——成熟子宇宙 U（锚周 valid ∧ 指数自 2018-12-28 无
缺口；探测定稿 |U|=69，指数首现一律 2013-09-06）上 MIMOModel 默认参数年冻结
N∈{13,26,52}，沉默持有 vs 全平 × 毛/基准/压力三档；锚=沪深300(510300)、
U 等权年再平衡、归档 L1/L0 数字并排。

用法：python ashare_hold_probe.py [--skip-part1]
报告：output/sector-rotation/2026-11/ashare-hold-probe-2026-11-07.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.baselines import EqualWeightAnnual  # noqa: E402
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import WeeklyFrame, build_weekly_frame  # noqa: E402
from sector_rotation.models import MIMOModel, ROCState, make_strategy  # noqa: E402
from sector_rotation.portfolio import RiskState  # noqa: E402
from sector_rotation.universe import UniverseSpec, load_universe  # noqa: E402
from sector_rotation.walkforward import run_walkforward  # noqa: E402
from repro_paper import N_GRID, ZERO, annual_group_returns, exec_iso_year  # noqa: E402

OUT = (REPO_ROOT / "output" / "sector-rotation" / "2026-11"
       / "ashare-hold-probe-2026-11-07.md")
ANCHOR = "2020-07-10"        # S5 OOS 锚（探索窗起点，与归档 L1 同窗）
END_CAP = "2026-11-06"       # 第 9 条最后消费周——窗硬顶，处女段 2026-11-13 起
IDX_T0 = "2018-12-28"        # 子宇宙指数完备性起点（提案 §2 冻结规则）
EXPECT_U = (60, 80)          # |U| 探测带（2026-11-07 实测 69；数据漂移护栏）
L1_BARE_ANCHOR = {"cagr": -0.1465, "sharpe": -0.43, "maxdd": -0.8088}
L1_ANCHOR_TOL = {"cagr": 5e-4, "sharpe": 0.02, "maxdd": 2e-3}
FROZEN = ("R20261107-05 A 股沉默持有探索（第 8 条纯探索，提案 2026-11-07-"
          "sector-rotation-ashare-hold-probe.md）：窗=决策周五 2020-07-10..2026-"
          "11-06（2026-11-13 起处女段零触及）· Part1 L1 w8/independent/k3/momentum"
          " 裸路径沉默持有 vs 全平（复现锚 -14.65%）· Part2 U=69 成熟子宇宙（锚周"
          " valid ∧ 指数自 2018-12-28 无缺口）MIMOModel 默认参数年冻结 N∈{13,26,52}"
          " 沉默持有 vs 全平 × 毛/基准/压力 · 持有规则=gate 空→持有上期组合（等权）"
          "· 锚=沪深300/U 等权年再平衡/归档 L1·L0 · 探索性只报告不判定")


def window_bounds(wf) -> tuple[int, int]:
    """探索窗 [start, end)：帧内出现 > END_CAP 的周五 = 处女段进帧 → 终止
    （数据被动更新护栏，同 repro_hold_confirm.EXPECT_WEEKS 精神）；start 行
    须恰为 ANCHOR、末行须恰为 END_CAP（快照漂移即拦截——Part 1 复现锚依赖
    与归档运行同窗）。"""
    beyond = [f for f in wf.fridays if f > END_CAP]
    if beyond:
        raise RuntimeError(
            f"帧内出现处女段决策周 {beyond[0]}（> {END_CAP}）——先截窗再跑，"
            "探索窗不得触碰 2026-11-13 起数据")
    assert wf.fridays[-1] == END_CAP, (
        f"帧末行 {wf.fridays[-1]} ≠ {END_CAP}——数据快照漂移，先核对再跑")
    return wf.fridays.index(ANCHOR), len(wf.fridays)
    # 末行 valid 全 0（宇宙快照 as-of 工件）引擎按 valid.any() 跳行——
    # 与归档运行同语义（归档 OOS 324 周 = 325 行跳 1）


def mature_cohort(wf) -> np.ndarray:
    """U = {j：锚周 valid[j] ∧ index_close 自 IDX_T0 起全 finite}（提案 §2
    冻结规则：只用覆盖几何、零收益信息、零阈值）。|U| 探测带断言在 main。"""
    fin = np.isfinite(wf.index_close[wf.fridays.index(IDX_T0):])
    u = wf.valid[wf.fridays.index(ANCHOR)] & fin.all(axis=0)
    return np.flatnonzero(u)


def sub_frame(wf, cols: np.ndarray) -> WeeklyFrame:
    """全帧列切片到 U：MIMOModel 全员窗语义逐位复用（子宇宙=帧的成员全集），
    bench/fridays 原样。"""
    members = [wf.members[c] for c in cols]
    return WeeklyFrame(
        fridays=wf.fridays,
        index_close=wf.index_close[:, cols],
        etf_symbols=[[row[c] for c in cols] for row in wf.etf_symbols],
        etf_open=wf.etf_open[:, cols],
        etf_close=wf.etf_close[:, cols],
        etf_prev_close=wf.etf_prev_close[:, cols],
        etf_week_amount=wf.etf_week_amount[:, cols],
        members=members,
        spec=UniverseSpec(members, wf.spec.clusters),
        valid=wf.valid[:, cols],
        dvalid=wf.dvalid[:, cols],
        bench_300=wf.bench_300,
        etf_volume=None if wf.etf_volume is None else wf.etf_volume[:, cols])


def make_hold(select):
    """沉默持有（与 repro_hold_confirm.make_hold_strat 同构，select 泛化）：
    sel 非空=发声→照单；空=沉默→持有上期组合；无历史→现金。零新增参数。"""
    st = {"last": None, "spoke": 0, "silent": 0}

    def strat(wf_, t):
        sel = select(wf_, t)
        if sel:
            st["last"], st["spoke"] = sel, st["spoke"] + 1
            return sel
        st["silent"] += 1
        return st["last"] or {}

    return strat, st


def make_count(select):
    """全平对照的机制活性计数（不持有：沉默周=现金）：select 每周必调，
    只计数不改返回——与裸运行逐位等价。"""
    st = {"spoke": 0, "silent": 0}

    def strat(wf_, t):
        sel = select(wf_, t)
        st["spoke" if sel else "silent"] += 1
        return sel

    return strat, st


def _run_bare(wf, strat, cost, start, end):
    return run_walkforward(wf, strat, cost=cost,
                           risk=RiskState(wf.spec, enabled=False),
                           start=start, end=end)


def summarize(res, wf, st: dict) -> dict:
    """统一读数：CAGR/Sharpe/MaxDD/持仓结构 + 执行周 ISO 年归年 α（vs 沪深300
    同周口径，与美股族同构）+ 机制活性（spoke/silent）。"""
    years = [exec_iso_year(wf.fridays[t]) for t in res.t_rows]
    ann = annual_group_returns(years, res.weekly)
    bench = annual_group_returns(years, np.array([wf.bench_300[t] for t in res.t_rows]))
    alpha = {y: ann[y] - bench[y] for y in ann}
    n_pos = sum(1 for tr in res.trades if tr["holdings"])
    wins = sum(1 for r in res.weekly if r > 0)
    m = res.metrics
    return {"cagr": m["cagr"], "sharpe": m["sharpe"], "maxdd": m["max_dd"],
            "turnover": m.get("turnover", float("nan")),
            "annual": ann, "alpha": alpha,
            "mean_alpha": float(np.mean(list(alpha.values()))),
            "pos_years": sum(1 for v in alpha.values() if v > 0),
            "n_years": len(alpha),
            "avg_positions": (sum(len(tr["holdings"]) for tr in res.trades)
                              / max(len(res.trades), 1)),
            "weeks_with_positions": n_pos, "n_weeks": len(res.trades),
            "cond_win_rate": (wins / n_pos) if n_pos else float("nan"),
            "spoke": st["spoke"], "silent": st["silent"]}


def _mimo_models(wf_sub, window: int, start: int, end: int) -> dict[int, MIMOModel]:
    """年冻结协议（与美股族同构）：窗内年份 y 的模型在 y−1 年末决策周五 fit
    （训练行 ≤104 周全部来自已消费历史）。缺前年数据或训练行不足（U 成员
    指数 2018-12 前有孤立洞，长窗跨洞年份凑不齐 window+2 行）→ 该年无模型
    = 沉默，如实计入（与 forward_track._models_for 缺年语义一致）。"""
    years_run = sorted({int(wf_sub.fridays[t][:4]) for t in range(start, end)})
    models: dict[int, MIMOModel] = {}
    for y in years_run:
        train_ts = [t for t in range(len(wf_sub.fridays))
                    if wf_sub.fridays[t][:4] == str(y - 1)]
        if not train_ts:
            continue
        try:
            models[y] = MIMOModel(window=window).fit(wf_sub, train_ts[-1])
        except ValueError:
            print(f"[INFO] N={window} 年 {y} 模型训练行不足（指数洞截断窗）"
                  "——该年无模型=沉默")
    return models


def part2_cells(wf_sub, start, end) -> tuple[dict, dict, dict]:
    """三格 × {全平, 持有} × {毛, 基准, 压力}；模型每格 fit 一次共享，每跑
    独立 ROCState/持有状态/计数（同美股 I-8：成本档间信号逐位一致）。"""
    costs = [("毛", ZERO), ("基准", CostModel.base()), ("压力", CostModel.stress())]
    models_by_n = {n: _mimo_models(wf_sub, n, start, end) for n in N_GRID}
    cover = {n: sorted(models_by_n[n]) for n in N_GRID}
    cells: dict[int, dict[tuple[str, str], dict]] = {}
    for n in N_GRID:
        models = models_by_n[n]

        def _select(roc):
            def f(wf_, t):
                y = int(wf_.fridays[t][:4])
                return models[y].select(wf_, t, roc=roc) if y in models else {}
            return f

        for scheme in ("全平", "持有"):
            for cname, cost in costs:
                roc = ROCState()
                strat, st = (make_hold(_select(roc)) if scheme == "持有"
                             else make_count(_select(roc)))
                res = _run_bare(wf_sub, strat, cost, start, end)
                cells.setdefault(n, {})[(scheme, cname)] = summarize(res, wf_sub, st)
    anchors = {}
    for cname, cost in costs:
        strat, st = make_count(EqualWeightAnnual())
        res = _run_bare(wf_sub, strat, cost, start, end)
        anchors[f"U 等权·{cname}"] = summarize(res, wf_sub, st)
    return cells, anchors, cover


def _row_p1(name: str, c: dict) -> str:
    return (f"| {name} | {c['cagr']:+.2%} | {c['sharpe']:.2f} | "
            f"{c['maxdd']:.2%} | {c['turnover']:.0f} | "
            f"{c['spoke']}/{c['silent']} | "
            f"{c['weeks_with_positions']}/{c['n_weeks']} | "
            f"{c['cond_win_rate']:.1%} |")


def main(argv: list[str]) -> int:
    spec = load_universe(REPO_ROOT / "config" / "sector-rotation-universe.md")
    wf = build_weekly_frame(REPO_ROOT / "data", spec)
    start, end = window_bounds(wf)
    cols = mature_cohort(wf)
    assert EXPECT_U[0] <= len(cols) <= EXPECT_U[1], (
        f"|U|={len(cols)} 越探测带 {EXPECT_U}——数据漂移，先复核规则再跑")
    print(f"窗 [{wf.fridays[start]}..{wf.fridays[end - 1]}] · U={len(cols)} · "
          f"帧 {len(wf.fridays)} 周")
    lines = ["# A 股沉默持有探索性测试（R20261107-05，第 8 条纯探索）", "",
             f"冻结复读：{FROZEN}", "",
             f"窗：决策周五 {wf.fridays[start]}..{wf.fridays[end - 1]}（帧末行 "
             f"{wf.fridays[-1]} valid 全 0=宇宙快照 as-of 工件，引擎跳行与归档"
             "同语义）。", ""]

    # ---- Part 1：L1 裸路径 全平 vs 沉默持有（基准档） ----
    if "--skip-part1" not in argv:
        l1 = make_strategy("L1", k=3, window=8, l1_variant="independent")
        liq, st_liq = make_count(l1)
        res_liq = _run_bare(wf, liq, CostModel.base(), start, end)
        c_liq = summarize(res_liq, wf, st_liq)
        for key, tol in L1_ANCHOR_TOL.items():      # 复现锚（提案 §2）
            assert abs(c_liq[key] - L1_BARE_ANCHOR[key]) <= tol, (
                f"复现锚失配 {key}: {c_liq[key]:.4f} vs 归档 "
                f"{L1_BARE_ANCHOR[key]:.4f}（容差 {tol}）——数据快照已变，先核对")
        hold, st_hold = make_hold(lambda w, t: l1(w, t))
        res_hold = _run_bare(wf, hold, CostModel.base(), start, end)
        c_hold = summarize(res_hold, wf, st_hold)
        lines += ["## Part 1：L1（w8/independent/k3）裸路径——全平 vs 沉默持有（基准档）", "",
                  "| 方案 | CAGR | Sharpe | MaxDD | 换手Σ | 发声/沉默周 | 持仓周 | 条件胜率 |",
                  "|---|---|---|---|---|---|---|---|",
                  _row_p1("全平（=归档裸路径）", c_liq),
                  _row_p1("沉默持有", c_hold), "",
                  f"复现锚：全平 CAGR {c_liq['cagr']:+.2%} vs 归档 -14.65%"
                  f"（容差内逐位一致 ✓——同窗同引擎同成本）。持有−全平 CAGR 差 = "
                  f"{c_hold['cagr'] - c_liq['cagr']:+.2%}；沉默周 {st_hold['silent']}"
                  f" 周（L1 沉默=结构性：M_t 空/训练行不足）。", ""]
        p1 = (c_liq, c_hold, st_hold)
    else:
        p1 = None
        lines += ["## Part 1：--skip-part1 跳过", ""]

    # ---- Part 2：U 子宇宙 MIMO 冻结族 全平 vs 沉默持有 ----
    wf_sub = sub_frame(wf, cols)
    cells, anchors, cover = part2_cells(wf_sub, start, end)
    lines += [f"## Part 2：U={len(cols)} 成熟子宇宙 MIMO 移植（默认参数年冻结，vs 全平）",
              "",
              "| N | 方案 | CAGR 毛/基准/压力 | α均值(毛,vs 沪深300) | 正年 | "
              "MaxDD(基准) | 发声/沉默周 | 周均持仓 | 条件胜率 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for n in N_GRID:
        for scheme in ("全平", "持有"):
            g, b, s = (cells[n][(scheme, k)] for k in ("毛", "基准", "压力"))
            lines.append(
                f"| {n} | {scheme} | {g['cagr']:+.1%} / {b['cagr']:+.1%} / "
                f"{s['cagr']:+.1%} | {g['mean_alpha']:+.2%} | "
                f"{g['pos_years']}/{g['n_years']} | {b['maxdd']:.1%} | "
                f"{g['spoke']}/{g['silent']} | {g['avg_positions']:.1f} | "
                f"{g['cond_win_rate']:.1%} |")
    for n in (13, 52):
        lines += ["", f"**N={n} 持有（毛）逐年 α（执行周 ISO 年，vs 沪深300）**: "
                  + " ".join(f"{y}:{v:+.1%}" for y, v in
                             sorted(cells[n][("持有", "毛")]["alpha"].items()))]
    lines += ["", "年模型覆盖（y 模型 = y−1 年末 fit；缺 = 该年沉默）：" + " · ".join(
        f"N={n}: {','.join(map(str, cover[n])) or '无'}" for n in N_GRID)]
    lines += ["", "## 锚（同窗同成本口径）", "",
              "| 锚 | CAGR 毛/基准/压力 | α均值(基准) | MaxDD(基准) |",
              "|---|---|---|---|"]
    g, b, s = (anchors[f"U 等权·{k}"] for k in ("毛", "基准", "压力"))
    lines.append(f"| U 等权年再平衡 | {g['cagr']:+.1%} / {b['cagr']:+.1%} / "
                 f"{s['cagr']:+.1%} | {b['mean_alpha']:+.2%} | {b['maxdd']:.1%} |")
    years = [exec_iso_year(wf.fridays[t]) for t in range(start, end)
             if wf.valid[t].any()]
    bench = annual_group_returns(
        years, np.array([wf.bench_300[t] for t in range(start, end)
                         if wf.valid[t].any()]))
    lines.append("| 沪深300(510300) | " + " ".join(
        f"{y}:{v:+.1%}" for y, v in sorted(bench.items())) + " | — | — |")
    lines += ["| 归档 L1 裸（全宇宙 valid，基准档） | -14.65% | — | -80.88% |",
              "| 归档 L0 动量 lb1（全宇宙 valid，基准档） | -3.44% | — | -28.01% |",
              "", "## 披露", "",
              "- **探索性（第 8 条）**：只报告不判定，不构成任何晋级/复活依据；"
              "意外强正亦只登记候选——确认性使用须先冻结协议 + 第 9 条触发条件"
              "（尾段 2026-11-13 起 ≥100 周 + 候选先冻结 + 显式拍板）。",
              "- U 规则 = 锚周 valid ∧ 指数自 2018-12-28 无缺口（覆盖几何，零收益"
              "信息零阈值）；其确认性重用须连同规则一起预注册冻结，防宇宙钓鱼。",
              "- 持有语义：gate 空=持有上期组合等权；A 股执行闸门原生（周一开盘"
              "涨停弃买/周均成交额 ≥5000 万/缺失拦截）；RiskState 关=裸路径"
              "（与美股族同构，A 股 overlay 属另一自由度不在本轮）。",
              "- MIMO 训练行 ≤104 周 tj≤t_train−1 全部 ≤2019+（已消费历史）；"
              "成员中途 valid 洞按原生 masked 协议处理训练标签。",
              "- U 成员指数在 2018-12-28 前有孤立洞（TDX 序列非全连续）→ 长窗"
              "（N=52）跨洞年份训练行不足 = 该年无模型（沉默计入，见年模型覆盖"
              "行）；短窗不受影响。",
              "- 沉默语义差异：L1 沉默=结构性（M_t 空/训练行不足）；MIMO 沉默="
              "原生门（MC 置信 ∧ ROC 阈值）——美股机制的本体对应物在 Part 2。"]
    text = "\n".join(lines)
    assert FROZEN in text, "冻结配置未注入报告"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    if p1:
        print(f"Part1 全平 {p1[0]['cagr']:+.2%}（锚 -14.65% ✓）/ 持有 "
              f"{p1[1]['cagr']:+.2%} · 沉默周 {p1[2]['silent']}")
    for n in N_GRID:
        h, liq = cells[n][("持有", "毛")], cells[n][("全平", "毛")]
        print(f"N={n}: 持有 CAGR {h['cagr']:+.2%} · α {h['mean_alpha']:+.2%} · "
              f"发声/沉默 {h['spoke']}/{h['silent']} ‖ 全平 CAGR {liq['cagr']:+.2%} · "
              f"α {liq['mean_alpha']:+.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
