# -*- coding: utf-8 -*-
"""单票大师面板 CLI（spec §5.4）。

    python tools/masters/run_masters.py 300476.SZ [--data-root ...] [--out output/masters/]

流程：abstain 判定 → build_context（TTM，缺期经 mootdx 补拉）→ 18 位跑 analyze
（ARPS/Serenity 常驻弃权，不进共识）→ apply_coverage 降权 → compute_consensus
→ 报告落 output/masters/YYYY-MM/<code>-<date>.md → run-log open/close 入账
（失败写 sentinel 不中断，同 persist_market_data 口径）。

边界纪律（spec §5.5）：报告页眉固定免责声明；Kelly 是建议数字不是指令；
分歧清单可整理为研究问题候选进 review-queue。
"""

from __future__ import annotations

import argparse
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
        f"- 市值 {context.market_cap:.0f} 亿元（人民币）",
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

    suffix = why
    ticker_label = f"{code}.{suffix}"
    context = build_context(ticker, data_root, fetch=fetch)
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

    _ledger(data_root, report_path, report_date)
    print(report_path)
    return report_path


def _ledger(data_root: Path, report_path: Path, trade_date: str) -> None:
    """run-log open/close（kind=masters）。失败写 sentinel 不中断。"""
    try:
        run_archive = _load_run_archive()
        try:
            run_id = run_archive.append_open(data_root, kind="masters", trade_date=trade_date)
        except Exception as exc:  # noqa: BLE001
            _ledger_failed(data_root, "append_open", exc)
            return
        try:
            # 账本内路径一律「解析根（data_root.parent）相对」
            report_rel = str(report_path.resolve().relative_to(data_root.parent.resolve()))
        except ValueError:
            report_rel = str(report_path.resolve())
        try:
            run_archive.append_close(data_root, run_id, report=report_rel, evidence_registered=None)
        except Exception as exc:  # noqa: BLE001
            _ledger_failed(data_root, "append_close", exc)
    except Exception as exc:  # noqa: BLE001 — run_archive 模块本身导入失败
        _ledger_failed(data_root, "import run_archive", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="单票大师面板（18 persona + 共识 + 报告 + run-log）")
    parser.add_argument("ticker", help="A 股代码，如 300476.SZ（ETF/指数/非 A 股自动 abstain）")
    parser.add_argument("--data-root", default=str(adapter.DEFAULT_DATA_ROOT))
    parser.add_argument("--out", default=str(REPO_ROOT / "output" / "masters"))
    parser.add_argument("--no-fetch", action="store_true",
                        help="禁用 mootdx 缺期补拉（只用本地 gpcw；缺期直接报错）")
    args = parser.parse_args(argv)
    run(args.ticker, Path(args.data_root), Path(args.out), fetch=not args.no_fetch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
