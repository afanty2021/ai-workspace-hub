# 来源: https://github.com/BruceLanLan/augur (MIT License)
# 锁定 commit: 0c721acc8522d4da57ea38bcd1852a30f23674e9
# 本地改动: 仅加此头注与文件更名（原 consensus/probability_calibrator.py）；正文逐字节一致。

# -*- coding: utf-8 -*-
"""Simple confidence calibration for consensus scores."""


def calibrate_confidence(score: float, confidence: float, agent_id: str = "consensus") -> float:
    """Map raw confidence toward calibrated range using score extremity."""
    score = max(0.0, min(10.0, score))
    confidence = max(0.0, min(1.0, confidence))
    # Extreme scores (far from 5) deserve slightly higher confidence
    extremity = abs(score - 5.0) / 5.0
    calibrated = confidence * (0.85 + 0.15 * extremity)
    return min(0.95, max(0.05, calibrated))
