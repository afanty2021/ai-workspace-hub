#!/usr/bin/env python3
"""ticker 后缀统一一次性迁移（2026-11-15 立项，Q-20261115-06①）。

目标形态（wiki/entities + wiki/sources 的 frontmatter ticker 与
entity_salience 键）：

1. 数字码一律带交易所后缀：002003.SZ / 00700.HK / 010736.OF；
   字母符号码（NVDA/MSFT）与 HK./US. 前缀形态保持不动；
2. HK 码统一港交所官方 5 位带前导零（2319.HK→02319.HK、0700.HK→00700.HK）；
3. 同卡去重（000807 + 000807.SZ → 000807.SZ）；
4. entity_salience 键随 ticker 同步改名；纯数字键无论是否改名一律
   加引号（消灭 `002003:` 未加引号被 YAML 按八进制解析成 int key 的坑）。

6 位 0 开头码的段规则：01x/02x/03x=场外基金专用段直接 .OF；
000xxx/002xxx 为深市股票与场外基金并存段，按 title/domain 基金关键词
判别并在决策表标注人工复核。文件名与 [[互链]] 不动（身份比对由
wiki_tagger._same_security_code 前导零归一承接）。BOM/CRLF 与 flow 风格
entity_salience 不自动改写，转人工处理。

用法：
    python system/scripts/ticker_suffix_migration.py            # dry-run 决策表
    python system/scripts/ticker_suffix_migration.py --apply    # 落盘
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

FUND_HINTS = re.compile(r"基金|联接|混合|灵活配置|净值|指数增强|QDII|ETF联接")
HK_RE = re.compile(r"^(\d{1,5})\.HK$")
DIGITS_RE = re.compile(r"^\d+$")
# 八进制污染还原表（2026-11-13 修根案残留：010736 被解析成 4574 固化在卡里）
POLLUTION_FIX = {"4574": ("010736.OF", "八进制污染还原（010736→4574 案残留）")}
SALIENCE_LINE_RE = re.compile(r"^(\s*)(.+?):(\s*)([^#\n]*?)\s*$")


def find_field_block(lines: list[str], field: str) -> tuple[int, int] | None:
    """行级定位 frontmatter 顶层字段块（首版 regex 的懒惰匹配在列表项行
    「- x」行首即 \\S 提前停、导致重写残留旧行——修根改行级收集）。

    块 = `field:` 行 + 其后所有「空行 / 缩进行 / '- ' 列表项行 / 含注释行」，
    遇下一个顶层键（非空且行首即非空白、非 '-'）即止。返回 [起始行, 结束行)
    的行号区间；未找到返回 None。
    """
    header = f"{field}:"
    start = None
    for i, line in enumerate(lines):
        if line.rstrip("\n").startswith(header):
            start = i
            break
        if line.startswith((" ", "\t", "-")) or not line.strip():
            continue  # 尚在上一字段块内（frontmatter 顶层键之前）
    if start is None:
        return None
    end = start + 1
    while end < len(lines):
        stripped = lines[end].rstrip("\n")
        if not stripped.strip() or stripped.startswith((" ", "\t", "- ")):
            end += 1
            continue
        break
    return start, end


def normalize_ticker(item: str, hints: str) -> tuple[str, str | None]:
    """返回 (新码, 决策注记|None)。注记非空=进人工复核。"""
    token = item.strip().upper()
    if not token:
        return item, None
    if token in POLLUTION_FIX:
        return POLLUTION_FIX[token]
    if HK_RE.match(token):
        padded = f"{HK_RE.match(token).group(1).zfill(5)}.HK"
        return padded, ("HK 补 5 位" if padded != token else None)
    if "." in token:
        return token, None  # 已带后缀（非 HK 形态）保持
    if not DIGITS_RE.match(token):
        return token, None  # 字母符号码 / HK. / US. 前缀：不动
    if len(token) == 6:
        if token[:2] in ("01", "02", "03"):
            return f"{token}.OF", None  # 场外基金专用段
        if token[:2] == "00" or token[:3] == "002":
            if FUND_HINTS.search(hints):
                return f"{token}.OF", "并存段基金关键词判别（复核）"
            return f"{token}.SZ", "并存段默认深市（复核）"
        if token[:2] == "11":
            return f"{token}.OF", None  # 场外基金 11 段（易方达系等，无股票共用）
        if token[:2] in ("15", "16"):
            return f"{token}.SZ", None  # 159 ETF / 16x LOF（深市场内）
        if token[0] in "3":
            return f"{token}.SZ", None
        if token[0] in "56":
            return f"{token}.SH", None
        if token[0] == "1":
            return token, "未知 11x/15x/16x 外的 1 开头段（未改，人工处理）"
        if token[0] == "8":
            return f"{token}.BJ", "北交所段（复核）"
        if token[:3] == "968":
            return f"{token}.OF", None  # 香港互认基金份额段（968176/968075 同族）
        if token[:2] == "90":
            return f"{token}.SH", None  # 900xxx 沪市 B 股
        return token, "未知 6 位段（未改，人工处理）"
    if len(token) in (4, 5):
        padded = token.zfill(5)
        return f"{padded}.HK", ("HK 补 5 位" if padded != token else None)
    return token, f"异常位长 {len(token)}（未改，人工处理）"


def split_frontmatter(text: str) -> tuple[str, str, str] | None:
    if not text.startswith("---"):
        return None
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    return m.group(1), m.group(0), text[m.end():]


def fund_hints(fm: dict) -> str:
    title = str(fm.get("title") or "")
    domain = fm.get("domain")
    if isinstance(domain, list):
        title += " " + " ".join(str(d) for d in domain)
    elif domain:
        title += f" {domain}"
    return title


def rewrite_salience_keys(
    block: str, renamed: dict[str, str], hints: str = ""
) -> tuple[str, int]:
    """逐行改写 salience 键：改名项换新键；引用键按段规则独立补后缀。

    引用键（非本卡 ticker 成员，如 600519 卡上的 600900）在半改态
    zip 截断下会漏进 renamed——数字键一律走 normalize_ticker 段规则，
    不依赖 renamed 命中（同治八进制 int key 与裸码形态）。
    """
    out: list[str] = []
    changed = 0
    for line in block.splitlines():
        if line.lstrip().startswith("entity_salience:"):
            out.append(line)
            continue
        m = SALIENCE_LINE_RE.match(line)
        if not m or line.lstrip().startswith(("#", "-", "{")):
            out.append(line)
            continue
        raw_key = m.group(2).strip()
        key = raw_key.strip("'\"")
        target, quote = renamed.get(key, key), False
        if key in renamed:
            target, quote = renamed[key], True
        elif POLLUTION_FIX.get(key):
            target, quote = POLLUTION_FIX[key]  # 污染还原（键侧同治）
        elif HK_RE.match(key):
            target = f"{HK_RE.match(key).group(1).zfill(5)}.HK"
            quote = True  # 键侧 4 位 HK 补 5（官方形态全局统一，不依赖本卡 ticker）
        elif DIGITS_RE.match(key):
            target, _ = normalize_ticker(key, hints)  # 引用键按段规则独立补后缀
            quote = True
        if quote and raw_key == f"'{target}'":
            out.append(line)  # 已是目标形态，零 churn
            continue
        if target != key or quote:
            out.append(f"{m.group(1)}'{target}':{m.group(3)}{m.group(4)}")
            changed += 1
            continue
        out.append(line)
    return "\n".join(out) + "\n", changed


def rewrite_flow_salience(
    line: str, renamed: dict[str, str], hints: str = ""
) -> tuple[str, int]:
    """改写 flow 风格 `entity_salience: {K: v, ...}`：键改名+数字键加引号。

    键值按逗号切分（值内不含逗号——salience 值均为单词），重渲染为
    quoted-flow 单行，保持键序。解析失败返回原行（转人工）。
    """
    head, _, body = line.partition("{")
    body = body.rstrip().rstrip("}").strip()
    if not body:
        return line, 0
    pairs: list[tuple[str, str]] = []
    for chunk in body.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition(":")
        if not sep:
            return line, 0
        key = key.strip().strip("'\"")
        if key in renamed:
            key = renamed[key]
        elif POLLUTION_FIX.get(key):
            key = POLLUTION_FIX[key][0]
        elif HK_RE.match(key):
            key = f"{HK_RE.match(key).group(1).zfill(5)}.HK"
        elif DIGITS_RE.match(key):
            key = normalize_ticker(key, hints)[0]
        pairs.append((key, value.strip()))
    if not pairs:
        return line, 0
    rendered = "entity_salience: {" + ", ".join(f"'{k}': {v}" for k, v in pairs) + "}"
    if rendered == line.rstrip("\n"):
        return line, 0
    return rendered + "\n", len(pairs)


def migrate_file(path: Path, apply: bool, rows: list[dict]) -> None:
    raw = path.read_text(encoding="utf-8")
    rel = path
    if path.name == "_index.md":
        return  # 自动生成索引（rebuild-index 管辖），不手工迁移
    if raw.startswith("﻿") or "\r\n" in raw:
        rows.append({"file": rel, "note": "BOM/CRLF 文件不自动改写（人工处理）", "old": "", "new": ""})
        return
    parts = split_frontmatter(raw)
    if parts is None:
        return
    fm_text, fm_full, _body = parts
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        rows.append({"file": rel, "note": f"YAML 解析失败（人工处理）：{exc}", "old": "", "new": ""})
        return
    ticker_raw = fm.get("ticker")
    if ticker_raw is None:
        return
    items = [str(x) for x in (ticker_raw if isinstance(ticker_raw, list) else [ticker_raw])]
    hints = fund_hints(fm)
    notes: list[str] = []
    new_items: list[str] = []
    for item in items:
        new, note = normalize_ticker(item, hints)
        if note:
            notes.append(f"{item}→{new}：{note}")
        if new not in new_items:
            new_items.append(new)
    renamed = {old: new for old, new in zip(items, new_items) if old != new}
    if len(new_items) != len(items):
        notes.append(f"去重 {len(items)}→{len(new_items)}")

    fm_lines = fm_text.split("\n")
    changed = False
    if renamed or items != new_items:
        span = find_field_block(fm_lines, "ticker")
        if span is None:
            rows.append({"file": rel, "note": "ticker 块未定位（人工处理）", "old": str(items), "new": ""})
            return
        s, e = span
        fm_lines[s:e] = ["ticker:"] + [f"- '{x}'" for x in new_items]
        changed = True

    span = find_field_block(fm_lines, "entity_salience")
    if span is not None:
        s, e = span
        block_lines = fm_lines[s:e]
        if "{" in block_lines[0]:
            rendered, n = rewrite_flow_salience(block_lines[0], renamed, hints)
            if n:
                fm_lines[s:e] = [rendered.rstrip("\n")]
                changed = True
                notes.append(f"flow salience 键同步/加引号 {n} 处")
        else:
            rewritten, n = rewrite_salience_keys("\n".join(block_lines), renamed, hints)
            if n:
                fm_lines[s:e] = rewritten.rstrip("\n").split("\n")
                changed = True
                notes.append(f"salience 键同步/加引号 {n} 处")

    if not changed:
        if notes:
            rows.append({"file": rel, "note": "；".join(notes), "old": "", "new": ""})
        return
    rows.append({"file": rel, "note": "；".join(notes) or "键加引号加固", "old": str(items), "new": str(new_items)})
    if apply:
        new_fm = "---\n" + "\n".join(fm_lines) + "\n---\n" + _body
        path.write_text(new_fm, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="落盘（默认 dry-run）")
    parser.add_argument("--root", default=".", help="工作区根目录")
    args = parser.parse_args()
    root = Path(args.root)
    rows: list[dict] = []
    for pattern in ("wiki/entities/*.md", "wiki/sources/*.md", "wiki/explorations/*.md"):
        for path in sorted(root.glob(pattern)):
            migrate_file(path, args.apply, rows)
    print(f"{'[APPLY]' if args.apply else '[DRY-RUN]'} 变更文件 {len(rows)} 个：\n")
    for row in rows:
        print(f"- {row['file']}")
        if row["old"]:
            print(f"    {row['old']} → {row['new']}")
        if row["note"]:
            print(f"    注记：{row['note']}")
    review = [r for r in rows if "复核" in r["note"] or "人工" in r["note"]]
    print(f"\n需人工复核：{len(review)} 个")
    if not args.apply:
        print("dry-run 未落盘；确认后加 --apply。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
