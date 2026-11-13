#!/usr/bin/env python3
"""Shared frontmatter parsing: PyYAML fast path + canonical dependency-free fallback.

knowledge_lifecycle / workspace_doctor / workspace_status 三脚本共用，避免
各持一份漂移的降级解析器（历史教训：三份实现各自静默丢不同字段——列表、
折行标量、嵌套段——同一文件在不同脚本下解析结果不同）。

fallback 能力：块式/内联列表、折行标量（PyYAML fold 同语义：单换行→空格）、
null/~ 字面量归一、一层嵌套 dict、缩进注释剥离、顶格非 key 行安全忽略、
进程级单次降级告警。已知与 PyYAML 的类型分歧（review_due 的 date vs str、
纯数字 ticker 的 int vs str）由消费侧 str()/as_list 兜底，不影响 _index
生成与召回。结构级已知局限（真实语料零形态，宽容处理而非拒绝）：
块列表项后缩进续行、空 key 先折行正文再遇列表项、中文 key（顶层
_FIELD_RE 限 ASCII）、内联非空 dict 保持字符串。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # Core Mode remains dependency-free.
    yaml = None

_FALLBACK_WARNING_SHOWN = False

_FALLBACK_HINT = (
    "[frontmatter_parse] PyYAML 不可用，启用降级 frontmatter 解析器"
    "（列表/折行标量/一层嵌套已覆盖）——降级模式产出可能与 PyYAML 存在"
    "类型分歧，建议在装有 PyYAML 的环境运行（如 conda run -n Quant-3.11）"
)


def _warn_fallback_parser_once() -> None:
    global _FALLBACK_WARNING_SHOWN
    if _FALLBACK_WARNING_SHOWN:
        return
    _FALLBACK_WARNING_SHOWN = True
    print(_FALLBACK_HINT, file=sys.stderr)


_FIELD_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.+?)\s*$")
_NESTED_FIELD_RE = re.compile(r"^\s+([^\s:]+)\s*:(?:\s+(.*))?\s*$")


def _parse_fallback(raw: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    current_key: str | None = None  # 空 key 后的块式列表/嵌套挂靠点
    fold_key: str | None = None  # 有值标量的折行挂靠点
    for line in raw.splitlines():
        field = _FIELD_RE.match(line)
        if field:
            key = field.group(1)
            raw_value = field.group(2).strip()
            # 带引号判定须在剥壳前做：k: ''（带引号空串）保持空字符串
            # （PyYAML 语义），与裸空值（→None 挂列表）区分。
            quoted = (
                len(raw_value) >= 2
                and raw_value[0] == raw_value[-1]
                and raw_value[0] in "'\""
            )
            if raw_value in {"null", "~"}:
                # 裸 null/~ 字面量归一为 None，防字符串真值骗过
                # 「晋级前必须留空」类门禁；带引号 "null" 保持字符串语义。
                value = ""
            else:
                value = raw_value.strip("'\"")
            if quoted and not value:
                values[key] = ""
                current_key = None
                fold_key = None
                continue
            current_key = key if not value else None
            if value.startswith("[") and value.endswith("]"):
                values[key] = [
                    item.strip().strip("'\"")
                    for item in value[1:-1].split(",")
                    if item.strip()
                ]
                fold_key = None
            elif value == "{}":
                # 内联空 dict（如 entity_salience: {}）对齐 PyYAML 空 dict
                # 语义；非空内联 dict 真实语料未出现，维持字符串现状。
                values[key] = {}
                fold_key = None
            elif value:
                values[key] = value
                fold_key = key
            else:
                values[key] = None
                # 空 key 保留折行挂靠：兼容「summary: 换行后直接缩进写正文」。
                fold_key = key
            continue
        item = _LIST_ITEM_RE.match(line)
        if item and current_key:
            # None 占位会挡住 append；标量+列表项混排是非法 YAML，
            # 归一为列表而不让 fallback 崩溃。
            if not isinstance(values.get(current_key), list):
                values[current_key] = []
            values[current_key].append(item.group(1).strip("'\""))
            continue
        nested = _NESTED_FIELD_RE.match(line)
        if nested and current_key:
            # 一层嵌套 dict（entity_salience/tagging 等）；嵌套值与顶层
            # 同款 null/~ 归一（带引号空串保持 ''，裸空值→None）。
            if not isinstance(values.get(current_key), dict):
                values[current_key] = {}
            nested_raw = (nested.group(2) or "").strip()
            nested_quoted = (
                len(nested_raw) >= 2
                and nested_raw[0] == nested_raw[-1]
                and nested_raw[0] in "'\""
            )
            if nested_raw in {"null", "~"}:
                nested_value = None
            else:
                nested_value = nested_raw.strip("'\"")
                if not nested_value and not nested_quoted:
                    nested_value = None
            values[current_key][nested.group(1)] = nested_value
            continue
        if nested and fold_key:
            # 缩进 key: value 行属嵌套结构，PyYAML 解析为 mapping 而非标量
            # 折行；不支持更深结构但须终止挂靠，防止被当成正文拼进标量值。
            fold_key = None
            continue
        continuation = line.strip()
        if (
            continuation
            and not continuation.startswith("#")
            and fold_key
            and line[:1].isspace()
        ):
            # 折行标量续行：PyYAML 把单换行折叠为空格，这里按同语义拼接；
            # 缩进注释行与 PyYAML 一致按注释剥离，顶格非 key 行不拼接（安全忽略）。
            base = values[fold_key]
            values[fold_key] = f"{base} {continuation}" if base else continuation
    return values


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)

# 列表折叠检测（EXP-08-01 同日两案修根）：手工 Edit frontmatter 列表时
# 缩进不一致（首项列首 0 空格、后续项 2 空格等）会被 PyYAML 折叠成单
# 字符串（'688702.SH - 688981.SH - 002714.SZ'），parse 不报错、项数静默
# 变少——本检查在解析前对原始文本做两道防线：
# ① 缩进一致性：同一列表块内所有 `- ` 项的缩进宽度必须一致；
# ② 折叠指纹：已知列表型字段的已解析标量若命中「token - token」折叠
#    指纹（无空格 token + 空格-空格-空格 分隔），说明折叠已经发生。
_LIST_KEYS_FOLD_CHECK = {
    "based_on",
    "ticker",
    "related",
    "domain",
    "concepts",
    "tags",
    "linked_entities",
    "linked_hypotheses",
    "knowledge_used",
    "wiki_pages_loaded",
    "evidence",
}
_FOLDED_ITEM_RE = re.compile(r"^\S+(?:\s+-\s+\S+)+$")


def check_list_integrity(path: Path) -> list[str]:
    """Return violation messages for folded/misindented frontmatter lists.

    空 list = 通过。检测对 PyYAML 与 fallback 两种解析路径都成立
    （第 ② 道走解析结果，第 ① 道走原始文本）。
    """
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return [f"{path.name}: 无法读取（{exc}）"]
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return []
    raw = match.group(1)
    violations: list[str] = []

    # ① 原始文本：同列表块内缩进一致性
    current_key: str | None = None
    current_indent: int | None = None
    for lineno, line in enumerate(raw.splitlines(), start=2):  # +1 frontmatter 起始行
        item = re.match(r"^(\s*)-\s", line)
        if item:
            # 列表项先于顶层 key 判定：合法列表允许项与 key 同列（0 缩进）
            if current_key:
                indent = len(item.group(1))
                if current_indent is None:
                    current_indent = indent
                elif indent != current_indent:
                    violations.append(
                        f"{path.name}: 第 {lineno} 行列表项缩进 {indent} 与本块首项 "
                        f"{current_indent} 不一致（字段 {current_key.rstrip(':')}）——"
                        "YAML 会把缩进异常项折叠进前一项"
                    )
            continue
        if not line[:1].isspace() and line.strip():
            top = re.match(r"^[A-Za-z_][\w-]*:(?:\s|$)", line)
            current_key = top.group(0) if top else None
            current_indent = None

    # ② 解析结果：已知列表字段的折叠指纹
    if yaml is not None:
        try:
            payload = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            return violations
    else:
        payload = _parse_fallback(raw)
    if isinstance(payload, dict):
        for key in _LIST_KEYS_FOLD_CHECK:
            value = payload.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str) and _FOLDED_ITEM_RE.match(item):
                    violations.append(
                        f"{path.name}: 字段 {key} 的列表项「{item}」命中折叠指纹"
                        "（疑似多项被 YAML 合并为单字符串）"
                    )
    return violations


def parse_frontmatter_file(path: Path) -> tuple[dict[str, Any], str, str | None]:
    """Return (meta, content, error); error is None on success."""
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return {}, "", str(exc)
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
    if not match:
        return {}, content, "missing frontmatter"
    raw = match.group(1)
    if yaml is not None:
        try:
            payload = yaml.safe_load(raw) or {}
        except yaml.YAMLError as exc:
            return {}, content, f"invalid YAML: {exc}"
        if not isinstance(payload, dict):
            return {}, content, "frontmatter is not a mapping"
        return payload, content, None
    _warn_fallback_parser_once()
    return _parse_fallback(raw), content, None
