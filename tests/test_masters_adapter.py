# -*- coding: utf-8 -*-
"""Task 7 适配层测试：TTM 对拍 / shares-PE 自洽 / coverage 降档 / ETF abstain /
行业回落 / 报告冒烟（tmp data-root，全离线——mootdx 补拉路径 monkeypatch，不真连）。"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "masters"))

import adapter  # noqa: E402
import run_masters  # noqa: E402
from adapter import apply_coverage, build_context, classify_target, industry_for, ttm_financials  # noqa: E402
from augur_core.registry import analyze_all  # noqa: E402


# ---------------------------------------------------------------- fixtures

def _gpcw_row(code: str, report_date: str, **vals) -> dict:
    row = {
        "code": code, "market": "SZ", "report_date": report_date,
        "eps_basic": 0.0, "eps_deducted": 0.0, "bps": 0.0, "roe": 0.0,
        "revenue": 0.0, "net_profit_parent": 0.0, "net_profit_deducted": 0.0,
        "inventory": 0.0, "monetary_funds": 0.0,
        "total_assets": 0.0, "total_liabilities": 0.0,
        "revenue_yoy": 0.0, "net_profit_yoy": 0.0, "deducted_yoy": 0.0,
        "forecast_min": None, "forecast_max": None, "file_hash": "test", "schema_version": 1,
    }
    row.update(vals)
    return row


# 手工构造的 300476 四期（累计口径，单位元）：TTM 期望可用 FY+Q3−Q3上年 逐项手算
_GPCW_300476 = [
    # FY2025：营收 100 亿 / 归母净利 10 亿 / eps 1.0
    _gpcw_row("300476", "2025-12-31", revenue=100e8, net_profit_parent=10e8, eps_basic=1.0,
              bps=20.0, roe=12.0, revenue_yoy=25.0, net_profit_yoy=20.0,
              total_assets=60e8, total_liabilities=30e8),
    # 2025 三季报累计：70 亿 / 7 亿 / 0.7
    _gpcw_row("300476", "2025-09-30", revenue=70e8, net_profit_parent=7e8, eps_basic=0.7,
              bps=19.0, roe=9.0, revenue_yoy=22.0, net_profit_yoy=18.0,
              total_assets=58e8, total_liabilities=29e8),
    # 2026 三季报累计（最新期）：90 亿 / 12 亿 / 1.2
    _gpcw_row("300476", "2026-09-30", revenue=90e8, net_profit_parent=12e8, eps_basic=1.2,
              bps=38.98, roe=8.83, revenue_yoy=30.77, net_profit_yoy=4.28,
              total_assets=71.3e8, total_liabilities=33.0e8),
    _gpcw_row("600276", "2026-09-30", revenue=1.0, net_profit_parent=1.0, eps_basic=1.0),
]


def _write_gpcw(data_root: Path, rows_by_date: dict[str, list[dict]]) -> None:
    fin = data_root / "finance"
    fin.mkdir(parents=True, exist_ok=True)
    for report_date, rows in rows_by_date.items():
        (fin / f"gpcw-{report_date}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _write_series(data_root: Path, ticker_file: str, *, days: int = 210, base_price: float = 10.0) -> None:
    sdir = data_root / "market" / "series"
    sdir.mkdir(parents=True, exist_ok=True)
    start = date(2026, 1, 1)
    rows = []
    for i in range(days):
        close = base_price + i * 0.05  # 温和上行，末日 close = base+ (days-1)*0.05
        rows.append({"date": str(start + timedelta(days=i)), "open": close - 0.1, "high": close + 0.2,
                     "low": close - 0.2, "close": close, "volume": 1000.0 + i,
                     "amount": close * 1000, "source": "test"})
    (sdir / ticker_file).write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def tmp_data_root(tmp_path: Path) -> Path:
    by_date: dict[str, list[dict]] = {}
    for row in _GPCW_300476:
        by_date.setdefault(row["report_date"], []).append(row)
    _write_gpcw(tmp_path / "data", by_date)
    _write_series(tmp_path / "data", "300476.SZ.jsonl")
    return tmp_path / "data"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """补拉路径全 mock——测试永不真连 mootdx。"""
    monkeypatch.setattr(adapter, "_run_finance_update",
                        lambda root, backfill: (_ for _ in ()).throw(
                            AssertionError("测试不应触发网络补拉")))


# ---------------------------------------------------------------- TTM 对拍

def test_ttm_manual_formula(tmp_data_root):
    """TTM(t) = FY(t-1) + 累计(t) − 累计(t同期上年)，逐项手算对拍（最新期 2026Q3）。"""
    ttm = ttm_financials("300476", tmp_data_root, fetch=False)
    assert ttm["revenue"] == pytest.approx((100 + 90 - 70) * 1e8)
    assert ttm["net_profit_parent"] == pytest.approx((10 + 12 - 7) * 1e8)
    assert ttm["eps"] == pytest.approx(1.0 + 1.2 - 0.7)
    assert ttm["window"] == "2025Q4-2026Q3"
    assert ttm["latest_report_date"] == "2026-09-30"


def test_ttm_latest_is_fy(tmp_data_root):
    """最新期即年报：TTM = FY 本身，窗口当年 Q1-Q4。"""
    _write_gpcw(tmp_data_root, {"2026-12-31": [
        _gpcw_row("300476", "2026-12-31", revenue=130e8, net_profit_parent=15e8, eps_basic=1.6)]})
    ttm = ttm_financials("300476", tmp_data_root, fetch=False)
    assert ttm["revenue"] == pytest.approx(130e8)
    assert ttm["net_profit_parent"] == pytest.approx(15e8)
    assert ttm["eps"] == pytest.approx(1.6)
    assert ttm["window"] == "2026Q1-2026Q4"


def test_ttm_missing_period_raises_without_fetch(tmp_data_root):
    """缺依赖期且禁 fetch：raise（缺数据不编造），不静默降级。"""
    (tmp_data_root / "finance" / "gpcw-2025-12-31.jsonl").unlink()
    with pytest.raises(ValueError, match="依赖期缺失"):
        ttm_financials("300476", tmp_data_root, fetch=False)


def test_ttm_backfill_called_when_missing(tmp_data_root, monkeypatch):
    """缺期时走补拉钩子（mock），补拉落盘后重读成功。"""
    (tmp_data_root / "finance" / "gpcw-2025-12-31.jsonl").unlink()
    calls = []

    def fake_backfill(root, backfill):
        calls.append(backfill)
        _write_gpcw(root, {"2025-12-31": [_gpcw_row("300476", "2025-12-31",
                                                    revenue=100e8, net_profit_parent=10e8,
                                                    eps_basic=1.0)]})

    monkeypatch.setattr(adapter, "_run_finance_update", fake_backfill)
    ttm = ttm_financials("300476", tmp_data_root, fetch=True)
    assert calls == [5]
    assert ttm["eps"] == pytest.approx(1.5)


# ---------------------------------------------------------------- build_context

def test_build_context_shares_pe_consistency(tmp_data_root):
    """shares=归母净利/eps 反推 → pe×eps≈price、market_cap=price×shares 自洽。"""
    ctx = build_context("300476.SZ", tmp_data_root, fetch=False)
    meta = ctx.mcp_metrics["masters_adapter"]
    shares = meta["shares"]
    assert shares == pytest.approx(15e8 / 1.5)  # 手工：净利 15 亿 / eps 1.5
    assert ctx.eps == pytest.approx(1.5)
    assert ctx.pe * ctx.eps == pytest.approx(ctx.price, rel=1e-6)
    # 市值口径（USD 十亿，persona 阈值按此调校）：人民币市值/固定汇率/1e9
    assert ctx.market_cap == pytest.approx(ctx.price * shares / adapter.USD_CNY / 1e9)
    # lynch 规模档判定等效断言：手工 USD 市值一致（<10B=小盘加分档）
    manual_usd_bn = ctx.price * shares / 7.2 / 1e9
    assert ctx.market_cap == pytest.approx(manual_usd_bn)
    assert ctx.market_cap < 10  # 204.5 亿 CNY ≈ 2.84B USD → lynch 小盘档
    # 报告展示口径保留人民币亿元
    assert ctx.mcp_metrics["masters_adapter"]["market_cap_cny_yi"] == pytest.approx(
        ctx.price * shares / 1e8)
    assert ctx.debt_ratio == pytest.approx(33.0 / 71.3)
    assert ctx.roe == pytest.approx(0.0883)          # gpcw % 值 → 小数
    assert ctx.revenue_growth == pytest.approx(0.3077)
    assert ctx.profit_margins == pytest.approx(15e8 / 120e8)
    assert ctx.sector == "Technology" and ctx.industry == "电子-PCB"
    assert ctx.field_availability["gross_margins"] == "missing"
    assert ctx.field_availability["pe"] == "replay"
    assert ctx.as_of_date == "2026-07-29"  # 210 天自 2026-01-01


def test_build_context_accepts_bare_code(tmp_data_root):
    ctx = build_context("300476", tmp_data_root, fetch=False)
    assert ctx.ticker == "300476"


# ---------------------------------------------------------------- abstain

@pytest.mark.parametrize("ticker,reason_frag", [
    ("513880.SH", "ETF"),
    ("512000.SH", "ETF"),
    ("^IXIC", "非 A 股个股代码"),
    ("NVDA", "非 A 股个股代码"),
    ("000660.KS", "非 A 股个股代码"),
    ("830001.BJ", "北交所"),
])
def test_abstain_targets(ticker, reason_frag):
    status, _, why = classify_target(ticker)
    assert status == "abstain"
    assert reason_frag in why


def test_etf_run_exits_with_abstain(tmp_path):
    with pytest.raises(SystemExit, match="abstain|ETF"):
        run_masters.run("513880.SH", tmp_path, tmp_path / "out", fetch=False)


# ---------------------------------------------------------------- 行业映射

def test_industry_map_hit_and_fallback():
    assert industry_for("600276", "SH")["industry_key"] == "healthcare"
    assert industry_for("300476", "SZ")["sector_en"] == "Technology"
    fallback = industry_for("999999", "SZ")
    assert fallback == {"industry_key": "china", "sector_en": "China", "industry_cn": ""}
    # 映射键集必须都是 industry_matrix._SECTOR_WEIGHTS 的合法键（防手滑写错）
    from augur_core.consensus.industry_matrix import _SECTOR_WEIGHTS
    for entry in adapter.load_industry_map()["codes"].values():
        assert entry["industry_key"] in set(_SECTOR_WEIGHTS) | {"china"}


# ---------------------------------------------------------------- coverage 后处理

def test_apply_coverage_degrades_duan_yongping(tmp_data_root):
    """缺 debt 型/毛利率型依赖（gross_margins/current_ratio 等）→ duan coverage ×0.6
    且 metadata.degraded_factors 非空；原 coverage 由 persona 按数据自报（本数据面
    fcf=0、gross_margins=0 → 0.4 档）。"""
    ctx = build_context("300476.SZ", tmp_data_root, fetch=False)
    results = analyze_all(ctx)
    duan = results["duan_yongping"]
    before = duan.coverage_confidence
    results = apply_coverage(results, ctx)
    assert duan.coverage_confidence == pytest.approx(before * 0.6)
    degraded = duan.metadata["degraded_factors"]
    factors = {d["factor"] for d in degraded}
    assert "long_term_durability" in factors      # current_ratio 缺失命中的加分型路径
    assert "business_clarity" in factors          # fcf/gross_margins 缺失
    assert any("current_ratio" in d["missing_fields"] for d in degraded)
    # 常驻弃权两位不在 deps 表里，不受影响
    assert "arps" not in adapter.load_persona_deps()


# ---------------------------------------------------------------- 报告冒烟

def test_report_smoke(tmp_path, tmp_data_root, monkeypatch):
    """tmp data-root 全流程：报告落盘、结构齐全、run-log open+close 入账。"""
    out_dir = tmp_path / "output" / "masters"
    report = run_masters.run("300476.SZ", tmp_data_root, out_dir, fetch=False)
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    for fragment in ["免责声明", "常驻弃权", "arps", "serenity", "共识", "half-Kelly",
                     "数据截至", "2025Q4-2026Q3", "missing 清单", "不是指令"]:
        assert fragment in text, fragment
    # 16 位参与：报告应含多位大师标题，且不含常驻弃权两位的评分条目
    assert text.count("### ") == 16
    assert "### ARPS" not in text and "### Serenity" not in text
    # run-log：open + close（kind=masters），close 带报告相对路径
    ledger = tmp_data_root / ".state" / "run-log.jsonl"
    assert ledger.exists()
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    kinds = [(r["type"], r.get("kind")) for r in rows]
    assert ("open", "masters") in kinds
    close_rows = [r for r in rows if r["type"] == "close"]
    assert len(close_rows) == 1
    assert close_rows[0]["report"] == str(report.relative_to(tmp_path))


# ---------------------------------------------------------------- 实施评审 #3 / #2c / #5a

def test_eps_zero_derived_chain_missing_and_coverage(tmp_data_root):
    """#3（上轮 I8 同型）：eps_ttm=0 → shares/market_cap/pe 派生链失效。

    值保持 0 但 field_availability 标 missing；lynch/thiel/cathie_wood 把
    market_cap 用于阈值加分路径（market_cap=0 会被当极小市值加分），
    apply_coverage 必须降权且 degraded_factors 含 market_cap。
    """
    # 覆写四期 eps 全为 0 → TTM eps = 0（FY + Q3 − Q3上年 = 0）
    patched = []
    for row in _GPCW_300476:
        new = dict(row)
        if new["code"] == "300476":
            new["eps_basic"] = 0.0
        patched.append(new)
    by_date: dict[str, list[dict]] = {}
    for row in patched:
        by_date.setdefault(row["report_date"], []).append(row)
    _write_gpcw(tmp_data_root, by_date)

    ctx = build_context("300476.SZ", tmp_data_root, fetch=False)
    assert ctx.eps == 0 and ctx.market_cap == 0 and ctx.pe == 0  # 值保持 0
    for field in ("eps", "shares", "market_cap", "pe"):
        assert ctx.field_availability.get(field) == "missing", field

    results = analyze_all(ctx)
    before = {aid: results[aid].coverage_confidence
              for aid in ("lynch", "thiel", "cathie_wood")}
    results = apply_coverage(results, ctx)
    for aid in ("lynch", "thiel", "cathie_wood"):
        resp = results[aid]
        assert resp.coverage_confidence == pytest.approx(before[aid] * 0.6), aid
        assert any("market_cap" in d["missing_fields"]
                   for d in resp.metadata["degraded_factors"]), aid


def test_run_log_disable_skips_masters_ledger(tmp_path, tmp_data_root, monkeypatch):
    """#5a：RUN_LOG_DISABLE=1 跳过账本（与 persist_market_data 同语义）。"""
    monkeypatch.setenv("RUN_LOG_DISABLE", "1")
    report = run_masters.run("300476.SZ", tmp_data_root, tmp_path / "out", fetch=False)
    assert report.exists()
    assert not (tmp_data_root / ".state" / "run-log.jsonl").exists()


def test_out_root_outside_repo_isolates_ledger(tmp_path, tmp_data_root, monkeypatch,
                                               tmp_path_factory):
    """#2c：--out 根在仓库外而 data-root 在仓库内（冒烟跑形态）→ 账本写 out 根
    下 .state/（与报告同生命周期），不碰 data-root 的 .state/。"""
    monkeypatch.setattr(run_masters, "REPO_ROOT", tmp_path)  # 假仓库根 = tmp_path
    out_dir = tmp_path_factory.mktemp("masters-smoke-outside")  # out 在（假）仓库外
    run_masters.run("300476.SZ", tmp_data_root, out_dir, fetch=False)
    assert (out_dir / ".state" / "run-log.jsonl").exists()
    assert not (tmp_data_root / ".state" / "run-log.jsonl").exists()
    rows = [json.loads(line) for line in
            (out_dir / ".state" / "run-log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["type"] for r in rows] == ["open", "close"]
    assert all(r.get("kind") in (None, "masters") for r in rows)
