# -*- coding: utf-8 -*-
"""A 股数据适配层（spec §5.3）：gpcw + series → augur_core MarketContext。

三件事：
1. TTM 合成（`ttm_financials`）：本地 `data/finance/gpcw-*.jsonl` 按报告期取数，
   不足时经 mootdx 补拉（复用 `tools/daily-watch/scripts/update_finance_snapshots.py`
   的 run_finance_update，落盘规范一致）；公式见函数注释。
2. `build_context`：series 技术面 + gpcw 直值 + TTM 推导值填 MarketContext，
   field_availability 逐字段标注，缺省字段显式标 missing。
3. `apply_coverage`：按 persona_deps.json 把「因子依赖字段缺失」翻译成
   coverage_confidence ×0.6 + degraded_factors（persona 不读 field_availability，
   缺失可见性只能靠这层后处理，spec §5.3 I8）。

行业路由（I9）：不走 detect_industry（.SZ/.SH 后缀会被 classify 短路进 "china"），
industry_map.json 直填 industry_matrix 的行业键 + 英文 sector 关键词。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from augur_core.personas.base import AgentResponse, MarketContext

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTERS_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = REPO_ROOT / "data"

# A 股常驻弃权（spec §5.5）：ARPS=加密/黄金专属，Serenity=美股小票画像
PERMANENT_ABSTAIN = {
    "arps": "常驻弃权（A 股不适配：加密/黄金专属框架）",
    "serenity": "常驻弃权（A 股不适配：美股小票 Twitter 交易者画像）",
}

# 适配层数据面（gpcw+series）拿不到、persona 打分会踩的字段——field_availability
# 一律标 "missing"（vendored 缺省：数值字段 0、ownership 字段 None）
ADAPTER_MISSING_FIELDS = (
    "gross_margins", "operating_margins", "fcf",
    "current_ratio", "quick_ratio",
    "institutional_ownership", "insider_ownership",
    "short_interest", "volatility_20d", "volatility_60d", "volatility_252d",
    "max_drawdown", "beta_1y", "rsi", "macd", "macd_signal", "macd_histogram",
    "atr", "stoch_k", "stoch_d", "dividend_yield", "payout_ratio",
)

# 固定汇率近似（USD/CNY）：MarketContext 的市值类字段（market_cap/ebitda/total_cash/
# total_debt）口径是 **USD 十亿**，persona 阈值（lynch 小盘<10/大盘>100 等）按此调校——
# 填人民币亿元会系统性错位规模档判定。适配层统一换算成 USD 十亿；报告侧换回人民币展示。
# fcf 同口径（它进 fcf_yield 分母），本层数据面 fcf 缺省 0，恒等式下无需处理。
USD_CNY = 7.2

_ETF_PREFIXES = ("51", "56", "58")     # 沪市 ETF 代码段（513880/512000 等）
_ETF_PREFIXES_SZ = ("15", "16", "18")  # 深市 ETF 代码段（watchlist 暂无，防御性收录）
_A_SHARE_BOARD_FIRST = {"0": "SZ", "3": "SZ", "6": "SH"}  # 主板/创业板/科创板；北交所(4/8/9)未接入


# ---------------------------------------------------------------------------
# 代码归一与 abstain 判定（spec §5.5）
# ---------------------------------------------------------------------------

def classify_target(ticker: str) -> tuple[str, str, str]:
    """归一标的 → (status, code, suffix_or_reason)。status ∈ {"stock", "abstain"}。

    abstain 条件（spec §5.5 边界）：ETF 代码段 / ^ 指数前缀 / 非 6 位纯数字
    （美股/韩股/商品）/ 北交所（数据面未接入）。stock 时第三位是交易所后缀。
    """
    raw = (ticker or "").strip()
    if not raw:
        return "abstain", "", "空代码"
    upper = raw.upper()
    if upper.startswith("^") or not re.fullmatch(r"\d{6}(\.(SZ|SH|BJ))?", upper):
        return "abstain", raw, "非 A 股个股代码（指数/美股/韩股/商品等，数据面不支持）"
    code = upper.split(".")[0]
    suffix = upper.split(".")[1] if "." in upper else _A_SHARE_BOARD_FIRST.get(code[0], "")
    if code[:2] in _ETF_PREFIXES or code[:2] in _ETF_PREFIXES_SZ:
        return "abstain", code, "ETF（不是公司标的，无 gpcw 财务面）"
    if code[0] not in _A_SHARE_BOARD_FIRST:
        return "abstain", code, "北交所/非常规代码段（数据面未接入）"
    return "stock", code, suffix


def _find_series_path(data_root: Path, code: str, suffix: str) -> Path | None:
    if suffix:
        p = data_root / "market" / "series" / f"{code}.{suffix}.jsonl"
        if p.exists():
            return p
    for guess in ("SH", "SZ"):
        p = data_root / "market" / "series" / f"{code}.{guess}.jsonl"
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# 行业映射（I9：直填 industry_matrix 键，不走 detect_industry）
# ---------------------------------------------------------------------------

_FALLBACK_INDUSTRY = {"industry_key": "china", "sector_en": "China", "industry_cn": ""}


def load_industry_map() -> dict:
    return json.loads((MASTERS_DIR / "industry_map.json").read_text(encoding="utf-8"))


def industry_for(code: str, suffix: str = "", industry_map: dict | None = None) -> dict:
    """A 股代码 → {industry_key, sector_en, industry_cn}；缺失回落 china/China。"""
    mapping = industry_map or load_industry_map()
    for key in (f"{code}.{suffix}" if suffix else code, code):
        hit = mapping.get("codes", {}).get(key)
        if hit:
            return dict(hit)
    return dict(_FALLBACK_INDUSTRY)


# ---------------------------------------------------------------------------
# gpcw 读取与 mootdx 补拉
# ---------------------------------------------------------------------------

def load_gpcw_periods(data_root: Path, code: str) -> dict[str, dict]:
    """扫 data/finance/gpcw-*.jsonl → {report_date: row}（单文件单报告期）。"""
    periods: dict[str, dict] = {}
    finance_dir = Path(data_root) / "finance"
    if not finance_dir.is_dir():
        return periods
    for path in sorted(finance_dir.glob("gpcw-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or f'"{code}"' not in line:
                continue
            row = json.loads(line)
            if row.get("code") == code:
                periods[str(row["report_date"])] = row
    return periods


def _run_finance_update(data_root: Path, backfill: int) -> None:
    """mootdx 补拉钩子（复用 update_finance_snapshots.run_finance_update，其落盘即规范）。

    独立成模块级函数：测试 monkeypatch 这里即可离线测补拉路径，不真连通达信。
    """
    script_dir = str(REPO_ROOT / "tools" / "daily-watch" / "scripts")
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from update_finance_snapshots import run_finance_update  # noqa: PLC0415

    run_finance_update(Path(data_root), backfill=backfill)


def _quarter_of(report_date: str) -> int:
    return {"03-31": 1, "06-30": 2, "09-30": 3, "12-31": 4}[report_date[5:]]


def ttm_financials(code: str, data_root: Path | str | None = None, *, fetch: bool = True) -> dict:
    """TTM 合成：TTM(t) = FY(t-1) + 累计(t) − 累计(t同期上年)。

    复核链（A 股披露节奏假设，gpcw 的 report_date 只有期末）：
    - 常规披露假设：一季报 4 月底 / 半年报 8 月底 / 三季报 10 月底 / 年报次年 4 月底；
      期号按 report_date 的月末判定（03-31=Q1、06-30=H1、09-30=Q3、12-31=FY），
      gpcw 各期均为年初至期末的累计口径（update_finance_snapshots 列映射注释）。
    - 最新期 t 是 FY 时：TTM = FY 本身（窗口 = 当年 Q1-Q4）。
    - 否则需要三个报告期：FY(t-1)（12-31）、t（期末）、t 同期上年；任缺其一 → 补拉后重读，
      仍缺则 raise（缺数据不编造，spec §5.5）。
    - eps TTM 用同一公式对 eps_basic 滚动（每股口径下累计值可直接加减）。

    返回：{revenue, net_profit_parent, eps, window, latest_report_date, latest_row}，
    金额单位元、eps 单位元；window 如 "2025Q4-2026Q3"。
    """
    data_root = Path(data_root) if data_root else DEFAULT_DATA_ROOT
    periods = load_gpcw_periods(data_root, code)

    def _reload_after_fetch() -> dict[str, dict]:
        nonlocal periods
        if fetch:
            # 文件按最新在前取 N 期。最新期非 FY 时依赖期是「最新期 / 上年年报 / 上年同期」，
            # 年报在上年文件序列里排第 4、同期排第 5（中间隔着当年两个 interim）——实测
            # 300476（最新 2026Q3）：backfill=4 只到 2025-12-31，2025-09-30 是第 5 新。
            # FY 时只需最新 1 期。取 5 覆盖全部节奏。
            _run_finance_update(data_root, backfill=5)
            periods = load_gpcw_periods(data_root, code)
        return periods

    if not periods:
        _reload_after_fetch()
        if not periods:
            raise ValueError(f"{code}: 本地无 gpcw 数据且补拉后仍为空（mootdx 不可用或代码无财报）")

    latest_date = max(periods)
    latest = periods[latest_date]
    year, q = latest_date[:4], _quarter_of(latest_date)

    if q == 4:  # 最新期即年报：TTM = FY
        prev_fy, cur, prev_same = latest, None, None
        window = f"{year}Q1-{year}Q4"
    else:
        prev_fy_date = f"{int(year) - 1}-12-31"
        prev_same_date = f"{int(year) - 1}-{latest_date[5:]}"
        missing = [d for d in (prev_fy_date, prev_same_date) if d not in periods]
        if missing:
            _reload_after_fetch()
            missing = [d for d in (prev_fy_date, prev_same_date) if d not in periods]
            if missing:
                raise ValueError(f"{code}: TTM 依赖期缺失 {missing}（本地+补拉后仍无）")
        prev_fy, cur, prev_same = periods[prev_fy_date], latest, periods[prev_same_date]
        window = f"{int(year) - 1}Q4-{year}Q{q}"

    def _ttm(field: str) -> float:
        if cur is None:  # FY 口径
            return float(prev_fy[field] or 0)
        return float(prev_fy[field] or 0) + float(cur[field] or 0) - float(prev_same[field] or 0)

    return {
        "revenue": _ttm("revenue"),
        "net_profit_parent": _ttm("net_profit_parent"),
        "eps": _ttm("eps_basic"),
        "window": window,
        "latest_report_date": latest_date,
        "latest_row": latest,
    }


# ---------------------------------------------------------------------------
# series 技术面
# ---------------------------------------------------------------------------

def _sma(closes: list[float], n: int) -> float:
    if len(closes) < n:
        return 0.0
    return sum(closes[-n:]) / n


def load_series(data_root: Path, code: str, suffix: str) -> list[dict]:
    path = _find_series_path(data_root, code, suffix)
    if path is None:
        raise ValueError(f"{code}: 找不到 data/market/series/{code}.SZ(SH).jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) < 2:
        raise ValueError(f"{code}: series 行数不足（{len(rows)}），无法计算技术面")
    rows.sort(key=lambda r: r["date"])
    return rows


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------

def build_context(code: str, data_root: Path | str | None = None, *, fetch: bool = True) -> MarketContext:
    """组装单票 MarketContext（spec §5.3 字段映射表）。

    单位约定：market_cap 用 **USD 十亿**（人民币市值 ÷ USD_CNY 固定汇率换算，与
    persona 阈值口径对齐；报告侧换回人民币亿元展示）；roe / 增长字段一律 0-1 小数
    （gpcw 的 % 值 /100）；profit_margins = 归母净利(TTM)/营收(TTM)；price/pe/pb/ps
    等比率类与无单位字段不做汇率换算（分子分母同币种，汇率约掉）。

    shares 推导链（禁用净资产/bps 法，spec 拍板 #4）：
      shares = 归母净利(TTM) / eps_basic(TTM)
      —— bps 法的净资产含少数股东权益（300476 实测 +5.5% 系统偏差），eps 法与
      市值/PE 自洽：market_cap = price × shares；pe = price / eps(TTM)。
    """
    data_root = Path(data_root) if data_root else DEFAULT_DATA_ROOT
    status, norm, suffix_or_reason = classify_target(code)
    if status != "stock":
        raise ValueError(f"{code}: 非 A 股个股（{suffix_or_reason}），不能 build_context")
    suffix = suffix_or_reason

    ttm = ttm_financials(norm, data_root, fetch=fetch)
    latest = ttm["latest_row"]
    rows = load_series(data_root, norm, suffix)
    last, prev = rows[-1], rows[-2]
    price = float(last["close"])
    change_pct = (price / float(prev["close"]) - 1) * 100

    closes = [float(r["close"]) for r in rows]
    window_rows = [r for r in rows if r["date"] >= f"{int(last['date'][:4]) - 1}-{last['date'][5:]}"]
    high_52w = max(float(r["high"]) for r in window_rows)
    low_52w = min(float(r["low"]) for r in window_rows)
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)

    industry = industry_for(norm, suffix)

    # shares / 估值推导链（见 docstring）
    eps_ttm = ttm["eps"]
    shares = ttm["net_profit_parent"] / eps_ttm if eps_ttm not in (0, None) else 0.0
    market_cap_cny = price * shares                 # 元
    market_cap_usd_bn = market_cap_cny / USD_CNY / 1e9  # USD 十亿（persona 阈值口径）
    pe = price / eps_ttm if eps_ttm else 0.0
    bps = float(latest.get("bps") or 0)
    pb = price / bps if bps else 0.0
    ps = market_cap_cny / ttm["revenue"] if ttm["revenue"] else 0.0  # 同币种比率，汇率约掉
    profit_margins = ttm["net_profit_parent"] / ttm["revenue"] if ttm["revenue"] else 0.0
    total_assets = float(latest.get("total_assets") or 0)
    debt_ratio = float(latest.get("total_liabilities") or 0) / total_assets if total_assets else 0.0

    replay_fields = [
        "price", "change_pct", "market_cap", "pe", "pb", "ps", "revenue",
        "revenue_growth", "earnings_growth", "roe", "debt_ratio", "profit_margins",
        "eps", "sector", "industry", "fifty_two_week_high", "fifty_two_week_low",
        "price_vs_52w_high", "price_vs_52w_low", "sma20", "sma50", "sma200", "volume",
    ]
    availability = {f: "replay" for f in replay_fields}
    if not sma200:
        availability["sma200"] = "missing"  # 序列不足 200 日
    availability.update({f: "missing" for f in ADAPTER_MISSING_FIELDS})

    ctx = MarketContext(
        ticker=norm,
        price=price,
        change_pct=change_pct,
        market_cap=market_cap_usd_bn,
        pe=pe,
        pb=pb,
        ps=ps,
        revenue=ttm["revenue"],
        revenue_growth=float(latest.get("revenue_yoy") or 0) / 100,
        earnings_growth=float(latest.get("net_profit_yoy") or 0) / 100,
        roe=float(latest.get("roe") or 0) / 100,
        debt_ratio=debt_ratio,
        profit_margins=profit_margins,
        eps=eps_ttm,
        sector=industry["sector_en"],
        industry=industry.get("industry_cn") or industry["industry_key"],
        volume=float(last.get("volume") or 0),
        fifty_two_week_high=high_52w,
        fifty_two_week_low=low_52w,
        price_vs_52w_high=(price / high_52w - 1) * 100,
        price_vs_52w_low=(price / low_52w - 1) * 100,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        field_availability=availability,
        as_of_date=str(last["date"]),
    )
    # 供报告「数据截至」段使用（MarketContext 无对应字段，mcp_metrics 是现成的附加袋）
    ctx.mcp_metrics["masters_adapter"] = {
        "ttm_window": ttm["window"],
        "gpcw_report_date": ttm["latest_report_date"],
        "series_last_date": str(last["date"]),
        "shares": shares,
        "market_cap_cny_yi": market_cap_cny / 1e8,  # 人民币亿元（报告展示口径）
        "industry": industry,
        "suffix": suffix,
    }
    return ctx


# ---------------------------------------------------------------------------
# coverage 后处理（spec §5.3 I8 缺失可见性）
# ---------------------------------------------------------------------------

def load_persona_deps() -> dict:
    deps = json.loads((MASTERS_DIR / "persona_deps.json").read_text(encoding="utf-8"))
    return {k: v for k, v in deps.items() if not k.startswith("_")}


def apply_coverage(
    responses: dict[str, AgentResponse],
    context: MarketContext,
    deps: dict | None = None,
) -> dict[str, AgentResponse]:
    """命中依赖缺失 → coverage_confidence ×0.6 + metadata["degraded_factors"] 追加。

    coverage_confidence 参与共识权重（engine 归一后乘入），降权自动传导进共识。
    追加语义：persona 自己也可能写 degraded_factors，这里只 append 不覆盖。
    """
    deps = deps if deps is not None else load_persona_deps()
    availability = context.field_availability or {}
    for agent_id, resp in responses.items():
        agent_deps = deps.get(agent_id)
        if not agent_id or not agent_deps:
            continue
        degraded = list(resp.metadata.get("degraded_factors") or [])
        for factor, fields in agent_deps.items():
            missing = [f for f in fields if availability.get(f) == "missing"]
            if missing:
                degraded.append({
                    "factor": factor,
                    "missing_fields": missing,
                    "note": f"因子 {factor} 基于缺省值（缺 {', '.join(missing)}），已降权",
                })
        if degraded:
            resp.coverage_confidence = round(resp.coverage_confidence * 0.6, 4)
            resp.metadata["degraded_factors"] = degraded
    return responses
