# tools/sector-rotation/make_us_universe.py
"""美股宇宙清单生成（R20261106-02 §6 U3）：论文 §1.1 原始 11 成员逐字——
XLK/XLV/XLY/VOX/XLF/XLI/XLP/XLU/XLB/IYR/XLE（通讯=VOX、地产=IYR，非
XLC/XLRE；11 只 2012 前全部上市，全窗成员齐备）。退化情形：index_code==
ETF 符号、候选集单元素（Task 1 pick_bypass_single 消费）、limit_pct=1.0
（涨停闸门永不触发）、无簇表。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sector_rotation.universe import Member, UniverseSpec, write_universe  # noqa: E402

US_MEMBERS = ["XLK", "XLV", "XLY", "VOX", "XLF", "XLI",
              "XLP", "XLU", "XLB", "IYR", "XLE"]
NAMES = {
    "XLK": "Technology Select Sector SPDR", "XLV": "Health Care Select Sector SPDR",
    "XLY": "Consumer Discretionary Select Sector SPDR", "VOX": "Communication Services Select Sector SPDR",
    "XLF": "Financial Select Sector SPDR", "XLI": "Industrial Select Sector SPDR",
    "XLP": "Consumer Staples Select Sector SPDR", "XLU": "Utilities Select Sector SPDR",
    "XLB": "Materials Select Sector SPDR", "IYR": "iShares U.S. Real Estate ETF",
    "XLE": "Energy Select Sector SPDR",
}
OUT = REPO_ROOT / "config" / "sector-rotation-us-universe.md"


def write_config(path: Path) -> None:
    spec = UniverseSpec([Member(s, NAMES[s], (s,), 1.0) for s in US_MEMBERS], {})
    write_universe(path, spec, status="confirmed")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "status: confirmed\n---",
        "status: confirmed\n"
        "# 2026-11-06 美股域重开（R20261106-02，用户指令+论文 §1.1 原始清单）：11 成员\n"
        "# 退化情形 index_code==ETF 符号；limit_pct=1.0 禁用涨停闸门；无簇表（cluster_for→None）；\n"
        "# 单候选集由 build_weekly_frame(pick_bypass_single=True) 旁路 pick（§7 第 5 行）。\n"
        "---", 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    write_config(OUT)
    print(f"written: {OUT}")
