"""自定义数值序列（spec §4.4/§5.4）：人与 agent 共用入口。

date=真实日期（记录/发布日），period=数据所属期（可选）——月度数据不硬编假日期。
与行情层语义相反：同 (series,date) 默认拒绝，--overwrite 显式覆盖。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_data_io import atomic_write_text
from mootdx_source import log

_CSV_FIELDS = ("date", "period", "value", "unit", "source", "note")


def _series_path(data_root: Path, series: str) -> Path:
    return data_root / "custom" / f"{series}.jsonl"


def _load_registry(data_root: Path) -> dict:
    path = data_root / "custom" / "registry.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_registry(data_root: Path, registry: dict) -> None:
    atomic_write_text(data_root / "custom" / "registry.json",
                      json.dumps(registry, ensure_ascii=False, indent=1))


def _load_rows(data_root: Path, series: str) -> list[dict[str, Any]]:
    path = _series_path(data_root, series)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def append_record(data_root: Path, *, series: str, name: str, date: str, value: float,
                  unit: str, source: str, period: str | None = None,
                  note: str | None = None, overwrite: bool = False) -> Path:
    # 与 save_news_snapshot 的 slug 守卫同构：series 名直接拼进 custom/ 路径，
    # "../" 可写穿重写行情层文件；校验放在读 registry 之前，坏名连目录都不建
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", series):
        raise ValueError(f"series 名只接受 [a-z0-9][a-z0-9-]*（得到 {series!r}）——防路径写穿")
    registry = _load_registry(data_root)
    if series not in registry:  # 首次自动注册
        registry[series] = {"name": name, "unit": unit, "category": "", "description": "",
                            "created_at": datetime.now(timezone.utc).isoformat()}
        _save_registry(data_root, registry)
    rows = _load_rows(data_root, series)
    record = {"date": date, "period": period, "value": float(value), "unit": unit,
              "source": source, "note": note,
              "recorded_at": datetime.now(timezone.utc).isoformat()}
    hit = [i for i, r in enumerate(rows) if r["date"] == date]
    if hit and not overwrite:
        raise ValueError(f"{series} 已有 {date} 的记录（value={rows[hit[0]]['value']}）；"
                         "人工数据不可静默重写，确认后用 --overwrite")
    if hit:
        rows[hit[0]] = record
    else:
        rows.append(record)
    rows.sort(key=lambda r: r["date"])
    path = _series_path(data_root, series)
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return path


def list_series(data_root: Path) -> dict:
    return _load_registry(data_root)


def show_series(data_root: Path, series: str, tail: int | None = None) -> list[dict]:
    rows = _load_rows(data_root, series)
    return rows[-tail:] if tail else rows


def import_csv(data_root: Path, series: str, csv_path: Path, *, overwrite: bool = False) -> dict:
    stats = {"imported": 0, "skipped": 0}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            record = {key: (raw.get(key) or None) for key in _CSV_FIELDS}
            if not record["date"] or record["value"] in (None, ""):
                stats["skipped"] += 1  # 空 date/value 是坏行：跳过计数，不写毒行、不炸整批
                continue
            try:
                append_record(data_root, series=series, name=series, date=record["date"],
                              value=float(record["value"]), unit=record["unit"] or "",
                              source=record["source"] or "", period=record["period"],
                              note=record["note"], overwrite=overwrite)
                stats["imported"] += 1
            except (ValueError, TypeError):
                stats["skipped"] += 1
    log(f"csv-import {series}: {stats}")
    return stats


def main(argv: list[str] | None = None) -> int:
    from market_data_io import resolve_data_root

    parser = argparse.ArgumentParser(description="自定义数值序列存储（spec §5.4）")
    sub = parser.add_subparsers(dest="command", required=True)
    p_append = sub.add_parser("append")
    p_append.add_argument("--series", required=True)
    p_append.add_argument("--name", required=True)
    p_append.add_argument("--date", required=True)
    p_append.add_argument("--value", type=float, required=True)
    p_append.add_argument("--unit", required=True)
    p_append.add_argument("--source", required=True)
    p_append.add_argument("--period")
    p_append.add_argument("--note")
    p_append.add_argument("--overwrite", action="store_true")
    sub.add_parser("list")  # 无参数子命令，不得赋值（F841）
    p_show = sub.add_parser("show")
    p_show.add_argument("--series", required=True)
    p_show.add_argument("--tail", type=int)
    p_csv = sub.add_parser("csv-import")
    p_csv.add_argument("--series", required=True)
    p_csv.add_argument("--file", required=True)
    p_csv.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    data_root = resolve_data_root()

    if args.command == "append":
        try:
            path = append_record(data_root, series=args.series, name=args.name, date=args.date,
                                 value=args.value, unit=args.unit, source=args.source,
                                 period=args.period, note=args.note, overwrite=args.overwrite)
        except ValueError as exc:  # 重复 (series,date) 拒绝的干净收口：log + 退出码 1，不出 CLI traceback
            log(f"Error: {exc}")
            return 1
        print(path)
    elif args.command == "list":
        print(json.dumps(list_series(data_root), ensure_ascii=False, indent=1))
    elif args.command == "show":
        print(json.dumps(show_series(data_root, args.series, args.tail),
                         ensure_ascii=False, indent=1))
    else:
        print(json.dumps(import_csv(data_root, args.series, Path(args.file),
                                    overwrite=args.overwrite), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
