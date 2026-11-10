"""R20261110-07 弱票反转观察清单：scan 核语义 + 日报节渲染降级。"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "stage-bottom"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from weak_scan import scan_one  # noqa: E402
from generate_daily_report import render_weak_reversal_section  # noqa: E402


def _rows_from_closes(closes, today_iso, seed=11):
    rng = np.random.default_rng(seed)
    rows, d = [], date.fromisoformat(today_iso)
    span = len(closes)
    from datetime import timedelta
    d0 = d - timedelta(days=span * 2)
    for k, c in enumerate(closes):
        rows.append({
            "date": (d0 + timedelta(days=int(k * 1.4))).isoformat(),  # 交易日近似
            "open": float(c * 0.995), "high": float(c * 1.01),
            "low": float(c * 0.99), "close": float(c),
            "volume": 1e6, "amount": 8e7,               # amt20=8000 万 > 3000 万
        })
    # 强制末两行=今日与昨日（scan_one 只看 rows[-2:] 的 U4/交叉）
    rows[-1]["date"] = today_iso
    rows[-2]["date"] = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
    return rows


def test_flat_no_signal():
    today = "2026-11-10"
    rows = _rows_from_closes(np.full(300, 10.0), today)
    assert scan_one(rows, today) is None


def test_deep_v_reversal_fires_gate70_or_none_semantics():
    """深跌后单根大反弹：交叉恰在最后一根 → gate70；字段齐全。"""
    today = "2026-11-10"
    rng = np.random.default_rng(7)
    dn = 100.0 * np.cumprod(1.0 - 0.035 + rng.normal(0, 0.01, 60))
    up = dn[-1] * 1.052                      # 单根 +5.2%：RSI 0→~30 一次过 20
    closes = np.concatenate([np.full(190, 100.0), dn, [up]])
    rows = _rows_from_closes(closes, today)
    ev = scan_one(rows, today)
    assert ev is not None, "工程夹具应触发信号（若噪声敏感，调 seed 而非断言）"
    assert ev["kind"] == "gate70", "深跌 60 根后 ADX 应爆表走主臂（评审 M-3：锁 gate70 专属性）"
    assert 20.0 < ev["rsi5"] < 60.0
    assert ev["amt20"] >= 3e7 and ev["bars"] >= 250


def test_report_section_missing_artifact_degrades(tmp_path):
    out = render_weak_reversal_section(tmp_path, "2026-11-10")
    assert "无扫描产物" in out and "R20261110-07" in out


def test_report_section_reads_artifact(tmp_path):
    art = tmp_path / "output" / "screen" / "weak-reversal" / "2026-11-10.md"
    art.parent.mkdir(parents=True)
    art.write_text("gate70 弱票反转扫描（2026-11-10）：**3 只**主信号。", encoding="utf-8")
    out = render_weak_reversal_section(tmp_path, "2026-11-10")
    assert "3 只" in out
    # 昨日产物不冒充今日
    out_stale = render_weak_reversal_section(tmp_path, "2026-11-11")
    assert "无扫描产物" in out_stale
