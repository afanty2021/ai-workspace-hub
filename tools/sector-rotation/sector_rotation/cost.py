"""两档成本模型（spec §3.7 v1.2：历史段禁今日实测点差，闸门两档都过）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 1.0
    spread_bps: float = 10.0     # 语义 = 单边点差（评审 C1 修正）
    impact_bps: float = 0.0

    @classmethod
    def base(cls) -> "CostModel":
        return cls(spread_bps=10.0)

    @classmethod
    def stress(cls) -> "CostModel":
        return cls(spread_bps=20.0)

    def side_bps(self) -> float:
        return self.commission_bps + self.spread_bps + self.impact_bps

    def roundtrip_bps(self) -> float:
        return 2 * self.side_bps()
