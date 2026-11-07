"""参数默认值——2026-11-07 对靶 Pine 源码后全部取自原脚本真实默认值。

出处：tools/wyckoff/reference/lunqfx-wyckoff.pine INPUTS 段（用户手拷，逐行核对）。
此前「自定猜测值」版本已废弃；语义差异见 machine.py docstring 的移植注记。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    # --- climax（SC/BC）判定 ---
    climax_lookback: int = 50      # trendLen：SC 须打 lookback 窗最低低点（BC 镜像最高高点）；
                                   # 亦作 WAIT_AR 的 AR 超时窗（自 climax 极值 bar 起）
    climax_range_atr: float = 1.2  # climRng：bar range ≥ ×ATR
    climax_vol_mult: float = 1.5   # climVol：volume ≥ ×SMA20（含当前 bar）；无 volume 序列跳过
    atr_period: int = 50           # ta.atr(50) = Wilder RMA；前 period-1 根为 na，机器整体被其门控

    # --- swing / 区间 ---
    swing_strength: int = 3        # pivLen：pivot 两侧确认根数
    min_ar_atr: float = 2.0        # arMin：AR 行程 ≥ ×ATR（ATR 取确认 bar 时值）
    max_range_atr: float = 10.0    # maxH：AR 行程 > ×ATT 判非交易区间，丢弃不计
    min_range_len: int = 15        # minRange：更早突破/破位 = V-turn，丢弃不计
    st_zone_frac: float = 0.35     # stTol：ST 须回到 climax 侧 35% 区间高度内且不破

    # --- Spring / UTAD ---
    spring_max_out: int = 3        # sprBars：pendN > 3（破位 bar 起第 4 根仍未收回）判失败
    fail_depth_frac: float = 0.30  # failDep：收盘越过 climax 侧超区间高度 30% = 破坏（影线深度不判）

    # --- 超时 ---
    range_max_bars: int = 300      # maxRng：区间态自 SC bar；spring 态自 spring 极值 bar
    markup_max_bars: int = 300     # maxLeg：自 SOS bar
