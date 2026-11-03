"""DuckDB 查询层（spec §5.6）——五个具名视图，唯一 import duckdb 的组件。

规模预期：~7000 文件 / ~450 万行全扫 Apple Silicon 秒级；视图按需创建
（ensure_view），torn 尾行靠 ignore_errors=true 跳过（原子写把概率压到最低）。
缺 duckdb 时 exit 2 指向 requirements，不降级。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mootdx_source import log


def _require_duckdb():
    try:
        import duckdb

        return duckdb
    except ImportError:
        log("Error: duckdb 未安装。安装：python -m pip install -r tools/daily-watch/requirements-market-data.txt")
        sys.exit(2)


_VIEW_PATTERNS = {
    "market_quotes": "market/series/*.jsonl",
    "sector_index": "sector/series/*.jsonl",
    "index_series": "index/series/*.jsonl",
    "finance": "finance/gpcw-*.jsonl",
    "custom_series": "custom/*.jsonl",  # registry.json 不是 .jsonl，天然排除
}


def ensure_view(con, data_root: Path, view: str) -> None:
    """按需建视图（I1）：目录还没有数据文件就 raise RuntimeError——DuckDB 对空 glob
    直接 IO Error，e2e 早期（finance/ 未生成时查行情）会当场崩。

    传 glob 串且不开 union_by_name（N4 e2e 实测定案，两个坑都踩过）：
    ① 显式文件列表 ~7500 条时建视图直接 OOM；② 换 glob 串后仍 OOM——真凶是
    union_by_name 对每个文件做 schema 并集探测，DuckDB 2.0 在数千文件规模下
    缓冲爆内存（实测 38 GiB，SET threads=1 无效）；去掉后同数据集 0.5s 建完。
    代价：视图 schema 取自采样窗口内的文件样本（duckdb 2.0 实际对有限多文件
    采样嗅探，非「首文件」定义），同目录异构键不在采样窗口会被静默忽略——
    五个视图目录各由唯一写者模块固定键集（spec §4 字段字典），新增字段须全目
    录同步。存在性预检保留（I1）：目录空仍 raise RuntimeError 而非 IO Error。
    ignore_errors=true 容忍 torn 尾行（M11，跳过语义）不变。
    """
    files = sorted(data_root.glob(_VIEW_PATTERNS[view]))
    if not files:
        raise RuntimeError(
            f"{view} 无数据文件（{data_root / _VIEW_PATTERNS[view]}）——先跑对应的 update/append 脚本")
    pattern = (data_root / _VIEW_PATTERNS[view]).resolve().as_posix()
    con.execute(
        f"CREATE OR REPLACE VIEW {view} AS "
        f"SELECT * FROM read_json_auto('{pattern}', filename=true, ignore_errors=true)")


def _view_for(ticker: str) -> str:
    """裸 6 位按段位路由：88 前缀 = TDX 板块 → sector_index；000/399 前缀 = 交易所
    指数 → index_series；其余（.SH/.SZ 后缀、海外票、其它裸代码）→ market_quotes。"""
    if re.fullmatch(r"\d{6}", ticker):
        if ticker.startswith("88"):
            return "sector_index"
        if ticker.startswith(("000", "399")):
            return "index_series"
    return "market_quotes"


def _rows(con, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """执行并转 dict 列表；DATE/TIMESTAMP 归一为 ISO 字符串。

    read_json_auto 会把 ISO 日期串推断成 DATE（duckdb 1.5/2.0 行为一致），
    查询层对外契约（含 CLI json 输出）统一为字符串日期。
    """
    rows = con.execute(sql, params).fetchall()
    cols = [d[0] for d in con.description]
    return [
        {c: v.isoformat() if isinstance(v, (date, datetime)) else v for c, v in zip(cols, row)}
        for row in rows
    ]


def query_quote(con, data_root: Path, ticker: str) -> dict[str, Any] | None:
    view = _view_for(ticker)
    ensure_view(con, data_root, view)
    rows = _rows(con, f"SELECT * FROM {view} WHERE filename LIKE ? ORDER BY date DESC LIMIT 1",
                 (f"%{ticker}.jsonl",))
    return rows[0] if rows else None


def query_range(con, data_root: Path, ticker: str, start: str, end: str) -> list[dict[str, Any]]:
    view = _view_for(ticker)
    ensure_view(con, data_root, view)
    return _rows(con, f"SELECT * FROM {view} WHERE filename LIKE ? AND date BETWEEN ? AND ? "
                      "ORDER BY date", (f"%{ticker}.jsonl", start, end))


def query_finance(con, data_root: Path, code: str, last: int = 4) -> list[dict[str, Any]]:
    ensure_view(con, data_root, "finance")
    return _rows(con, "SELECT * FROM finance WHERE code = ? ORDER BY report_date DESC LIMIT ?",
                 (code.zfill(6), last))


def sector_top(con, data_root: Path, top: int = 20) -> list[dict[str, Any]]:
    ensure_view(con, data_root, "sector_index")
    sql = f"""
    WITH ranked AS (
      SELECT filename, date, close, up_count, down_count,
             ROW_NUMBER() OVER (PARTITION BY filename ORDER BY date DESC) AS rn
      FROM sector_index WHERE close IS NOT NULL
    )
    SELECT regexp_extract(l1.filename, '([0-9]{{6}})\\.jsonl$', 1) AS code,
           l1.date, l1.close,
           CASE WHEN l2.close IS NOT NULL AND l2.close <> 0
                THEN round((l1.close - l2.close) / l2.close * 100, 2) END AS pct_change,
           l1.up_count, l1.down_count
    FROM ranked l1 LEFT JOIN ranked l2
      ON l1.filename = l2.filename AND l2.rn = 2
    WHERE l1.rn = 1
    ORDER BY pct_change DESC NULLS LAST
    LIMIT {int(top)}
    """
    return _rows(con, sql)


def run_sql(con, sql: str) -> list[dict[str, Any]]:
    return _rows(con, sql)


def main(argv: list[str] | None = None) -> int:
    from market_data_io import resolve_data_root
    from save_custom_data import show_series

    parser = argparse.ArgumentParser(description="市场数据 DuckDB 查询（spec §5.6）")
    sub = parser.add_subparsers(dest="command", required=True)
    p_quote = sub.add_parser("quote")
    p_quote.add_argument("--ticker", required=True)
    p_range = sub.add_parser("range")
    p_range.add_argument("--ticker", required=True)
    p_range.add_argument("--start", required=True)
    p_range.add_argument("--end", required=True)
    p_finance = sub.add_parser("finance")
    p_finance.add_argument("--ticker", required=True)
    p_finance.add_argument("--last", type=int, default=4)
    p_sector = sub.add_parser("sector")
    p_sector.add_argument("--top", type=int, default=20)
    p_custom = sub.add_parser("custom")
    p_custom.add_argument("--series", required=True)
    p_custom.add_argument("--tail", type=int)
    p_sql = sub.add_parser("sql")
    p_sql.add_argument("--sql", required=True)
    args = parser.parse_args(argv)
    data_root = resolve_data_root()

    if args.command == "custom":  # 不走 DuckDB，直接读文件（duckdb 未装也能用）
        try:
            rows = show_series(data_root, args.series, args.tail)
        except ValueError as exc:  # 坏 JSONL 等：log + 退出码 1，不出 CLI traceback（与 save_custom_data 同款收口）
            log(f"Error: {exc}")
            return 1
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    duckdb = _require_duckdb()  # 下移到 custom 早退之后：直读 JSONL 的分支不该被它挡
    con = duckdb.connect(":memory:")
    if args.command == "quote":
        out = query_quote(con, data_root, args.ticker)
    elif args.command == "range":
        out = query_range(con, data_root, args.ticker, args.start, args.end)
    elif args.command == "finance":
        out = query_finance(con, data_root, args.ticker, args.last)
    elif args.command == "sector":
        out = sector_top(con, data_root, args.top)
    else:  # sql：能建的视图都建，缺组只警告（用户 SQL 没用到就能跑）
        for view in _VIEW_PATTERNS:
            try:
                ensure_view(con, data_root, view)
            except RuntimeError as exc:
                log(f"Warning: {exc}")
        out = run_sql(con, args.sql)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
