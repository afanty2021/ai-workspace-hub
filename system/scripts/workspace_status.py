#!/usr/bin/env python3
"""Summarize actionable research-workspace state without changing files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from frontmatter_parse import parse_frontmatter_file  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def find_workspace_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "workspace" / "workspace-config.md").is_file():
            return candidate
    return current


def parse_frontmatter(path: Path) -> dict[str, Any]:
    # 解析实现在共享模块 frontmatter_parse（与 knowledge_lifecycle /
    # workspace_doctor 同源，防三份降级解析器各自漂移）；错误时返回 {}
    # 与旧降级行为一致（status 看板容错读，不因单文件损坏中断）。
    meta, _, _error = parse_frontmatter_file(path)
    return meta


def relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def pending_queue_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[-1].lower() != "pending":
            continue
        rows.append({"id": cells[0], "type": cells[1], "object": cells[2]})
    return rows


_MODULE_NUM_RE = re.compile(r"四模块第\s*([0-9]+(?:\s*[/~]\s*[0-9]+)*)\s*次")


def _expand_module_numbers(raw: str) -> list[int]:
    """展开「四模块第 X 次」捕获组：支持 N、N/M（斜杠合写）、N~M（区间）三种写法。"""
    tokens = [t.strip() for t in re.split(r"[/~]", raw) if t.strip()]
    numbers = [int(t) for t in tokens]
    if "~" in raw and len(numbers) >= 2:
        return list(range(numbers[0], numbers[-1] + 1))
    return numbers


def check_module_number_ledger(root: Path) -> dict[str, Any]:
    """四模块序号账本全局对账（Q-20261114-04 修根 B）：报告声明 vs profile 观察行。

    防线目标（friction-log 2026-11-14 两案，漏记/撞号家族第 3 案）：
    ① 漏记——报告正文声明了序号但 profile「本轮观察」缺该行；
    ② 撞号——同一序号被多份不同报告声明（无人值守批次子 agent 自记序号旁路）；
    ③ profile 撞行——同一序号多行。
    单向检查：报告正文不写序号声明的票不报（序号声明非报告必填项）。
    """
    research_dir = root / "output" / "research"
    report_nums: dict[int, set[str]] = {}
    for path in sorted(research_dir.rglob("*.md")):
        # preflight/ 是回执目录：回执文本会引用其他研究的序号（命卡上下文），
        # 不研究报告本体（真实冒烟 2026-11-14：18/19/31 撞号均为回执引用误报）。
        if "preflight" in path.relative_to(research_dir).parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _MODULE_NUM_RE.finditer(text):
            for n in _expand_module_numbers(match.group(1)):
                report_nums.setdefault(n, set()).add(relative(path, root))
    profile_path = root / "workspace" / "research-profile.md"
    profile_nums: dict[int, int] = {}
    if profile_path.is_file():
        text = profile_path.read_text(encoding="utf-8", errors="ignore")
        section = text
        if "## 本轮观察" in text:
            section = text.split("## 本轮观察", 1)[1].split("\n## ", 1)[0]
        for match in _MODULE_NUM_RE.finditer(section):
            for n in _expand_module_numbers(match.group(1)):
                profile_nums[n] = profile_nums.get(n, 0) + 1
    missing = sorted(n for n in report_nums if n not in profile_nums)
    dup_reports = {
        str(n): sorted(paths)
        for n, paths in sorted(report_nums.items())
        if len(paths) > 1
    }
    dup_profile = sorted(n for n, c in profile_nums.items() if c > 1)
    return {
        "reports_declared": len(report_nums),
        "profile_rows": len(profile_nums),
        "missing_in_profile": missing,
        "duplicate_across_reports": dup_reports,
        "duplicate_in_profile": dup_profile,
        "ok": not (missing or dup_reports or dup_profile),
    }


# —— 观察行触发器对账（Q-20261115-06③：M-1 浔兴压缩案机械化）——
# 行首研究 ID 段双键定位报告：R-id（R20261111-02-tencent-0700.md 命名系）
# 或裸码（2026-11-15-yili-600887-… 命名系）；两键都不在文件名（勤辰类
# 拼音命名）则跳过对账，仅做行内 lint。
_TRIGGER_TOK_RE = re.compile(r"\bT([0-9]{1,2})\b")
_TRIGGER_RANGE_RE = re.compile(r"\bT([0-9]{1,2})\s*[-–~]\s*T?([0-9]{1,2})\b")
_ROW_HEADER_RE = re.compile(r"^- [0-9]{4}-[0-9]{2}-[0-9]{2}（([^）]*)）")
_ROW_RID_RE = re.compile(r"\bR([0-9]{8}-[0-9]{2,3})\b")
_ROW_CODE_RE = re.compile(r"(?<![0-9])([0-9]{4,6})(?![0-9])")
_MAX_TRIGGER_ID = 30  # 触发器编号史最大 T13；T80/T05/T22 类行文噪音滤除


def _trigger_ids(text: str) -> set[int]:
    """提取 T 编号集合：单点（T3）与区间（T1-T7/T9-T11）都展开。"""
    ids: set[int] = set()
    for m in _TRIGGER_RANGE_RE.finditer(text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= hi <= _MAX_TRIGGER_ID:
            ids.update(range(lo, hi + 1))
    for m in _TRIGGER_TOK_RE.finditer(text):
        n = int(m.group(1))
        if n <= _MAX_TRIGGER_ID:
            ids.add(n)
    return ids


def _report_trigger_ids(text: str) -> set[int]:
    """报告侧 T 编号=观察哨/触发器节内提取（整文 grep 会吃进 T80/T22 行文噪音）。"""
    ids: set[int] = set()
    in_section = False
    for line in text.splitlines():
        if line.startswith("#"):
            in_section = ("观察哨" in line) or ("触发器" in line)
            if in_section:
                ids |= _trigger_ids(line)
            continue
        stripped = line.strip()
        # 节起判允许「- **时间结论**（触发器…）」类列表加粗前缀
        # （腾讯案：T4 藏在该块、漏判后报告侧只剩 T1-T3）。
        if re.match(r"(?:-\s*)?\*\*", stripped) and (
            "观察哨" in stripped or "触发器" in stripped
        ):
            in_section = True
            ids |= _trigger_ids(stripped)
            continue
        # 节内只吸收含 T 记号的行——绕开条目格式枚举（①②③ 圆圈行/表格/
        # 缩进子弹等变体全兼容），节边界（下一个 # 头）之外不吸收。
        if in_section and _TRIGGER_TOK_RE.search(line):
            ids |= _trigger_ids(line)
    return ids


def check_profile_trigger_ledger(root: Path) -> dict[str, Any]:
    """观察行触发器对账（Q-20261115-06③ 修根）：报告触发器表 ↔ profile 行 T 编号。

    病灶（M-1 浔兴案）：报告/message 均 T1-T6、行压缩为 T1/T2——人工才能
    发现不对称。规则：①凡报告有编号触发器表，行必须携带覆盖其全部编号的
    「触发器 T…」段（等号列举或 T1-Tn 引用式均可）；②行含 T 编号必须挂
    「触发器」关键词（E 类括号内嵌式回收）；③行含「触发器」关键词必须有
    编号（B 类散文式回收）。
    """
    profile_path = root / "workspace" / "research-profile.md"
    research_dir = root / "output" / "research"
    issues: list[str] = []
    rows_total = 0
    reconciled = 0
    if not profile_path.is_file():
        return {"rows": 0, "reconciled": 0, "issues": [], "ok": True}
    # 双通道定位报告：①四模块序号连接——报告声明「四模块第 N 次」↔行内
    # 同声明，序号全局唯一（中芯/华友/日经等头注无码、文件名无 R-id 的行
    # 只有此键能入账）；②文件名键（R-id/裸码 glob）。两通道并集。
    # 通道③：报告自身 R-id——preflight 回执行 `preflight/RXXXXXXXX-XX.md`
    # 是报告自己的研究 ID 精确指纹（早期报告不声明四模块序号、文件名也
    # 不带 R-id，只剩此键）。三通道并集。
    trigger_by_path: dict[Path, set[int]] = {}
    module_report_ids: dict[int, set[int]] = {}
    selfrid_report_ids: dict[str, set[int]] = {}
    for path in sorted(research_dir.rglob("*.md")):
        if "preflight" in path.relative_to(research_dir).parts:
            continue
        report_text = path.read_text(encoding="utf-8", errors="ignore")
        ids = _report_trigger_ids(report_text)
        trigger_by_path[path] = ids
        for m in _MODULE_NUM_RE.finditer(report_text):
            for n in _expand_module_numbers(m.group(1)):
                module_report_ids.setdefault(n, set()).update(ids)
        # 通道③主源=frontmatter preflight_id 字段（报告自身 R-id 自指纹，
        # PF-RXXXXXXXX-XX-哈希 式）；兜底=行内回执行路径（含 -preflight.md
        # 后缀变体）——早期报告两种格式并存（西超 PF- 裸式/华友后缀式）。
        m = re.search(
            r"^\s*preflight_id:\s*PF-R([0-9]{8}-[0-9]{2,3})",
            report_text,
            re.MULTILINE,
        )
        if m:
            selfrid_report_ids.setdefault(f"R{m.group(1)}", set()).update(ids)
        else:
            for m2 in re.finditer(
                r"preflight/R([0-9]{8}-[0-9]{2,3})(?:-preflight)?\.md", report_text
            ):
                selfrid_report_ids.setdefault(f"R{m2.group(1)}", set()).update(ids)
    text = profile_path.read_text(encoding="utf-8", errors="ignore")
    section = text
    if "## 本轮观察" in text:
        section = text.split("## 本轮观察", 1)[1].split("\n## ", 1)[0]
    for row in section.splitlines():
        if not row.startswith("- 20"):
            continue
        rows_total += 1
        label = row[:36]
        row_ids = _trigger_ids(row)
        has_kw = "触发器" in row
        if has_kw and not row_ids:
            issues.append(f"{label}…：行含「触发器」但无 T 编号")
        if row_ids and not has_kw:
            issues.append(f"{label}…：T 编号未挂「触发器」段（散嵌正文）")
        # 对账只针对四模块研究摘要行：惯例确认/模板变更等非研究行
        # （无「四模块第 N 次」声明）不携带触发器，豁免（首跑抓到
        # 「R20261111-12/13 收尾」行误报后加）。
        if "四模块第" not in row:
            continue
        header = _ROW_HEADER_RE.match(row)
        if header is None:
            continue
        # 头注内日期（补录 2026-11-14 等）剥掉再取码——「2026」被当
        # code 会 glob 命中全年报告，并集污染成 T13（首跑三全案）；
        # 环视防把 R-id 内部（R20261110-06 的「1110-06」）误当日期
        # （二跑南瑞案：剩「2026」同样全局污染）。
        header_text = re.sub(
            r"(?<![0-9])[0-9]{4}[-/][0-9]{2}([-/][0-9]{2})?(?![0-9])",
            " ",
            header.group(1),
        )
        keys: set[str] = set(_ROW_CODE_RE.findall(header_text))
        keys.update(f"R{rid}" for rid in _ROW_RID_RE.findall(header.group(1)))
        report_ids: set[int] = set()
        for m in _MODULE_NUM_RE.finditer(row):
            for n in _expand_module_numbers(m.group(1)):
                report_ids |= module_report_ids.get(n, set())
        for key in keys:
            if key in selfrid_report_ids:
                report_ids |= selfrid_report_ids[key]
        if not keys and not report_ids:
            continue
        for key in keys:
            for path in research_dir.rglob(f"*{key}*.md"):
                if path in trigger_by_path:
                    report_ids |= trigger_by_path[path]
        if not report_ids:
            continue
        reconciled += 1
        if not row_ids:
            issues.append(
                f"{label}…：报告有触发器表 T1-T{max(report_ids)} 但行未列"
            )
        else:
            # 判据=行集合 ⊇ 报告集合（max 相等不够：巨星行仅 T8 散提、
            # 报告 T1-T8，max 同为 8 但行并未覆盖 T1-T7）。
            missing_ids = sorted(report_ids - row_ids)
            if missing_ids:
                issues.append(
                    f"{label}…：行缺 T{'、'.join(map(str, missing_ids))}"
                    f"（报告触发器表 T1-T{max(report_ids)}，M-1 压缩）"
                )
    return {
        "rows": rows_total,
        "reconciled": reconciled,
        "issues": issues,
        "ok": not issues,
    }


def is_overdue(value: Any) -> bool:
    if not value:
        return False
    try:
        return date.fromisoformat(str(value)[:10]) < date.today()
    except ValueError:
        return False


def collect_status(root: Path) -> dict[str, Any]:
    active_research: list[dict[str, str]] = []
    research_without_preflight: list[str] = []
    for path in sorted((root / "output" / "research").glob("*.md")):
        meta = parse_frontmatter(path)
        status = str(meta.get("status") or "draft").lower()
        if status in {"draft", "active", "in_progress", "进行中"}:
            active_research.append(
                {
                    "id": str(meta.get("id") or path.stem),
                    "path": relative(path, root),
                    "status": status,
                    "preflight_id": str(meta.get("preflight_id") or ""),
                }
            )
            if not meta.get("preflight_id"):
                research_without_preflight.append(str(meta.get("id") or path.stem))

    open_hypotheses: list[dict[str, Any]] = []
    overdue_reviews: list[str] = []
    closed_statuses = {"closed", "archived", "rejected", "推翻", "已兑现", "暂停"}
    for path in sorted((root / "hypothesis").glob("H*.md")):
        meta = parse_frontmatter(path)
        status = str(meta.get("status") or "unknown")
        filename_match = re.match(r"H\d+", path.stem)
        hypothesis_id = str(
            meta.get("id") or (filename_match.group(0) if filename_match else path.stem)
        )
        if status.lower() not in closed_statuses and status not in closed_statuses:
            open_hypotheses.append(
                {
                    "id": hypothesis_id,
                    "status": status,
                    "certainty": meta.get("certainty"),
                    "path": relative(path, root),
                }
            )
        if is_overdue(meta.get("next_review_at")):
            overdue_reviews.append(hypothesis_id)

    pending_evidence: list[dict[str, str]] = []
    for path in sorted((root / "evidence").glob("**/*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta = parse_frontmatter(path)
        if str(meta.get("review_status") or "pending").lower() == "pending":
            pending_evidence.append(
                {
                    "id": str(meta.get("id") or path.stem),
                    "path": relative(path, root),
                }
            )

    knowledge_counts: dict[str, dict[str, int]] = {}
    overdue_knowledge_reviews: list[dict[str, str]] = []
    knowledge_promotion_candidates: list[dict[str, str]] = []
    knowledge_locations = {
        "exploration": (root / "wiki/explorations",),
        "pattern": (root / "wiki/patterns", root / "workspace/patterns"),
        "rule": (root / "wiki/rules",),
    }
    for knowledge_type, folders in knowledge_locations.items():
        for folder in folders:
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.md")):
                if path.name.startswith("_") or path.name.lower() == "readme.md":
                    continue
                meta = parse_frontmatter(path)
                status = str(meta.get("status") or "missing")
                knowledge_counts.setdefault(knowledge_type, {})[status] = (
                    knowledge_counts.setdefault(knowledge_type, {}).get(status, 0) + 1
                )
                item_id = str(meta.get("id") or path.stem)
                if is_overdue(meta.get("review_due")):
                    overdue_knowledge_reviews.append(
                        {"id": item_id, "type": knowledge_type, "path": relative(path, root)}
                    )
                confirmations = meta.get(
                    "primary_confirmations"
                    if knowledge_type == "pattern"
                    else "independent_confirmations"
                )
                try:
                    confirmation_count = int(confirmations or 0)
                except (TypeError, ValueError):
                    confirmation_count = 0
                reason = ""
                if knowledge_type == "exploration" and status == "validated":
                    reason = "复盘是否提炼为 pattern"
                elif knowledge_type == "pattern" and status == "active" and confirmation_count >= 3:
                    reason = "已达到 rule 的案例数量门槛"
                elif knowledge_type == "rule" and status == "candidate" and confirmation_count >= 3:
                    reason = "可确认是否启用"
                if reason:
                    knowledge_promotion_candidates.append(
                        {"id": item_id, "type": knowledge_type, "reason": reason, "path": relative(path, root)}
                    )

    queue = pending_queue_rows(root / "workspace" / "review-queue.md")
    watchlist = root / "config" / "daily-watchlist-watchlist.md"
    profile_path = root / "workspace" / "research-profile.md"
    profile_text = (
        profile_path.read_text(encoding="utf-8-sig") if profile_path.is_file() else ""
    )
    version_match = re.search(r"^- version:\s*`?([^`\n]+)", profile_text, re.MULTILINE)
    count_match = re.search(
        r"^- calibrated_research_count:\s*`?(\d+)", profile_text, re.MULTILINE
    )

    recommendations: list[str] = []
    if pending_evidence:
        recommendations.append(
            f"复盘 {len(pending_evidence)} 条待确认新证据，再决定是否调整假设。"
        )
    if queue:
        recommendations.append(f"处理 {len(queue)} 条待确认动作。")
    if overdue_reviews:
        recommendations.append("复盘已到期假设：" + "、".join(overdue_reviews) + "。")
    if overdue_knowledge_reviews:
        recommendations.append(f"复盘 {len(overdue_knowledge_reviews)} 张已到期知识卡。")
    if knowledge_promotion_candidates:
        recommendations.append(f"审查 {len(knowledge_promotion_candidates)} 张知识卡是否应晋级。")
    if active_research:
        recommendations.append("继续或收口进行中的研究。")
    if research_without_preflight:
        recommendations.append(
            "为进行中研究补 Research Preflight：" + "、".join(research_without_preflight) + "。"
        )
    if not watchlist.is_file():
        recommendations.append("初始化唯一执行股票池 config/daily-watchlist-watchlist.md。")
    if not recommendations:
        recommendations.append("当前没有积压；可以开始新研究或生成今日日报。")

    ledger = check_module_number_ledger(root)
    if not ledger["ok"]:
        parts = []
        if ledger["missing_in_profile"]:
            parts.append("报告声明但 profile 缺观察行：" + "、".join(map(str, ledger["missing_in_profile"])))
        if ledger["duplicate_across_reports"]:
            parts.append(
                "撞号（多报告同序号）："
                + "、".join(f"第 {n} 次×{len(fs)}" for n, fs in ledger["duplicate_across_reports"].items())
            )
        if ledger["duplicate_in_profile"]:
            parts.append("profile 重复行：" + "、".join(map(str, ledger["duplicate_in_profile"])))
        recommendations.append("四模块序号账本异常——" + "；".join(parts) + "。")

    trigger_ledger = check_profile_trigger_ledger(root)
    if not trigger_ledger["ok"]:
        shown = trigger_ledger["issues"][:6]
        more = len(trigger_ledger["issues"]) - len(shown)
        recommendations.append(
            "观察行触发器对账异常——"
            + "；".join(shown)
            + (f"；等共 {more} 项…" if more > 0 else "")
            + "。"
        )

    return {
        "workspace": str(root),
        "active_research": active_research,
        "research_preflight": {
            "receipts": len(list((root / "output/research/preflight").glob("*.md"))),
            "missing_for_active_research": research_without_preflight,
        },
        "open_hypotheses": open_hypotheses,
        "pending_evidence": pending_evidence,
        "pending_reviews": queue,
        "overdue_hypothesis_reviews": overdue_reviews,
        "knowledge_lifecycle": {
            "counts": knowledge_counts,
            "overdue_reviews": overdue_knowledge_reviews,
            "promotion_candidates": knowledge_promotion_candidates,
        },
        "watchlist_ready": watchlist.is_file(),
        "research_profile": {
            "version": version_match.group(1).strip() if version_match else "unknown",
            "calibrated_research_count": int(count_match.group(1)) if count_match else 0,
        },
        "module_number_ledger": ledger,
        "profile_trigger_ledger": trigger_ledger,
        "recommendations": recommendations,
    }


def render_text(status: dict[str, Any]) -> str:
    lines = ["AI Workspace Hub 状态", f"工作区：{status['workspace']}", ""]
    lines.extend(
        [
            f"进行中研究：{len(status['active_research'])}",
            f"Preflight 回执：{status['research_preflight']['receipts']}（进行中缺失 {len(status['research_preflight']['missing_for_active_research'])}）",
            f"开放假设：{len(status['open_hypotheses'])}",
            f"待复盘证据：{len(status['pending_evidence'])}",
            f"待确认动作：{len(status['pending_reviews'])}",
            f"已到期复盘：{len(status['overdue_hypothesis_reviews'])}",
            f"到期知识卡：{len(status['knowledge_lifecycle']['overdue_reviews'])}",
            f"知识晋级候选：{len(status['knowledge_lifecycle']['promotion_candidates'])}",
            f"执行股票池：{'READY' if status['watchlist_ready'] else 'MISSING'}",
            f"四模块序号账本：{'OK' if status['module_number_ledger']['ok'] else '异常'}（报告声明 {status['module_number_ledger']['reports_declared']} 序号 / profile {status['module_number_ledger']['profile_rows']} 行）",
            f"观察行触发器对账：{'OK' if status['profile_trigger_ledger']['ok'] else '异常'}（观察行 {status['profile_trigger_ledger']['rows']} / 对账 {status['profile_trigger_ledger']['reconciled']} / 异常 {len(status['profile_trigger_ledger']['issues'])}）",
            "",
            "建议下一步：",
        ]
    )
    lines.extend(f"- {item}" for item in status["recommendations"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    status = collect_status(find_workspace_root(args.root))
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(render_text(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
