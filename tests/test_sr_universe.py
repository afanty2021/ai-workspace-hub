from pathlib import Path

import pytest

from sector_rotation.universe import (Member, UniverseSpec, cluster_for,
                                      load_universe, point_in_time_pick,
                                      write_universe)


def _spec():
    return UniverseSpec(
        members=[
            Member("881101", "工程机械", ("528030.SH", "516810.SH"), 0.10),
            Member("881127", "半导体", ("512480.SH",), 0.10),
        ],
        clusters={2019: {"881101": "c-a", "881127": "c-b"},
                  2021: {"881101": "c-x", "881127": "c-x"}})


def test_roundtrip(tmp_path: Path):
    path = tmp_path / "universe.md"
    write_universe(path, _spec(), status="draft")
    assert load_universe(path) == _spec()


def test_cluster_for_uses_latest_available_generation():
    # 口径（评审 C8 修正的是测试、不是实现）：代 g 聚类窗 [g, g+1]，g+2 年起才可用
    # （spec §3.6"t 时点用 t-2 至 t-1 年收益"）。照旧测试改实现 = 引入当年收益泄漏。
    spec = _spec()
    assert cluster_for(spec, "2019-01-04") is None           # 无可用代
    assert cluster_for(spec, "2020-06-05") is None           # 2019 代 2021 年起才可用
    assert cluster_for(spec, "2022-01-07") == {"881101": "c-a", "881127": "c-b"}
    assert cluster_for(spec, "2023-01-06") == {"881101": "c-x", "881127": "c-x"}


def test_load_rejects_bad_header(tmp_path: Path):
    p = tmp_path / "u.md"
    p.write_text("---\ntype: sector-rotation-universe\n---\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未解析到任何成员"):
        load_universe(p)


def _bar(d, amount):
    return {"date": d, "amount": amount}


def test_point_in_time_pick_respects_listing_age_and_liquidity():
    # （Task 4 下沉：随 point_in_time_pick 自 tests/test_sr_universe_build.py 搬来）
    old = [_bar(f"2024-01-{i:02d}", 3e8) for i in range(2, 22)]     # 2024 起，>2 年史
    young = [_bar(f"2025-06-{i:02d}", 5e8) for i in range(2, 22)]   # 上市 <2 年
    thin = [_bar(f"2024-01-{i:02d}", 2e7) for i in range(2, 22)]    # 均额 2000 万 <1 亿
    bars = {"528030.SH": old, "516810.SH": young, "159999.SZ": thin}
    assert point_in_time_pick(
        ["528030.SH", "516810.SH", "159999.SZ"], bars, "2026-11-06") == "528030.SH"
    assert point_in_time_pick(["516810.SH"], bars, "2026-11-06") is None
