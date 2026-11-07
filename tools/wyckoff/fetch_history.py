"""深历史回拉 CLI：为 universe 各票拉 2016 起日线，写 data/wyckoff/daily/ 缓存。

用法：
    python tools/wyckoff/fetch_history.py [--start 2016-01-01] [--symbols 600276.SH,IDX:000300]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wyckoff.loader import fetch_deep_history, load_universe  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="威科夫验证：mootdx 深历史回拉")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--symbols", default="", help="逗号分隔，缺省全 universe")
    args = ap.parse_args(argv)

    items = load_universe()
    if args.symbols:
        want = {s.strip() for s in args.symbols.split(",") if s.strip()}
        items = [i for i in items if i.symbol in want]
    for item in items:
        added, status = fetch_deep_history(item, start=args.start)
        print(f"{item.symbol:<14} {item.name:<10} +{added:>5}  {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
