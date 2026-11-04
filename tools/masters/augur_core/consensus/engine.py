# 来源: https://github.com/BruceLanLan/augur (MIT License)
# 锁定 commit: 0c721acc8522d4da57ea38bcd1852a30f23674e9
# 本地改动: 从 augur/consensus/engine.py 的 ConsensusEngine.compute() 摘取纯计算主干并
#           重写为模块级函数 compute_consensus()；剥离清单见模块 docstring。

# -*- coding: utf-8 -*-
"""Vendored consensus engine — pure computation, no I/O.

从 augur ConsensusEngine.compute() 摘取的主干（输出形状尽量对齐原版）：
  - 信号计数与加权多数表决（方向性平票 → NEUTRAL）
  - 行业加权：get_agent_weights(industry_key) + restrict_weights_to_agents
    （industry_key 由调用方/适配层给定，默认 "general"；原版的
    detect_industry/regime/macro 路径不在本函数内触发）
  - coverage_confidence 归一后乘入权重
  - sector 关键词加权增益（tech→cathie_wood/aschenbrenner/thiel 等，纯本地逻辑）
  - calibrate_confidence 置信度校准
  - half-Kelly 仓位：bullish 且 score>=5 时
      pct = min(20.0, round(((score-5)/5 * conf) * 0.5 * 100, 1))，
      pct<1 且 conf>=0.5 时保底 1%；bearish→0；neutral→max(0, round((conf-0.5)*3, 1))
    写入 metadata["position_sizing"] 与 metadata["position_pct"]
  - 低参与度标记（<3 个有效 agent → low_participation，置信度抬到 >=0.2）
  - 分歧度 divergence（原始人头计数）与最终 score/confidence clamp
  - 全员看多时的风险提示追加

相对原版 compute() 剥离的调用点（全部涉及外部 I/O 或学习态）：
  sentiment 因子、MetaModel 混合、RiskManager 否决、agent 相关性惩罚、
  ten_x 覆盖层、learning 预测记录、rolling-IC 动态权重、
  feedback 文件加载（global weights / industry_matrix.json / agent_correlation.json）、
  regime/macro_features/regime_router、yfinance（无任何网络/文件 I/O）。

行业权重口径说明：原版有效 agent 不在行业权重表内时回退 global weights，
本版剥离 feedback 后等价回退为 1/valid_count（restrict_weights_to_agents 的均分路径）。
"""

import math
from typing import Dict, Optional

from augur_core.consensus.calibration import calibrate_confidence
from augur_core.consensus.industry_matrix import get_agent_weights
from augur_core.consensus.weighting import restrict_weights_to_agents
from augur_core.personas.base import AgentResponse, MarketContext, SignalType


def _normalize_coverage_confidence(coverage: float) -> float:
    """Clamp model applicability weight to a finite [0, 1] range."""
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
        return 1.0
    if not math.isfinite(coverage):
        return 1.0
    return max(0.0, min(1.0, float(coverage)))


def compute_consensus(
    results: Dict[str, AgentResponse],
    ticker: str = "",
    industry_key: str = "general",
    context: Optional[MarketContext] = None,
) -> AgentResponse:
    """Compute consensus signal with industry weighting (pure, no I/O)."""
    if not results:
        return AgentResponse(
            agent_id="consensus",
            agent_name="Multi-Agent Consensus",
            signal=SignalType.NEUTRAL,
            confidence=0,
            score=0,
            reasoning="No results",
        )

    # --- Industry-aware weights ---
    weights = get_agent_weights(industry_key)
    valid_agent_ids = [
        aid for aid, resp in results.items() if resp.signal != SignalType.ERROR
    ]
    if valid_agent_ids:
        weights = restrict_weights_to_agents(weights, valid_agent_ids)

    # --- Signal counting and scoring ---
    signal_counts = {SignalType.BULLISH: 0.0, SignalType.NEUTRAL: 0.0, SignalType.BEARISH: 0.0}
    total_score = 0.0
    total_weight = 0.0
    total_confidence = 0.0
    all_findings = []
    all_risks = []
    adjusted_weights = {}

    for agent_id, response in results.items():
        if response.signal == SignalType.ERROR:
            continue
        w = weights.get(agent_id, 0.0)
        if w <= 0:
            # Agent not in industry table (or empty weights map): even split fallback,
            # matching restrict_weights_to_agents semantics for absent agents.
            valid_count = len(valid_agent_ids) or 1
            w = 1.0 / valid_count

        w *= _normalize_coverage_confidence(response.coverage_confidence)

        # Sector-aware weight boosting
        if context and hasattr(context, "sector") and context.sector:
            sector_lower = (context.sector or "").lower()
            industry_lower = (context.industry or "").lower() if hasattr(context, "industry") else ""
            is_tech = sector_lower in ("technology", "information technology") or any(
                kw in industry_lower
                for kw in ["artificial intelligence", "machine learning", "semiconductor", "software"]
            )
            is_financial = "financial" in sector_lower
            is_healthcare = "health" in sector_lower or "medical" in sector_lower

            if is_tech and agent_id in ("cathie_wood", "aschenbrenner", "thiel"):
                w *= 1.3
            elif is_financial and agent_id in ("buffett", "graham", "marks"):
                w *= 1.2
            elif is_healthcare and agent_id == "fisher":
                w *= 1.2

        adjusted_weights[agent_id] = w

        if response.signal in signal_counts:
            signal_counts[response.signal] += w
        total_score += response.score * w
        total_confidence += response.confidence * w
        total_weight += w
        all_findings.extend(response.key_findings)
        all_risks.extend(response.risks)

    # Normalize
    if total_weight > 0:
        total_score /= total_weight
        total_confidence /= total_weight
    else:
        total_score = 0.0
        total_confidence = 0.0

    # Weighted majority vote — directional ties resolve to NEUTRAL
    if sum(signal_counts.values()) <= 0:
        consensus_signal = SignalType.NEUTRAL
    else:
        max_weight = max(signal_counts.values())
        tied = [sig for sig, w in signal_counts.items() if w == max_weight]
        if len(tied) == 1:
            consensus_signal = tied[0]
        elif SignalType.NEUTRAL in tied:
            consensus_signal = SignalType.NEUTRAL
        elif SignalType.BULLISH in tied and SignalType.BEARISH in tied:
            consensus_signal = SignalType.NEUTRAL
        else:
            consensus_signal = tied[0]

    # --- Probability calibration ---
    calibrated_confidence = min(0.95, total_confidence)
    calibrated_confidence = calibrate_confidence(total_score, calibrated_confidence, "consensus")

    result = AgentResponse(
        agent_id="consensus",
        agent_name="Multi-Agent Consensus",
        signal=consensus_signal,
        confidence=calibrated_confidence,
        score=total_score,
        reasoning=f"Consensus from {len(results)} agents",
        key_findings=all_findings[:5],
        risks=all_risks[:3],
    )

    # --- Kelly position sizing (simplified half-Kelly) ---
    try:
        sig = result.signal.value
        score = result.score
        conf = result.confidence
        # Half-Kelly: f = 0.5 * (p - (1-p)/b) clamped to 0-20%
        if sig == "bullish" and score >= 5:
            # edge = (score - 5) / 5  maps [5,10] → [0,1]
            edge = max(0, (score - 5) / 5)
            full_kelly = edge * conf
            pct = min(20.0, round(full_kelly * 0.5 * 100, 1))
            # Minimum 1% token position for bullish signal with sufficient confidence
            if pct < 1.0 and conf >= 0.5:
                pct = 1.0
        elif sig == "bearish":
            pct = 0.0
        else:
            pct = max(0.0, round((conf - 0.5) * 3.0, 1))

        position = {
            "position_pct": pct,
            "signal": sig,
            "score": round(score, 2),
            "confidence": round(conf, 3),
            "rationale": f"half-Kelly: {pct:.1f}% (score={score:.1f}, conf={conf:.0%})",
        }
        result.metadata["position_sizing"] = position
        result.metadata["position_pct"] = pct
    except Exception:
        pass

    if adjusted_weights:
        result.metadata["weighting"] = {
            "industry": industry_key,
            "participating_agents": len(adjusted_weights),
            "agent_weights": {
                aid: round(w, 4) for aid, w in sorted(adjusted_weights.items())
            },
        }

    # --- Low participation check ---
    valid_results = {k: v for k, v in results.items() if v.signal != SignalType.ERROR}
    if len(valid_results) < 3:
        result.metadata["low_participation"] = True
        result.confidence = max(0.2, result.confidence)
    if valid_results and sum(
        1 for r in valid_results.values() if r.signal == SignalType.BULLISH
    ) == len(valid_results):
        result.risks.append("All agents bullish - historically this consensus often means overvaluation")
        if context and hasattr(context, "pe") and context.pe > 30:
            result.risks.append(f"PE={context.pe:.1f}, valuation elevated - consider stop-loss")

    # --- Divergence score (raw non-weighted head-counts) ---
    _bull_raw = sum(1 for r in valid_results.values() if r.signal == SignalType.BULLISH)
    _bear_raw = sum(1 for r in valid_results.values() if r.signal == SignalType.BEARISH)
    _neu_raw = sum(1 for r in valid_results.values() if r.signal == SignalType.NEUTRAL)
    _active_raw = _bull_raw + _bear_raw
    _div_score = round(2.0 * min(_bull_raw, _bear_raw) / _active_raw, 3) if _active_raw > 0 else 0.0
    result.metadata["divergence"] = {
        "score": _div_score,
        "bullish_count": _bull_raw,
        "bearish_count": _bear_raw,
        "neutral_count": _neu_raw,
        "total_valid": len(valid_results),
        "is_divergent": min(_bull_raw, _bear_raw) >= 2 and _div_score >= 0.4,
    }

    # Clamp final score to valid range [0, 10]
    if not math.isfinite(result.score):
        result.score = 0.0
    else:
        result.score = max(0.0, min(10.0, result.score))
    if not math.isfinite(result.confidence):
        result.confidence = 0.2
    else:
        result.confidence = max(0.0, min(1.0, result.confidence))

    return result
