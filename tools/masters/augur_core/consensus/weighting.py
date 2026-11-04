# 来源: https://github.com/BruceLanLan/augur (MIT License)
# 锁定 commit: 0c721acc8522d4da57ea38bcd1852a30f23674e9
# 本地改动: 仅摘取 restrict_weights_to_agents（剥离 build_consensus_weights/regime/
#           macro_features/feedback 依赖），并加此头注；函数体逐字节一致。

# -*- coding: utf-8 -*-
"""Restrict industry weight maps to participating agents."""

from typing import Dict, List


def restrict_weights_to_agents(
    weights: Dict[str, float],
    agent_ids: List[str],
) -> Dict[str, float]:
    """Keep weights for participating agents only and renormalize to sum 1."""
    if not agent_ids:
        return {}
    if not weights:
        n = len(agent_ids)
        return {aid: 1.0 / n for aid in agent_ids}
    restricted = {aid: weights[aid] for aid in agent_ids if aid in weights}
    if not restricted:
        n = len(agent_ids)
        return {aid: 1.0 / n for aid in agent_ids}
    total = sum(restricted.values())
    if total <= 0:
        n = len(agent_ids)
        return {aid: 1.0 / n for aid in agent_ids}
    return {aid: v / total for aid, v in restricted.items()}
