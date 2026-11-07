# tools/sector-rotation/forward_track.py
"""R20261107-03 沉默持有方案族——前向纸面跟踪器（产品化评估基础设施）。

动机：确认窗（2023-01..2026-10-23）不含 2026-11 崩盘，防守能力未验——
前向周频跟踪从现在开始积累证据（2026-11 起新数据不属任何消费窗，不触碰
「不得重跑」条款；冻结窗口的确定性重放仅用于 ROC/持仓状态初始化，属只读
取证类，不产生新判定数字）。

协议（与冻结族逐字同构，repro_hold_confirm.make_hold_strat）：年模型 y 在
y−1 年末决策周五 fit；决策时点 ROC 回填上周标签；gate 集空=持有上期名单。
每周五收盘后跑：数据增量（us_backfill fetch，或 --no-fetch 用现存数据）→
重放冻结窗初始化状态 → 对新决策周（冻结末界之后）逐周出决策入 log →
状态落档。同一周五重复跑=幂等跳过（状态已含该周）。

用法：python forward_track.py [--no-fetch] [--bootstrap-only]
状态/日志：output/sector-rotation/forward/{state.json,track-log.jsonl}（gitignore）
"""
from __future__ import annotations

import json
import sys
from collections import deque

import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.models import MIMOModel, ROCState  # noqa: E402
from repro_hold_confirm import FROZEN, TAIL_END, tail_bounds  # noqa: E402
from repro_paper import N_GRID, build_frame  # noqa: E402

FWD_DIR = REPO_ROOT / "output" / "sector-rotation" / "forward"
STATE = FWD_DIR / "state.json"
LOG = FWD_DIR / "track-log.jsonl"


# ---- ROCState 序列化（trailing 52 对 + last_t/last_pred） ----

def roc_to_json(roc: ROCState) -> dict:
    # np.asarray 容错：round-trip 后 pairs/last_pred 是 list（select 会原样
    # 回存 roc.last_pred），数组与列表统一转 JSON
    return {"last_t": roc.last_t,
            "last_pred": (None if roc.last_pred is None
                          else np.asarray(roc.last_pred).tolist()),
            "pairs": [[np.asarray(p).tolist(), np.asarray(lb).tolist()]
                      for p, lb in roc.pairs]}


def roc_from_json(d: dict) -> ROCState:
    roc = ROCState()
    roc.last_t = d["last_t"]
    roc.last_pred = None if d["last_pred"] is None else list(d["last_pred"])
    roc.pairs = deque([(p, lb) for p, lb in d["pairs"]], maxlen=52)
    return roc


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"last_decision": None, "per_n": {}}


def save_state(st: dict) -> None:
    FWD_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def append_log(rec: dict) -> None:
    FWD_DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def log_dates() -> set[str]:
    if not LOG.exists():
        return set()
    return {json.loads(ln)["friday"] for ln in
            LOG.read_text(encoding="utf-8").splitlines() if ln.strip()}


# ---- 决策步进 ----

def _models_for(wf, years: set[int], window_by_year: dict[int, int]) -> dict:
    """年模型缓存：y 模型在 y−1 年末决策周五 fit（冻结协议）。"""
    out: dict[tuple[int, int], MIMOModel] = {}
    for y in sorted(years):
        train_ts = [t for t in range(len(wf.fridays))
                    if wf.fridays[t][:4] == str(y - 1)]
        if not train_ts:
            continue
        out[y] = MIMOModel(window=window_by_year[y]).fit(wf, train_ts[-1])
    return out


def step(wf, n: int, t: int, st: dict, models: dict[int, MIMOModel]) -> dict:
    """处理决策周 t（单 N）：ROC/名单状态在 st 内演化；返回决策记录。
    gate 集空=持有上期名单（与 make_hold_strat 同构，状态外置可持久化）。"""
    y = int(wf.fridays[t][:4])
    key = str(n)
    per = st["per_n"].setdefault(key, {"roc": roc_to_json(ROCState()),
                                       "roster": []})
    roc = roc_from_json(per["roc"])
    sel = models[y].select(wf, t, roc=roc) if y in models else {}
    roster = sorted(sel) if sel else list(per["roster"])
    rec = {"n": n, "friday": wf.fridays[t], "year": y,
           "spoke": bool(sel), "roster": roster,
           "members": [wf.members[j].etf_candidates[0] for j in roster],
           "weights": {wf.members[j].etf_candidates[0]: 1.0 / len(roster)
                       for j in roster} if roster else {}}
    per["roc"] = roc_to_json(roc)
    per["roster"] = roster
    return rec


def main(argv: list[str]) -> int:
    if "--no-fetch" not in argv:
        from us_backfill import main as backfill_main
        rc = backfill_main(["fetch"])
        if rc != 0:
            print("[WARN] 增量数据失败——用现存数据继续（--no-fetch 语义）")
    wf = build_frame()
    start, _ = tail_bounds(wf)
    years = {int(wf.fridays[t][:4]) for t in range(start, len(wf.fridays))}
    st = load_state()
    logged = log_dates()
    # 状态初始化（只读取证类）：从冻结窗首周重放到已处理的最后决策周
    # ——确定性同代码路径，不产生新判定数字；冻结窗内不写 log
    last_done = st["last_decision"]
    t_from = start if last_done is None else wf.fridays.index(last_done) + 1
    t_last = len(wf.fridays) - 1          # 末帧周=本周五收盘决策（执行周未到）
    new_recs = []
    for n in N_GRID:
        models = _models_for(wf, years, {y: n for y in years})
        for t in range(t_from, t_last + 1):
            rec = step(wf, n, t, st, models)
            if wf.fridays[t] > TAIL_END and wf.fridays[t] not in logged:
                new_recs.append(rec)
    if "--bootstrap-only" in argv:
        save_state(st)
        print(f"bootstrap 完成：状态至 {st['last_decision']}（不写 log）")
        return 0
    for rec in new_recs:                   # 先全后写：同周五三格聚齐再落盘
        append_log(rec)
    if new_recs:
        st["last_decision"] = new_recs[-1]["friday"]
    elif t_from <= t_last:
        st["last_decision"] = wf.fridays[t_last]
    save_state(st)
    for rec in new_recs:
        print(f"[{rec['friday']}] N={rec['n']}: "
              f"{'发声' if rec['spoke'] else '沉默持有'} "
              f"{rec['members'] if rec['members'] else '现金'}")
    if not new_recs:
        print(f"无新决策周（状态已至 {st['last_decision']}）")
    print(f"冻结族：{FROZEN[:60]}…（全文见提案）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
