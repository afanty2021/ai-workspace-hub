# tests/test_sr_universe_build.py
import numpy as np

import build_universe  # noqa: E402


def _bar(d, amount):
    return {"date": d, "amount": amount}


def test_filter_etf_candidates_keeps_industry_etf():
    listing = [
        {"code": "512480", "name": "半导体ETF"}, {"code": "512000", "name": "券商ETF"},
        {"code": "510300", "name": "沪深300ETF"}, {"code": "513330", "name": "恒生互联网ETF"},
        {"code": "511990", "name": "华宝添益"}, {"code": "518880", "name": "黄金ETF"},
        {"code": "159915", "name": "创业板ETF"}, {"code": "562400", "name": "机器人ETF"},
    ]
    kept = build_universe.filter_etf_candidates(listing)
    # 后缀口径（与 Member.etf_candidates / data/market/series/{sym}.jsonl 一致，
    # brief 原断言用裸码与本 brief 自身 point_in_time_pick 用例的后缀键矛盾——修测试）
    assert {"512480.SH", "512000.SH", "562400.SH"} <= set(kept)
    assert not ({"510300.SH", "513330.SH", "511990.SH", "518880.SH", "159915.SZ"}
                & set(kept))


def test_point_in_time_pick_respects_listing_age_and_liquidity():
    old = [_bar(f"2024-01-{i:02d}", 3e8) for i in range(2, 22)]     # 2024 起，>2 年史
    young = [_bar(f"2025-06-{i:02d}", 5e8) for i in range(2, 22)]   # 上市 <2 年
    thin = [_bar(f"2024-01-{i:02d}", 2e7) for i in range(2, 22)]    # 均额 2000 万 <1 亿
    bars = {"528030.SH": old, "516810.SH": young, "159999.SZ": thin}
    assert build_universe.point_in_time_pick(
        ["528030.SH", "516810.SH", "159999.SZ"], bars, "2026-11-06") == "528030.SH"
    assert build_universe.point_in_time_pick(["516810.SH"], bars, "2026-11-06") is None


def test_cluster_by_correlation_groups_high_corr():
    rng = np.random.default_rng(7)
    base = rng.normal(size=104)
    rets = np.column_stack([base, base + 0.05 * rng.normal(size=104),
                            rng.normal(size=104)])
    cl = build_universe.cluster_by_correlation(rets, ["A", "B", "C"])
    assert cl["A"] == cl["B"] != cl["C"]


def test_filter_excludes_sz_bond_segment_and_broad_abbrev():
    # Minor#2（评审）：深市 520-563 债券段与沪市 ETF 段撞号——market=0 只认 158/159；
    # 双向对照：深/沪真行业票必须仍通过，证明市场判没有误伤。
    listing = [
        {"code": "520109", "name": "26振业01", "market": 0},   # 深市债
        {"code": "159995", "name": "芯片ETF", "market": 0},     # 深市行业票 → 保留
        {"code": "516010", "name": "游戏ETF", "market": 1},     # 沪市行业票 → 保留
        # Important#1（评审）：TDX 缩写名宽基族，绕过 ETF 字样判的漏网类
        {"code": "588120", "name": "科100ETF"}, {"code": "589300", "name": "科综嘉实"},
        {"code": "589980", "name": "科基100"}, {"code": "159627", "name": "中证100"},
        {"code": "512910", "name": "100ETF"}, {"code": "159571", "name": "创200"},
        {"code": "159923", "name": "D100ETF"}, {"code": "515860", "name": "科技100"},
        {"code": "159808", "name": "创100RT"}, {"code": "159592", "name": "中证50"},
    ]
    kept = set(build_universe.filter_etf_candidates(listing))
    assert {"159995.SZ", "516010.SH"} <= kept
    assert not ({"520109.SH", "588120.SH", "589300.SH", "589980.SH", "159627.SZ",
                 "512910.SH", "159571.SZ", "159923.SZ", "515860.SH", "159808.SZ",
                 "159592.SZ"} & kept)
