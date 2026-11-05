# tools/sector-rotation/sector_rotation/data.py
"""point-in-time 周五决策帧（spec §3.1/§3.3）：每周执行 ETF 由当时达标规则择一。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from .universe import Member, UniverseSpec, point_in_time_pick


@dataclass
class WeeklyFrame:
    fridays: list[str]
    index_close: np.ndarray
    etf_symbols: list[list[str]]
    etf_open: np.ndarray
    etf_close: np.ndarray
    etf_prev_close: np.ndarray
    etf_week_amount: np.ndarray
    members: list[Member] = field(repr=False)
    spec: UniverseSpec = field(repr=False)
    valid: np.ndarray
    dvalid: np.ndarray
    bench_300: np.ndarray


def _load_daily(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                row = json.loads(ln)
                out[row["date"]] = row
    return out


def _week_key(d: str) -> int:
    day = date.fromisoformat(d)
    iso = day.isocalendar()
    return date.fromisocalendar(iso[0], iso[1], 1).toordinal()


def _corrupt_weeks(series: dict[str, dict]) -> set[int]:
    """拆分防护（T4 修正案，T3 实测 76 件 >30% 事件）：close-to-close 单日
    |涨跌| > 30% 且生效日为周二~周五的日期所在 ISO 周——该执行周 open→close
    被份额拆分/缩股污染（场内行业 ETF ±10/20% 涨跌停下不可能是真实行情）。
    周一生效良性（整执行周 post-split），不标记。返回污染周 key 集。"""
    out: set[int] = set()
    dates = sorted(series)
    for prev, d in zip(dates, dates[1:]):
        if date.fromisoformat(d).weekday() == 0:    # 周一跳空（对上周五）不标记
            continue
        c0, c1 = float(series[prev]["close"]), float(series[d]["close"])
        if c0 > 0 and abs(c1 / c0 - 1) > 0.30:
            out.add(_week_key(d))
    return out


def build_weekly_frame(data_root: Path, spec: UniverseSpec,
                       *, bench_symbol: str = "510300.SH") -> WeeklyFrame:
    members = spec.members
    idx_series = [_load_daily(data_root / "sector" / "series" / f"{m.index_code}.jsonl")
                  for m in members]
    all_etf_syms = sorted({s for m in members for s in m.etf_candidates})
    etf_data = {s: _load_daily(data_root / "market" / "series" / f"{s}.jsonl")
                for s in all_etf_syms}
    bars = {s: [row for row in series.values()]
            for s, series in ((s, dict(sorted(etf_data[s].items()))) for s in all_etf_syms)}
    corrupt = {s: _corrupt_weeks(etf_data[s]) for s in all_etf_syms}

    week_last: list[dict[int, dict]] = []
    for series in idx_series:
        by_week: dict[int, dict] = {}
        for d in sorted(series):
            wk = _week_key(d)
            by_week[wk] = {"date": d, "row": series[d]}
        week_last.append(by_week)
    etf_bounds = []
    for s in all_etf_syms:
        first, last, prev_last, amt = {}, {}, {}, {}
        for d in sorted(etf_data[s]):
            wk = _week_key(d)
            if wk not in first:
                first[wk] = etf_data[s][d]
            prev_last[wk] = last.get(wk)
            last[wk] = etf_data[s][d]
        rows_by_week: dict[int, list[dict]] = {}
        for d in sorted(etf_data[s]):
            rows_by_week.setdefault(_week_key(d), []).append(etf_data[s][d])
        amt = {wk: sum(r["amount"] for r in rows) / len(rows)
               for wk, rows in rows_by_week.items()}
        etf_bounds.append((first, last, prev_last, amt))

    bench = _load_daily(data_root / "market" / "series" / f"{bench_symbol}.jsonl")
    bench_first, bench_last = {}, {}
    for d in sorted(bench):
        wk = _week_key(d)
        bench_first.setdefault(wk, bench[d])
        bench_last[wk] = bench[d]

    all_weeks = sorted({wk for by_week in week_last for wk in by_week})
    T, L = len(all_weeks), len(members)
    shape = (T, L)
    idx_close = np.full(shape, np.nan)
    etf_symbols = [[""] * L for _ in range(T)]
    etf_open = np.full(shape, np.nan)
    etf_close = np.full(shape, np.nan)
    etf_prev = np.full(shape, np.nan)
    etf_amt = np.full(shape, np.nan)
    valid = np.zeros(shape, dtype=bool)
    dvalid = np.zeros(shape, dtype=bool)
    bench_ret = np.full(T, np.nan)
    fridays: list[str] = []
    for ti, wk in enumerate(all_weeks):
        fridays.append(max(by_week[wk]["date"] for by_week in week_last if wk in by_week))
        next_wk = next((c for c in (wk + 7, wk + 14) if c in bench_first), None)
        if next_wk is not None:
            bench_ret[ti] = (bench_last[next_wk]["close"]
                             / bench_first[next_wk].get("open",
                                                        bench_first[next_wk]["close"]) - 1)
        for li, m in enumerate(members):
            if wk in week_last[li]:
                idx_close[ti, li] = float(week_last[li][wk]["row"]["close"])
            pick = point_in_time_pick(list(m.etf_candidates), bars, fridays[-1])
            if pick is None:
                continue
            bi = all_etf_syms.index(pick)
            first, last, prev_last, amt = etf_bounds[bi]
            if wk in last:                 # 决策期可得，独立于执行周是否存在（评审 C7）
                etf_prev[ti, li] = float(last[wk]["close"])
            dvalid[ti, li] = bool(np.isfinite(idx_close[ti, li])
                                  and np.isfinite(etf_prev[ti, li]))
            etf_symbols[ti][li] = pick     # 决策期即记录 point-in-time 选择（C7 信号帧用）
            next_wk = next((c for c in (wk + 7, wk + 14) if c in first), None)
            if next_wk is None:
                continue
            etf_open[ti, li] = float(first[next_wk].get("open", first[next_wk]["close"]))
            etf_close[ti, li] = float(last[next_wk]["close"])
            etf_amt[ti, li] = float(amt.get(next_wk, np.nan))
            # 拆分防护：执行周含周二~周五生效的 >30% 单日跳空 → valid=False
            # 出宇宙一周（dvalid/价格序列不动，只屏蔽该 member-week）。
            valid[ti, li] = bool(dvalid[ti, li]
                                 and np.isfinite(etf_open[ti, li])
                                 and np.isfinite(etf_close[ti, li])
                                 and next_wk not in corrupt[pick])
    return WeeklyFrame(fridays, idx_close, etf_symbols, etf_open, etf_close,
                       etf_prev, etf_amt, members, spec, valid, dvalid, bench_ret)
