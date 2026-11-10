"""R20261110-05 沉默持有方案族——崩盘段检验（预注册载体）。

冻结载体：workspace/proposals/2026-11-10-hold-crash-check.md（先于任何运行写盘；
§8 附录=首跑复现门失败排查与门修订，状态载体门替代归档 summary 门）。

三段（提案 §3-§5 + §8 修订）：
  Phase 1  状态重建（消费窗 199 周）——归档 summary 对靶降级为披露表（根因=
           us_backfill 全量重拉静默改史，归档数字绑定已消失数据态）；
  Gate     状态载体门：重放终态必须命中前向跟踪器持久化状态（11-07 独立引导
           重放）——三格 10-30 持仓、10-30/11-06 沉默/发声逐格一致，不一致即
           异常终止（不构成消费）；
  Phase 2/3  扩展 exec W45（崩盘周）三格收益/α_week/EW-11 锚/MaxDD 创深/
           gate 行为 + 决策 2026-11-06 gate-only 实时读数 + W45 逐日解剖。

用法：python hold_crash_check.py——OUT 已存在默认拒覆盖（单次消费）。
"""
from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.models import MIMOModel, ROCState  # noqa: E402
from repro_paper import (  # noqa: E402
    N_GRID, US_DATA, ZERO, _run, alpha_vs_paper, annual_group_returns,
    build_frame, exec_iso_year)

OUT = (REPO_ROOT / "output" / "sector-rotation" / "2026-11"
       / "us-hold-crash-check-2026-11-10.md")
TRACKER_LOG = (REPO_ROOT / "output" / "sector-rotation" / "forward"
               / "track-log.jsonl")
TAIL_START, TAIL_END = "2023-01-01", "2026-10-23"
D_CRASH_FRIDAY = "2026-11-06"
W45_DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]

# 归档披露值（已消费报告 §5；首跑证明不可重放对靶——数据层静默改史，见提案 §8）
ARCH = {
    13: {"mean_alpha": 0.0425, "cagr": 0.2290, "pos_weeks": 190, "turnover": 47, "maxdd": -0.157},
    26: {"mean_alpha": 0.0297, "cagr": 0.2145, "pos_weeks": 188, "turnover": 54, "maxdd": -0.127},
    52: {"mean_alpha": 0.0495, "cagr": 0.2250, "pos_weeks": 173, "turnover": 62, "maxdd": -0.137},
}

FROZEN = ("R20261110-05 崩盘段检验（冻结于运行前，提案 2026-11-10-hold-crash-check.md "
          "含 §8 门修订附录）：载体=R20261107-03 冻结方案族零改动（MIMOModel 默认参数 "
          "seed 20261106 · 纯价格 N∈{13,26,52} 三格整族 · gate 集空→持有上一期组合 · "
          "ROCState 跨年共享 · 冷启动 2023-01 · 毛 α 主判定）· 扩展周用 2025-12-26 锚"
          "冻结的 2026 模型（零新训练）· 状态载体门=重放终态命中前向跟踪器持久化状态"
          "（归档 summary 对靶降级为披露，根因=us_backfill 静默改史）· 扩展 exec W45="
          "决策 2026-10-30 · 判定域=三格 α_week 族中位：≥0 相对防守成立 / [−1%,0) 中性 / "
          "<−1% 相对防守失败 · 单周零功效，描述性归类不动族级强正判定 · 单次消费")


def recon_bounds(wf) -> tuple[int, int]:
    """重建区间（镜像 R20261107-03 tail_bounds，无 EXPECT_WEEKS 带——数据已更新）。"""
    idx = [t for t in range(len(wf.fridays))
           if TAIL_START <= wf.fridays[t] <= TAIL_END
           and exec_iso_year(wf.fridays[t]) >= 2023
           and bool(wf.valid[t].all())]
    assert idx and list(range(idx[0], idx[-1] + 1)) == idx, "重建窗周不连续"
    return idx[0], idx[-1] + 1


def fit_models(wf, window: int, start: int, ext_end: int) -> dict[int, MIMOModel]:
    """年冻结模型（协议同 repro_hold_confirm.hold_cell；A/B 两跑共享同一批）。"""
    years_run = sorted({int(wf.fridays[t][:4]) for t in range(start, ext_end)})
    models: dict[int, MIMOModel] = {}
    for y in years_run:
        train_ts = [t for t in range(len(wf.fridays))
                    if wf.fridays[t][:4] == str(y - 1)]
        assert train_ts, f"{y} 无前年训练锚（数据缺口）"
        models[y] = MIMOModel(window=window).fit(wf, train_ts[-1])
    return models


def make_strat(models: dict[int, MIMOModel], roc: ROCState, hist: dict, last: dict):
    """沉默持有协议（与 repro_hold_confirm.make_hold_strat 逐行同语义；hist 记录
    gate 原始输出 vs 最终持仓，last 显式外置供状态延续）。"""
    def strat(wf_, t):
        y = int(wf_.fridays[t][:4])
        if y not in models:
            return {}
        sel = models[y].select(wf_, t, roc=roc)
        out = sel if sel else (last["w"] or {})
        hist[t] = {"gate": dict(sel), "held": dict(out)}
        if sel:
            last["w"] = sel
        return out
    return strat


def cell_metrics_199(wf, res) -> dict:
    """消费窗 199 周指标（口径逐行镜像 hold_cell：毛 α 主判定）。"""
    years = [exec_iso_year(wf.fridays[t]) for t in res.t_rows]
    ann = annual_group_returns(years, res.weekly)
    bench = annual_group_returns(
        years, np.array([wf.bench_300[t] for t in res.t_rows]))
    al = alpha_vs_paper(ann, bench)
    return {"mean_alpha": float(np.mean(list(al.values()))),
            "cagr": res.metrics["cagr"], "maxdd": res.metrics["max_dd"],
            "pos_weeks": sum(1 for tr in res.trades if tr["holdings"]),
            "turnover": int(round(res.metrics.get("turnover", 0.0)))}


def load_tracker_log() -> dict[tuple[int, str], dict]:
    rows = [json.loads(l) for l in open(TRACKER_LOG) if l.strip()]
    return {(r["n"], r["friday"]): r for r in rows}


def load_tracker_state() -> dict:
    """前向跟踪器 state.json（含 per_n.roc.last_t；评审 M-4：§8 状态载体门 last_t 子句）。"""
    p = TRACKER_LOG.parent / "state.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def verdict_family(alpha_week: dict[int, float]) -> str:
    med = float(np.median(list(alpha_week.values())))
    if med >= 0:
        return (f"相对防守成立（族中位 α_week {med:+.2%} ≥ 0）——崩盘周未跑输大盘，"
                "持有结构的行业构成自带缓冲")
    if med >= -0.01:
        return (f"中性（族中位 α_week {med:+.2%} ∈ [−1%,0)）——与大盘同跌同损，"
                "无缓冲也无放大")
    return (f"相对防守失败（族中位 α_week {med:+.2%} < −1%）——持仓构成在崩盘周"
            "放大损伤，EXP-20261107-05 风险注记坐实")


def daily_basket_path(held: dict[int, float], members) -> list[float]:
    """W45 持仓篮子逐日 NAV（周一开盘建仓=1.0，收盘 MTM）。"""
    px: dict[int, dict[str, tuple[float, float]]] = {}
    for col in held:
        sym = members[col].index_code
        rows = {}
        with open(US_DATA / "market" / "series" / f"{sym}.jsonl") as fh:
            for line in fh:
                b = json.loads(line)
                if b["date"] in W45_DAYS:
                    rows[b["date"]] = (float(b["open"]), float(b["close"]))
        assert len(rows) == 5, f"{sym} W45 日线缺行（{len(rows)}/5）"
        px[col] = rows
    nav = [1.0]
    for d in W45_DAYS[1:]:
        nav.append(sum(w * px[col][d][1] / px[col][W45_DAYS[0]][0]
                       for col, w in held.items()))
    return nav


def spy_daily_path() -> list[float]:
    rows = {}
    with open(US_DATA / "market" / "series" / "SPY.jsonl") as fh:
        for line in fh:
            b = json.loads(line)
            if b["date"] in W45_DAYS:
                rows[b["date"]] = (float(b["open"]), float(b["close"]))
    return [1.0] + [rows[d][1] / rows[W45_DAYS[0]][0] for d in W45_DAYS[1:]]


def main(argv: list[str]) -> int:
    if OUT.exists() and "--force-out" not in argv:
        print(f"[FAIL] 报告已存在：{OUT}——单次消费防覆盖，确认传 --force-out")
        return 1

    wf = build_frame()
    start, rec_end = recon_bounds(wf)
    t1030, t1106 = rec_end, rec_end + 1
    assert rec_end - start == 199, f"重建窗 {rec_end - start} 周 ≠ 199"
    assert wf.fridays[t1030] == "2026-10-30", wf.fridays[t1030]
    assert wf.fridays[t1106] == D_CRASH_FRIDAY, wf.fridays[t1106]
    assert bool(wf.valid[t1030].all()), "W45 执行周 valid 缩水"
    assert not bool(wf.valid[t1106].any()), "W46 应无执行数据（gate-only）"

    lines = ["# US 沉默持有方案族——崩盘段检验（R20261110-05）", "",
             f"预注册冻结配置：{FROZEN}", "",
             f"重建窗：决策 {wf.fridays[start]}..{TAIL_END} 共 199 周；扩展 exec W45="
             f"决策 2026-10-30（11-02..11-06，含崩盘 11-05/06）；决策 2026-11-06 "
             "gate-only（W46 无数据）。", "",
             "## Phase 1 状态重建——归档对靶披露（§8 降级为非门）", "",
             "| N | 毛 α 均值 重放/归档 | 毛 CAGR 重放/归档 | 持仓周 重放/归档 | "
             "换手Σ 重放/归档 | MaxDD 重放/归档 |", "|---|---|---|---|---|---|"]

    cells = {}
    for n in N_GRID:
        models = fit_models(wf, n, start, t1030 + 1)
        assert set(models) == {2023, 2024, 2025, 2026}
        rocA, lastA = ROCState(), {"w": None}
        resA = _run(wf, make_strat(models, rocA, {}, lastA), start, rec_end, cost=ZERO)
        m = cell_metrics_199(wf, resA)
        a = ARCH[n]
        lines.append(f"| {n} | {m['mean_alpha']:+.2%} / {a['mean_alpha']:+.2%} "
                     f"| {m['cagr']:+.2%} / {a['cagr']:+.2%} "
                     f"| {m['pos_weeks']} / {a['pos_weeks']} "
                     f"| {m['turnover']} / {a['turnover']} "
                     f"| {m['maxdd']:.1%} / {a['maxdd']:.1%} |")
        rocB, lastB, histB = ROCState(), {"w": None}, {}
        resB = _run(wf, make_strat(models, rocB, histB, lastB), start, t1030 + 1, cost=ZERO)
        assert np.allclose(resB.weekly[:199], resA.weekly, atol=1e-12), "扩展跑前段漂移"
        # 11-06 gate-only：ROC 快照副本直调（不污染主状态）
        snap = ROCState()
        snap.pairs = deque(rocB.pairs, maxlen=52)
        snap.last_t, snap.last_pred = rocB.last_t, rocB.last_pred.copy()
        sel_1106 = models[2026].select(wf, t1106, roc=snap)
        cells[n] = {"resB": resB, "m199": m, "hist": histB,
                    "sel_1106": dict(sel_1106)}
    lines += ["",
              "重放≠归档的根因（提案 §8 排查）：us_backfill 全量重拉 yahoo（auto_adjust）"
              "以 batch 权威写者按字段覆盖全部历史行——消费跑数据态已被静默覆盖，归档 "
              "summary 绑定在不再存在的数据上。N=26/52 差 0.3-0.5pp、N=13 差 3.8pp："
              "微小改史经 ROC 阈值/持仓路径放大（方案族路径敏感，本身入风险披露）。", ""]

    # ---- 状态载体门（§8 修订）：重放终态 vs 前向跟踪器持久化状态 ----
    trk = load_tracker_log()
    state_per_n = load_tracker_state().get("per_n") or {}
    names = lambda d: "+".join(sorted(wf.members[c].index_code for c in d)) or "（空/现金）"
    gate_fails = []
    for n in N_GRID:
        h = cells[n]["hist"]
        for t, fri in ((t1030, "2026-10-30"), (t1106, "2026-11-06")):
            key = (n, fri)
            if key not in trk:
                gate_fails.append(f"N={n} {fri} 跟踪器无落档")
                continue
            row = trk[key]
            if fri == "2026-10-30":
                mine_spoke, mine_set = bool(h[t]["gate"]), names(h[t]["gate"])
            else:
                sel = cells[n]["sel_1106"]
                mine_spoke, mine_set = bool(sel), names(sel)
            if mine_spoke != bool(row["spoke"]) or (
                    mine_spoke and mine_set != "+".join(sorted(row["members"]))):
                gate_fails.append(f"N={n} {fri}: 重放 {'发声 ' + mine_set if mine_spoke else '沉默'}"
                                  f" vs 跟踪器 {'发声 ' + '+'.join(row['members']) if row['spoke'] else '沉默'}")
        # 评审 M-4：§8 状态载体门 last_t 子句——跟踪器 ROC 消费进度须恰在 11-06 决策索引
        lt = ((state_per_n.get(str(n)) or {}).get("roc") or {}).get("last_t")
        if lt != t1106:
            gate_fails.append(f"N={n}: 跟踪器 roc.last_t={lt} ≠ 11-06 决策索引 {t1106}")
    if gate_fails:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(lines) + "\n\n[ABORT] 状态载体门未过——异常终止，"
                       "不构成消费（提案 §8）：\n" + "\n".join(gate_fails) + "\n",
                       encoding="utf-8")
        print("[ABORT] 状态载体门未过:", *gate_fails, sep="\n  ")
        return 1
    lines += ["## 状态载体门：过——三格 10-30/11-06 行为与跟踪器落档逐格一致", ""]

    # ---- Phase 2 崩盘周 ----
    spy_w45 = float(wf.bench_300[t1030])
    ew_w45 = float(np.nanmean(wf.etf_close[t1030] / wf.etf_open[t1030] - 1.0))
    lines += ["## Phase 2 崩盘周（exec W45，2026-11-02..11-06）", "",
              f"基准：SPY 同周 open→close **{spy_w45:+.2%}**；EW-11 锚（全 11 等权）"
              f"**{ew_w45:+.2%}**。", "",
              "| N | W45 组合 | α_week vs SPY | vs EW-11 | MaxDD 扩展后 | 消费窗(重放) | 创深 |",
              "|---|---|---|---|---|---|---|"]
    alpha_week = {}
    for n in N_GRID:
        r = float(cells[n]["resB"].weekly[-1])
        alpha_week[n] = r - spy_w45
        dd_ext = cells[n]["resB"].metrics["max_dd"]
        dd_old = cells[n]["m199"]["maxdd"]
        deeper = dd_ext < dd_old - 0.002
        lines.append(f"| {n} | {r:+.2%} | {r - spy_w45:+.2%} | {r - ew_w45:+.2%} "
                     f"| {dd_ext:.1%} | {dd_old:.1%} | {'是' if deeper else '否'} |")
    lines += ["", f"**判定（§5 预声明域，机械归类）：{verdict_family(alpha_week)}**", "",
              "### gate 行为与持仓（决策 10-23 → 10-30 → 11-06）", ""]
    for n in N_GRID:
        h = cells[n]["hist"]
        for t, lab in ((t1030 - 1, "10-23"), (t1030, "10-30")):
            if t in h:
                spoke = "发声" if h[t]["gate"] else "沉默持有"
                lines.append(f"- N={n} 决策 {lab}：{spoke}"
                             + (f" gate={names(h[t]['gate'])}" if h[t]["gate"] else "")
                             + f" → 持仓 {names(h[t]['held'])}")
        sel = cells[n]["sel_1106"]
        action = (f"发声 → W46 新持仓 {names(sel)}" if sel
                  else f"沉默 → W46 继续持有 {names(h[t1030]['held'])}")
        lines.append(f"- N={n} 决策 11-06（gate-only）：{action}")
    lines.append("")

    # ---- Phase 3 W45 逐日解剖 ----
    lines += ["## W45 逐日解剖（周一开盘建仓=1.0，收盘 MTM）", "",
              "| 日 | SPY | " + " | ".join(f"N={n}" for n in N_GRID) + " |",
              "|---" * (len(N_GRID) + 2) + "|"]
    spy_nav = spy_daily_path()
    navs = {n: daily_basket_path(cells[n]["hist"][t1030]["held"], wf.members)
            for n in N_GRID}
    for i, d in enumerate(W45_DAYS[1:], start=1):
        tag = "（崩盘日）" if d == "2026-11-05" else "（反弹日）" if d == "2026-11-06" else ""
        row = [d + tag, f"{spy_nav[i] - 1:+.2%}"]
        row += [f"{navs[n][i] - 1:+.2%}" for n in N_GRID]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "周收益核对（逐日合成 vs 引擎周频）: "
              + " ".join(f"N={n}: {navs[n][-1] - 1:+.2%} vs {float(cells[n]['resB'].weekly[-1]):+.2%}"
                         for n in N_GRID),
              "", "## 披露", "",
              "- 单周零功效：档位是描述性归类，不构成对 R20261107-03 族级强正判定的"
              "升级/降级（该判定维持冻结）；不外推「崩盘防守能力」一般结论。",
              "- 状态重建经用户明示放开（冻结提案 §5 预留）；重放状态经独立同日引导的"
              "前向跟踪器落档交叉验证（状态载体门），已消费报告未重判未重写。",
              "- 归档 summary 不可重放对靶（披露表）——根因=数据层静默改史"
              "（us_backfill 全量重拉 upsert），修复待拍板另入队列；连带披露：方案族"
              "对输入微扰路径敏感（N=26/52 漂 0.3-0.5pp、N=13 漂 3.8pp）。",
              "- 毛口径（成本 ZERO，同消费窗主判定）；SPY=TR 代理；崩盘周 ETF 流动性/"
              "滑点未建模。", "", "单次消费：本报告写出即已消费，不得重跑（数据再更新后"
              "W46 检验须新提案）。"]

    text = "\n".join(lines)
    assert FROZEN in text, "冻结配置未注入报告"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    for n in N_GRID:
        print(f"N={n}: W45 {float(cells[n]['resB'].weekly[-1]):+.2%} "
              f"α_week {alpha_week[n]:+.2%} "
              f"MaxDD {cells[n]['resB'].metrics['max_dd']:.1%}")
    print(f"判定: {verdict_family(alpha_week)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
