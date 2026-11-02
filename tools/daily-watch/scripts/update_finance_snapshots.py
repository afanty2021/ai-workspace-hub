"""财务快照（spec §4.3/§5.3）：gpcw 按报告期一文件，hash 台账零下载探测。

列映射铁律：659 列=403 中文名+256 无名 colNN+9 组重名（各 ×2）——按(列名, 出现序号)
钉死列位置，禁止按列名取值；mootdx 布局变化时 column_positions 直接 raise。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from market_data_io import atomic_write_text
from mootdx_source import _MOOTDX_LOCK, _candidate_tdx_servers, _get_mootdx_client, log

COLUMN_MAP: dict[str, tuple[str, int]] = {
    "eps_basic": ("基本每股收益", 0),
    "eps_deducted": ("扣除非经常性损益每股收益", 0),
    "bps": ("每股净资产", 0),
    "roe": ("净资产收益率", 0),                                  # 第一次出现=每股指标段
    "revenue": ("其中：营业收入", 0),                            # 累计口径（非后段单季「营业收入」）
    "net_profit_parent": ("归属于母公司所有者的净利润", 0),      # 第一次=累计
    "net_profit_deducted": ("扣除非经常性损益后的净利润", 0),    # 第一次=累计
    "inventory": ("存货", 0),
    "monetary_funds": ("货币资金", 0),
    "total_assets": ("资产总计", 0),
    "total_liabilities": ("负债合计", 0),
    "revenue_yoy": ("营业收入增长率(%)", 0),
    "net_profit_yoy": ("净利润增长率(%)", 0),
    "deducted_yoy": ("扣非净利润同比(%)", 0),
    "forecast_min": ("业绩预告-本期净利润同比增幅下限%", 0),
    "forecast_max": ("业绩预告-本期净利润同比增幅上限%", 0),
}

_PLACEHOLDER_MAX_BYTES = 1024 * 1024  # 未来期 164B 占位空壳，>1MB 才是真文件（spec §12）
_MARKET_BY_FIRST_CHAR = {"6": "SH", "0": "SZ", "3": "SZ", "4": "BJ", "8": "BJ", "9": "BJ"}


@contextmanager
def _affair_gp_bestip(ip: str, port: int):
    """整 run 级把 GP 文件服务钉到已验证服务器（files/download/parse 共用一条通道）。

    BaseFinancial.__init__ 读 config.get('BESTIP')['GP']（financial/base.py:44）——
    run 级 set 覆盖全链，finally 恢复原值。0.11.7 的 config.set 只改内存不落盘
    （mootdx_source._preserve_mootdx_bestip 同款机制与结论），不污染后续行情连接。
    """
    from mootdx import config as mootdx_config

    mootdx_config.setup()
    saved = mootdx_config.get("BESTIP")
    merged = dict(saved) if isinstance(saved, dict) else {}
    merged["GP"] = (ip, int(port))
    mootdx_config.set("BESTIP", merged)
    try:
        yield
    finally:
        mootdx_config.set("BESTIP", saved)  # setup() 后 BESTIP 恒有值，无条件恢复原值


def _fallback_gp_server() -> tuple[str, int]:
    """已验证可用的行情服务器。client.server 是当前真实连接那台（mootdx_source:232
    显式传 server 构造）；裸 factory 分支 server=None（valid_server(None)），退回
    精选表头名（探测维持的优先表）。⚠️ 不能用 client.bestip——那是 BaseQuotes 的
    类属性 None，解包直接 TypeError。持 `_MOOTDX_LOCK` 再取单例（mootdx_source:188
    契约：调用方必须已持锁）；负缓存窗口内 _get_mootdx_client 会 raise，由
    files_with_fallback 收敛成干净报错。"""
    with _MOOTDX_LOCK:
        server = getattr(_get_mootdx_client(), "server", None)
    return tuple(server) if server else _candidate_tdx_servers()[0]


def files_with_fallback() -> tuple[list[dict], tuple[str, int] | None]:
    """默认 GP 通 → (files, None)；不通 → (经行情服务器取得的 files, (ip, port))。"""
    from mootdx.affair import Affair

    try:
        files = Affair.files()
        if files:
            return files, None
    except Exception as exc:  # noqa: BLE001
        log(f"Warning: Affair 默认 bestip 失败，改用行情服务器 GP 兜底: {exc}")
    try:
        ip_port = _fallback_gp_server()
        with _affair_gp_bestip(*ip_port):
            return (Affair.files() or []), ip_port
    except Exception as exc:  # noqa: BLE001 — 兜底也可能全灭（如全网负缓存窗口），收敛成干净报错
        raise RuntimeError("财务快照中止：Affair 默认通道与行情服务器兜底均不可用"
                           "（可能是全网负缓存窗口，稍后重试）") from exc


def download_gpcw(filename: str, downdir: Path) -> None:
    from mootdx.financial.financial import Financial  # financial/__init__.py 是 0 字节

    Financial().fetch_only(filename=filename, downdir=str(downdir))


def parse_gpcw(downdir: Path, filename: str) -> pd.DataFrame:
    from mootdx.affair import Affair

    return Affair.parse(downdir=str(downdir), filename=filename)


def column_positions(columns) -> dict[str, int]:
    """(列名, 出现序号) → 列位置。映射键找不到就 raise——静默错列比崩溃更糟。"""
    positions: dict[str, int] = {}
    for key, (name, occurrence) in COLUMN_MAP.items():
        hits = [i for i, col in enumerate(columns) if col == name]
        if len(hits) <= occurrence:
            raise ValueError(f"列映射失败: {key} <- '{name}'#{occurrence}（实际出现 {len(hits)} 次）"
                             "——mootdx gpcw 布局可能已变化")
        positions[key] = hits[occurrence]
    return positions


def rows_from_dataframe(df: pd.DataFrame, report_date: str, file_hash: str) -> list[dict]:
    pos = column_positions(df.columns)
    rows: list[dict] = []
    for code, record in df.iterrows():
        code = str(code).zfill(6)

        def val(key: str) -> float | None:
            raw = record.iloc[pos[key]]
            return None if pd.isna(raw) else float(raw)

        def forecast(key: str) -> float | None:
            raw = val(key)
            return None if raw == 0 else raw  # 0 视为无预告（spec §4.3）

        rows.append({
            "code": code,
            "market": _MARKET_BY_FIRST_CHAR.get(code[0], "SZ"),
            "report_date": report_date,
            **{key: val(key) for key in COLUMN_MAP if not key.startswith("forecast")},
            "forecast_min": forecast("forecast_min"),
            "forecast_max": forecast("forecast_max"),
            "file_hash": file_hash,
            "schema_version": 1,
        })
    return rows


def _report_date_from(filename: str) -> str:
    match = re.match(r"gpcw(\d{8})\.zip", filename)
    if not match:
        raise ValueError(f"非 gpcw 文件名: {filename}")
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def run_finance_update(data_root: Path, *, backfill: int | str = 0) -> dict:
    stats = {"ok": 0, "skip": 0, "fail": 0}
    finance_dir = data_root / "finance"
    raw_dir = finance_dir / "_raw"
    finance_dir.mkdir(parents=True, exist_ok=True)  # Financial.content 是裸 open()，目录必须先在
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_files, gp_fallback = files_with_fallback()
    files = [f for f in raw_files if f["filesize"] > _PLACEHOLDER_MAX_BYTES]
    files.sort(key=lambda x: x["filename"], reverse=True)  # 最新期在前
    count = len(files) if backfill == "all" else max(int(backfill), 1)
    targets = files[:count]
    log(f"财务快照：非占位 {len(files)} 期，本次处理 {len(targets)} 期（backfill={backfill}）")

    meta_path = finance_dir / "_meta.json"
    meta: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    gp_ctx = _affair_gp_bestip(*gp_fallback) if gp_fallback else contextlib.nullcontext()
    with gp_ctx:  # 默认 GP 不通时，download/parse 也钉在已验证服务器上（I3）
        for item in targets:
            filename = item["filename"]
            try:
                if meta.get(filename, {}).get("hash") == item["hash"]:
                    stats["skip"] += 1
                    continue
                download_gpcw(filename, raw_dir)
                df = parse_gpcw(raw_dir, filename)
                rows = rows_from_dataframe(df, _report_date_from(filename), item["hash"])
                atomic_write_text(
                    finance_dir / f"gpcw-{_report_date_from(filename)}.jsonl",
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
                meta[filename] = {"hash": item["hash"], "rows": len(rows),
                                  "fetched_at": datetime.now(timezone.utc).isoformat()}
                atomic_write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=1))
                stats["ok"] += 1
                log(f"财务快照 {filename}: {len(rows)} 行写入")
            except Exception as exc:  # noqa: BLE001
                stats["fail"] += 1
                log(f"Warning: {filename} 处理失败: {exc}")
    log(f"财务汇总: {stats}")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="gpcw 财务快照盘后检查（spec §5.3）")
    parser.add_argument("--backfill", default="0", help="期数 N 或 all；默认 0=只盯最新期")
    args = parser.parse_args(argv)
    backfill: int | str = args.backfill if args.backfill == "all" else int(args.backfill)
    from market_data_io import resolve_data_root

    try:
        stats = run_finance_update(resolve_data_root(), backfill=backfill)
    except RuntimeError as exc:  # 双通道全灭的干净收口（N5）：log + 退出码 1，不出 CLI traceback
        log(f"Error: {exc}")
        return 1
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
