"""国内流动性时序（Q-20261109-04 出界项 C3）：Shibor + 中国国债收益率 + 社融增量。

- Shibor 隔夜/1 周：东财 datacenter `RPT_IMP_INTRESTRATEN`（零 key，与财报日历
  同构：EM_DC_BASE_URL + EM_DC_HEADERS + 2 次重试 + success 校验）。DR007 严格口径
  （存款类机构质押回购加权）与 M2 本期不接——Shibor-1W 为信用拆借口径，与质押
  回购存在口径差，仪表读数须带此注记。
- 中国 10 年期国债收益率（Q-20261113-04）：东财 datacenter `RPTA_WEB_TREASURYYIELD`
  （零 key，同一 datacenter 通道；中债估值口径 EOD 日频，T+1 发布——与 ^TNX 实时
  快照不同源不同步，仪表两行并列不互为备份）。同报表另有 CN 2/30Y 与 US 各期限
  字段，需要时按 CN_TREASURY_INDICATORS 扩。
- 社融增量（月度）：MOFCOM `POST /datamofcom/front/gnmy/shrzgmQuery`（零 key，
  akshare macro_china_shrzgm 同源端点）。gov 站 TLS/改版风险高于东财——**失败只
  告警不阻塞 Shibor，退出码不因社融失败而非零**（降级语义，同「没配降级不报错」）。
- 写入走 save_custom_data.append_record（同 (series,date) 拒绝=幂等；旧日期已
  存在按 skip 计，不静默重写人工数据）。
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

from fetch_market_data import DEFAULT_TIMEOUT, EM_DC_BASE_URL, EM_DC_HEADERS
from mootdx_source import log
from save_custom_data import append_record

# 东财 datacenter 拆借利率的期限码（akshare rate_interbank 同源映射：隔夜=001、1周=101）
SHIBOR_INDICATORS = {
    "shibor-overnight": ("001", "Shibor 隔夜", "%"),
    "shibor-1w": ("101", "Shibor 1周", "%"),
}

# 东财 datacenter 中美国债收益率报表的期限字段（akshare bond_zh_us_rate 同源映射；
# 2026-11-13 实测 9,387 行回溯至 1990——只取 CN 10Y，其余按需扩）
CN_TREASURY_INDICATORS = {
    "cn-10y-treasury": ("EMM00166466", "中国10年期国债收益率", "%"),
}

MOFCOM_SFR_URL = "https://data.mofcom.gov.cn/datamofcom/front/gnmy/shrzgmQuery"
MOFCOM_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _dc_get_json(url: str, label: str) -> dict[str, Any]:
    """datacenter GET + 2 次重试 + success 校验（Shibor/国债收益率共用）。"""
    payload: dict[str, Any] | None = None
    for attempt in range(2):  # datacenter 惯例：带头偶发抖动，重试一次通常即好
        try:
            resp = requests.get(url, timeout=DEFAULT_TIMEOUT, headers=EM_DC_HEADERS)
            resp.raise_for_status()
            payload = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise RuntimeError(f"{label} datacenter 请求失败: {exc}") from exc
    if not (payload or {}).get("success"):
        raise RuntimeError(f"{label} datacenter 响应 success 非 truthy")
    return payload


def _dc_rows(payload: dict[str, Any], date_key: str, value_key: str) -> list[dict[str, str]]:
    """datacenter 行通用清洗：日期截前 10 位、非数值剔除、倒序转正序。"""
    rows = (payload.get("result") or {}).get("data") or []
    out = []
    for item in rows:
        day = str(item.get(date_key) or "")[:10]
        value = item.get(value_key)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and isinstance(value, (int, float)):
            out.append({"date": day, "value": float(value)})
    out.reverse()  # 请求倒序 → 落盘正序
    return out


def fetch_shibor_rows(indicator_id: str) -> list[dict[str, str]]:
    """东财 datacenter 拆借利率 → [{date, value}]（正序；REPORT_DATE 取前 10 位）。"""
    url = (f"{EM_DC_BASE_URL}?reportName=RPT_IMP_INTRESTRATEN"
           "&columns=REPORT_DATE,REPORT_PERIOD,IR_RATE,CHANGE_RATE"
           f"&filter=%28MARKET_CODE%3D%22001%22%29%28CURRENCY_CODE%3D%22CNY%22%29"
           f"%28INDICATOR_ID%3D%22{indicator_id}%22%29"
           "&pageNumber=1&pageSize=500&sortColumns=REPORT_DATE&sortTypes=-1"
           "&source=WEB&client=WEB")
    return _dc_rows(_dc_get_json(url, "Shibor"), "REPORT_DATE", "IR_RATE")


def fetch_cn_treasury_rows(field: str) -> list[dict[str, str]]:
    """东财 datacenter 中美国债收益率 → [{date, value}]（正序；SOLAR_DATE 取前 10 位）。

    中债估值口径 EOD（非实时）：最新行 T 或 T+1 发布，缺当日行属正常不是断连。"""
    url = (f"{EM_DC_BASE_URL}?reportName=RPTA_WEB_TREASURYYIELD"
           f"&columns=SOLAR_DATE%2C{field}"
           "&pageNumber=1&pageSize=500&sortColumns=SOLAR_DATE&sortTypes=-1"
           "&source=WEB&client=WEB")
    return _dc_rows(_dc_get_json(url, "中国国债收益率"), "SOLAR_DATE", field)


def fetch_social_financing_rows() -> list[dict[str, str]]:
    """MOFCOM 社融增量 → [{period, value}]（akshare 同源字段 tiosfs，单位亿元）。"""
    resp = requests.post(MOFCOM_SFR_URL, headers=MOFCOM_HEADERS, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"MOFCOM 社融响应非数组: {type(data).__name__}")
    out = []
    for item in data:
        month = str(item.get("date") or "")  # 形如 201501 / 2015-01
        m = re.fullmatch(r"(\d{4})-?(\d{2})", month)
        value = item.get("tiosfs")
        if m and isinstance(value, (int, float)):
            out.append({"period": f"{m.group(1)}-{m.group(2)}", "value": float(value)})
    out.sort(key=lambda x: x["period"])
    return out


def _append_many(data_root: Path, *, series: str, name: str, unit: str, source: str,
                 items: list[dict[str, Any]],
                 sink: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    """逐条 append；同日已存在=幂等 skip（人工数据不静默重写）。
    sink 非空时收集实际写入的 (文件, 行日期)——运行账本 data-close（batch_ledger）。"""
    stats = {"imported": 0, "skipped": 0}
    for item in items:
        try:
            path = append_record(data_root, series=series, name=name,
                                 date=item["date"], value=item["value"], unit=unit,
                                 source=source, period=item.get("period"))
            stats["imported"] += 1
            if sink is not None:
                # 社融月度行 date=YYYY-MM，账本锚须完整日期（run_archive 行锚定走
                # fromisoformat）——补 -01；行内 date 不可解析被 row_anchor_hash 保守
                # 计入 = 截至本次写入的整文件哈希语义，保护不缩水（max 评审 I-1）
                anchor = (f"{item['date']}-01" if len(str(item["date"])) == 7
                          else item["date"])
                sink.append((path, anchor))
        except ValueError as exc:
            if "已有" in str(exc):
                stats["skipped"] += 1
            else:
                raise
    log(f"{series}: {stats}")
    return stats


def update_shibor(data_root: Path,
                   sink: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    total = {"imported": 0, "skipped": 0}
    for series, (indicator_id, name, unit) in SHIBOR_INDICATORS.items():
        rows = fetch_shibor_rows(indicator_id)
        if not rows:
            raise RuntimeError(f"{series} datacenter 返回 0 条有效行")
        stats = _append_many(data_root, series=series, name=name, unit=unit,
                             source="eastmoney-datacenter", items=rows, sink=sink)
        for key in total:
            total[key] += stats[key]
    return total


def update_cn_treasury(data_root: Path,
                       sink: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    total = {"imported": 0, "skipped": 0}
    for series, (field, name, unit) in CN_TREASURY_INDICATORS.items():
        rows = fetch_cn_treasury_rows(field)
        if not rows:
            raise RuntimeError(f"{series} datacenter 返回 0 条有效行")
        stats = _append_many(data_root, series=series, name=name, unit=unit,
                             source="eastmoney-datacenter", items=rows, sink=sink)
        for key in total:
            total[key] += stats[key]
    return total


def update_social_financing(data_root: Path,
                             sink: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    rows = fetch_social_financing_rows()
    if not rows:
        raise RuntimeError("MOFCOM 社融返回 0 条有效行")
    return _append_many(data_root, series="social-financing", name="社会融资规模增量",
                        unit="亿元", source="mofcom",
                        items=[{"date": r["period"], "period": r["period"],
                                "value": r["value"]} for r in rows], sink=sink)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="国内流动性时序更新（Shibor+中国国债收益率+社融）")
    parser.add_argument("--only", choices=["shibor", "cn10y", "social", "all"], default="all")
    args = parser.parse_args(argv)
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    from batch_ledger import close_batch, open_batch

    run_id = open_batch("batch-liquidity", data_root)
    written: list[tuple[Path, str]] = []
    used: set[str] = set()  # 实际写入的系列才记源（max 评审 M-3）
    fail = False
    missing: list[dict] = []
    if args.only in ("shibor", "all"):
        try:
            update_shibor(data_root, sink=written)
            used.add("eastmoney-datacenter")
        except Exception as exc:  # noqa: BLE001
            fail = True
            missing.append({"item": "shibor", "reason": str(exc)})
            log(f"Warning: Shibor 更新失败: {exc}")
    if args.only in ("cn10y", "all"):
        try:
            update_cn_treasury(data_root, sink=written)
            used.add("eastmoney-datacenter")
        except Exception as exc:  # noqa: BLE001 — 同 Shibor：东财主通道失败=非零
            fail = True
            missing.append({"item": "cn-10y-treasury", "reason": str(exc)})
            log(f"Warning: 中国国债收益率更新失败: {exc}")
    if args.only in ("social", "all"):
        try:
            update_social_financing(data_root, sink=written)
            used.add("mofcom")
        except Exception as exc:  # noqa: BLE001 — 降级语义：社融失败不连坐 Shibor/退出码
            missing.append({"item": "social-financing", "reason": str(exc)})
            log(f"Warning: 社融更新失败（不阻塞，下次重试）: {exc}")
    close_batch(run_id, written, data_root, sources=sorted(used), missing=missing)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
