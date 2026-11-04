#!/usr/bin/env python3
"""evidence_lint —— 证据三时点巡检（system/integrations/object-model.md「三时点规范」段）。

逐条检查 evidence/YYYY-MM/*.md 的 frontmatter 三时点字段：

- ``observed_at``：业务时点，日历日（裸 date 或引号串均可，双类型归一为字符串再解析）。
- ``available_at``：必填，ISO 8601 **带时区**时刻；无时区 = 违规（error）。缺失的旧文件
  不算错，进「未核实」清单（缺省口径 available_at = recorded_at，禁止被当作已核实）。
- ``recorded_at``：带时区时刻或裸日期；裸日期按当日 00:00+08:00 归一。

单调性用**日粒度包含判定**（不做 naive/aware 直接比较）：

    date(observed_at) ≤ date(available_at 换算+08:00) ≤ date(recorded_at 换算+08:00)

等号允许（同日可得同日记录合法），违反 = error。时区数学（DST 正确性）是人工责任，
lint 只检查「带时区 + 日粒度单调」，不做跨时区换算校验。

frontmatter 解析是零依赖手写 reader：只认 ``---`` 闭合块内的顶层 ``key: value`` 标量行
（引号剥壳），列表/嵌套结构跳过——三时点字段全是标量，够用，不引 pyyaml。

退出码：有 error → 1；只有未核实或全部干净 → 0。``--json`` 输出机器可读结果。

用法：

    python3 system/scripts/evidence_lint.py                     # 巡检 evidence/
    python3 system/scripts/evidence_lint.py --evidence-root /path/to/evidence
    python3 system/scripts/evidence_lint.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PLUS8 = timezone(timedelta(hours=8))
# 月份目录：YYYY-MM（4 位年-2 位月），只扫这类目录下的 *.md
MONTH_DIR_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# ISO 8601 日期 / 带时区时刻的宽松形状（时区部分单独检查，便于给出精确原因）
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TZ_SUFFIX_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


# ---------------------------------------------------------------------------
# frontmatter 解析（零依赖，仅顶层标量）
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict[str, str]:
    """取 ``---`` 闭合块的顶层 ``key: value`` 标量，值剥引号。

    不在闭合块内、带缩进（列表项/嵌套）、或空值的行一律跳过——``key:`` 空值与
    键缺失同口径（available_at 空值同样落「未核实」清单）。首行 BOM（\\ufeff）
    容忍。无闭合 frontmatter 返回空 dict（由调用方按缺字段处理）。
    """
    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return fields
        if not stripped or line[:1] in (" ", "\t") or stripped.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if value:
            fields[key.strip()] = value
    return fields  # 未闭合：给已收集到的（宽容处理，字段在就能查）


# ---------------------------------------------------------------------------
# 时间解析与归一
# ---------------------------------------------------------------------------

def to_plus8_date(value: str) -> date:
    """任意合法取值 → +08:00 口径的日历日。

    裸日期直接取 date；带时区时刻换算 +08:00 后取 date。
    无时区时刻在这里就是违规，由调用方先检查，本函数不兜底。
    """
    if DATE_RE.match(value):
        return date.fromisoformat(value)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(PLUS8).date()


def has_timezone(value: str) -> bool:
    return bool(TZ_SUFFIX_RE.search(value))


# ---------------------------------------------------------------------------
# 单文件校验
# ---------------------------------------------------------------------------

def lint_file(path: Path) -> tuple[list[dict], bool]:
    """校验单个证据文件，返回 (errors, unverified)。

    error 项：{file, field, reason}；unverified 为布尔（缺 available_at 的旧文件，
    缺省口径 = recorded_at，单独清单、不计成败）。
    """
    rel = str(path)
    fields = parse_frontmatter(path.read_text(encoding="utf-8"))
    errors: list[dict] = []
    unverified = False
    observed_ok = False  # 形状与日期都合法才进单调性分支，避免同一字段重复报错

    # observed_at：必填，必须是合法日历日（裸 date 或引号串等价；形状对但日期非法
    # 如 2026-99-99 同样是 error，不能让单个畸形文件崩掉整个 lint）
    observed = fields.get("observed_at")
    if not observed:
        errors.append({"file": rel, "field": "observed_at", "reason": "缺失"})
    elif not DATE_RE.match(observed):
        errors.append(
            {"file": rel, "field": "observed_at", "reason": f"应为 YYYY-MM-DD 日历日，实际 {observed!r}"}
        )
    else:
        try:
            date.fromisoformat(observed)
            observed_ok = True
        except ValueError:
            errors.append({"file": rel, "field": "observed_at", "reason": f"无法解析：{observed!r}"})

    # recorded_at：必填，裸日期或带时区时刻
    recorded = fields.get("recorded_at")
    if not recorded:
        errors.append({"file": rel, "field": "recorded_at", "reason": "缺失"})
    elif not DATE_RE.match(recorded) and not has_timezone(recorded):
        errors.append(
            {"file": rel, "field": "recorded_at", "reason": f"裸日期或带时区时刻，实际 {recorded!r}"}
        )

    # available_at：缺失 → 未核实清单；存在则必须带时区且可解析
    available = fields.get("available_at")
    if not available:
        unverified = True
    elif not has_timezone(available):
        errors.append(
            {"file": rel, "field": "available_at", "reason": "无时区（必须 ISO 8601 带时区时刻）"}
        )

    # 单调性：日粒度包含 date(observed) ≤ date(available→+08) ≤ date(recorded→+08)
    if observed_ok and observed and recorded and (
        DATE_RE.match(recorded) or has_timezone(recorded)
    ):
        try:
            rec_date = to_plus8_date(recorded)
        except ValueError:
            errors.append({"file": rel, "field": "recorded_at", "reason": f"无法解析：{recorded!r}"})
            rec_date = None
        if rec_date is None:
            return errors, unverified
        if available and has_timezone(available):
            try:
                av_date = to_plus8_date(available)
            except ValueError:
                errors.append(
                    {"file": rel, "field": "available_at", "reason": f"无法解析：{available!r}"}
                )
                av_date = None
            if av_date is not None:
                try:
                    obs_date = date.fromisoformat(observed)
                except ValueError:
                    errors.append(
                        {"file": rel, "field": "observed_at", "reason": f"无法解析：{observed!r}"}
                    )
                    return errors, unverified
                if obs_date > av_date:
                    errors.append({
                        "file": rel,
                        "field": "observed_at/available_at",
                        "reason": f"日粒度单调性违反：observed {obs_date} > available {av_date}",
                    })
                if av_date > rec_date:
                    errors.append({
                        "file": rel,
                        "field": "available_at/recorded_at",
                        "reason": f"日粒度单调性违反：available {av_date} > recorded {rec_date}",
                    })

    return errors, unverified


# ---------------------------------------------------------------------------
# 目录扫描与 CLI
# ---------------------------------------------------------------------------

def lint_tree(evidence_root: Path) -> dict:
    """扫描 evidence_root 下 YYYY-MM/*.md，返回汇总 dict。"""
    errors: list[dict] = []
    unverified: list[str] = []
    scanned = 0
    if evidence_root.is_dir():
        for month_dir in sorted(p for p in evidence_root.iterdir()
                                if p.is_dir() and MONTH_DIR_RE.match(p.name)):
            for md in sorted(month_dir.glob("*.md")):
                scanned += 1
                file_errors, file_unverified = lint_file(md)
                errors.extend(file_errors)
                if file_unverified:
                    unverified.append(str(md))
    return {"scanned": scanned, "errors": errors, "unverified": unverified}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="证据三时点巡检（object-model「三时点规范」）")
    parser.add_argument("--evidence-root", default="evidence", help="evidence 根目录（默认 ./evidence）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    args = parser.parse_args(argv)

    result = lint_tree(Path(args.evidence_root))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["errors"]:
            print(f"错误 {len(result['errors'])} 项：")
            for e in result["errors"]:
                print(f"  [error] {e['file']} :: {e['field']} :: {e['reason']}")
        if result["unverified"]:
            print(f"未核实 {len(result['unverified'])} 项（缺 available_at，缺省口径 = recorded_at）：")
            for f in result["unverified"]:
                print(f"  [unverified] {f}")
        if not result["errors"] and not result["unverified"]:
            print(f"干净：{result['scanned']} 个文件全部通过三时点校验")
        else:
            print(f"共扫描 {result['scanned']} 个文件；error {len(result['errors'])}，"
                  f"未核实 {len(result['unverified'])}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
