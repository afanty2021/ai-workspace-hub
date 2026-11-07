from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dotenv import dotenv_values

from market_data_io import parse_trade_date
from workspace_paths import (
    find_workspace_root,
    resolve_config_dir,
    resolve_config_path,
    resolve_env_path,
    resolve_evidence_dir,
    resolve_hypothesis_dir,
    resolve_reports_dir,
    resolve_template_path,
)

# Windows 控制台可能默认 cp1252/GBK，统一 UTF-8 输出避免中文触发 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def load_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.is_file():
        log(f"Warning: {env_path} not found; continuing without API keys")
        return {}
    raw_text = env_path.read_text(encoding="utf-8-sig")
    parsed = dotenv_values(stream=StringIO(raw_text))
    values: dict[str, str] = {}
    for key, value in parsed.items():
        if value is None:
            continue
        values[key] = value
        if key not in os.environ:
            os.environ[key] = value
    return values


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8-sig") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"配置文件 {config_path} 必须是映射结构")
    return payload


def run_json_script(workspace_root: Path, script_name: str) -> dict[str, Any]:
    local_scripts = Path(__file__).resolve().parent
    script_path = local_scripts / script_name
    if not script_path.exists():
        script_path = workspace_root / "scripts" / script_name
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.stderr.strip():
        log(completed.stderr.strip())
    if completed.returncode != 0:
        raise RuntimeError(
            f"{script_name} exited with code {completed.returncode}; "
            "see the log output above for the underlying error"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{script_name} did not produce valid JSON: {exc}") from exc


def _persist_market_data_hook(market_data: dict[str, Any],
                              macro_meta: dict[str, Any] | None = None) -> None:
    """持久化钩子（spec §3：失败永不阻塞日报，只 log warning）。

    macro_meta = fetch_macro_data 的 meta（4c 宏观调用序前移后传入，其
    missing_symbols 能进运行账本 data-close 的 missing；None/未启用宏观察时省略）。
    """
    try:
        import persist_market_data

        persist_market_data.run_persist_hook(market_data, macro_meta=macro_meta)
    except Exception as exc:  # noqa: BLE001
        log(f"Warning: persist hook failed (report continues): {exc}")


def fetch_macro_or_degrade(workspace_root: Path, enabled: bool) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """宏观抓取 + 失败降级（实施评审 #1）：macro 崩只丢宏观段，不连坐市场数据落盘。

    宏观调用序前移到 persist hook 之前（spec §3.3 拍板 #2 ②）后，若无隔离，
    macro 崩会把 hook 一起拖死——市场数据整个不落盘（旧调用序只丢报告不丢数据，
    属回归）。失败路径：stderr 告警 + macro_data={} + meta 标失败原因（missing_symbols
    含 ALL，data-close 的 missing 透传可见），hook 照常执行。
    """
    if not enabled:
        return {}, None
    try:
        macro_data = run_json_script(workspace_root, "fetch_macro_data.py")
        return macro_data, macro_data.get("meta") or None
    except Exception as exc:  # noqa: BLE001 — 宏观属可降级模块
        log(f"Warning: fetch_macro_data 失败（宏观段降级为空，市场数据照常落盘）: {exc}")
        return {}, {"missing_symbols": ["ALL"], "reason": f"macro fetch failed: {exc}"[:200]}


def format_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):+.2f}%"


def format_num(value: Any, digits: int = 2, prefix: str = "") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return f"{prefix}{value}"
    if isinstance(value, float):
        return f"{prefix}{value:.{digits}f}"
    return f"{prefix}{value}"


def status_from_change(value: Any) -> str:
    if value is None:
        return "N/A"
    numeric = float(value)
    if numeric > 1:
        return "强势"
    if numeric > 0:
        return "上涨"
    if numeric < -1:
        return "偏弱"
    if numeric < 0:
        return "下跌"
    return "持平"


def translate_sentiment(value: Any) -> str:
    if value is None:
        return "N/A"

    mapping = {
        "Optimistic": "乐观",
        "Normal": "中性",
        "Cautious": "谨慎",
        "Panic": "恐慌",
        "Unknown": "未知",
        "risk-on": "风险偏好回升",
        "risk-off": "风险偏好下降",
    }
    text = str(value).strip()
    if not text:
        return "N/A"
    parts = [part.strip() for part in text.split(",") if part.strip()]
    translated = [mapping.get(part, part) for part in parts]
    return "，".join(translated) if translated else "N/A"


class SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize_modules(config: dict[str, Any]) -> dict[str, bool]:
    modules = config.get("modules") or {}
    if not isinstance(modules, dict):
        modules = {}
    return {
        "macro": bool(modules.get("macro", True)),
        "earnings": bool(modules.get("earnings", True)),
        "focus_areas": bool(modules.get("focus_areas", True)),
    }


def build_macro_defaults() -> dict[str, dict[str, Any]]:
    return {
        "VIX": {"price": None, "change_pct": None, "status": "N/A"},
        "SPY": {"price": None, "change_pct": None},
        "QQQ": {"price": None, "change_pct": None},
        "GLD": {"price": None, "change_pct": None},
        "CLUSD": {"price": None, "change_pct": None},
        "BTC": {"price": None, "change_pct": None},
    }


def render_market_overview(
    macro_data: dict[str, Any], enabled: bool
) -> tuple[str, str]:
    macro = build_macro_defaults()
    if enabled:
        macro.update(macro_data.get("macro") or {})
        summary = translate_sentiment(macro_data.get("sentiment") or "N/A")
    else:
        summary = "宏观模块已关闭"

    rows = [
        "| 指标 | 数值 | 涨跌幅 | 状态 |",
        "|------|------|--------|------|",
        (
            f"| VIX | {format_num(macro['VIX'].get('price'))} | "
            f"{format_pct(macro['VIX'].get('change_pct'))} | "
            f"{translate_sentiment(macro['VIX'].get('status', 'N/A'))} |"
        ),
        (
            f"| SPY | {format_num(macro['SPY'].get('price'))} | "
            f"{format_pct(macro['SPY'].get('change_pct'))} | "
            f"{status_from_change(macro['SPY'].get('change_pct'))} |"
        ),
        (
            f"| QQQ | {format_num(macro['QQQ'].get('price'))} | "
            f"{format_pct(macro['QQQ'].get('change_pct'))} | "
            f"{status_from_change(macro['QQQ'].get('change_pct'))} |"
        ),
        (
            f"| GLD | {format_num(macro['GLD'].get('price'))} | "
            f"{format_pct(macro['GLD'].get('change_pct'))} | "
            f"{status_from_change(macro['GLD'].get('change_pct'))} |"
        ),
        (
            f"| WTI | {format_num(macro['CLUSD'].get('price'))} | "
            f"{format_pct(macro['CLUSD'].get('change_pct'))} | "
            f"{status_from_change(macro['CLUSD'].get('change_pct'))} |"
        ),
        (
            f"| BTC | {format_num(macro['BTC'].get('price'), prefix='$')} | "
            f"{format_pct(macro['BTC'].get('change_pct'))} | "
            f"{status_from_change(macro['BTC'].get('change_pct'))} |"
        ),
    ]
    return "\n".join(rows), summary


def render_key_movers(movers: list[dict[str, Any]]) -> str:
    rows = [
        "| 代码 | 名称 | 涨跌幅 | 分类 | 摘要 |",
        "|------|------|--------|------|------|",
    ]
    if movers:
        for mover in movers[:10]:
            change = format_pct(mover["changesPercentage"])
            rows.append(
                f"| {mover['ticker']} | {mover['name']} | {change} | "
                f"{mover['category']} | 用 WebSearch 补充新闻与原因分析 |"
            )
    else:
        rows.append("| 暂无 | 当前没有股票超过异动阈值 | N/A | N/A | 无需补充 |")
    return "\n".join(rows)


def render_other_movers(
    quotes: list[dict[str, Any]], movers: list[dict[str, Any]] | None = None
) -> str:
    rows = [
        "| 代码 | 名称 | 涨跌幅 |",
        "|------|------|--------|",
    ]
    mover_tickers = {item["ticker"] for item in (movers or []) if "ticker" in item}
    other_movers = sorted(
        [
            item
            for item in quotes
            if item.get("changesPercentage") is not None
            and item.get("ticker") not in mover_tickers
        ],
        key=lambda item: abs(float(item["changesPercentage"])),
        reverse=True,
    )[:5]
    if other_movers:
        for mover in other_movers:
            change = format_pct(mover["changesPercentage"])
            rows.append(
                f"| {mover['ticker']} | {mover['name']} | {change} |"
            )
    else:
        rows.append("| 暂无 | 当前没有可展示的其他异动 | N/A |")
    return "\n".join(rows)


def render_earnings_sections(
    earnings: list[dict[str, Any]], enabled: bool, status: dict[str, Any] | None = None
) -> tuple[str, str]:
    """财报跟踪两张表：已披露 / 待披露。行形状兼容两路源——

    - 东财预约披露（A 股，source=eastmoney-disclosure）：reportDate/appointDate/
      actualDate/daysUntil，无 EPS；
    - FMP earning_calendar（美股）：date/eps/epsEstimated。
    表格统一为「代码｜日期｜报告期｜备注」，EPS 细节进备注，不再分设两张表头。
    """
    reported_rows = [
        "| 代码 | 名称 | 报告期 | 日期 | 备注 |",
        "|------|------|--------|------|------|",
    ]
    upcoming_rows = [
        "| 代码 | 名称 | 报告期 | 预约披露日 | 备注 |",
        "|------|------|--------|------------|------|",
    ]
    if not enabled:
        reported_rows.append("| 模块关闭 | N/A | N/A | N/A | 财报模块已关闭 |")
        upcoming_rows.append("| 模块关闭 | N/A | N/A | N/A |")
        return "\n".join(reported_rows), "\n".join(upcoming_rows)

    if status is not None and status.get("state") != "ok":
        reason = {"not_configured": "未配置财报数据源，本轮未检查",
                  "failed": "财报获取失败，不能判断是否有财报",
                  "disabled": "财报模块已关闭"}.get(status.get("state"), "财报数据状态未确认")
        return f"> {reason}", f"> {reason}"

    cn_rows = [e for e in earnings if e.get("source") == "eastmoney-disclosure"]
    fmp_rows = [e for e in earnings if e.get("source") != "eastmoney-disclosure"]

    for item in cn_rows:
        remark = f"预约 {item['appointDate']}" if item.get("appointDate") else ""
        if item.get("actualDate"):
            reported_rows.append(
                f"| {item['ticker']} | {item['name']} | {item.get('reportTypeName') or item.get('reportDate') or 'N/A'} | "
                f"{item['actualDate']} | {remark} |"
            )
        else:
            days = item.get("daysUntil")
            flag = "（本周）" if isinstance(days, int) and 0 <= days <= 7 else ""
            upcoming_rows.append(
                f"| {item['ticker']} | {item['name']} | {item.get('reportTypeName') or item.get('reportDate') or 'N/A'} | "
                f"{item.get('appointDate') or 'N/A'} | 距今 {days if isinstance(days, int) else 'N/A'} 天{flag} |"
            )

    for item in fmp_rows[:6]:
        actual_eps = item.get("eps")
        estimated_eps = item.get("epsEstimated")
        if actual_eps is not None:
            surprise = (
                format_num(actual_eps - estimated_eps, digits=2)
                if isinstance(estimated_eps, (int, float)) else "N/A"
            )
            reported_rows.append(
                f"| {item['ticker']} | {item['name']} | N/A | {item.get('date') or 'N/A'} | "
                f"EPS 实际 {actual_eps} / 预期 {estimated_eps if estimated_eps is not None else 'N/A'}"
                f"（surprise {surprise}），市场反应用 WebSearch 补充 |"
            )
        else:
            upcoming_rows.append(
                f"| {item['ticker']} | {item['name']} | N/A | {item.get('date') or 'N/A'} | "
                f"预期 EPS {estimated_eps if estimated_eps is not None else 'N/A'} |"
            )

    if len(reported_rows) == 2:
        reported_rows.append(
            "| 暂无 | N/A | N/A | N/A | 当前没有已披露财报条目 |"
        )
    if len(upcoming_rows) == 2:
        upcoming_rows.append("| 暂无 | N/A | N/A | N/A |")
    return "\n".join(reported_rows), "\n".join(upcoming_rows)


def render_themes(config: dict[str, Any], enabled: bool) -> str:
    if not enabled:
        return "### 模块关闭\n\n- `focus_areas` 模块已关闭。"

    focus_areas = config.get("focus_areas") or []
    if not focus_areas:
        return "### 暂无\n\n- 当前配置未设置 focus areas。"

    blocks: list[str] = []
    for area in focus_areas[:3]:
        name = str(area.get("name") or "未命名主题")
        keywords = "、".join(str(item) for item in area.get("keywords") or [])
        blocks.append(f"### {name}")
        blocks.append("")
        blocks.append(f"- 关键词：{keywords or '未配置'}")
        blocks.append("- 用 Claude Code WebSearch 进行主题新闻检索并在核实来源后写入。")
        blocks.append("")
    return "\n".join(blocks).rstrip()


def render_sources(modules: dict[str, bool]) -> str:
    lines = ["- `fetch_market_data.py`：拉取监控池当前或最近可用行情、异动和财报数据"]
    if modules["macro"]:
        lines.append("- `fetch_macro_data.py`：配置 FMP 后拉取 VIX、指数、商品和 BTC 数据")
    else:
        lines.append("- `fetch_macro_data.py`：当前配置已关闭宏观模块，本次未调用")
    lines.append(
        "- 新闻部分：由 Claude Code 通过 WebSearch 补充，不能用本地行情接口替代"
    )
    lines.append("- 假设联动部分：由本地 hypothesis 文件扫描生成，结论需要人工确认")
    return "\n".join(lines)


def load_template(template_path: Path) -> str:
    return template_path.read_text(encoding="utf-8-sig")


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-") or "hypothesis"


def extract_frontmatter(content: str) -> dict[str, Any]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
    if not match:
        return {}
    try:
        payload = yaml.safe_load(match.group(1)) or {}
        return payload if isinstance(payload, dict) else {}
    except yaml.YAMLError:
        return {}


def extract_title(content: str, fallback: str) -> str:
    match = re.search(r"^#\s+(H\d+)\s*[:：]\s*(.+)$", content, re.MULTILINE)
    if match:
        return match.group(2).strip()
    return fallback


# Ticker shapes accepted in the 关联标的 table (first column):
# - US style, optional share class: F, NVDA, BRK.B, BF-B
# - Numeric codes with a market suffix: 601857.SH, 0700.HK, 005930.KS
# The cell must already be written in uppercase; mixed-case words such as
# company names ("Apple") are intentionally rejected to avoid false positives.
RELATED_TICKER_PATTERN = re.compile(
    r"[A-Z][A-Z0-9]{0,4}(?:[.-][A-Z0-9]{1,2})?"
    r"|\d{4,6}\.[A-Z]{1,2}"
)


def extract_related_tickers(content: str) -> set[str]:
    tickers: set[str] = set()
    section_match = re.search(
        r"##\s*关联标的(.*?)(?:\n##\s|\Z)", content, re.DOTALL
    )
    if section_match:
        section = section_match.group(1)
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and cells[0] and cells[0] != "公司" and set(cells[0]) != {"-"}:
                candidate = cells[0]
                if candidate != candidate.upper():
                    continue
                if RELATED_TICKER_PATTERN.fullmatch(candidate):
                    tickers.add(candidate)
    return tickers


def keyword_matches_text(keyword: str, haystack: str) -> bool:
    normalized = keyword.strip().lower()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9\s-]*", normalized):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
        return re.search(pattern, haystack) is not None
    return normalized in haystack


def read_hypotheses(workspace_root: Path) -> list[dict[str, Any]]:
    hypothesis_dir = resolve_hypothesis_dir(workspace_root)
    if not hypothesis_dir.exists():
        return []

    items: list[dict[str, Any]] = []
    for file_path in sorted(hypothesis_dir.glob("H*.md")):
        content = file_path.read_text(encoding="utf-8-sig")
        frontmatter = extract_frontmatter(content)
        fallback_title = file_path.stem
        filename_id_match = re.match(r"(H\d+)", file_path.stem)
        hypothesis_id = str(
            frontmatter.get("id")
            or (filename_id_match.group(1) if filename_id_match else file_path.stem)
        )
        linked_entities = frontmatter.get("linked_entities") or []
        if isinstance(linked_entities, str):
            linked_entities = [linked_entities]
        frontmatter_tickers = {
            str(item).upper() for item in linked_entities if str(item).strip()
        }
        items.append(
            {
                "id": hypothesis_id,
                "title": extract_title(content, fallback_title),
                "certainty": frontmatter.get("certainty"),
                "status": frontmatter.get("status"),
                "tickers": frontmatter_tickers | extract_related_tickers(content),
                "content": content,
                "path": file_path,
            }
        )
    return items


def collect_hypothesis_signals(
    hypotheses: list[dict[str, Any]],
    config: dict[str, Any],
    movers: list[dict[str, Any]],
    earnings: list[dict[str, Any]],
    today: date | None = None,
) -> list[dict[str, Any]]:
    # today 可注入：事件级闸门按「今天」算距今天数，不注入则测试用例
    # 会随真实日历滑出窗口而变红（复查 N-1 时间炸弹的修根）。
    gate_today = (today or date.today()).isoformat()
    signals: list[dict[str, Any]] = []
    signal_keys: set[tuple[str, str, str]] = set()

    for hypothesis in hypotheses:
        for mover in movers[:10]:
            ticker = str(mover.get("ticker", "")).upper()
            if not ticker or ticker not in hypothesis["tickers"]:
                continue
            key = (hypothesis["id"], "mover", ticker)
            if key in signal_keys:
                continue
            signal_keys.add(key)
            change = format_pct(mover.get("changesPercentage"))
            signals.append(
                {
                    "hypothesis_id": hypothesis["id"],
                    "hypothesis_title": hypothesis["title"],
                    "signal_type": "mover",
                    "ref": ticker,
                    # 三时点接线（spec §2.1/C6）：业务时点取 quote 的 tradeDate，
                    # 市场口径决定 available_at 的收盘换算规则
                    "observed_trade_date": mover.get("tradeDate"),
                    "market": mover.get("market", ""),
                    "display": (
                        f"- {hypothesis['id']} `{hypothesis['title']}` "
                        f"<- {ticker} {change}，建议补充今日异动原因和证据判断。"
                    ),
                    "summary": (
                        f"{ticker} 今日涨跌幅 {change}，"
                        f"分类 {mover.get('category', 'N/A')}"
                    ),
                    "auto_writeback": True,
                }
            )

        for earning in earnings[:10]:
            ticker = str(earning.get("ticker", "")).upper()
            if not ticker or ticker not in hypothesis["tickers"]:
                continue
            # 事件级闸门（评审 #2 双管齐下之二）：CN 预约披露行在 -40/+35 窗内
            # 长驻 earnings，只有临近披露/刚披露的事件才值得写假设时间线——
            # daysUntil ∈ [0,7]（本周预约）或 actualDate 距今 ≤7 天（刚披露）。
            # 闸门只管信号写回；渲染端 earnings 表格仍展示窗口全量。
            if earning.get("source") == "eastmoney-disclosure":
                near_appoint = isinstance(earning.get("daysUntil"), int) and 0 <= earning["daysUntil"] <= 7
                recently_actual = _within_days(earning.get("actualDate"), gate_today, 7)
                if not (near_appoint or recently_actual):
                    continue
            key = (hypothesis["id"], "earnings", ticker)
            if key in signal_keys:
                continue
            signal_keys.add(key)
            estimated = earning.get("epsEstimated")
            actual = earning.get("eps")
            surprise = "N/A"
            if isinstance(estimated, (int, float)) and isinstance(actual, (int, float)):
                surprise = format_num(actual - estimated, digits=2)
            signals.append(
                {
                    "hypothesis_id": hypothesis["id"],
                    "hypothesis_title": hypothesis["title"],
                    "signal_type": "earnings",
                    "ref": ticker,
                    # 财报业务时点 = 披露日（FMP earning_calendar 的 date 字段）
                    "observed_trade_date": earning.get("date"),
                    # 事件日用于 marker 幂等（评审 #2 双管齐下之一）
                    "event_date": earning.get("actualDate") or earning.get("appointDate") or earning.get("date"),
                    "market": earning.get("market", ""),
                    "display": (
                        f"- {hypothesis['id']} `{hypothesis['title']}` "
                        f"<- {ticker} 财报事件，建议核对财报是否强化或削弱原假设。"
                    ),
                    "summary": (
                        f"{ticker} 财报：实际 EPS "
                        f"{actual if actual is not None else 'N/A'}，"
                        f"预期 EPS {estimated if estimated is not None else 'N/A'}，"
                        f"surprise {surprise}"
                    ),
                    "auto_writeback": True,
                }
            )

    focus_areas = config.get("focus_areas") or []
    for hypothesis in hypotheses:
        for area in focus_areas[:3]:
            if not matches_focus_area(hypothesis, area):
                continue
            name = str(area.get("name") or "未命名主题")
            key = (hypothesis["id"], "theme", name)
            if key in signal_keys:
                continue
            signal_keys.add(key)
            signals.append(
                {
                    "hypothesis_id": hypothesis["id"],
                    "hypothesis_title": hypothesis["title"],
                    "signal_type": "theme",
                    "ref": name,
                    "display": (
                        f"- {hypothesis['id']} `{hypothesis['title']}` "
                        f"命中主题 `{name}`，如果今天相关新闻密集，建议更新证据时间线。"
                    ),
                    "summary": f"主题 `{name}` 在今日 watchlist 中仍为重点跟踪方向",
                    "auto_writeback": False,
                }
            )

    return signals


def matches_focus_area(hypothesis: dict[str, Any], area: dict[str, Any]) -> bool:
    haystack = f"{hypothesis['title']}\n{hypothesis['content']}".lower()
    keywords = [str(item).lower() for item in area.get("keywords") or []]
    required_any = [str(item).lower() for item in area.get("required_any") or []]
    excluded = [str(item).lower() for item in area.get("exclude") or []]
    if any(keyword_matches_text(keyword, haystack) for keyword in excluded):
        return False
    if required_any and not any(
        keyword_matches_text(keyword, haystack) for keyword in required_any
    ):
        return False
    return (
        any(keyword_matches_text(keyword, haystack) for keyword in keywords)
        if keywords
        else False
    )


def format_certainty(certainty: Any) -> str:
    if certainty is None:
        return "N/A"
    return f"{certainty}%"


def hypothesis_settings(config: dict[str, Any]) -> tuple[bool, bool]:
    """Return (enabled, auto_writeback) from config.hypothesis_tracking.

    Both default to True to preserve backwards-compatible behavior.
    """
    hypothesis_config = config.get("hypothesis_tracking") or {}
    if not isinstance(hypothesis_config, dict):
        hypothesis_config = {}
    enabled = bool(hypothesis_config.get("enabled", True))
    auto_writeback = bool(hypothesis_config.get("auto_writeback", True))
    return enabled, auto_writeback


def build_hypothesis_section(
    hypotheses: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    config: dict[str, Any],
) -> str:
    enabled, auto_writeback = hypothesis_settings(config)
    hypothesis_config = config.get("hypothesis_tracking") or {}
    if not isinstance(hypothesis_config, dict):
        hypothesis_config = {}
    if not enabled:
        return "### 模块关闭\n\n- `hypothesis_tracking.enabled` 已关闭。"

    if not hypotheses:
        return (
            "### 当前状态\n\n"
            "- 当前还没有任何 hypothesis 文件。\n"
            "- 如果今天出现重复主题或强信号，建议运行 `/ht-new` 建立第一条投资假设。"
        )

    lines: list[str] = []
    lines.append("### 已追踪假设概览")
    lines.append("")
    lines.append("| ID | 名称 | 确定性 | 状态 | 关联标的 |")
    lines.append("|----|------|--------|------|----------|")
    for item in hypotheses:
        tickers = "、".join(sorted(item["tickers"])) if item["tickers"] else "N/A"
        lines.append(
            f"| {item['id']} | {item['title']} | "
            f"{format_certainty(item['certainty'])} | "
            f"{item.get('status') or 'N/A'} | {tickers} |"
        )

    lines.append("")
    lines.append("### 今日触发信号")
    lines.append("")
    if signals:
        max_matches = int(hypothesis_config.get("max_matches", 8))
        lines.extend(signal["display"] for signal in signals[:max_matches])
    else:
        lines.append("- 今天没有发现与现有假设明显命中的个股或主题。")

    lines.append("")
    lines.append("### 操作建议")
    lines.append("")
    if signals:
        writeback_signals = [signal for signal in signals if signal.get("auto_writeback")]
        if auto_writeback and writeback_signals:
            lines.append(
                "- 已将本地可确认信号登记到 `evidence/`，并在对应假设中追加证据引用。"
            )
        elif auto_writeback:
            lines.append("- 当前只有主题匹配，等待网页核验后再决定是否写入假设证据。")
        else:
            lines.append("- `auto_writeback` 已关闭，本次信号仅展示，不回写假设文件。")
        lines.append("- 如需整体回看当前假设状态，运行 `/ht-status`。")
    else:
        lines.append(
            "- 如果今日重复出现某个主题，考虑运行 `/ht-new` 建立新的跟踪假设。"
        )
    lines.append("- 如果今天已经发生买卖动作，运行 `/ht-trade` 记录交易并回写假设。")

    return "\n".join(lines)


def _within_days(iso_date: Any, today_text: str, days: int) -> bool:
    """iso_date 在 today_text（ISO）之前 0~days 天（含当天）→ True。

    未来日期 False：actualDate 晚于今天是脏数据（未来不可能已披露），不能放行
    进信号。畸形输入 False。
    """
    try:
        delta = date.fromisoformat(str(iso_date)) - date.fromisoformat(str(today_text))
    except (ValueError, TypeError):
        return False
    return -days <= delta.days <= 0


def build_signal_marker(date_text: str, signal: dict[str, Any]) -> str:
    signal_type = str(signal["signal_type"])
    # earnings 信号按事件日（actualDate or appointDate）构造 marker：同一财报
    # 事件在 -40 天回看窗内每天重进 earnings，用报告日去重会每天写一条新时间线
    # 条目（最长 40 天）；事件日让跨日去重幂等。其他信号类型维持报告日。
    effective_date = str(signal.get("event_date") or date_text)
    ref = slugify(str(signal["ref"]))
    hypothesis_id = slugify(str(signal["hypothesis_id"]))
    return f"DW-{effective_date}-{signal_type}-{ref}-{hypothesis_id}"


def build_evidence_id(date_text: str, signal: dict[str, Any]) -> str:
    # 契约（object-model）：E-YYYYMMDD-...，日期紧凑无连字符；DW- marker 保持 ISO 连字符。
    signal_type = slugify(str(signal["signal_type"]))
    ref = slugify(str(signal["ref"]))
    hypothesis_id = slugify(str(signal["hypothesis_id"]))
    return f"E-{date_text.replace('-', '')}-{signal_type}-{ref}-{hypothesis_id}"


_BEIJING = ZoneInfo("Asia/Shanghai")
_US_EAST = ZoneInfo("America/New_York")


def _available_at_for(observed_day: str, market: str) -> tuple[str, str | None]:
    """按 object-model 三时点规范生成 available_at（收盘即可得）。

    A 股（CN）：当地日历日 15:00+08:00 收盘；美股个股与美股指数（US/INDEX）：
    美东 16:00 收盘按当期实际偏移（ZoneInfo 处理 EST/EDT）换算成 +08:00。
    其余市场（KR/FX/CMDTY/未知）判定不了收盘口径：A 股口径保守填写并返回注记。
    返回 (available_at, 注记或 None)。
    """
    market_upper = (market or "").strip().upper()
    if market_upper in ("US", "INDEX"):
        close_et = datetime.fromisoformat(f"{observed_day}T16:00:00").replace(tzinfo=_US_EAST)
        return close_et.astimezone(_BEIJING).isoformat(timespec="seconds"), None
    note = None
    if market_upper != "CN":
        note = (f"市场 {market_upper or '未知'} 无法判定收盘口径，"
                "available_at 按 A 股 15:00+08:00 保守填写")
    return f"{observed_day}T15:00:00+08:00", note


def _evidence_path_for(workspace_root: Path, date_text: str,
                       signal: dict[str, Any]) -> Path:
    """证据文件的落盘路径（纯计算，无 IO）——去重判断需要先于写入拿到路径。"""
    evidence_id = build_evidence_id(date_text, signal)
    return resolve_evidence_dir(workspace_root) / date_text[:7] / f"{evidence_id}.md"


def write_signal_evidence(
    workspace_root: Path,
    date_text: str,
    signal: dict[str, Any],
    report_relpath: str,
) -> tuple[Path, bool]:
    evidence_id = build_evidence_id(date_text, signal)
    evidence_path = _evidence_path_for(workspace_root, date_text, signal)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if evidence_path.exists():
        return evidence_path, False

    signal_type = str(signal["signal_type"])
    ref = str(signal["ref"]).upper()
    metric = "price_change" if signal_type == "mover" else "earnings"

    # 三时点（spec §2.1/C6）：observed_at = 业务时点（quote tradeDate / 财报披露日），
    # 取不到回退报告日并正文注记；available_at = 收盘即可得（市场口径见 _available_at_for）；
    # recorded_at = 证据写入时刻（带时区）。
    notes: list[str] = []
    observed_day = parse_trade_date(signal.get("observed_trade_date"))
    if observed_day is None:
        observed_day = date_text
        notes.append(f"observed_at 未能从信号数据取得业务时点（tradeDate/date 缺失或不可解析："
                     f"{signal.get('observed_trade_date')!r}），回退报告日 {date_text}")
    available_at, available_note = _available_at_for(observed_day, str(signal.get("market") or ""))
    if available_note:
        notes.append(available_note)
    recorded_at = datetime.now().astimezone().isoformat(timespec="seconds")

    frontmatter = {
        "id": evidence_id,
        "type": "evidence",
        "observed_at": observed_day,
        "available_at": available_at,
        "recorded_at": recorded_at,
        "source_type": "daily-watch",
        "source_path": report_relpath,
        "source_url": None,
        "direction": "pending",
        "confidence": "pending",
        "review_status": "pending",
        "linked_hypotheses": [str(signal["hypothesis_id"])],
        "linked_entities": [ref],
        "metric": metric,
        "dedup_key": build_signal_marker(date_text, signal),
    }
    yaml_text = yaml.safe_dump(
        frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip()
    timing_note = ("\n## 时点注记\n\n" + "\n\n".join(f"- {n}" for n in notes) + "\n"
                   if notes else "")
    content = (
        f"---\n{yaml_text}\n---\n\n"
        f"# {evidence_id}\n\n"
        f"## 观察\n\n{signal['summary']}\n\n"
        f"{timing_note}"
        "## 与假设的关系\n\n"
        f"关联 `{signal['hypothesis_id']}`。这是自动采集的信号，方向和权重待复盘确认。\n\n"
        "## 来源\n\n"
        f"- `{report_relpath}`\n"
    )
    evidence_path.write_text(content, encoding="utf-8")
    return evidence_path, True


def render_signal_evidence(
    date_text: str,
    signal: dict[str, Any],
    report_relpath: str,
    evidence_relpath: str,
) -> str:
    marker = build_signal_marker(date_text, signal)
    evidence_id = build_evidence_id(date_text, signal)
    return "\n".join(
        [
            f"- 🟡 **[{marker}] {evidence_id}** - {signal['summary']}",
            f"  - 证据：{evidence_relpath}",
            f"  - 来源：{report_relpath}",
            "  - 影响：待复盘；本条引用不改变 frontmatter 中的确定性或状态。",
        ]
    )


def append_to_date_block(section_body: str, date_text: str, entry_text: str) -> str:
    date_pattern = re.compile(
        rf"(?ms)^###\s*{re.escape(date_text)}\s*\n(.*?)(?=^###\s|^##\s|^---\s*$|\Z)"
    )
    match = date_pattern.search(section_body)
    if match:
        block = match.group(0).rstrip()
        updated = block + "\n" + entry_text + "\n"
        return section_body[: match.start()] + updated + section_body[match.end() :]

    addition = f"\n\n### {date_text}\n\n{entry_text}\n"
    # If the section ends with a horizontal rule ("---"), insert the new date
    # block before it so entries stay inside the section instead of drifting
    # past the visual separator.
    trailing_rule = re.search(r"(?ms)\n-{3,}[ \t]*\n?\s*\Z", section_body)
    if trailing_rule:
        head = section_body[: trailing_rule.start()].rstrip()
        tail = section_body[trailing_rule.start() :]
        return head + addition + tail
    suffix = "\n" if not section_body.endswith("\n") else ""
    return section_body.rstrip() + addition + suffix


def append_signal_to_hypothesis(
    content: str,
    date_text: str,
    signal: dict[str, Any],
    report_relpath: str,
    evidence_relpath: str,
) -> tuple[str, bool]:
    marker = build_signal_marker(date_text, signal)
    if marker in content:
        return content, False

    entry_text = render_signal_evidence(
        date_text, signal, report_relpath, evidence_relpath
    )
    section_pattern = re.compile(r"(?ms)^##\s*证据时间线\s*\n(.*?)(?=^##\s|\Z)")
    match = section_pattern.search(content)
    if not match:
        appended = (
            content.rstrip()
            + "\n\n## 证据时间线\n\n"
            + f"### {date_text}\n\n{entry_text}\n"
        )
        return appended, True

    updated_body = append_to_date_block(match.group(1), date_text, entry_text)
    updated_content = content[: match.start(1)] + updated_body + content[match.end(1) :]
    return updated_content, True


def apply_hypothesis_updates(
    workspace_root: Path,
    hypotheses: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    report_path: Path,
    date_text: str,
) -> int:
    report_relpath = str(report_path.relative_to(workspace_root)).replace("\\", "/")
    hypothesis_map = {item["id"]: item for item in hypotheses}
    writeback_count = 0

    for signal in signals:
        if not signal.get("auto_writeback"):
            continue
        hypothesis = hypothesis_map.get(str(signal["hypothesis_id"]))
        if not hypothesis:
            continue
        # 去重先行（复查 N-2）：时间线已含 marker 的事件说明证据早写过，必须先判
        # 再落盘——否则 7 天闸门窗内同一事件每个报告日都新建一个 E-报告日 证据
        # 文件（evidence_id 按报告日命名，跨日不撞名，exists() 幂等拦不住）。
        path = Path(hypothesis["path"])
        original = path.read_text(encoding="utf-8")
        evidence_relpath = str(
            _evidence_path_for(workspace_root, date_text, signal)
            .relative_to(workspace_root)
        ).replace("\\", "/")
        updated, changed = append_signal_to_hypothesis(
            original, date_text, signal, report_relpath, evidence_relpath
        )
        if changed and updated != original:
            write_signal_evidence(workspace_root, date_text, signal, report_relpath)
            path.write_text(updated, encoding="utf-8")
            writeback_count += 1

    return writeback_count


# 行情 ticker 与实际交付口径不一致（或需要口径提示）时的注记。
# ticker 名义来源与真实交付源不同时，读者需要在这里看到，而不是翻 README。
SOURCE_CALIBER_NOTES = {
    "HG=F": "交付口径为 LME 三月铜（USD/吨）；ticker 名义是 COMEX 铜（USD/磅），两者价位差约 4 倍",
    "^TNX": "美十债收益率实时快照（东财 171.US10Y；FRED DGS10 T+1 降级备用）",
    "NQ00Y": "小型纳指当月连续期货实时快照（东财 103.NQ00Y，CME E-mini Nasdaq 100；24 小时交易，日报时点为最新成交）",
    "XAUUSD=X": "现货金（伦敦金），USD/盎司",
    "DX-Y.NYB": "ICE 美元指数（DINIW 口径）",
    "000660.KS": "KRW 计价；EOD 源为收盘价非实时",
    "03800.HK": "HKD 计价；港股成交量单位为股（CN 侧为手，跨市场比较需 ×/÷100）",
    "562800.SH": "mootdx/TDX 对沪市 56xxxx 段 ETF 价位系统性 ×10（精度位元数据缺陷，2026-11-06 八服务器实测；涨跌幅正确，价格/昨收/高低偏大 10 倍，用户拍板保持现状记档）",
}


def render_data_coverage(market_data: dict[str, Any], macro_data: dict[str, Any],
                         modules: dict[str, bool]) -> str:
    """Preserve provider dates and distinguish missing data from empty results."""
    meta = market_data.get("meta") or {}
    quote_meta = meta.get("quotes") or {}
    rows = ["### 数据覆盖与日期", "",
            f"- 行情抓取时间（UTC）：{meta.get('fetched_at') or '未提供'}"]
    missing = quote_meta.get("missing_tickers") or []
    if missing:
        rows.append("- 行情未取得：" + "、".join(missing) + "；异动结论仅覆盖成功取得的数据。")
    if not market_data.get("quotes"):
        rows.append("- 没有可用行情，不能据此判断市场没有异动。")
    earnings = meta.get("earnings") or {}
    if modules["earnings"] and earnings.get("state") == "ok":
        # 两通道窗口口径不同（FMP=本周、东财=-40/+35 天），分别展示
        window_parts = []
        if earnings.get("fmp_period_start"):
            window_parts.append(
                f"美股 {earnings['fmp_period_start']} 至 {earnings.get('fmp_period_end', '未提供')}")
        if earnings.get("cn_period_start"):
            window_parts.append(
                f"A 股 {earnings['cn_period_start']} 至 {earnings.get('cn_period_end', '未提供')}")
        if window_parts:
            rows.append("- 财报检查区间：" + "；".join(window_parts) + "。")
    if modules["macro"]:
        macro_meta = macro_data.get("meta") or {}
        if macro_meta.get("reason") == "FMP_API_KEY not set":
            rows.append("- 宏观数据源未配置，本轮未检查。")
        elif not macro_data.get("macro") or macro_meta.get("missing_symbols"):
            rows.append("- 宏观数据未完整取得，N/A 不代表数值为零或没有变化。")
    rows.extend(["", "| 代码 | 来源 | 来源交易日 / 时间（原始口径） |", "|---|---|---|"])
    for quote in market_data.get("quotes") or []:
        stamp = quote.get("tradeDate")
        rows.append(f"| {quote['ticker']} | {quote.get('source') or '未提供'} | {stamp or '未提供，时效待确认'} |")
    caliber_notes = [
        f"- 口径注记（{ticker}）：{note}"
        for ticker, note in SOURCE_CALIBER_NOTES.items()
        if any(q.get("ticker") == ticker for q in market_data.get("quotes") or [])
    ]
    if caliber_notes:
        rows.extend(["", *caliber_notes])
    rows.extend(["", "来源日期不等于报告日期；最近可用报价不承诺为实时行情。"])
    return "\n".join(rows)


def build_report(
    workspace_root: Path,
    config: dict[str, Any],
    template_text: str,
    market_data: dict[str, Any],
    macro_data: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> Path:
    today = date.today()
    weekday_map = {
        "Monday": "星期一",
        "Tuesday": "星期二",
        "Wednesday": "星期三",
        "Thursday": "星期四",
        "Friday": "星期五",
        "Saturday": "星期六",
        "Sunday": "星期日",
    }
    weekday = weekday_map[today.strftime("%A")]
    report_dir = resolve_reports_dir(workspace_root) / today.strftime("%Y-%m")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{today.isoformat()}.md"

    modules = normalize_modules(config)
    quotes = market_data.get("quotes") or []
    movers = market_data.get("movers") or []
    earnings = market_data.get("earnings") or []
    market_table, market_summary = render_market_overview(macro_data, modules["macro"])
    earnings_reported, earnings_upcoming = render_earnings_sections(
        earnings, modules["earnings"], (market_data.get("meta") or {}).get("earnings", {"state": "unknown"})
    )
    context = SafeFormatDict(
        DATE=today.isoformat(),
        WEEKDAY=weekday,
        REPORT_NOTE=(
            "> 说明：本文件由本地脚本先生成数据骨架。新闻检索、原因分析与主题研究应由 "
            "Claude Code 在运行 `/dw-today` 时通过 WebSearch 补充。"
        ),
        MARKET_OVERVIEW_TABLE=market_table,
        MARKET_SUMMARY=market_summary,
        KEY_MOVERS_TABLE=(render_key_movers(movers) if quotes else "> 行情未取得，本轮无法判断是否有异动。"),
        OTHER_MOVERS_TABLE=render_other_movers(quotes, movers),
        EARNINGS_REPORTED_TABLE=earnings_reported,
        EARNINGS_UPCOMING_TABLE=earnings_upcoming,
        THEMES_SECTION=render_themes(config, modules["focus_areas"]),
        HYPOTHESIS_SECTION=build_hypothesis_section(hypotheses, signals, config),
        SOURCES_SECTION=render_sources(modules) + "\n\n" + render_data_coverage(market_data, macro_data, modules),
    )
    rendered = template_text.format_map(context).rstrip() + "\n"
    report_path.write_text(rendered, encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the daily watchlist report (market data, macro, hypothesis signals)."
    )
    parser.parse_args()
    script_dir = Path(__file__).resolve().parent
    workspace_root = find_workspace_root(script_dir)
    config_dir = resolve_config_dir(workspace_root)
    load_env_file(resolve_env_path(config_dir))
    config = load_config(resolve_config_path(config_dir))
    modules = normalize_modules(config)
    template_text = load_template(resolve_template_path(workspace_root))

    market_data = run_json_script(workspace_root, "fetch_market_data.py")
    # 宏观调用序前移到 persist hook 之前（spec §3.3 拍板 #2 ②）：宏观降级清单
    # （meta.missing_symbols）才能进 data-close 的 missing；macro_data 消费位置不变。
    # 宏观失败只降级不连坐（实施评审 #1，见 fetch_macro_or_degrade）。
    macro_data, macro_meta = fetch_macro_or_degrade(workspace_root, modules["macro"])
    _persist_market_data_hook(market_data, macro_meta=macro_meta)
    movers = market_data.get("movers") or []
    earnings = market_data.get("earnings") or []
    hypothesis_enabled, auto_writeback = hypothesis_settings(config)
    hypotheses = read_hypotheses(workspace_root) if hypothesis_enabled else []
    signals = (
        collect_hypothesis_signals(hypotheses, config, movers, earnings)
        if hypothesis_enabled
        else []
    )
    report_path = build_report(
        workspace_root,
        config,
        template_text,
        market_data,
        macro_data,
        hypotheses,
        signals,
    )
    if hypothesis_enabled and auto_writeback:
        apply_hypothesis_updates(
            workspace_root, hypotheses, signals, report_path, date.today().isoformat()
        )
    print(json.dumps({"report_path": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
