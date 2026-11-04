# -*- coding: utf-8 -*-
"""Task 6 对拍测试：vendored augur_core vs 原仓 /Users/berton/Github/Invest/augur。

- persona 对拍：importlib 从原仓直接加载 persona 源文件（stub augur.personas.base =
  vendored base，规避原版 _merge_saved_thresholds 的 feedback 钩子），同一
  MarketContext 下逐字段断言与 vendored 版一致。
- consensus：固定 response 集合，手工计算加权分/置信度/half-Kelly，断言 1% 保底与
  20% 上限分支。
- 原仓不存在时对拍部分整体 skip（CI 环境不失败）；consensus 部分始终运行。
"""

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUGUR_REPO = Path("/Users/berton/Github/Invest/augur")
AUGUR_PERSONAS = AUGUR_REPO / "src" / "augur" / "personas"
# 对拍锁（实施评审 I-A）：vendored 引擎声明对齐上游 0c721ac；对拍读的是上游**工作树**，
# 一旦 pull/checkout 移动 HEAD，对拍锁即失效——这里 fail（不是 skip），强制要么把上游
# checkout 回 0c721ac，要么 re-vendor 并同步更新全部 vendored 文件头注锁与本断言。
AUGUR_LOCKED_SHA = "0c721ac"

sys.path.insert(0, str(REPO_ROOT / "tools" / "masters"))

import augur_core.personas.base as vendored_base  # noqa: E402
from augur_core.consensus.engine import compute_consensus  # noqa: E402
from augur_core.personas.base import (  # noqa: E402
    AgentResponse,
    MarketContext,
    SignalType,
)

PERSONA_CLASSES = {
    "arps": "ArpsAgent",
    "aschenbrenner": "AschenbrennerAgent",
    "buffett": "BuffettAgent",
    "cathie_wood": "CathieWoodAgent",
    "dalio": "DalioAgent",
    "dan_bin": "DanBinAgent",
    "dayu": "DayuAgent",
    "duan_yongping": "DuanYongpingAgent",
    "fisher": "FisherAgent",
    "graham": "GrahamAgent",
    "li_lu": "LiLuAgent",
    "lynch": "LynchAgent",
    "marks": "MarksAgent",
    "munger": "MungerAgent",
    "serenity": "SerenityAgent",
    "soros": "SorosAgent",
    "thiel": "ThielAgent",
    "zhang_lei": "ZhangLeiAgent",
}

pytestmark_orig = pytest.mark.skipif(
    not AUGUR_PERSONAS.is_dir(), reason=f"augur 原仓不存在: {AUGUR_REPO}"
)


# ---------------------------------------------------------------- contexts

def _rich_context() -> MarketContext:
    return MarketContext(
        ticker="AAPL",
        company_name="Apple Inc.",
        price=200.0,
        change_pct=1.2,
        market_cap=3000.0,
        pe=25.0,
        forward_pe=22.0,
        peg_ratio=1.4,
        pb=38.0,
        ps=7.5,
        fcf=100.0,
        revenue=390.0,
        revenue_growth=0.08,
        earnings_growth=0.15,
        gross_margins=0.46,
        operating_margins=0.30,
        profit_margins=0.26,
        roe=1.5,
        roa=0.28,
        debt_ratio=0.35,
        current_ratio=0.9,
        quick_ratio=0.85,
        price_vs_52w_high=0.95,
        price_vs_52w_low=1.8,
        sector="Technology",
        industry="Consumer Electronics, Semiconductor",
        business_summary="Designs smartphones and personal computers.",
        dividend_yield=0.005,
        rsi=58.0,
        sma50=190.0,
        sma200=175.0,
        volatility_20d=0.18,
        sharpe_ratio=1.2,
        max_drawdown=-0.25,
    )


def _sparse_context() -> MarketContext:
    return MarketContext(ticker="000000.SS")


def _china_context() -> MarketContext:
    return MarketContext(
        ticker="600519.SS",
        price=1700.0,
        market_cap=2100.0,
        pe=25.0,
        pb=8.0,
        revenue=150.0,
        revenue_growth=0.15,
        earnings_growth=0.18,
        gross_margins=0.91,
        roe=0.32,
        debt_ratio=0.2,
        sector="中国",
        industry="白酒",
    )


def _pe_zero_context() -> MarketContext:
    # pe=0 = 适配层 eps 缺失占位（availability missing），非真亏损——dayu 声明式
    # 补丁后不得按"未盈利=早期机会"加分
    return MarketContext(ticker="300999.SZ", pe=0.0, ps=8.0, revenue_growth=0.3)


def _pe_negative_context() -> MarketContext:
    # 真亏损（pe<0）：保留上游"未盈利=早期机会"语义，dayu 两处仍加分
    return MarketContext(ticker="300998.SZ", pe=-12.0, ps=8.0, revenue_growth=0.3)


CONTEXTS = {"rich_tech": _rich_context, "sparse": _sparse_context, "china": _china_context,
            "pe_zero": _pe_zero_context, "pe_negative": _pe_negative_context}


# ---------------------------------------------------------------- helpers

def _load_original_persona(name: str, monkeypatch):
    """从原仓源文件直接加载 persona 模块，stub augur.personas.base = vendored base。

    dayu 例外：vendored 有声明式 pe 补丁（DAYU_PE_PATCH，见 dayu.py 头注②——
    pe 未知占位 0 不加分，仅真亏损保留上游语义），对拍前对上游源做同一字符串
    替换，其余 persona 逐字节直载。
    """
    stub_a = types.ModuleType("augur")
    stub_p = types.ModuleType("augur.personas")
    stub_a.personas = stub_p
    monkeypatch.setitem(sys.modules, "augur", stub_a)
    monkeypatch.setitem(sys.modules, "augur.personas", stub_p)
    monkeypatch.setitem(sys.modules, "augur.personas.base", vendored_base)

    path = AUGUR_PERSONAS / f"{name}.py"
    source = path.read_text(encoding="utf-8")
    if name == "dayu":
        source = source.replace(*DAYU_PE_PATCH)
    spec = importlib.util.spec_from_file_location(f"augur_orig_personas_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    code = compile(source, str(path), "exec")
    exec(code, mod.__dict__)  # noqa: S102 - 对拍加载原仓源（含声明式替换）
    return mod


# dayu 声明式补丁（与 vendored dayu.py 的本地改动②严格同串）：上游把 pe=0（适配层
# eps 缺失占位）与真亏损都加分，本地仅保留 pe<0 分支。锁测试对上游应用同一替换。
DAYU_PE_PATCH = ("pe == 0 or pe < 0", "pe < 0")


def _load_vendored_persona(name: str):
    return importlib.import_module(f"augur_core.personas.{name}")


def _make_response(agent_id: str, name: str, signal: SignalType, score: float, conf: float):
    return AgentResponse(
        agent_id=agent_id,
        agent_name=name,
        signal=signal,
        confidence=conf,
        score=score,
        reasoning="test",
        coverage_confidence=1.0,
    )


# ---------------------------------------------------------------- 对拍锁：上游 HEAD 必须停在 0c721ac

@pytest.mark.skipif(not AUGUR_REPO.is_dir(), reason="augur 原仓不存在")
def test_augur_upstream_locked_at_parity_sha():
    """对拍读的是上游工作树——上游一 pull 对拍锁即失效，故先断言 HEAD == 0c721ac。

    fail（不是 skip）：要么 `git -C /Users/berton/Github/Invest/augur checkout 0c721ac`，
    要么 re-vendor 并同步更新全部 vendored 头注锁 + 本处 AUGUR_LOCKED_SHA。
    """
    proc = subprocess.run(
        ["git", "-C", str(AUGUR_REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert proc.returncode == 0, f"rev-parse 失败: {proc.stderr.strip()}"
    head = proc.stdout.strip()
    assert head == AUGUR_LOCKED_SHA, (
        f"上游已移动：HEAD={head}，对拍锁声明的基线是 {AUGUR_LOCKED_SHA}。"
        "要么 checkout 0c721ac，要么 re-vendor 并更新全部头注锁与 AUGUR_LOCKED_SHA。"
    )


# ---------------------------------------------------------------- 对拍：18 personas × 3 contexts

@pytest.mark.skipif(not AUGUR_PERSONAS.is_dir(), reason="augur 原仓不存在")
@pytest.mark.parametrize("ctx_name", list(CONTEXTS))
@pytest.mark.parametrize("persona", sorted(PERSONA_CLASSES))
def test_persona_parity_with_original(persona, ctx_name, monkeypatch):
    orig_mod = _load_original_persona(persona, monkeypatch)
    vend_mod = _load_vendored_persona(persona)
    cls_name = PERSONA_CLASSES[persona]

    orig_agent = getattr(orig_mod, cls_name)()
    vend_agent = getattr(vend_mod, cls_name)()

    ctx = CONTEXTS[ctx_name]()
    orig_resp = orig_agent.analyze(ctx)
    vend_resp = vend_agent.analyze(ctx)

    assert vend_resp.signal == orig_resp.signal
    assert vend_resp.score == orig_resp.score
    assert vend_resp.confidence == orig_resp.confidence
    assert vend_resp.coverage_confidence == orig_resp.coverage_confidence
    assert vend_resp.key_findings == orig_resp.key_findings
    assert vend_resp.risks == orig_resp.risks
    assert vend_resp.metadata == orig_resp.metadata


@pytest.mark.skipif(not AUGUR_PERSONAS.is_dir(), reason="augur 原仓不存在")
def test_base_delta_is_hook_removal_only(monkeypatch):
    """vendored BaseAgent 与原版仅差 _merge_saved_thresholds 钩子。"""
    spec = importlib.util.spec_from_file_location(
        "augur_orig_base", AUGUR_PERSONAS / "base.py"
    )
    orig_base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orig_base)

    assert not hasattr(vendored_base.BaseAgent, "_merge_saved_thresholds")
    assert hasattr(orig_base.BaseAgent, "_merge_saved_thresholds")

    orig_attrs = {a for a in dir(orig_base.BaseAgent) if not a.startswith("__")}
    vend_attrs = {a for a in dir(vendored_base.BaseAgent) if not a.startswith("__")}
    assert vend_attrs == orig_attrs - {"_merge_saved_thresholds"}

    # thresholds 不再被 feedback 覆盖：构造后保持传入值
    agent = vendored_base.BaseAgent(
        agent_id="t", name="t", identity="t", philosophy=["价值"],
        scoring_weights={"a": 1.0}, thresholds={"bullish_threshold": 6.0},
    )
    assert agent.thresholds == {"bullish_threshold": 6.0}


# ---------------------------------------------------------------- dayu 声明式 pe 补丁

def test_dayu_pe_zero_no_bonus_pe_negative_keeps_upstream():
    """pe=0（未知占位）不加分、pe<0（真亏损）保留上游加分——两处条件各验一遍。"""
    from augur_core.personas.dayu import DayuAgent

    agent = DayuAgent()
    base = MarketContext(ticker="X", pe=20.0, ps=8.0, revenue_growth=0.3)
    pe0 = MarketContext(ticker="X", pe=0.0, ps=8.0, revenue_growth=0.3)
    peneg = MarketContext(ticker="X", pe=-12.0, ps=8.0, revenue_growth=0.3)

    # 信息优势因子：pe=0 与正常 pe 同分；pe<0 比基准多 1
    assert agent._score_information_edge(pe0, "technology") == \
        agent._score_information_edge(base, "technology")
    assert agent._score_information_edge(peneg, "technology") == \
        agent._score_information_edge(base, "technology") + 1

    # 叙事时机因子（ps>5 才触发）：同上
    assert agent._score_narrative_timing(pe0, "technology", "") == \
        agent._score_narrative_timing(base, "technology", "")
    assert agent._score_narrative_timing(peneg, "technology", "") == \
        agent._score_narrative_timing(base, "technology", "") + 1


@pytest.mark.skipif(not AUGUR_PERSONAS.is_dir(), reason="augur 原仓不存在")
def test_dayu_vendored_source_has_declared_patch_only(monkeypatch):
    """vendored dayu 源与「上游源 + 声明式替换」逐字节一致（除头注本地改动声明行）。"""
    vendored_path = REPO_ROOT / "tools" / "masters" / "augur_core" / "personas" / "dayu.py"
    vendored = vendored_path.read_text(encoding="utf-8")
    vendored_body = vendored.split('"""\n', 1)[1]  # 头注（含改动声明）不参与比对
    # 本地声明式改动落位：上游条件串已不存在，且恰被替换为 pe < 0
    assert DAYU_PE_PATCH[0] not in vendored_body
    assert vendored_body.count("if pe < 0:") == 1
    assert vendored_body.count("if (pe < 0) and ps > 5:") == 1
    # 对拍上游（工作树，锁 0c721ac）：应用同一替换后，正文（头注之后）逐字节一致
    upstream = (AUGUR_PERSONAS / "dayu.py").read_text(encoding="utf-8")
    patched = upstream.replace("from augur.personas.base import", "from augur_core.personas.base import") \
                      .replace(*DAYU_PE_PATCH)
    patched_body = patched.split('"""\n', 1)[1] if '"""\n' in patched else patched
    assert vendored_body == patched_body


# ---------------------------------------------------------------- consensus 手工对拍

def test_consensus_hand_computed_china_weights():
    """china 行业权重 + 3 个 response 的加权分/置信度/Kelly 与手工计算一致。

    china 表: duan_yongping 1.45, zhang_lei 1.35, li_lu 1.3 (dan_bin 1.22,
    dayu 1.18, munger 1.05 不参与)。restrict 后归一基数 = 4.10。
    """
    results = {
        "duan_yongping": _make_response("duan_yongping", "Duan", SignalType.BULLISH, 8.0, 0.7),
        "zhang_lei": _make_response("zhang_lei", "Zhang", SignalType.BULLISH, 7.0, 0.6),
        "li_lu": _make_response("li_lu", "Li", SignalType.NEUTRAL, 5.0, 0.5),
    }
    out = compute_consensus(results, ticker="600519.SS", industry_key="china")

    base = {"duan_yongping": 1.45, "zhang_lei": 1.35, "li_lu": 1.3}
    total = sum(base.values())  # 4.10
    exp_score = (8.0 * 1.45 + 7.0 * 1.35 + 5.0 * 1.3) / total
    exp_conf_raw = (0.7 * 1.45 + 0.6 * 1.35 + 0.5 * 1.3) / total
    extremity = abs(exp_score - 5.0) / 5.0
    exp_conf = min(0.95, max(0.05, exp_conf_raw * (0.85 + 0.15 * extremity)))

    assert out.signal == SignalType.BULLISH  # bullish 2.80 vs neutral 1.30
    assert out.score == pytest.approx(exp_score, abs=1e-9)
    assert out.confidence == pytest.approx(exp_conf, abs=1e-9)

    # half-Kelly: edge=(score-5)/5, pct=round(edge*conf*0.5*100,1)
    edge = (exp_score - 5.0) / 5.0
    exp_pct = min(20.0, round(edge * exp_conf * 0.5 * 100, 1))
    assert exp_pct > 1.0  # 本例不触发保底
    assert out.metadata["position_pct"] == pytest.approx(exp_pct)
    assert out.metadata["position_sizing"]["position_pct"] == pytest.approx(exp_pct)

    # divergence：2 bullish / 0 bearish → score 0, 非分歧
    assert out.metadata["divergence"] == {
        "score": 0.0, "bullish_count": 2, "bearish_count": 0,
        "neutral_count": 1, "total_valid": 3, "is_divergent": False,
    }
    assert "low_participation" not in out.metadata


def test_consensus_kelly_one_pct_floor():
    """bullish 且分数贴线：edge*conf*50 < 1 但 conf>=0.5 → 保底 1%。"""
    results = {
        "duan_yongping": _make_response("dp", "D", SignalType.BULLISH, 5.05, 0.75),
    }
    out = compute_consensus(results, ticker="X", industry_key="china")
    assert out.signal == SignalType.BULLISH
    # 手工: conf_raw=0.75, extremity=0.01 → cal=0.75*0.8515=0.638625 (>=0.5)
    # edge=0.01 → raw pct=round(0.3193,1)=0.3 <1 → 保底 1.0
    assert out.confidence == pytest.approx(0.638625, abs=1e-9)
    assert out.metadata["position_pct"] == 1.0
    assert out.metadata["low_participation"] is True


def test_consensus_kelly_twenty_pct_cap():
    """极端 bullish：edge=1, conf=0.95 → 47.5% 截断到 20%。"""
    results = {
        "duan_yongping": _make_response("dp", "D", SignalType.BULLISH, 10.0, 0.95),
        "zhang_lei": _make_response("zl", "Z", SignalType.BULLISH, 10.0, 0.95),
        "li_lu": _make_response("ll", "L", SignalType.BULLISH, 10.0, 0.95),
    }
    out = compute_consensus(results, ticker="X", industry_key="china")
    assert out.signal == SignalType.BULLISH
    assert out.score == pytest.approx(10.0)
    assert out.confidence == pytest.approx(0.95)
    assert out.metadata["position_pct"] == 20.0
    # 全员看多 → 追加过度乐观风险提示
    assert any("overvaluation" in r for r in out.risks)


def test_consensus_bearish_zero_and_neutral_scaled():
    """bearish → 0 仓位；neutral → (conf-0.5)*3。"""
    bearish = {
        "duan_yongping": _make_response("dp", "D", SignalType.BEARISH, 2.0, 0.8),
        "zhang_lei": _make_response("zl", "Z", SignalType.BEARISH, 3.0, 0.8),
        "li_lu": _make_response("ll", "L", SignalType.BEARISH, 2.5, 0.8),
    }
    out = compute_consensus(bearish, industry_key="general")
    assert out.signal == SignalType.BEARISH
    assert out.metadata["position_pct"] == 0.0

    neutral = {
        "duan_yongping": _make_response("dp", "D", SignalType.NEUTRAL, 5.0, 0.7),
        "zhang_lei": _make_response("zl", "Z", SignalType.NEUTRAL, 5.0, 0.7),
        "li_lu": _make_response("ll", "L", SignalType.NEUTRAL, 5.0, 0.7),
    }
    out = compute_consensus(neutral, industry_key="general")
    assert out.signal == SignalType.NEUTRAL
    # conf_raw=0.7, extremity=0 → cal=0.7*0.85=0.595 → pct=round(0.095*3? no:
    # (0.595-0.5)*3 = 0.285 → round=0.3
    assert out.confidence == pytest.approx(0.595, abs=1e-9)
    assert out.metadata["position_pct"] == 0.3


def test_consensus_empty_and_tie_to_neutral():
    empty = compute_consensus({})
    assert empty.signal == SignalType.NEUTRAL
    assert empty.score == 0

    tie = {
        "duan_yongping": _make_response("dp", "D", SignalType.BULLISH, 8.0, 0.6),
        "zhang_lei": _make_response("zl", "Z", SignalType.BEARISH, 3.0, 0.6),
        "li_lu": _make_response("ll", "L", SignalType.NEUTRAL, 5.0, 0.6),
        "dan_bin": _make_response("db", "B", SignalType.NEUTRAL, 5.0, 0.6),
    }
    out = compute_consensus(tie, industry_key="china")
    # bullish 1.45 vs bearish 1.35 vs neutral 2.52 → neutral 胜出
    assert out.signal == SignalType.NEUTRAL


def test_registry_analyze_all():
    from augur_core.registry import AGENTS, analyze_all

    assert len(AGENTS) == 18
    for ctx_factory in CONTEXTS.values():
        results = analyze_all(ctx_factory())
        assert set(results) == set(AGENTS)
        for resp in results.values():
            assert isinstance(resp, AgentResponse)
            assert resp.signal in (
                SignalType.BULLISH, SignalType.NEUTRAL, SignalType.BEARISH, SignalType.ERROR,
            )
