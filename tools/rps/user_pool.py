# -*- coding: utf-8 -*-
"""池依赖臂：用户自选池（42 只个股）在全市场 RPS250 横截面中的位置（2026-11-06）。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from rps_core import rps_main

# 用户池个股（剔 ETF/场外基金/指数：51/56/58/15 ETF 段、021179 场外、881 指数段）
RAW = """000630 000660 002415 002545 300049 300124 300274 300308 300476
300750 300760 301358 600079 600096 600176 600276 600309 600456 600660
600989 601899 603087 603259 603345 603648 603993 605016 688825"""
NAMES = {"000630": "铜陵有色", "000660": "天齐锂业", "002415": "海康威视", "002545": "东方铁塔",
         "300049": "福瑞医科", "300124": "汇川技术", "300274": "阳光电源",
         "300308": "中际旭创", "300476": "胜宏科技", "300750": "宁德时代", "300760": "迈瑞医疗",
         "301358": "湖南裕能", "600079": "ST人福", "600096": "云天化", "600176": "中国巨石",
         "600276": "恒瑞医药", "600309": "万华化学", "600456": "宝钛股份", "600660": "福耀玻璃",
         "600989": "宝丰能源", "601899": "紫金矿业", "603087": "甘李药业", "603259": "药明康德",
         "603345": "安井食品", "603648": "畅联股份", "603993": "洛阳钼业", "605016": "匠心家居",
         "688825": "铁建重工"}


def to_local(c: str) -> str:
    return c + (".SH" if c.startswith(("6", "9")) else ".SZ")


b = rps_main(cache=Path(__file__).resolve().parents[2] / "data/research/R20261110-04/rps_bundle.pkl")
day = b["rps250"].index[-1]
print(f"用户池个股 {len(RAW.split())} 只，全市场横截面末日 {day.date()}（6267 票宇宙）\n")
print(f"{'票':<12}{'RPS50':>7}{'RPS120':>8}{'RPS250':>8}")
rows = []
for c in sorted(RAW.split()):
    sym = to_local(c)
    r50 = b["rps50"].loc[day, sym] if sym in b["rps50"].columns else float("nan")
    r120 = b["rps120"].loc[day, sym] if sym in b["rps120"].columns else float("nan")
    r250 = b["rps250"].loc[day, sym] if sym in b["rps250"].columns else float("nan")
    rows.append((c, r50, r120, r250))
    print(f"{c} {NAMES.get(c,'')[:6]:<7}{r50:>7.1f}{r120:>8.1f}{r250:>8.1f}")

df = pd.DataFrame(rows, columns=["code", "r50", "r120", "r250"]).set_index("code")
print(f"\n池内 RPS250 分布：>90: {(df.r250>90).sum()}  50-90: {((df.r250>50)&(df.r250<=90)).sum()}  "
      f"<50: {(df.r250<=50).sum()}  中位 {df.r250.median():.1f}")
print(f"全市场对照：RPS250>90 占比 ~10%（百分位构造），池中位 {df.r250.median():.1f} "
      f"vs 全市场中位 50 → 池整体 {'偏强' if df.r250.median()>50 else '中性偏弱'}（相对全市场 250 日强度）")
