"""统计聚合：track record（对齐脚本面板口径）+ 通用箱体突破基线对照。

基线设计的动机：回答「威科夫结构选择是否比任意箱体突破多了信息」——
同一套 measured-move 量具（1×/2× 箱高、失效=箱另一侧、同视野超时）套在
「收盘突破 L 根滚动箱体」上，与 SOS/SOW 队列并排比较。
horizon 默认 300 对齐 Pine maxLeg（markup/markdown 超时），否则 T2/失败率
对比带窗口偏置（v1 曾用 120，v2 起对齐）。
基线不去重趋势段（突破后 L 根内的重复突破跳过），与示意图机「一次一个」近似对齐。
"""
from __future__ import annotations

from dataclasses import dataclass

from .machine import Bar, Schematic


def track_record(schems: list[Schematic]) -> dict:
    """单 symbol（或池化）track record：只统计 finished（complete/failed/expired）。"""
    out: dict = {}
    for kind in ("accum", "dist"):
        sel = [s for s in schems if s.kind == kind]
        finished = [s for s in sel if s.finished]
        broke = [s for s in finished if s.sos is not None]
        t1 = [s for s in broke if s.t1_hit_bar is not None]
        t2 = [s for s in broke if s.outcome == "complete"]
        fail_after = [s for s in broke if s.outcome_detail == "invalidated_after_sos"]
        lens = [s.range_len for s in broke if s.range_len is not None]
        out[kind] = {
            "n_finished": len(finished),
            "n_complete": sum(1 for s in finished if s.outcome == "complete"),
            "n_failed": sum(1 for s in finished if s.outcome == "failed"),
            "n_expired": sum(1 for s in finished if s.outcome == "expired"),
            "n_spring": sum(1 for s in finished if s.spring is not None),
            "n_broke": len(broke),
            "p_spring": _r(len([s for s in finished if s.spring is not None]), len(finished)),
            "p_broke": _r(len(broke), len(finished)),
            "p_t1_given_sos": _r(len(t1), len(broke)),
            "p_t2_given_sos": _r(len(t2), len(broke)),
            "p_fail_after_sos": _r(len(fail_after), len(broke)),
            "avg_range_len": round(sum(lens) / len(lens), 1) if lens else None,
        }
    return out


def _r(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


# ---------------------------------------------------------------------------
# 基线：通用箱体突破（无威科夫结构选择）
# ---------------------------------------------------------------------------


@dataclass
class BaselineEvent:
    kind: str            # up / down
    bar: int
    date: str
    box_height: float
    outcome: str         # complete / failed / expired
    t1_hit: bool


def box_baseline(rows: list[Bar], box_len: int = 60, horizon: int = 300) -> list[BaselineEvent]:
    """收盘突破前 box_len 根滚动高/低点 → 与示意图同一套目标量具。"""
    n = len(rows)
    events: list[BaselineEvent] = []
    skip_until = -1
    for t in range(box_len, n - 1):
        if t <= skip_until:
            continue
        hi = max(r.high for r in rows[t - box_len:t])
        lo = min(r.low for r in rows[t - box_len:t])
        h = hi - lo
        if h <= 0:
            continue
        direction = None
        if rows[t].close > hi:
            direction = "up"
            t1, t2, invalid = hi + h, hi + 2 * h, lo
        elif rows[t].close < lo:
            direction = "down"
            t1, t2, invalid = lo - h, lo - 2 * h, hi
        if direction is None:
            continue
        outcome, t1_hit = "expired", False
        for j in range(t + 1, min(t + 1 + horizon, n)):
            r = rows[j]
            if direction == "up":
                if r.close < invalid:
                    outcome = "failed"
                    break
                if r.high >= t1:
                    t1_hit = True
                if r.high >= t2:
                    outcome = "complete"
                    break
            else:
                if r.close > invalid:
                    outcome = "failed"
                    break
                if r.low <= t1:
                    t1_hit = True
                if r.low <= t2:
                    outcome = "complete"
                    break
        events.append(BaselineEvent(direction, t, rows[t].date, h, outcome, t1_hit))
        skip_until = t + box_len  # 一次一个：突破后 box_len 根内不再报
    return events


def baseline_stats(events: list[BaselineEvent]) -> dict:
    out: dict = {}
    for kind in ("up", "down"):
        sel = [e for e in events if e.kind == kind]
        out[kind] = {
            "n": len(sel),
            "p_t2": _r(sum(1 for e in sel if e.outcome == "complete"), len(sel)),
            "p_t1": _r(sum(1 for e in sel if e.t1_hit), len(sel)),
            "p_failed": _r(sum(1 for e in sel if e.outcome == "failed"), len(sel)),
        }
    return out
