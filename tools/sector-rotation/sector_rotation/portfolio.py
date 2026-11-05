# tools/sector-rotation/sector_rotation/portfolio.py
"""执行闸门/风控/持币式同簇截断（spec §3.5/§3.6 v1.2）。"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .cost import CostModel
from .data import WeeklyFrame
from .universe import UniverseSpec, cluster_for

WEEKLY_MIN_AMOUNT_WAN = 5000.0


class RiskState:
    def __init__(self, spec: UniverseSpec, *, enabled: bool = True):
        self.spec = spec
        self.enabled = enabled
        self.loss_weeks = 0
        self.wins: dict[int, list[bool]] = {i: [] for i in range(len(spec.members))}
        self.cooldown: dict[int, int] = {}
        self.banned: set[int] = set()
        self.binds = 0
        self.halved = False                     # 评审 I2：年内回撤 ≥8% 降半仓至新高
        self.halted = False                     # 评审 I2：绝对亏损 ≥10% 全停
        self.start_nav: float | None = None
        self.ytd_high = 0.0
        self.ytd_year: int | None = None

    def apply(self, t: int, wf: WeeklyFrame, desired: dict[int, float],
              last_week_pos_returns: dict[int, float] | None,
              *, nav: float = 1.0) -> dict[int, float]:
        if not self.enabled:
            return dict(desired)
        year = int(wf.fridays[t][:4])
        if self.start_nav is None:
            self.start_nav = nav
        if self.ytd_year != year:               # 新年重置年内高点
            self.ytd_year, self.ytd_high = year, nav
        self.ytd_high = max(self.ytd_high, nav)
        if nav <= self.start_nav * 0.90:        # 组合绝对亏损 ≥10% → 永久停
            self.halted = True
        if self.halted:
            return {}
        if nav >= self.ytd_high:                # 创年内新高 → 恢复满仓
            self.halved = False
        elif nav / self.ytd_high <= 0.92:       # 年内回撤 ≥8% → 降半仓
            self.halved = True
        if last_week_pos_returns:
            if all(r < 0 for r in last_week_pos_returns.values()):
                self.loss_weeks += 1
            else:
                self.loss_weeks = 0
            for i, r in last_week_pos_returns.items():
                self.wins[i].append(r > 0)
                if r <= -0.05:
                    self.banned.add(i)
                hist = self.wins[i][-8:]
                if len(hist) == 8 and sum(hist) / 8 < 0.45:
                    self.cooldown[i] = 2
        if self.loss_weeks >= 4:
            self.loss_weeks = 0
            return {}
        cmap = cluster_for(self.spec, wf.fridays[t])   # None 代 → 约束跳过
        picked: dict[int, float] = {}
        cluster_cnt: Counter[str] = Counter()
        scale = 0.5 if self.halved else 1.0
        for i in sorted(desired, key=lambda j: -desired[j]):
            if i in self.banned or self.cooldown.get(i, 0) > 0:
                continue
            if cmap is not None:
                cl = cmap.get(wf.members[i].index_code)
                if cl is not None:
                    if cluster_cnt[cl] >= 2:
                        self.binds += 1              # 持币：不补位不归一
                        continue
                    cluster_cnt[cl] += 1
            picked[i] = desired[i] * scale           # 截断资/半仓资 = 现金，不归一
        for i in list(self.cooldown):
            self.cooldown[i] -= 1
            if self.cooldown[i] <= 0:
                del self.cooldown[i]
        self.banned.clear()
        return picked


def simulate_week(wf: WeeklyFrame, t: int, weights_prev: dict[int, float],
                  weights_new: dict[int, float], cost: CostModel
                  ) -> tuple[float, dict[int, float], dict[int, float]]:
    # 执行闸门（spec §3.5）：周一开盘涨停弃买；周内日均成交额 <5000 万拦截；
    # etf_open 缺失（nan）单独记 "missing"（执行注：与 limit_up 拆开分别记）。
    # 跌停顺延首版简化：周五清仓一律按 close 计损益，顺延只影响成本时点
    # （周频口径影响 ≤1bp）——README 已知限制声明。
    blocked: dict[int, str] = {}
    executed: dict[int, float] = {}
    for i, w in weights_new.items():
        member = wf.members[i]
        limit_up = wf.etf_prev_close[t, i] * (1 + member.limit_pct * 0.995)
        if not np.isfinite(wf.etf_open[t, i]):
            blocked[i] = "missing"
        elif wf.etf_open[t, i] >= limit_up:
            blocked[i] = "limit_up"
        elif (not np.isfinite(wf.etf_week_amount[t, i])
              or wf.etf_week_amount[t, i] < WEEKLY_MIN_AMOUNT_WAN * 1e4):
            blocked[i] = "liquidity"
        else:
            executed[i] = w
    gross = {i: wf.etf_close[t, i] / wf.etf_open[t, i] - 1.0 for i in executed}
    port_gross = sum(executed[i] * gross[i] for i in executed)
    # 评审 C5：净换手计费——逐资产 |新 − 旧(漂移后)| × 单边成本；持有过周末 ≈ 0 成本
    turnover = sum(abs(executed.get(i, 0.0) - weights_prev.get(i, 0.0))
                   for i in set(executed) | set(weights_prev))
    costs = turnover * cost.side_bps() / 1e4
    detail = {"blocked": blocked, "turnover": turnover,
              "gross": port_gross, "costs": costs}
    return port_gross - costs, gross, detail
