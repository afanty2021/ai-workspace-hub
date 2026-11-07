"""验证 CLI：universe 逐票跑状态机 + 基线，输出 JSON 与 Markdown 报告。

用法：
    python tools/wyckoff/run_validation.py                    # 全量
    python tools/wyckoff/run_validation.py --limit 4          # 冒烟
    python tools/wyckoff/run_validation.py --symbols 600276.SH,IDX:000300
    python tools/wyckoff/run_validation.py --set min_range_len=30   # 敏感性
输出：output/wyckoff/{tag}-validation.json / .md
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wyckoff.loader import load_symbol, load_universe  # noqa: E402
from wyckoff.machine import detect  # noqa: E402
from wyckoff.params import Params  # noqa: E402
from wyckoff.stats import baseline_stats, box_baseline, track_record  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]


def schematic_row(sym: str, name: str, s) -> dict:
    return {
        "symbol": sym, "name": name, "kind": s.kind, "outcome": s.outcome,
        "detail": s.outcome_detail,
        "sc_date": s.sc_date, "sos_date": s.sos.date if s.sos else None,
        "end_date": s.end_date,
        "spring": s.spring is not None,
        "t1_hit": s.t1_hit_bar is not None,
        "range_len": s.range_len, "height_atr": round(s.height_atr, 1) if s.height_atr else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="威科夫示意图状态机 A 股验证")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--set", action="append", default=[],
                    help="覆盖参数 key=value（可多次）")
    ap.add_argument("--tag", default="", help="输出文件名前缀（缺省日期）")
    args = ap.parse_args(argv)

    params = Params()
    for kv in args.set:
        key, _, val = kv.partition("=")
        if not hasattr(params, key):
            ap.error(f"未知参数: {key}")
        params = dataclasses.replace(params, **{key: type(getattr(params, key))(val)})

    items = load_universe()
    if args.symbols:
        want = {s.strip() for s in args.symbols.split(",") if s.strip()}
        items = [i for i in items if i.symbol in want]
    if args.limit:
        items = items[:args.limit]

    all_schems, per_symbol, all_base = [], [], []
    for item in items:
        bars, src = load_symbol(item)
        schems = detect(bars, params) if len(bars) >= params.climax_lookback else []
        base = box_baseline(bars)
        tr = track_record(schems)
        per_symbol.append({
            "symbol": item.symbol, "name": item.name, "group": item.group,
            "bars": len(bars), "first": bars[0].date if bars else None,
            "last": bars[-1].date if bars else None, "source": src,
            "track_record": tr,
            "baseline": baseline_stats(base),
            "n_schematics": len(schems),
        })
        all_schems += [schematic_row(item.symbol, item.name, s) for s in schems]
        all_base += base

    pooled = _pooled(all_schems)
    detail = {
        "params": dataclasses.asdict(params),
        "universe": [{"symbol": i.symbol, "name": i.name, "group": i.group} for i in items],
        "per_symbol": per_symbol,
        "schematics": all_schems,
        "pooled_track_record": pooled,
        "pooled_baseline": baseline_stats(all_base),
    }
    tag = args.tag or date.today().isoformat()
    out_dir = _REPO / "output" / "wyckoff"
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / f"{tag}-validation.json"
    jpath.write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
    mpath = out_dir / f"{tag}-validation.md"
    mpath.write_text(_markdown(detail, tag), encoding="utf-8")
    print(f"written: {jpath}\nwritten: {mpath}")
    return 0


def _pooled(rows: list[dict]) -> dict:
    out = {}
    for kind in ("accum", "dist"):
        sel = [r for r in rows if r["kind"] == kind]
        finished = sel  # rows 只含 emitted（含 vturn/dropped/aborted），过滤：
        finished = [r for r in sel if r["outcome"] in ("complete", "failed", "expired")]
        broke = [r for r in finished if r["sos_date"]]
        out[kind] = {
            "n_finished": len(finished),
            "n_complete": sum(1 for r in finished if r["outcome"] == "complete"),
            "n_failed": sum(1 for r in finished if r["outcome"] == "failed"),
            "n_expired": sum(1 for r in finished if r["outcome"] == "expired"),
            "n_spring": sum(1 for r in finished if r["spring"]),
            "n_broke": len(broke),
            "p_spring": _pr(sum(1 for r in finished if r["spring"]), len(finished)),
            "p_broke": _pr(len(broke), len(finished)),
            "p_t1_given_sos": _pr(sum(1 for r in broke if r["t1_hit"]), len(broke)),
            "p_t2_given_sos": _pr(sum(1 for r in broke if r["outcome"] == "complete"), len(broke)),
            "p_fail_after_sos": _pr(
                sum(1 for r in broke if r["detail"] == "invalidated_after_sos"), len(broke)),
            "avg_range_len": _avg([r["range_len"] for r in broke if r["range_len"]]),
        }
    return out


def _pr(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def _avg(xs: list[int]) -> float | None:
    return round(sum(xs) / len(xs), 1) if xs else None


def _md_table(rows: list[dict]) -> str:
    if not rows:
        return "(无)"
    keys = list(rows[0].keys())
    head = "| " + " | ".join(keys) + " |"
    sep = "|" + "|".join("---" for _ in keys) + "|"
    body = "\n".join("| " + " | ".join(str(r[k]) for k in keys) + " |" for r in rows)
    return "\n".join([head, sep, body])


def _markdown(d: dict, tag: str) -> str:
    lines = [f"# 威科夫示意图状态机 A 股验证（{tag}）", ""]
    lines += ["## 池化 track record（全部 finished 示意图）", ""]
    pooled = d["pooled_track_record"]
    lines.append(_md_table([
        {"kind": k, **v} for k, v in pooled.items()
    ]))
    lines += ["", "## 池化基线（通用箱体突破，同套目标量具）", ""]
    lines.append(_md_table([{"kind": k, **v} for k, v in d["pooled_baseline"].items()]))
    lines += ["", "## 参数", "", "```json", json.dumps(d["params"], ensure_ascii=False, indent=1), "```", ""]
    lines += ["## 分 symbol track record", ""]
    for ps in d["per_symbol"]:
        tr = ps["track_record"]
        n = tr["accum"]["n_finished"] + tr["dist"]["n_finished"]
        if n == 0:
            continue
        lines.append(f"### {ps['symbol']} {ps['name']}（{ps['first']}→{ps['last']}，{ps['bars']} 根，{ps['source']}）")
        lines.append(_md_table([{"kind": k, **v} for k, v in tr.items() if v["n_finished"]]))
        lines.append(f"- 基线: {json.dumps(ps['baseline'], ensure_ascii=False)}")
        lines.append("")
    lines += ["## 示意图明细", "", _md_table(d["schematics"])]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
