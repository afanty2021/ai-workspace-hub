"""达摩达兰标普 500 隐含股权风险溢价（月度，Q-20261123-05 接线，2026-11-23 查证属实）。

源：NYU Stern Aswath Damodaran 主页**每月初**更新一次（2008-09 起未断，其人
2022 博客/2023 论文两处原话确认；剧烈波动月份另有日内加更，不在本通路）。
直链 workbook 固定文件名 ``implprem/ERPbymonth.xlsx``：整本全量 218 个月、
~48KB，无需窗口参数，逐月追加、同 (series,date) 幂等 skip。零 key。

口径（2026-11-23 实测表头）：
- value = **ERP (T12m)**——隐含溢价跨期可比主序列，FRACTION ×100 存 %。
- note = 上下文一行：SP=点位 TB=10Y（%）sust=可持续派息口径（%）ER=内含
  期望收益（%）；缺列 token 省略。
- 历史锚：T12m 序列中位 5.25%、2022-10 加息峰 6.21%、2020-04 崩底 6.16%；
  2026-11-01 读数 3.79% 为 218 个月最低档（要价最薄）。

用法定位：**要价温度计**——ERP 低=市场要的风险补偿低（定价贵/脆弱），崩盘
自动跳升；与三灯灯1 双因子同向读数，不进灯、不设阈值（清单预注册纪律之外）。
日报宏观段自动渲染最新读数+历史分位（generate_daily_report 委托本模块
erp_state/format_erp_section）。失败语义：本脚本唯一载荷即本系列 → 失败
非零退出（同 RRP 主系列）；18:25 档 prompt 注明 ERP 失败只警告、不影响
流动性主档判读。openpyxl 为 Quant-3.11 现成依赖（mootdx 链已带）。
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from fetch_market_data import DEFAULT_TIMEOUT
from mootdx_source import log
from save_custom_data import append_record, show_series

ERP_URL = ("https://pages.stern.nyu.edu/~adamodar/"
           "pc/implprem/ERPbymonth.xlsx")

ERP_SERIES = "us-erp-monthly"
ERP_SERIES_NAME = "达摩达兰标普500隐含股权风险溢价（月度，T12m 口径）"
SOURCE_TAG = "damodaran-nyu-stern"

SHEET_NAME = "Historical ERP"
HEADER_DATE = "Start of month"
# 表头名 → 记录字段（逐名定位列索引，防源表加列错位；schema 漂移宁可红）
HEADER_MAP = {
    "S&P 500": "sp",
    "T.Bond Rate": "tb",
    "ERP (T12 m with sustainable payout)": "sust",
    "ERP (T12m)": "erp",
    "Expected Return": "er",
}

STALE_DAYS = 45   # 月度源 45 天无新读数 = 通路或源异常，渲染显式标注
MIN_N_PERCENTILE = 24  # 分位语句最少样本（两年），不足不谈分位


def fetch_erp_workbook() -> bytes:
    """拉 ERPbymonth.xlsx 原始字节（固定文件名整本全量）。"""
    resp = requests.get(ERP_URL, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    if len(resp.content) < 1000:
        raise RuntimeError(f"ERP workbook 异常（{len(resp.content)} 字节）")
    return resp.content


def parse_erp_rows(xlsx_bytes: bytes) -> list[dict[str, Any]]:
    """workbook 字节 → [{date, erp(%), note}] 正序。

    - 按**表头名**定位列（防源表加列错位）；缺 ``Historical ERP`` 表或缺任一
      必需表头 → RuntimeError（schema 漂移可见，不静默错位）。
    - date 取每月首日 ISO；ERP (T12m) 缺失的行整行跳过（早期残缺行）。
    - note 上下文 token（SP/TB/sust/ER）有则拼、缺则省。
    """
    from openpyxl import load_workbook

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl 对该 workbook 常发 Unknown extension UserWarning，cron 日志降噪
        wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True, read_only=True)
    if SHEET_NAME not in wb.sheetnames:
        raise RuntimeError(f"workbook 缺 {SHEET_NAME!r} 表：{wb.sheetnames}")
    ws = wb[SHEET_NAME]
    rows_iter = ws.iter_rows(values_only=True)
    col_idx: dict[str, int] = {}
    for row in rows_iter:
        cells = list(row or [])
        if HEADER_DATE in cells:
            # 键=记录字段名（sp/tb/sust/erp/er），值=列索引（防源表加列错位）
            col_idx = {HEADER_MAP.get(name, name): cells.index(name)
                       for name in (HEADER_DATE, *HEADER_MAP) if name in cells}
            break
    missing_fields = [k for k in (HEADER_DATE, "erp") if k not in col_idx]
    if missing_fields:
        raise RuntimeError(f"ERP 表头漂移：缺 {missing_fields}")
    out: list[dict[str, Any]] = []
    for row in rows_iter:
        cells = list(row or [])
        if col_idx[HEADER_DATE] >= len(cells):
            continue
        raw_day = cells[col_idx[HEADER_DATE]]
        if isinstance(raw_day, datetime):
            day = raw_day.date()
        elif isinstance(raw_day, date):
            day = raw_day
        else:
            day = None
            text = str(raw_day or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                day = date.fromisoformat(text)
        if day is None:
            continue
        def _num(field: str) -> float | None:
            idx = col_idx.get(field)
            if idx is None or idx >= len(cells):
                return None
            val = cells[idx]
            return float(val) if isinstance(val, (int, float)) \
                and not isinstance(val, bool) else None
        erp = _num("erp")
        if erp is None:  # T12m 缺失 = 残缺行整行跳过
            continue
        sp, tb = _num("sp"), _num("tb")
        sust, er = _num("sust"), _num("er")
        tokens = [f"SP={sp:g}" if sp is not None else "",
                  f"TB={tb * 100:.2f}%" if tb is not None else "",
                  f"sust={sust * 100:.2f}%" if sust is not None else "",
                  f"ER={er * 100:.2f}%" if er is not None else ""]
        out.append({"date": day.isoformat(), "erp": round(erp * 100, 2),
                    "note": " ".join(t for t in tokens if t)})
    out.sort(key=lambda r: r["date"])
    return out


def update_damodaran_erp(data_root: Path,
                         sink: list[tuple[Path, str]] | None = None
                         ) -> dict[str, int]:
    """整本解析幂等落盘（series=us-erp-monthly，unit=%，月度逐月追加）。"""
    rows = parse_erp_rows(fetch_erp_workbook())
    if not rows:
        raise RuntimeError("ERP workbook 解析出 0 条有效行")
    stats = {"imported": 0, "skipped": 0}
    for item in rows:
        try:
            path = append_record(data_root, series=ERP_SERIES,
                                 name=ERP_SERIES_NAME, date=item["date"],
                                 value=item["erp"], unit="%", source=SOURCE_TAG,
                                 note=item["note"] or None)
            stats["imported"] += 1
            if sink is not None:
                sink.append((path, item["date"]))
        except ValueError as exc:
            if "已有" in str(exc):
                stats["skipped"] += 1
            else:
                raise
    log(f"{ERP_SERIES}[{SOURCE_TAG}]: {stats}")
    return stats


def erp_state(data_root: Path, today: date | None = None) -> dict[str, Any]:
    """本地序列 → 渲染状态（最新读数+历史分位+陈旧标注；零网络）。"""
    rows = show_series(data_root, ERP_SERIES)
    if not rows:
        return {"ok": False}
    latest = rows[-1]
    values = [float(r["value"]) for r in rows]
    n_lower = sum(1 for v in values if v < latest["value"])
    day = date.fromisoformat(str(latest["date"])[:10])
    stale_days = (today or date.today()) - day
    return {"ok": True, "date": day.isoformat(), "erp": latest["value"],
            "note": latest.get("note") or "", "n": len(values),
            "n_lower": n_lower, "stale_days": stale_days.days}


def format_erp_section(state: dict[str, Any]) -> str:
    """日报宏观段一行块：读数+分位+用法注记；无数据降级为通路提示。"""
    if not state.get("ok"):
        return ("> 达摩达兰隐含 ERP 暂无本地读数（月度通路 "
                "`update_damodaran_erp.py`，NYU Stern 每月初更新）。")
    parts = [f"达摩达兰隐含 ERP（T12m）：{state['erp']:.2f}%",
             f"（{state['date']} 读数"]
    if state["note"]:
        parts.append(f"；{state['note']}")
    parts.append("）")
    if state["n"] >= MIN_N_PERCENTILE:
        parts.append(f"——{state['n']} 个月（2008-09 起）中仅 "
                     f"{state['n_lower']} 个月更低")
    if state["stale_days"] > STALE_DAYS:
        parts.append(f"；**读数已 {state['stale_days']} 天未更新，检查通路**")
    parts.append("。要价温度计（低=定价贵/脆弱，崩盘自动跳升）只记读数不作灯，"
                 "每月初更新。")
    return "> " + "".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="达摩达兰标普500隐含 ERP 月度序列更新（Q-20261123-05）")
    parser.parse_args(argv)          # 无旗标可取；调用只为 argparse 校验/帮助（ruff F841）
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    from batch_ledger import close_batch, open_batch

    run_id = open_batch("batch-damodaran-erp", data_root)
    written: list[tuple[Path, str]] = []
    missing: list[dict] = []
    used: set[str] = set()
    fail = False
    try:
        stats = update_damodaran_erp(data_root, sink=written)
        if stats["imported"] > 0:  # 实际写入才记源（全 skip 幂等重跑不虚记）
            used.add(SOURCE_TAG)
    except Exception as exc:  # noqa: BLE001 — 唯一载荷失败=非零（同 RRP 语义）
        fail = True
        missing.append({"item": ERP_SERIES, "reason": str(exc)})
        log(f"Warning: 达摩达兰 ERP 更新失败: {exc}")
    close_batch(run_id, written, data_root, sources=sorted(used), missing=missing)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
