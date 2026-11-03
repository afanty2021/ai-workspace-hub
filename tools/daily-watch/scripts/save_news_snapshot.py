"""新闻原文快照（spec §4.5/§5.5）：markdown = frontmatter + 原文全文，URL 规范化 dedup。

agent 先抓原文存临时文件，本脚本只负责规范化落盘——不抓网页（抓取在日报 agent 流程里）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from market_data_io import atomic_write_text
from mootdx_source import log


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    # 保留参数排序后重建：同 URL 不同参数序 → 同 key（否则 md5 不同，dedup 漏判）
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_"))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def dedup_key(url: str) -> str:
    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()


def _frontmatter_field(text: str, field: str) -> str | None:
    # 只在首 --- 块（frontmatter）内找：全文 MULTILINE 会被正文里碰巧出现的
    # 同名字段行（代码块/示例）误命中 dedup 判定
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break  # frontmatter 结束，正文不参与
        match = re.fullmatch(rf"{field}: (.+)", line.strip())
        if match:
            return match.group(1).strip()
    return None


def find_existing(data_root: Path, url: str) -> Path | None:
    key = dedup_key(url)
    news_dir = data_root / "news"
    if not news_dir.exists():
        return None
    for path in sorted(news_dir.rglob("*.md")):
        if _frontmatter_field(path.read_text(encoding="utf-8"), "dedup") == key:
            return path
    return None


def save_snapshot(data_root: Path, *, url: str, title: str, date: str, slug: str,
                  input_path: Path, partial: bool = False) -> tuple[Path, str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError(f"slug 只接受 kebab-case（小写字母数字连字符）: {slug!r}")  # 防路径逃逸
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"--date 须为 YYYY-MM-DD（得到 {date!r}）")  # date 也进路径，同构防线
    existing = find_existing(data_root, url)
    if existing:
        return existing, "skipped"
    out_dir = data_root / "news" / date[:4] / date[5:7]
    filename = f"{date}-{slug}.md"
    target = out_dir / filename
    if target.exists():  # 同日同 slug、不同 URL → md5 前 6 位后缀保唯一
        target = out_dir / f"{date}-{slug}-{dedup_key(url)[:6]}.md"
    body = input_path.read_text(encoding="utf-8")
    frontmatter = (
        "---\n"
        f"url: {url}\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"fetched_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"dedup: {dedup_key(url)}\n"
        f"partial: {'true' if partial else 'false'}\n"
        "---\n\n"
    )
    atomic_write_text(target, frontmatter + body)
    return target, "saved"


def main(argv: list[str] | None = None) -> int:
    from market_data_io import resolve_data_root

    parser = argparse.ArgumentParser(description="新闻原文快照落盘（spec §5.5）")
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--input", required=True, help="已抓取的原文 markdown 临时文件")
    parser.add_argument("--partial", action="store_true", help="标记不完整抓取")
    args = parser.parse_args(argv)
    try:
        path, status = save_snapshot(resolve_data_root(), url=args.url, title=args.title,
                                     date=args.date, slug=args.slug,
                                     input_path=Path(args.input), partial=args.partial)
    except ValueError as exc:  # slug/date 守卫：log + 退出码 1，不出 CLI traceback（与 save_custom_data 同款收口）
        log(f"Error: {exc}")
        return 1
    print(f"{status}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
