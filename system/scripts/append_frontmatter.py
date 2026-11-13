#!/usr/bin/env python3
"""向 Markdown frontmatter 的列表/映射字段安全追加项——替代手工 Edit。

修根背景（2026-11-13，EXP-20261108-01 同日两案）：手工 Edit frontmatter
列表时缩进不一致，PyYAML 把缩进错位项静默折叠成单字符串（'A - B - C'），
parse 不报错、项数变少。本工具三点保证：

1. 只重写目标字段块，其余字节不动；
2. 新项缩进继承本块既有首项（列首 0 缩进与 2 缩进两种仓库风格都兼容，
   新建列表统一列首 0 缩进，与 yaml.safe_dump 默认一致）；
3. 写出后跑 check_list_integrity + 项数复验（追加后列表项数必须恰好 +N），
   任何异常响亮失败，不落半成品。

用法：
    # 列表追加（--item 可重复）
    python system/scripts/append_frontmatter.py wiki/explorations/X.md \
        --list ticker --item 002714.SZ --item 02714.HK

    # 嵌套映射追加（如 entity_salience）
    python system/scripts/append_frontmatter.py wiki/explorations/X.md \
        --map entity_salience --entry 002714.SZ=core

    # 预览不落盘
    ... --dry-run

幂等：待加项已存在则跳过并提示，不产生重复项。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import yaml  # noqa: E402

from frontmatter_parse import check_list_integrity  # noqa: E402

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_TOP_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:")


def _list_items(payload: dict, field: str) -> list:
    value = payload.get(field)
    if isinstance(value, list):
        return [item for item in value]
    return []


def append_to_file(
    path: Path,
    *,
    list_field: str | None = None,
    items: list[str] | None = None,
    map_field: str | None = None,
    entry: tuple[str, str] | None = None,
    dry_run: bool = False,
) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SystemExit(f"ERROR: {path.name} 无 frontmatter")
    raw = match.group(1)
    body = text[match.end() :]
    try:
        payload = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"ERROR: frontmatter 不是合法 YAML：{exc}")

    lines = raw.split("\n")
    applied: list[str] = []
    skipped: list[str] = []

    def field_block_range(field: str) -> tuple[int, int] | None:
        """返回字段块 [起始行号, 结束行号(不含下一顶层 key)]；None=字段不存在。"""
        start = None
        for idx, line in enumerate(lines):
            if _TOP_KEY_RE.match(line) and line.split(":", 1)[0] == field:
                start = idx
                break
        if start is None:
            return None
        end = len(lines)
        for idx in range(start + 1, len(lines)):
            if _TOP_KEY_RE.match(lines[idx]):
                end = idx
                break
        return start, end

    # ── 列表追加 ─────────────────────────────────────────────
    if list_field is not None:
        existing = [str(v) for v in _list_items(payload, list_field)]
        current_value = payload.get(list_field)
        if current_value is not None and not isinstance(current_value, list):
            raise SystemExit(
                f"ERROR: 字段 {list_field} 是标量（{current_value!r}），"
                "手工转列表后再用本工具"
            )
        new_items = [it for it in (items or []) if it not in existing]
        skipped = [it for it in (items or []) if it in existing]
        if new_items:
            block = field_block_range(list_field)
            if block is None:
                # 新建字段：追加到 frontmatter 末尾，列首 0 缩进
                insert_at = len(lines)
                while insert_at > 0 and not lines[insert_at - 1].strip():
                    insert_at -= 1
                addition = [f"{list_field}:"] + [f"- {it}" for it in new_items]
                lines[insert_at:insert_at] = addition
            else:
                start, end = block
                block_lines = lines[start:end]
                item_lines = [l for l in block_lines[1:] if re.match(r"^\s*-\s", l)]
                inline = re.match(r"^[A-Za-z_][\w-]*:\s*\[(.*)\]\s*$", block_lines[0])
                if inline is not None:
                    # 内联列表转块式（保序）
                    inner = inline.group(1).strip()
                    rendered = [f"{list_field}:"]
                    if inner:
                        rendered += [f"- {piece.strip()}" for piece in inner.split(",")]
                    rendered += [f"- {it}" for it in new_items]
                    lines[start:end] = rendered
                else:
                    indent = (
                        re.match(r"^(\s*)-", item_lines[0]).group(1)  # type: ignore[union-attr]
                        if item_lines
                        else ""
                    )
                    insert_at = end
                    while insert_at > start + 1 and not lines[insert_at - 1].strip():
                        insert_at -= 1
                    addition = [f"{indent}- {it}" for it in new_items]
                    lines[insert_at:insert_at] = addition
            applied += [f"{list_field}: {it}" for it in new_items]

    # ── 嵌套映射追加 ─────────────────────────────────────────
    if map_field is not None:
        if entry is None:
            raise SystemExit("ERROR: --map 需要 --entry KEY=VALUE")
        key, value = entry
        current = payload.get(map_field)
        if current is not None and not isinstance(current, dict):
            raise SystemExit(f"ERROR: 字段 {map_field} 不是映射")
        if isinstance(current, dict) and key in current:
            skipped.append(f"{map_field}.{key}（已存在={current[key]}）")
        else:
            block = field_block_range(map_field)
            if block is None:
                insert_at = len(lines)
                while insert_at > 0 and not lines[insert_at - 1].strip():
                    insert_at -= 1
                lines[insert_at:insert_at] = [f"{map_field}:", f"  {key}: {value}"]
            else:
                start, end = block
                insert_at = end
                while insert_at > start + 1 and not lines[insert_at - 1].strip():
                    insert_at -= 1
                lines[insert_at:insert_at] = [f"  {key}: {value}"]
            applied.append(f"{map_field}.{key}={value}")

    if not applied:
        return {"path": str(path), "applied": [], "skipped": skipped, "written": False}

    new_raw = "\n".join(lines)
    new_text = f"---\n{new_raw}\n---\n{body}"

    # 写出前三重复验：解析成功 + 目标项数 + 无折叠
    try:
        new_payload = yaml.safe_load(new_raw) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"ERROR: 拟写入内容不是合法 YAML（未落盘）：{exc}")
    if list_field is not None:
        expect = len(_list_items(payload, list_field)) + len(
            [a for a in applied if a.startswith(f"{list_field}: ")]
        )
        actual = len(_list_items(new_payload, list_field))
        if actual != expect:
            raise SystemExit(
                f"ERROR: 复验失败（未落盘）：{list_field} 期望 {expect} 项，"
                f"解析得 {actual} 项——疑似折叠"
            )
    tmp = path.with_suffix(path.suffix + ".tmp-append")
    tmp.write_text(new_text, encoding="utf-8")
    violations = check_list_integrity(tmp)
    if violations:
        tmp.unlink(missing_ok=True)
        raise SystemExit(
            "ERROR: 写出内容列表校验失败（未落盘）：" + "；".join(violations)
        )
    tmp.unlink(missing_ok=True)

    if dry_run:
        return {"path": str(path), "applied": applied, "skipped": skipped, "written": False, "dry_run": True}
    path.write_text(new_text, encoding="utf-8")
    return {"path": str(path), "applied": applied, "skipped": skipped, "written": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--list", dest="list_field", help="列表字段名（如 ticker/based_on）")
    parser.add_argument("--item", action="append", default=[], help="待追加项（可重复）")
    parser.add_argument("--map", dest="map_field", help="嵌套映射字段名（如 entity_salience）")
    parser.add_argument("--entry", help="KEY=VALUE（配合 --map）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.list_field and not args.map_field:
        parser.error("需要 --list 或 --map")
    if args.list_field and not args.item:
        parser.error("--list 需要 --item")
    entry = None
    if args.entry:
        if "=" not in args.entry:
            parser.error("--entry 格式须为 KEY=VALUE")
        key, value = args.entry.split("=", 1)
        entry = (key, value)
    result = append_to_file(
        args.file,
        list_field=args.list_field,
        items=args.item,
        map_field=args.map_field,
        entry=entry,
        dry_run=args.dry_run,
    )
    import json

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
