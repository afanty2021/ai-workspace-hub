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
    def __init__(self, spec: UniverseSpec, *, enabled: bool = True,
                 halt_wait_weeks: int = 13, probe_frac: float = 0.5,
                 probe_confirm_weeks: int = 4):
        # S6-A（spec v1.2.3 §3.6）：全停从吸收态改探针重启滞回态——
        # 触发后持币 halt_wait_weeks 周（触发当周计入）→ probe_frac 仓探针
        # probe_confirm_weeks 周 → 探针期收益 ≥0 确认恢复满仓 / <0 否决回到停机，
        # 循环不限次。触发条件只在正常态评估（滞回：探针期内不看绝对线）。
        # 默认参数 = 选择窗网格冻结值（N=13/f=0.5/M=4，spec §6.3 2026-11-05），
        # 取代草案先验 N=8——引擎默认行为与预注册参数保持一致。
        self.spec = spec
        self.enabled = enabled
        self.halt_wait_weeks = halt_wait_weeks
        self.probe_frac = probe_frac
        self.probe_confirm_weeks = probe_confirm_weeks
        self.loss_weeks = 0
        self.wins: dict[int, list[bool]] = {i: [] for i in range(len(spec.members))}
        self.cooldown: dict[int, int] = {}
        self.banned: set[int] = set()
        self.binds = 0
        self.halved = False                     # 评审 I2：年内回撤 ≥8% 降半仓至新高
        self.halted = False                     # 评审 I2：绝对亏损 ≥10% 全停（S6-A 改滞回态）
        self.wait_weeks = 0                     # S6-A：当前停机周期已等待周数
        self.probing = False                    # S6-A：是否处于探针期
        self.probe_nav0: float = 0.0            # S6-A：探针起点 NAV（确认判据分母）
        self.probe_weeks = 0                    # S6-A：当前探针期已过周数
        self.halt_events: list[str] = []        # S6-A：触发日志（friday 列表）
        self.halt_rejects = 0                   # S6-A：探针否决次数
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
        probe_scale = 1.0
        if not self.halted and nav <= self.start_nav * 0.90:
            self.halted = True                  # 组合绝对亏损 ≥10% → 停机（S6-A 滞回态）
            self.halt_events.append(wf.fridays[t])
        if self.halted:
            self.wait_weeks += 1                # 触发当周计为持币第 1 周
            if self.wait_weeks <= self.halt_wait_weeks:
                return {}
            if not self.probing:                # 等待期满 → 本周为探针第 1 周
                self.probing, self.probe_nav0, self.probe_weeks = True, nav, 0
            self.probe_weeks += 1
            if self.probe_weeks > self.probe_confirm_weeks:
                if nav >= self.probe_nav0:      # 探针期收益 ≥0 → 确认，本周恢复满仓
                    self.halted, self.probing = False, False
                    self.wait_weeks = 0
                else:                           # 否决 → 回到停机等待（循环不限次）
                    self.halted, self.probing = True, False
                    self.wait_weeks = 1         # 否决当周计为新周期第 1 周（与触发当周同口径）
                    self.halt_rejects += 1
                    return {}
            else:
                probe_scale = self.probe_frac
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
        # S6-A：探针期敞口 = probe_frac（有定义的状态敞口）；回撤减半只在
        # 非探针态生效（确认恢复满仓后若仍低于年内高点，减半规则自然接手）
        scale = probe_scale if self.probing else (0.5 if self.halved else 1.0)
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
