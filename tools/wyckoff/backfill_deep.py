"""全市场深历史回填：data/market/series 全部非 .TDX 票 → data/wyckoff/daily 回拉至 --start。

EXP-20261107-06 剩余待验证（全市场深历史周线）的数据侧。mootdx 串行（pytdx
RLock 在 mootdx_source 层），~6900 票 × ~4-5 页 ≈ 数小时，必须后台跑。

断点续跑：data/wyckoff/backfill-log.jsonl 每票一行终态；重跑跳过已 ok 的票，
--retry-failed 重做 fail 票。进度每 25 票打一行（速率 + ETA）。

用法：
    python tools/wyckoff/backfill_deep.py [--start 2015-01-01] [--limit N] [--retry-failed]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wyckoff.loader import UniverseItem, fetch_deep_history, repo_paths  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]


def market_symbols() -> list[UniverseItem]:
    market, _, _ = repo_paths()
    return [UniverseItem(symbol=f.stem, name="", group="全市场", store_path=f)
            for f in sorted(market.glob("*.jsonl")) if not f.stem.endswith(".TDX")]


def read_log(path: Path) -> dict[str, str]:
    """symbol → 最终 status（同票多行时后行覆盖前行）。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            out[r["symbol"]] = r["status"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="威科夫全市场深历史回填（可断点续跑）")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 票（试跑估时用）")
    ap.add_argument("--retry-failed", action="store_true", help="重做 fail 终态的票")
    args = ap.parse_args(argv)

    items = market_symbols()
    if args.limit:
        items = items[: args.limit]

    log_path = _REPO / "data" / "wyckoff" / "backfill-log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    done = read_log(log_path)
    todo = []
    for i in items:
        st = done.get(i.symbol)
        if st and st.startswith("ok"):
            continue
        if st and st.startswith("fail") and not args.retry_failed:
            continue
        todo.append(i)
    print(f"universe={len(items)} already_ok={len(items) - len(todo)} todo={len(todo)}",
          flush=True)

    t0 = time.time()
    n_ok = n_fail = 0
    for k, item in enumerate(todo, 1):
        ts = datetime.now().isoformat(timespec="seconds")
        try:
            added, status = fetch_deep_history(item, start=args.start)
        except Exception as exc:  # noqa: BLE001
            added, status = 0, f"fail: {exc}"
        if status.startswith("import-fail"):
            print(f"[{ts}] {item.symbol} {status} — mootdx 不可用，中止", flush=True)
            return 2
        if status.startswith("ok"):
            n_ok += 1
        else:
            n_fail += 1
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"symbol": item.symbol, "status": status,
                                 "added": added, "ts": ts}, ensure_ascii=False) + "\n")
        if k % 25 == 0 or k == len(todo):
            el = time.time() - t0
            rate = k / el if el else 0.0
            eta_min = (len(todo) - k) / rate / 60 if rate else 0.0
            print(f"[{datetime.now().isoformat(timespec='seconds')}] {k}/{len(todo)} "
                  f"ok={n_ok} fail={n_fail} {rate:.2f}sym/s ETA={eta_min:.0f}min", flush=True)
    print(f"done: ok={n_ok} fail={n_fail}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
