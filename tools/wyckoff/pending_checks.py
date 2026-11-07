"""待验证项收口（EXP-20261107-06 待验证 1-3 项）：

1. box_len=32 基线变体——区间长度匹配稳健性（威科夫平均区间 ~32 根 vs 基线箱 60）；
2. 周线周期——日线按 ISO 周聚合后同状态机同参数跑 track record；
3. SOW 早期动量分组显著性——逐 symbol 配对（SOW 前瞻 vs 该 symbol 基线下破前瞻），
   符号检验 + 配对 t（横截面相关下 t 值只作量级参考，符号检验为主）。

用法：python tools/wyckoff/pending_checks.py
输出：stdout 摘要 + output/wyckoff/pending-checks.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wyckoff.loader import load_symbol, load_universe  # noqa: E402
from wyckoff.machine import Bar, detect  # noqa: E402
from wyckoff.params import Params  # noqa: E402
from wyckoff.stats import baseline_stats, box_baseline, track_record  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_HORIZONS = (10, 20, 60)


def to_weekly(bars: list[Bar]) -> list[Bar]:
    """日线 → ISO 周 bar（open 首日 / high max / low min / close 末日 / volume 求和）。"""
    from datetime import date as _date

    weeks: dict[tuple, list[Bar]] = {}
    order: list[tuple] = []
    for b in bars:
        iso = _date.fromisoformat(b.date).isocalendar()[:2]
        if iso not in weeks:
            weeks[iso] = []
            order.append(iso)
        weeks[iso].append(b)
    out: list[Bar] = []
    for iso in order:
        grp = weeks[iso]
        vols = [g.volume for g in grp if g.volume]
        out.append(Bar(
            date=grp[-1].date,
            open=grp[0].open,
            high=max(g.high for g in grp),
            low=min(g.low for g in grp),
            close=grp[-1].close,
            volume=sum(vols) if vols else None,
        ))
    return out


def fwd(bars: list[Bar], i: int, h: int) -> float | None:
    j = i + h
    return bars[j].close / bars[i].close - 1 if j < len(bars) else None


def event_fwd(rows: list[dict], bars_by_sym: dict[str, list[Bar]], direction: str) -> dict:
    """rows: {symbol, date, dir}；按 direction 过滤，返回 {h: [sign 调整后收益]}。"""
    by_h: dict[int, list[float]] = {h: [] for h in _HORIZONS}
    for r in rows:
        if r["dir"] != direction:
            continue
        bars = bars_by_sym[r["symbol"]]
        i = next((k for k, b in enumerate(bars) if b.date == r["date"]), None)
        if i is None:
            continue
        sign = 1 if direction == "up" else -1
        for h in _HORIZONS:
            v = fwd(bars, i, h)
            if v is not None:
                by_h[h].append(sign * v)
    return by_h


def main() -> int:
    items = load_universe()
    p = Params()
    bars_by_sym: dict[str, list[Bar]] = {}
    all_schem = []
    all_base32 = []
    all_week_schem = []
    all_week_base = []
    # 逐 symbol 配对（item 3）
    per_sym: dict[str, dict] = {}

    for item in items:
        bars, _ = load_symbol(item)
        bars_by_sym[item.symbol] = bars

        schems = detect(bars, p)
        all_schem += schems
        base32 = box_baseline(bars, box_len=32)
        all_base32 += base32

        # SOW 与基线下破的逐 symbol 前瞻（item 3 用）
        sow = [{"symbol": item.symbol, "date": s.sos.date, "dir": "down"}
               for s in schems if s.kind == "dist" and s.sos]
        bdown = [{"symbol": item.symbol, "date": e.date, "dir": "down"} for e in base32]
        if sow or bdown:
            per_sym[item.symbol] = {"sow": event_fwd(sow, bars_by_sym, "down"),
                                    "base": event_fwd(bdown, bars_by_sym, "down")}

        # 周线（item 2）
        wk = to_weekly(bars)
        all_week_schem += detect(wk, p)
        all_week_base += box_baseline(wk, box_len=32)

    out: dict = {"box32": baseline_stats(all_base32), "weekly": {}}

    # item 1：box_len=32 基线（与 box60、威科夫并排）
    tr = track_record(all_schem)
    out["wyckoff_daily"] = tr
    avg_len = {(k): v.get("avg_range_len") for k, v in tr.items()}
    out["note_avg_range_len"] = avg_len

    # item 2：周线 track record + 周线基线
    wtr = track_record(all_week_schem)
    out["weekly"]["wyckoff"] = wtr
    out["weekly"]["baseline_box32w"] = baseline_stats(all_week_base)
    out["weekly"]["n_weekly_bars_minmax"] = None  # 摘要打印里给

    # item 3：分组显著性
    sig = {}
    for h in _HORIZONS:
        diffs, sow_means, n_neg = [], [], 0
        for sym, d in per_sym.items():
            s = d["sow"].get(h, [])
            b = d["base"].get(h, [])
            if not s or not b:
                continue
            ms = sum(s) / len(s)
            mb = sum(b) / len(b)
            sow_means.append(ms)
            diffs.append(ms - mb)  # >0 = SOW 比该票基线下破更有利（更跌）
            if ms < 0:
                n_neg += 1
        n = len(diffs)
        res = {"n_symbols": n,
               "symbols_sow_mean_negative": n_neg,
               "symbols_sow_beats_base": sum(1 for x in diffs if x > 0),
               "mean_diff": round(sum(diffs) / n, 4) if n else None,
               "median_sow_mean": round(sorted(sow_means)[n // 2], 4) if n else None}
        if n >= 5:
            # 配对 t（量级参考；横截面相关膨胀下不作为检验用）
            mu = sum(diffs) / n
            sd = (sum((x - mu) ** 2 for x in diffs) / (n - 1)) ** 0.5
            res["paired_t"] = round(mu / (sd / n ** 0.5), 2) if sd else None
        sig[f"h{h}"] = res
    out["sow_grouping"] = sig

    print(json.dumps(out, ensure_ascii=False, indent=1))
    opath = _REPO / "output" / "wyckoff" / "pending-checks.json"
    opath.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {opath}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
