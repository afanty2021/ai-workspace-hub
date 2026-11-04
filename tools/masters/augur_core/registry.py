# 来源: https://github.com/BruceLanLan/augur (MIT License)
# 锁定 commit: 0c721acc8522d4da57ea38bcd1852a30f23674e9
# 本地改动: 新写文件——18 个 persona 实例化清单 + analyze_all；persona 类本身逐字节来自原仓。

# -*- coding: utf-8 -*-
"""augur_core registry — instantiate the 18 vendored personas and run them all."""

from augur_core.personas.arps import ArpsAgent
from augur_core.personas.aschenbrenner import AschenbrennerAgent
from augur_core.personas.base import MarketContext
from augur_core.personas.buffett import BuffettAgent
from augur_core.personas.cathie_wood import CathieWoodAgent
from augur_core.personas.dalio import DalioAgent
from augur_core.personas.dan_bin import DanBinAgent
from augur_core.personas.dayu import DayuAgent
from augur_core.personas.duan_yongping import DuanYongpingAgent
from augur_core.personas.fisher import FisherAgent
from augur_core.personas.graham import GrahamAgent
from augur_core.personas.li_lu import LiLuAgent
from augur_core.personas.lynch import LynchAgent
from augur_core.personas.marks import MarksAgent
from augur_core.personas.munger import MungerAgent
from augur_core.personas.serenity import SerenityAgent
from augur_core.personas.soros import SorosAgent
from augur_core.personas.thiel import ThielAgent
from augur_core.personas.zhang_lei import ZhangLeiAgent

_PERSONA_CLASSES = [
    BuffettAgent, GrahamAgent, LynchAgent, DalioAgent, MungerAgent, SorosAgent,
    MarksAgent, CathieWoodAgent, FisherAgent, ArpsAgent, AschenbrennerAgent,
    DayuAgent, ThielAgent, DuanYongpingAgent, ZhangLeiAgent, LiLuAgent,
    DanBinAgent, SerenityAgent,
]

_instances = [cls() for cls in _PERSONA_CLASSES]
AGENTS = {a.agent_id: a for a in _instances}


def analyze_all(context: MarketContext) -> dict:
    """Run every persona on the same MarketContext; agent_id -> AgentResponse."""
    return {agent.agent_id: agent.analyze(context) for agent in AGENTS.values()}
