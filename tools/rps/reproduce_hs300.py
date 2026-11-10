# -*- coding: utf-8 -*-
"""对拍臂：文章 WorkBuddy 实测（沪深300 内 RPS250>95 共 15 只 + 前 5 名名单）。

文章口径：akshare 前复权日线，300 成分内 rank(pct=True)*100。
本臂口径：本地不复权+板别送转修复近似，300 成分内重排——前 5 名名单层面匹配
即认为公式实现正确（数值排序在两种复权口径下可能个别互换，属预期差异）。
"""
import akshare as ak
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from rps_core import rps_main

ARTICLE_TOP5 = ["中钨高新", "招商轮船", "中国巨石", "杰瑞股份", "拓荆科技"]

cons = ak.index_stock_cons(symbol="000300")
codes = cons["品种代码"].astype(str).str.zfill(6)
name_map = dict(zip(codes, cons["品种名称"]))
# 本地缓存代码后缀
def to_local(c: str) -> str:
    return c + (".SH" if c.startswith(("6", "9")) else ".SZ")

local_codes = [to_local(c) for c in codes]
print(f"沪深300 成分 {len(codes)} 只")

b = rps_main(cache=Path(__file__).resolve().parents[2] / "data/research/R20261110-04/rps_bundle.pkl")
ret250 = b["close_adj"] / b["close_adj"].shift(250) - 1.0

# 三个候选对拍日（文章实测日未注明，取缓存末日附近）
for day in ["2026-11-06", "2026-11-05", "2026-11-04"]:
    if pd.Timestamp(day) not in ret250.index:
        continue
    sub = ret250.loc[pd.Timestamp(day), [c for c in local_codes if c in ret250.columns]].dropna()
    # 上市一年以上近似：300 成分均老票，直接横排名
    rps = sub.rank(pct=True) * 100
    top = rps[rps > 95].sort_values(ascending=False)
    names = [f"{name_map[c[:6]]}({c[:6]})" for c in top.index[:5]]
    hit = [n for n in ARTICLE_TOP5 if any(n in x for x in names)]
    print(f"\n== {day}：横截面 {len(sub)} 只，RPS250>95 共 {len(top)} 只")
    print(f"   前 5 名：{names}")
    print(f"   文章名单命中：{len(hit)}/5 {hit}")
