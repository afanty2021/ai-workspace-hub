# -*- coding: utf-8 -*-
"""大师面板 CLI（spec §5.4 单票 + Task 8 批量）。

    python tools/masters/run_masters.py 300476.SZ [--data-root ...] [--out output/masters/]
    python tools/masters/run_masters.py --watchlist [--watchlist-config ...]   # 批量汇总表

流程：abstain 判定 → build_context（TTM，缺期经 mootdx 补拉）→ 18 位跑 analyze
（ARPS/Serenity 常驻弃权，不进共识）→ apply_coverage 降权 → compute_consensus
→ 报告落 output/masters/YYYY-MM/<code>-<date>.md → run-log open/close 入账
（失败写 sentinel 不中断，同 persist_market_data 口径）。账本写入根三态：
RUN_LOG_DISABLE=1 跳过；--out 根在仓库外（冒烟跑）账本随报告写 out 根下
.state/；其余写真实仓库 data/.state/。

边界纪律（spec §5.5）：报告页眉固定免责声明；Kelly 是建议数字不是指令；
分歧清单可整理为研究问题候选进 review-queue。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import adapter  # noqa: E402
from adapter import (  # noqa: E402
    PERMANENT_ABSTAIN,
    apply_coverage,
    build_context,
    classify_target,
    industry_for,
)
from augur_core.consensus.engine import compute_consensus  # noqa: E402
from augur_core.personas.base import SignalType  # noqa: E402
from augur_core.registry import AGENTS, analyze_all  # noqa: E402

DISCLAIMER = (
    "> **免责声明**：本报告是 18 位投资大师公开投资理念的规则化模拟观点（推测层），"
    "不代表本人立场，不构成投资建议；不作为 evidence，不写入 hypothesis。"
)


def _load_run_archive():
    """跨目录导入 system/scripts/run_archive.py（与 persist_market_data 同法）。"""
    script_dir = str(REPO_ROOT / "system" / "scripts")
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import run_archive  # noqa: PLC0415

    return run_archive


def _ledger_failed(data_root: Path, step: str, exc: Exception) -> None:
    """账本子步骤失败：stderr + sentinel，不中断报告产出。"""
    print(f"Warning: 运行账本 {step} 失败（写 sentinel，报告继续）: {exc}", file=sys.stderr)
    try:
        sentinel = data_root / ".state" / "run-log.error"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        with sentinel.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {step} "
                     f"{type(exc).__name__}: {exc}\n")
    except Exception as nested:  # noqa: BLE001
        print(f"Warning: run-log.error sentinel 写入失败: {nested}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 报告渲染（spec §5.4 结构）
# ---------------------------------------------------------------------------

def _factor_extremes(resp) -> tuple[str, str]:
    """从 metadata.factors 取最高/最低因子名（分歧清单用；无 factors 时回退空）。"""
    factors = (resp.metadata or {}).get("factors") or {}
    if not factors:
        return "", ""
    ordered = sorted(factors.items(), key=lambda kv: kv[1], reverse=True)
    return ordered[0][0], ordered[-1][0]


def render_report(ticker_label: str, context, results, consensus, industry, abstain_notes: dict) -> str:
    meta = context.mcp_metrics.get("masters_adapter", {})
    lines: list[str] = [
        f"# 大师面板：{ticker_label}",
        "",
        DISCLAIMER,
        "",
        f"- 标的：{ticker_label}｜行业：{industry.get('industry_cn') or ''}"
        f"（industry_key=`{industry.get('industry_key')}`，sector=`{context.sector}`）",
        f"- 参与大师：{len(results)} 位｜弃权：{len(abstain_notes)} 位",
        "",
        "## 常驻弃权",
        "",
    ]
    lines += [f"- **{AGENTS[aid].name}**（`{aid}`）：{reason}" for aid, reason in abstain_notes.items()]

    lines += ["", "## 各位大师", ""]
    for agent_id, resp in results.items():
        degraded = resp.metadata.get("degraded_factors") or []
        lines.append(f"### {resp.agent_name} — {resp.signal.value} "
                     f"（score {resp.score:.1f}/10，置信度 {resp.confidence:.0%}，"
                     f"适用性 {resp.coverage_confidence:.2f}）")
        if resp.key_findings:
            lines.append(f"- 关键发现：{'；'.join(resp.key_findings[:3])}")
        if resp.risks:
            lines.append(f"- 风险：{'；'.join(resp.risks[:3])}")
        if degraded:
            notes = "；".join(d["note"] for d in degraded[:4])
            lines.append(f"- **盲区（已降权）**：{notes}")
        lines.append("")

    sig = consensus.signal.value
    pos = consensus.metadata.get("position_sizing") or {}
    lines += [
        "## 共识",
        "",
        f"- **信号：{sig}**｜加权分 {consensus.score:.2f}/10｜置信度 {consensus.confidence:.0%}",
        f"- 参与人数：{len(results)}（行业权重 `{industry.get('industry_key')}` + coverage 归一 + sector 增益）",
        f"- 分歧度：{consensus.metadata.get('divergence', {}).get('score', 0)}",
        "",
    ]

    lines += ["## 分歧清单", ""]
    bulls = [r for r in results.values() if r.signal == SignalType.BULLISH]
    bears = [r for r in results.values() if r.signal == SignalType.BEARISH]
    if bulls and bears:
        for bull in bulls:
            b_top, _ = _factor_extremes(bull)
            for bear in bears:
                r_top, _ = _factor_extremes(bear)
                lines.append(
                    f"- **{bull.agent_name}（看多，最强因子 {b_top or 'N/A'}）** vs "
                    f"**{bear.agent_name}（看空，最强因子 {r_top or 'N/A'}）**"
                    "——各自理由：")
                lines.append(f"  - {bull.agent_name}: {bull.reasoning.splitlines()[0][:120]}")
                lines.append(f"  - {bear.agent_name}: {bear.reasoning.splitlines()[0][:120]}")
    else:
        lines.append("- 无多空对向分歧。")

    pct = pos.get("position_pct")
    lines += [
        "",
        "## half-Kelly 建议仓位",
        "",
        f"- **建议仓位：{pct if pct is not None else 'N/A'}%**（{pos.get('rationale', '')}）",
        "- 公式：bullish 且 score≥5 时 `pct = min(20, ((score-5)/5 × conf) × 0.5 × 100)`，"
        "低于 1% 且 conf≥0.5 保底 1%；bearish→0；neutral→`max(0, (conf-0.5)×3)`。",
        "- **Kelly 是建议数字不是指令**：只出现在本报告；`portfolio/` 写入照旧只走 review-queue。",
        "",
        "## 数据截至",
        "",
        f"- TTM 窗口：{meta.get('ttm_window', 'N/A')}（gpcw report_date {meta.get('gpcw_report_date', 'N/A')}）",
        f"- 行情截至：{meta.get('series_last_date', 'N/A')}（series 末日收盘 {context.price}）",
        f"- shares = 归母净利(TTM)/eps(TTM) = {meta.get('shares', 0) / 1e8:.2f} 亿股"
        "（禁用 bps 法：净资产含少数股东权益）",
        f"- 市值 {meta.get('market_cap_cny_yi', 0):.0f} 亿元（人民币；persona 口径按固定汇率"
        f" USD/CNY={adapter.USD_CNY} 换算为 {context.market_cap:.1f}B USD 参与规模档判定）",
        "",
        "## missing 清单（半盲声明）",
        "",
        "- gpcw+series 数据面拿不到：毛利率 / 营业利润率 / FCF / 流动比率 / 速动比率 /"
        " 机构与内部人持股 / 空头利息 / 波动率族 / RSI / MACD 族 / ATR / Stoch——"
        "相关因子基于 vendored 缺省值打分，命中 persona_deps 的大师已降权（适用性 ×0.6）并在上方标注。",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run(ticker: str, data_root: Path, out_dir: Path, *, fetch: bool = True) -> Path:
    """跑单票全流程，返回报告路径。abstain 标的直接 raise（CLI 打印弃权说明）。"""
    status, code, why = classify_target(ticker)
    if status != "stock":
        raise SystemExit(f"{ticker}: abstain —— {why}")

    report_path, _ = _analyze_and_report(code, why, data_root, out_dir, fetch=fetch)
    print(report_path)
    return report_path


def _analyze_and_report(code: str, suffix: str, data_root: Path, out_dir: Path, *,
                        fetch: bool = True) -> tuple[Path, dict]:
    """单票分析 + 报告 + run-log（run 与批量模式共用）。返回 (报告路径, 汇总行 dict)。"""
    ticker_label = f"{code}.{suffix}"
    context = build_context(code, data_root, fetch=fetch)
    industry = industry_for(code, suffix)

    all_results = analyze_all(context)
    abstain_notes = {aid: reason for aid, reason in PERMANENT_ABSTAIN.items() if aid in all_results}
    results = {aid: r for aid, r in all_results.items() if aid not in PERMANENT_ABSTAIN}
    results = apply_coverage(results, context)

    consensus = compute_consensus(results, ticker=ticker_label,
                                  industry_key=industry["industry_key"], context=context)

    report_date = context.mcp_metrics["masters_adapter"]["series_last_date"]
    month_dir = out_dir / f"{report_date[:7]}"
    month_dir.mkdir(parents=True, exist_ok=True)
    report_path = month_dir / f"{ticker_label}-{report_date}.md"
    report_path.write_text(
        render_report(ticker_label, context, results, consensus, industry, abstain_notes),
        encoding="utf-8")

    _ledger(data_root, report_path, report_date, out_dir=out_dir)

    # 汇总行素材（批量模式用；关键分歧取一对代表性行为空对）
    bulls = [r for r in results.values() if r.signal == SignalType.BULLISH]
    bears = [r for r in results.values() if r.signal == SignalType.BEARISH]
    top_pair = None
    if bulls and bears:
        bull, bear = bulls[0], bears[0]
        b_top, _ = _factor_extremes(bull)
        r_top, _ = _factor_extremes(bear)
        top_pair = {"bull": bull.agent_name, "bull_factor": b_top or "N/A",
                    "bear": bear.agent_name, "bear_factor": r_top or "N/A"}
    div = consensus.metadata.get("divergence") or {}
    summary = {
        "ticker": ticker_label,
        "score": consensus.score,
        "signal": consensus.signal.value,
        "participants": len(results),
        "abstains": len(abstain_notes),
        "kelly_pct": consensus.metadata.get("position_pct"),
        "divergence": div,
        "top_pair": top_pair,
        "report": report_path,
    }
    return report_path, summary


# ---------------------------------------------------------------------------
# watchlist 批量模式（Task 8）
# ---------------------------------------------------------------------------

WATCHLIST_DEFAULT = REPO_ROOT / "config" / "daily-watchlist-watchlist.md"


def parse_watchlist(path: Path) -> list[dict]:
    """解析 daily-watchlist 配置表，取 Market=CN 的行（A 股个股 + ETF）。

    海外/指数/宏观段（Market 非 CN）不进批量——classify_target 也会 abstain，
    但先按 Market 过滤避免无谓迭代。返回 [{ticker, name, market, category}]。
    """
    rows: list[dict] = []
    header: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if stripped.startswith("| Ticker") or stripped.startswith("|Ticker"):
                header = cells
                continue
            if not header or all(set(c) <= {"-", ":"} for c in cells):
                continue
            row = dict(zip(header, cells, strict=False))
            if row.get("Ticker") and row.get("Market") == "CN":
                rows.append({"ticker": row["Ticker"], "name": row.get("Name", ""),
                             "market": row["Market"], "category": row.get("Category", "")})
    return rows


def _research_questions(entries: list[dict]) -> list[str]:
    """分歧 → 研究问题候选：每个存在对向分歧的标的一条，措辞可验证。"""
    questions: list[str] = []
    for e in entries:
        pair = e.get("top_pair")
        if not pair:
            continue
        factor = pair["bull_factor"] if pair["bull_factor"] != "N/A" else pair["bear_factor"]
        topic = f"「{factor}」的多头逻辑" if factor != "N/A" else "多头核心逻辑"
        questions.append(
            f"- **{e['ticker']}**：{pair['bull']}（最强因子 {pair['bull_factor']}） vs "
            f"{pair['bear']}（最强因子 {pair['bear_factor']}）——候选研究问题："
            f"最新财报季 {e['ticker']} 的 {topic}是否仍成立？（待验证）")
    return questions


def render_watchlist_summary(entries: list[dict], trade_date: str, watchlist_path: Path) -> str:
    lines = [
        f"# 大师面板汇总：watchlist（{trade_date}）",
        "",
        DISCLAIMER,
        "",
        f"- 股票池：`{watchlist_path}`｜A 股个股逐票跑，ETF 全员 abstain 记一行",
        f"- 个股单票报告：`output/masters/{trade_date[:7]}/<code>-<date>.md`（本表只做对比汇总）",
        "",
        "| Ticker | 名称 | score | signal | 参与大师数 | 弃权数 | half-Kelly | 关键分歧 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        if e["status"] == "ok":
            div = e.get("divergence") or {}
            div_txt = (f"{div.get('bullish_count', 0)}多 vs {div.get('bearish_count', 0)}空"
                       f"（分歧度 {div.get('score', 0)}）") if div else "—"
            if e.get("top_pair"):
                div_txt += f"；{e['top_pair']['bull']} vs {e['top_pair']['bear']}"
            kelly = e["kelly_pct"] if e["kelly_pct"] is not None else "N/A"
            lines.append(f"| {e['ticker']} | {e['name']} | {e['score']:.2f} | {e['signal']} "
                         f"| {e['participants']} | {e['abstains']} | {kelly}% | {div_txt} |")
        elif e["status"] == "abstain":
            lines.append(f"| {e['ticker']} | {e['name']} | — | abstain | 0 | {len(AGENTS)} | — "
                         f"| {e['reason']} |")
        else:  # error
            lines.append(f"| {e['ticker']} | {e['name']} | ERR | error | — | — | — "
                         f"| 失败：{e['error']} |")

    lines += [
        "",
        "> **已知口径**：roe/增长字段为 gpcw 累计期 YTD 未年化；技术指标（RSI/MACD/ATR/"
        "波动率族等）缺省，dalio/soros/marks 等命中 persona_deps 的大师已降权（保守方向已知，"
        "本轮不补算 series 技术面）；市值按固定汇率 USD/CNY=7.2 换算参与规模档判定。",
        "",
        "## 分歧 → 研究问题（候选）",
        "",
    ]
    questions = _research_questions([e for e in entries if e["status"] == "ok"])
    lines += questions or ["- 本轮无对向分歧。"]
    lines += [
        "",
        "> 以上为**研究问题候选措辞**，确认后进 `workspace/review-queue.md`（本工具不自动写队列）。",
    ]
    return "\n".join(lines) + "\n"


def run_watchlist(data_root: Path, out_dir: Path, *, fetch: bool = True,
                  watchlist_path: Path | None = None, today: str | None = None) -> Path:
    """批量跑整个 watchlist：17 只个股逐票 + 4 ETF abstain 行 → 汇总表。

    单票失败不中断（失败行记 error 摘要）；汇总表自身也写 run-log open/close。
    """
    watchlist_path = watchlist_path or WATCHLIST_DEFAULT
    rows = parse_watchlist(watchlist_path)
    trade_date = today or datetime.now().strftime("%Y-%m-%d")

    entries: list[dict] = []
    for row in rows:
        status, code, why = classify_target(row["ticker"])
        entry = {"ticker": row["ticker"], "name": row["name"]}
        if status != "stock":
            entries.append({**entry, "status": "abstain", "reason": why})
            continue
        try:
            _, summary = _analyze_and_report(code, why, data_root, out_dir, fetch=fetch)
            entries.append({**entry, "status": "ok", "name": row["name"] or summary["ticker"],
                            **{k: summary[k] for k in
                               ("ticker", "score", "signal", "participants", "abstains",
                                "kelly_pct", "divergence", "top_pair")}})
        except Exception as exc:  # noqa: BLE001 — 单票失败不中断批量
            print(f"Warning: {row['ticker']} 失败（记 error 行继续）: {exc}", file=sys.stderr)
            entries.append({**entry, "status": "error",
                            "error": f"{type(exc).__name__}: {exc}"[:120]})

    month_dir = out_dir / trade_date[:7]
    month_dir.mkdir(parents=True, exist_ok=True)
    summary_path = month_dir / f"watchlist-{trade_date}.md"
    summary_path.write_text(render_watchlist_summary(entries, trade_date, watchlist_path),
                            encoding="utf-8")
    _ledger(data_root, summary_path, trade_date, out_dir=out_dir)
    print(summary_path)
    return summary_path


def _ledger_root(data_root: Path, out_dir: Path) -> Path | None:
    """账本写入根（实施评审 #2c/#5a）：

    - RUN_LOG_DISABLE=1 → None（逃生门，与 persist_market_data 同语义，跳过账本写入）；
    - --out 根在仓库外**而 data_root 在仓库内**（冒烟跑的典型形态：--out 指向
      /private/tmp/... 而 --data-root 用默认真实仓库）→ 账本改写到 out 根下
      .state/run-log.jsonl（与报告同生命周期），不再污染真实仓库 data/.state/；
    - 其余（两者同域：都在仓库内，或测试里都在 tmp）→ data_root。
    """
    if os.environ.get("RUN_LOG_DISABLE", "").strip() == "1":
        return None
    try:
        out_dir.resolve().relative_to(REPO_ROOT.resolve())
        return data_root  # 报告在仓库内 → 常规路径
    except ValueError:
        pass
    try:
        data_root.resolve().relative_to(REPO_ROOT.resolve())
        return out_dir     # 报告出仓库、账本根在仓库 → 隔离到 out 根
    except ValueError:
        return data_root   # 测试形态：data_root 本就在 tmp，与报告同生命周期


def _ledger(data_root: Path, report_path: Path, trade_date: str,
            out_dir: Path | None = None) -> None:
    """run-log open/close（kind=masters）。失败写 sentinel 不中断。

    out_dir 给出时按 _ledger_root 裁定账本根（冒烟隔离 / 逃生门）。
    """
    try:
        root = _ledger_root(data_root, out_dir or report_path.parent)
        if root is None:
            return
        run_archive = _load_run_archive()
        try:
            run_id = run_archive.append_open(root, kind="masters", trade_date=trade_date)
        except Exception as exc:  # noqa: BLE001
            _ledger_failed(root, "append_open", exc)
            return
        try:
            # 账本内路径一律「解析根（root.parent）相对」
            report_rel = str(report_path.resolve().relative_to(root.parent.resolve()))
        except ValueError:
            report_rel = str(report_path.resolve())
        try:
            run_archive.append_close(root, run_id, report=report_rel, evidence_registered=None)
        except Exception as exc:  # noqa: BLE001
            _ledger_failed(root, "append_close", exc)
    except Exception as exc:  # noqa: BLE001 — run_archive 模块本身导入失败
        _ledger_failed(data_root, "import run_archive", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="单票大师面板（18 persona + 共识 + 报告 + run-log）")
    parser.add_argument("ticker", nargs="?", help="A 股代码，如 300476.SZ（ETF/指数/非 A 股自动 abstain）")
    parser.add_argument("--watchlist", action="store_true",
                        help="批量模式：读 config/daily-watchlist-watchlist.md，个股逐票 + ETF abstain 行，"
                             "输出汇总表 output/masters/YYYY-MM/watchlist-<date>.md")
    parser.add_argument("--watchlist-config", default=str(WATCHLIST_DEFAULT),
                        help="批量模式的 watchlist 配置路径（默认 config/daily-watchlist-watchlist.md）")
    parser.add_argument("--data-root", default=str(adapter.DEFAULT_DATA_ROOT))
    parser.add_argument("--out", default=str(REPO_ROOT / "output" / "masters"))
    parser.add_argument("--no-fetch", action="store_true",
                        help="禁用 mootdx 缺期补拉（只用本地 gpcw；缺期直接报错）")
    args = parser.parse_args(argv)
    if args.watchlist:
        if args.ticker:
            parser.error("--watchlist 与单票 ticker 二选一")
        run_watchlist(Path(args.data_root), Path(args.out), fetch=not args.no_fetch,
                      watchlist_path=Path(args.watchlist_config))
    else:
        if not args.ticker:
            parser.error("请给单票 ticker，或用 --watchlist 批量模式")
        run(args.ticker, Path(args.data_root), Path(args.out), fetch=not args.no_fetch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
