"""一次性：全市场周线扩样（EXP-20261107-06 待验证 #2 的样本量补强）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pending_checks import to_weekly  # noqa: E402
from wyckoff.loader import rows_to_bars, read_jsonl  # noqa: E402
from wyckoff.machine import detect  # noqa: E402
from wyckoff.params import Params  # noqa: E402
from wyckoff.stats import baseline_stats, box_baseline, track_record  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    store = _REPO / "data" / "market" / "series"
    all_schem = []
    all_base = []
    n_ok = n_skip = 0
    for f in store.glob("*.jsonl"):
        if f.stem.endswith(".TDX"):
            continue
        rows = [r for r in read_jsonl(f)
                if all(r.get(k) is not None for k in ("open", "high", "low", "close"))]
        bars = rows_to_bars(rows)
        wk = to_weekly(bars)
        if len(wk) < 50:
            n_skip += 1
            continue
        all_schem += detect(wk, Params())
        all_base += box_baseline(wk, box_len=32)
        n_ok += 1
    tr = track_record(all_schem)
    print("symbols:", n_ok, "skipped:", n_skip)
    keys = ("n_finished", "n_broke", "n_complete", "p_t2_given_sos",
            "p_t1_given_sos", "p_fail_after_sos", "avg_range_len")
    for kind in ("accum", "dist"):
        print(kind, json.dumps({k: tr[kind][k] for k in keys}, ensure_ascii=False))
    print("baseline_box32w:", json.dumps(baseline_stats(all_base), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
