# -*- coding: utf-8 -*-
"""Task 8 批量模式测试：17+4 结构 / abstain 行数 / 失败不中断 / 汇总表 run-log。
_analyze_and_report 打桩（不真跑 18 persona×17）；另有 1+1 小样本真跑集成。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "masters"))

import run_masters  # noqa: E402

from test_masters_adapter import _gpcw_row, _write_gpcw, _write_series  # noqa: E402

# 模拟真实 watchlist：17 只 CN 个股 + 4 只 CN ETF + 3 行非 CN（应被排除）
_STOCKS = ["600276.SH", "603087.SH", "600079.SH", "600309.SH", "600989.SH", "600096.SH",
           "600456.SH", "002545.SZ", "301358.SZ", "601899.SH", "603993.SH", "000630.SZ",
           "002415.SZ", "300124.SZ", "300274.SZ", "300476.SZ", "605016.SH"]
_ETFS = ["513880.SH", "513330.SH", "513130.SH", "512000.SH"]
_NON_CN = ["^IXIC", "NVDA", "000660.KS"]

MOCK_WATCHLIST = "# Daily Watchlist\n\n## A 股\n\n| Ticker | Name | Market | Market Cap | Category | Tier | Hypothesis | Notes |\n|---|---|---|---|---|---|---|---|\n" + "".join(
    f"| {t} | 股{i} | CN | Large | 测试 | WARM |  |  |\n" for i, t in enumerate(_STOCKS)
) + "\n## ETF\n\n| Ticker | Name | Market | Market Cap | Category | Tier | Hypothesis | Notes |\n|---|---|---|---|---|---|---|---|\n" + "".join(
    f"| {t} | ETF{i} | CN | ETF | ETF-测试 | WARM |  |  |\n" for i, t in enumerate(_ETFS)
) + "\n## 海外\n\n| Ticker | Name | Market | Market Cap | Category | Tier | Hypothesis | Notes |\n|---|---|---|---|---|---|---|---|\n" + "".join(
    f"| {t} | 海外{i} | INDEX | - | 指数 | WARM |  |  |\n" for i, t in enumerate(_NON_CN)
)


def _fake_summary(code, suffix, *, signal="bullish", kelly=5.0, pair=True):
    return {
        "ticker": f"{code}.{suffix}", "score": 6.5, "signal": signal,
        "participants": 16, "abstains": 2, "kelly_pct": kelly,
        "divergence": {"score": 0.5, "bullish_count": 9, "bearish_count": 5,
                       "neutral_count": 2, "total_valid": 16, "is_divergent": True},
        "top_pair": {"bull": "Lynch", "bull_factor": "growth", "bear": "Graham",
                     "bear_factor": "valuation"} if pair else None,
    }


@pytest.fixture
def mock_watchlist(tmp_path: Path) -> Path:
    p = tmp_path / "watchlist.md"
    p.write_text(MOCK_WATCHLIST, encoding="utf-8")
    return p


def test_parse_watchlist_filters_cn(mock_watchlist):
    rows = run_masters.parse_watchlist(mock_watchlist)
    assert [r["ticker"] for r in rows] == _STOCKS + _ETFS
    assert all(r["market"] == "CN" for r in rows)
    assert rows[0]["name"] == "股0"


def test_batch_structure_17_plus_4(tmp_path, mock_watchlist, monkeypatch):
    """17 个股 + 4 ETF abstain；000630 失败不中断记 error 行；汇总表 run-log open/close。"""
    calls = []

    def fake_analyze(code, suffix, data_root, out_dir, *, fetch=True):
        calls.append(code)
        if code == "000630":  # 单票失败：批量必须继续
            raise ValueError("依赖期缺失：gpcw-2025-12-31.jsonl")
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"{code}.{suffix}.md", _fake_summary(
            code, suffix, pair=(code != "600276"))

    monkeypatch.setattr(run_masters, "_analyze_and_report", fake_analyze)
    data_root, out_dir = tmp_path / "data", tmp_path / "output" / "masters"
    summary = run_masters.run_watchlist(data_root, out_dir, fetch=False,
                                        watchlist_path=mock_watchlist, today="2026-11-04")
    assert len(calls) == 17  # 只有个股真跑，ETF 不进分析
    assert summary == out_dir / "2026-11" / "watchlist-2026-11-04.md"
    text = summary.read_text(encoding="utf-8")

    # 21 行数据行：17 ok + 4 abstain + 1 error（000630 失败转 error 行）
    body = [ln for ln in text.splitlines() if ln.startswith("| ") and "Ticker" not in ln]
    assert len(body) == 21
    assert sum("| abstain | 0 | 18 |" in ln for ln in body) == 4
    assert sum("| ERR | error |" in ln for ln in body) == 1
    assert "失败：ValueError: 依赖期缺失" in text
    # 表头/免责/已知口径
    for frag in ["| Ticker | 名称 | score | signal | 参与大师数 | 弃权数 | half-Kelly | 关键分歧 |",
                 "免责声明", "YTD 未年化", "已降权", "USD/CNY=7.2"]:
        assert frag in text, frag
    # 分歧 → 研究问题：有 pair 的个股各一条（17 − 1 error − 1 无分歧 = 15）+ 不自动写队列指引
    assert text.count("候选研究问题") == 15
    assert "workspace/review-queue.md" in text and "不自动写队列" in text

    # 汇总表自身入账：open + close(kind=masters)，close 指向汇总表
    rows = [json.loads(ln) for ln in
            (data_root / ".state" / "run-log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ("open", "masters") in [(r["type"], r.get("kind")) for r in rows]
    closes = [r for r in rows if r["type"] == "close"]
    assert len(closes) == 1
    assert closes[0]["report"].endswith("watchlist-2026-11-04.md")


def test_batch_small_sample_real_run(tmp_path):
    """小样本真跑集成：1 个股（mock 数据面）+ 1 ETF abstain，验证 _analyze_and_report 接线。"""
    data_root = tmp_path / "data"
    _write_gpcw(data_root, {r["report_date"]: [r] for r in [
        _gpcw_row("300476", "2025-12-31", revenue=100e8, net_profit_parent=10e8, eps_basic=1.0,
                  bps=20.0, roe=12.0, revenue_yoy=25.0, net_profit_yoy=20.0,
                  total_assets=60e8, total_liabilities=30e8),
        _gpcw_row("300476", "2025-09-30", revenue=70e8, net_profit_parent=7e8, eps_basic=0.7),
        _gpcw_row("300476", "2026-09-30", revenue=90e8, net_profit_parent=12e8, eps_basic=1.2,
                  bps=38.98, roe=8.83, revenue_yoy=30.77),
    ]})
    _write_series(data_root, "300476.SZ.jsonl")
    wl = tmp_path / "wl.md"
    wl.write_text(
        "# w\n\n| Ticker | Name | Market | Market Cap | Category | Tier | Hypothesis | Notes |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 300476.SZ | 胜宏科技 | CN | Large | PCB | WARM |  |  |\n"
        "| 513880.SH | 日经225ETF | CN | ETF | ETF-QDII | WARM |  |  |\n", encoding="utf-8")

    out_dir = tmp_path / "output" / "masters"
    summary = run_masters.run_watchlist(data_root, out_dir, fetch=False,
                                        watchlist_path=wl, today="2026-11-04")
    text = summary.read_text(encoding="utf-8")
    body = [ln for ln in text.splitlines() if ln.startswith("| 3") or ln.startswith("| 5")]
    assert len(body) == 2
    stock_row = next(ln for ln in body if "300476" in ln)
    assert "| 16 | 2 |" in stock_row  # 16 参与 + 2 常驻弃权
    assert "abstain" in next(ln for ln in body if "513880" in ln)
    # 个股单票报告确实落盘（series 末日 = 2026-01-01 + 209 天 = 2026-07-29）
    assert (out_dir / "2026-07" / "300476.SZ-2026-07-29.md").exists()


def test_cli_watchlist_flag_requires_no_ticker():
    with pytest.raises(SystemExit):
        run_masters.main(["300476.SZ", "--watchlist"])
    with pytest.raises(SystemExit):
        run_masters.main([])
