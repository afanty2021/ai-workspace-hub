"""事件前瞻收益：SOS/SOW 与基线突破收盘后 +10/+20/+60 根的 close→close 收益。

补充 P(T2|SOS) 的量纲盲区：目标没到不等于没涨。一次性分析脚本，读
run_validation 的输出明细 + 本地序列。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wyckoff.loader import load_symbol, load_universe  # noqa: E402
from wyckoff.machine import detect  # noqa: E402
from wyckoff.params import Params  # noqa: E402
from wyckoff.stats import box_baseline  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_HORIZONS = (10, 20, 60)


def fwd(bars, i: int, h: int) -> float | None:
    j = i + h
    return (bars[j].close / bars[i].close - 1) if j < len(bars) else None


def collect(rows: list[dict], bars_by_sym, key: str) -> dict:
    by_h = {h: [] for h in _HORIZONS}
    for r in rows:
        bars = bars_by_sym.get(r["symbol"])
        if bars is None or r.get(key) is None:
            continue
        i = next((k for k, b in enumerate(bars) if b.date == r[key]), None)
        if i is None:
            continue
        sign = 1 if r["kind"] == "accum" or r.get("dir") == "up" else -1
        for h in _HORIZONS:
            v = fwd(bars, i, h)
            if v is not None:
                by_h[h].append(sign * v)
    return {h: _stat(vs) for h, vs in by_h.items()}


def _stat(vs: list[float]) -> dict:
    if not vs:
        return {"n": 0}
    vs = sorted(vs)
    return {
        "n": len(vs),
        "mean": round(sum(vs) / len(vs), 4),
        "median": round(vs[len(vs) // 2], 4),
        "p25": round(vs[len(vs) // 4], 4),
        "p75": round(vs[3 * len(vs) // 4], 4),
    }


def main() -> int:
    items = {i.symbol: i for i in load_universe()}
    bars_by_sym = {}
    sos_rows, sow_rows, base_rows = [], [], []
    for sym, item in items.items():
        bars, _ = load_symbol(item)
        bars_by_sym[sym] = bars
        for s in detect(bars, Params()):
            row = {"symbol": sym, "kind": s.kind}
            if s.sos is not None:
                row["event_date"] = s.sos.date
                (sos_rows if s.kind == "accum" else sow_rows).append(row)
        for e in box_baseline(bars):
            base_rows.append({"symbol": sym, "kind": e.kind, "event_date": e.date,
                              "dir": e.kind})
    out = {
        "sos_accum": collect([{"symbol": r["symbol"], "kind": "accum",
                               "event_date": r["event_date"]} for r in sos_rows],
                             bars_by_sym, "event_date"),
        "sow_dist": collect([{"symbol": r["symbol"], "kind": "dist",
                              "event_date": r["event_date"]} for r in sow_rows],
                            bars_by_sym, "event_date"),
        "baseline_up": collect([r for r in base_rows if r["dir"] == "up"],
                               bars_by_sym, "event_date"),
        "baseline_down": collect([r for r in base_rows if r["dir"] == "down"],
                                 bars_by_sym, "event_date"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (_REPO / "output/wyckoff/forward-returns.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
