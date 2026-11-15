#!/usr/bin/env python3
"""Q-20261115-07：移除 entity 卡 exchange: 字段（dry-run 默认，幂等）。

exchange 是 ticker 后缀的确定函数（.SH→SSE/.SZ→SZSE/.HK→HKEX），
11-15 ticker 统一后纯冗余；未入 _schema.md、无消费者。
两种风格都删：inline 标量（`exchange: SZSE`）与 block 列表
（`exchange:\\n- SZSE`）。备份在 /tmp/exchange_backup_20261115/。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTITIES = ROOT / "wiki" / "entities"


def find_field_block(lines: list[str], field: str) -> tuple[int, int] | None:
    """行级块定位：field: 行 + 后续空行/缩进列表项行（inline 值不含列表项）。"""
    start = None
    prefix = f"{field}:"
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            start = i
            break
    if start is None:
        return None
    end = start + 1
    if lines[start][len(prefix):].strip():
        # inline 标量：单行，吞掉紧随的空行（防双空行）
        while end < len(lines) and lines[end].strip() == "":
            end += 1
        return start, max(start + 1, end - 1)
    # block 列表：吞后续缩进行、'- ' 列表项行与尾随空行
    # （首版漏 '- ' 分支致 dry-run 只删 field 行留孤儿列表项——与
    # ticker_suffix_migration.find_field_block 语义对齐后修复）
    def is_block_line(s: str) -> bool:
        return s.startswith((" ", "\t")) or s.startswith("- ")

    while end < len(lines) and (is_block_line(lines[end]) or lines[end].strip() == ""):
        if lines[end].strip() == "" and end + 1 < len(lines) and not is_block_line(lines[end + 1]):
            end += 1
            break
        end += 1
    return start, end


def main() -> int:
    apply = "--apply" in sys.argv
    targets = [p for p in sorted(ENTITIES.glob("*.md")) if p.name != "_index.md"]
    changed: list[tuple[Path, str]] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if "exchange:" not in text:
            continue
        lines = text.splitlines(keepends=True)
        block = find_field_block(lines, "exchange")
        if block is None:
            changed.append((path, "!!FOUND-BUT-NO-BLOCK"))
            continue
        start, end = block
        removed = "".join(lines[start:end]).strip()
        new_lines = lines[:start] + lines[end:]
        new_text = "".join(new_lines)
        # 删后防止出现连续两个空行（块首尾都吞了空行时）
        while "\n\n\n" in new_text:
            new_text = new_text.replace("\n\n\n", "\n\n")
        changed.append((path, removed))
        if apply:
            path.write_text(new_text, encoding="utf-8")
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] exchange field removal: {len(changed)} cards")
    for path, removed in changed:
        print(f"  {path.relative_to(ROOT)}: {removed!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
