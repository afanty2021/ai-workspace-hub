# tests/test_sr_backtest.py
import numpy as np

import backtest  # noqa: E402
from sector_rotation.walkforward import WalkResult


def _res(cagr=0.10):
    weekly = np.full(52, 0.0019)
    nav = np.concatenate([[1.0], np.cumprod(1 + weekly)])
    return WalkResult(nav, nav.copy(), weekly, list(range(52)),
                      {"cagr": cagr, "alpha": 0.02, "sharpe": 1.1, "max_dd": -0.1,
                       "win_rate": 0.55, "turnover": 90.0, "cost_drag": 0.11,
                       "cluster_binds": 4}, [])


def _tests(level, p_stress_eq=0.12):
    return {(level, "vs 随机", "base"): 0.03, (level, "vs 随机", "stress"): 0.05,
            (level, "vs 等权", "base"): 0.04, (level, "vs 等权", "stress"): p_stress_eq,
            (level, "vs 沪深300", "base"): 0.03, (level, "vs 沪深300", "stress"): 0.06,
            (level, "vs L0", "base"): 0.02, (level, "vs L0", "stress"): 0.03}


def test_render_report_matrix_and_power_note():
    text = backtest.render_report(
        {"L0": _res(), "等权持有": _res(0.05), "随机k3": _res(0.04)},
        _tests("L0"), level="L0", tag="L0-预注册",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="k=3 / 方向=动量 / lookback=1（2026-11-XX 预注册）", n_oos=370)
    assert "检验矩阵" in text and "未检出" in text          # 功效注释在
    assert "370" in text                                     # C9：动态周数
    assert "L0 闸门" in text and "未通过" in text           # stress 档 0.12 ≥0.1 → 未过


def test_render_report_level_param_and_exploratory_no_gate():
    text = backtest.render_report(                          # C6：L 级键不再空转
        {"L2": _res()}, _tests("L2", p_stress_eq=0.03),
        level="L2", tag="L2-确认",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="L2 主检验", n_oos=370)
    assert "vs L0" in text and "L2 闸门" in text and "通过" in text
    text2 = backtest.render_report(                         # I10：探索性无闸门行
        {"L2-k2": _res()}, _tests("L2", 0.9),
        level="L2", tag="L2-k2",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="探索性", exploratory=True, n_oos=370)
    assert "只报告不判定" in text2 and "闸门" not in text2


def test_render_report_bare_diagnostic_section():
    """S6-C：裸信号诊断段（只诊断不判定）；不传 diag 时不出现。"""
    diag = {"bare_cagr": 0.02, "bare_sharpe": 0.3, "bare_max_dd": -0.2,
            "halt_events": 2, "halt_rejects": 1}
    text = backtest.render_report(
        {"L0": _res()}, _tests("L0"), level="L0", tag="L0-确认",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="L0 主检验", n_oos=370, diag=diag)
    assert "裸信号诊断" in text and "S6-C" in text and "不判定" in text
    assert "触发 2 次" in text and "探针否决 1 次" in text and "+2.00%" in text
    text2 = backtest.render_report(
        {"L0": _res()}, _tests("L0"), level="L0", tag="L0-确认",
        tier_notes={"base": "10bp", "stress": "20bp"},
        prereg="L0 主检验", n_oos=370)
    assert "裸信号诊断" not in text2
