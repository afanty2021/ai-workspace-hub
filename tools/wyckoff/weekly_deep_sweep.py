"""全市场深历史周线汇总（EXP-20261107-06 剩余待验证收口）。

读 data/market/series 全部非 .TDX 票（data/wyckoff/daily 深历史缓存 + 共享库
尾部合并），ISO 周聚合后同状态机同参数，回答浅窗（2023-07→2026-11 单牛体制）
留下的三个问题：
- 池化 P(T2|SOS) 优势在 2015 起多体制深窗是否仍在、量级多少；
- 逐年切片——优势是跨 regime 稳健还是集中在单一牛市；
- 逐 symbol 配对——优势是否被少数票/横截面相关主导（符号计数 + 均值差）。

附带：周线前瞻收益（h=4/8/24 周，SOS vs 基线上破）与 dist 侧池化对照。
输出：stdout 摘要 + output/wyckoff/weekly-deep.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pending_checks import to_weekly  # noqa: E402
from wyckoff.loader import read_jsonl, repo_paths, rows_to_bars  # noqa: E402
from wyckoff.machine import detect  # noqa: E402
from wyckoff.params import Params  # noqa: E402
from wyckoff.stats import baseline_stats, box_baseline, track_record  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_HORIZONS = (4, 8, 24)   # 周


def _fwd_stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {"n": len(s),
            "mean": round(sum(s) / len(s), 4),
            "median": round(s[len(s) // 2], 4)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="威科夫全市场深历史周线汇总")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 票（冒烟用）")
    args = ap.parse_args(argv)

    market, _, cache_dir = repo_paths()
    p = Params()
    all_schem = []
    all_base = []
    per_sym: dict[str, dict] = {}
    per_year: dict[str, dict] = {}
    fwd_sos: dict[int, list[float]] = {h: [] for h in _HORIZONS}
    fwd_base: dict[int, list[float]] = {h: [] for h in _HORIZONS}
    n_ok = n_skip = 0
    n_base_unresolved = 0
    cov_min, cov_max = "", ""

    files = sorted(market.glob("*.jsonl"))
    if args.limit:
        files = files[: args.limit]
    for f in files:
        if f.stem.endswith(".TDX"):
            continue
        sym = f.stem
        cache = cache_dir / f"{sym.replace(':', '_')}.jsonl"
        rows = read_jsonl(cache) + read_jsonl(f)
        rows = [r for r in rows
                if all(r.get(k) is not None for k in ("open", "high", "low", "close"))]
        wk = to_weekly(rows_to_bars(rows))
        if len(wk) < 50:
            n_skip += 1
            continue
        if not cov_min or wk[0].date < cov_min:
            cov_min = wk[0].date
        if wk[-1].date > cov_max:
            cov_max = wk[-1].date

        schems = detect(wk, p)
        n_wk = len(wk)
        # 截尾对称化：基线「expired 但 horizon 窗没走完就到数据尾」= 未决，剔除；
        # 与示意图机「未终态不入 broke」对称。否则近年（窗 300 周 ≈ 5.7 年）
        # 基线被系统性压低 p_t2，制造牛市段伪优势。
        base = box_baseline(wk, box_len=32)
        before = len(base)
        base = [e for e in base
                if not (e.outcome == "expired" and e.bar + 301 > n_wk)]
        n_base_unresolved += before - len(base)
        all_schem += schems
        all_base += base

        idx = {b.date: i for i, b in enumerate(wk)}
        acc_broke = [s for s in schems
                     if s.kind == "accum" and s.finished and s.sos is not None]
        bup = [e for e in base if e.kind == "up"]
        if acc_broke or bup:
            per_sym[sym] = {
                "n_sos": len(acc_broke),
                "n_t2": sum(1 for s in acc_broke if s.outcome == "complete"),
                "base_n": len(bup),
                "base_t2": sum(1 for e in bup if e.outcome == "complete"),
            }
        for s in acc_broke:
            y = per_year.setdefault(s.sos.date[:4], {"acc_n": 0, "acc_t2": 0,
                                                     "base_n": 0, "base_t2": 0,
                                                     "acc_running": 0})
            y["acc_n"] += 1
            y["acc_t2"] += 1 if s.outcome == "complete" else 0
            i = idx.get(s.sos.date)
            for h in _HORIZONS:
                if i is not None and i + h < len(wk):
                    fwd_sos[h].append(wk[i + h].close / wk[i].close - 1)
        for e in bup:
            y = per_year.setdefault(e.date[:4], {"acc_n": 0, "acc_t2": 0,
                                                 "base_n": 0, "base_t2": 0})
            y["base_n"] += 1
            y["base_t2"] += 1 if e.outcome == "complete" else 0
            i = idx.get(e.date)
            for h in _HORIZONS:
                if i is not None and i + h < len(wk):
                    fwd_base[h].append(wk[i + h].close / wk[i].close - 1)
        n_ok += 1

    # 池化
    tr = track_record(all_schem)
    bs = baseline_stats(all_base)

    # 逐年切片
    years = {}
    for y in sorted(per_year):
        d = per_year[y]
        years[y] = {
            "acc_n": d["acc_n"],
            "acc_p_t2": round(d["acc_t2"] / d["acc_n"], 3) if d["acc_n"] else None,
            "base_n": d["base_n"],
            "base_p_t2": round(d["base_t2"] / d["base_n"], 3) if d["base_n"] else None,
        }
        if d["acc_n"] and d["base_n"]:
            years[y]["diff_pp"] = round(
                (d["acc_t2"] / d["acc_n"] - d["base_t2"] / d["base_n"]) * 100, 1)

    # 逐 symbol 配对（n≥3 双侧）
    paired = {s: v for s, v in per_sym.items() if v["n_sos"] >= 3 and v["base_n"] >= 3}
    diffs = [(v["n_t2"] / v["n_sos"]) - (v["base_t2"] / v["base_n"])
             for v in paired.values()]
    pairing = {
        "n_symbols_with_events": len(per_sym),
        "n_paired": len(paired),
        "wins": sum(1 for x in diffs if x > 0),
        "ties": sum(1 for x in diffs if x == 0),
        "losses": sum(1 for x in diffs if x < 0),
        "mean_diff_pp": round(sum(diffs) / len(diffs) * 100, 1) if diffs else None,
    }

    out = {
        "meta": {"n_symbols": n_ok, "skipped_lt50w": n_skip,
                 "weekly_coverage": f"{cov_min}→{cov_max}",
                 "params": "Pine 默认，box32w 基线，horizon=300",
                 "baseline_unresolved_dropped": n_base_unresolved,
                 "censoring_note": "基线 expired-未走完窗剔除，与威科夫未终态不入列对称"},
        "pooled": {"accum": tr["accum"], "dist": tr["dist"], "baseline": bs},
        "per_year": years,
        "per_symbol_pairing": pairing,
        "fwd_weeks": {f"h{h}": {"sos": _fwd_stats(fwd_sos[h]),
                                "base_up": _fwd_stats(fwd_base[h])}
                      for h in _HORIZONS},
        "survivorship_note": "宇宙=当前上市票（data/market/series），退市票 mootdx 不可得",
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    opath = _REPO / "output" / "wyckoff" / "weekly-deep.json"
    opath.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {opath}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
