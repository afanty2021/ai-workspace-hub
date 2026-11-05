from sector_rotation.cost import CostModel


def test_two_tiers_spec_arithmetic():
    """对拍 spec §7：单边点差 10bp × 2 + 佣金双边 = 22bp/周·全换手（评审 C1）。"""
    assert CostModel.base().spread_bps == 10.0
    assert CostModel.stress().spread_bps == 20.0
    assert CostModel.base().side_bps() == 11.0
    assert CostModel.stress().side_bps() == 21.0
    assert CostModel.base().roundtrip_bps() == 22.0
    assert CostModel.stress().roundtrip_bps() == 42.0
