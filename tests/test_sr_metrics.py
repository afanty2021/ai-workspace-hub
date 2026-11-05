import numpy as np

from sector_rotation.metrics import compute_metrics


def test_flat_nav_metrics():
    m = compute_metrics(np.ones(53), np.zeros(52),
                        benchmark_nav=np.linspace(1, 1.1, 53),
                        turnover=2.0, cost_drag=0.0012, cluster_binds=3)
    assert m["cagr"] == 0.0 and m["alpha"] < 0 and m["win_rate"] == 0.0
    assert m["cluster_binds"] == 3


def test_steady_growth():
    r = np.full(52, 0.001)
    nav = np.concatenate([[1.0], np.cumprod(1 + r)])
    m = compute_metrics(nav, r)
    assert abs(m["cagr"] - (1.001 ** 52 - 1)) < 1e-9
    assert np.isnan(m["sharpe"])            # 零波动约定 nan，报告层注明
    assert m["win_rate"] == 1.0
