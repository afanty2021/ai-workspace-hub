"""美元流动性时序（2026-11-22 Fed 一手源接线三项之一）：隔夜逆回购（ON RRP）每日用量。

- 主源 NY Fed markets API ``search.json?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD``
  （零 key，官方桌面操作一手数据；**日期参数必须带连字符**——YYYYMMDD 紧凑格式
  返回 HTTP 400 无响应体，2026-11-22 实测）。同日多轮操作按日聚合求和；
  ``totalAmtAccepted`` 为绝对美元 → 换算十亿美元（round 3 位）。
- 备份源 FRED ``fredgraph.csv?id=RRPONTSYD``（零 key，T+1 滞后；CSV 值即十亿
  美元，与主源零换算差）。2026-11-22 双源对拍：NY Fed 11-20 totalAmtAccepted=
  401000000 ↔ FRED 同日 0.401，逐位一致。auto 模式主源失败降 FRED，同
  (series,date) 幂等 skip 双源不双写。
- 写入 save_custom_data.append_record（同 update_cn_liquidity 模式）：
  series=us-rrp-daily，unit=十亿美元。
- 读法注记（FOMC20150723memo02 机制）：RRP 余额=美元体系流动性缓冲垫读数——
  峰值回落后趋零=QT 已开始直接抽银行准备金（2019-09 型回购压力的机制前件）；
  两房 P&I 月中窗口（每月 15-25 日）内读数波动放大属日历性，非趋势。

HY OAS 第二系列（Q-20261123-04 接线，2026-11-23）：FRED ``BAMLH0A0HYM2``
（ICE BofA US High Yield Index Option-Adjusted Spread，零 key，T+1），series=
us-hy-oas，FRED 原值 % ×100 存 bp（11-22 衰退判定读数 352bp 同口径）——
科技回补三灯清单灯1c 信用否决腿数据源（清单
workspace/monitoring/tech-reentry-three-lights.md，否决线 380bp×2 日）。
单源 FRED 无降级链；失败=告警+missing 不阻塞 RRP（降级语义同社融，
`update_cn_liquidity` 主系列失败才非零）。
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from fetch_market_data import DEFAULT_TIMEOUT
from mootdx_source import log
from save_custom_data import append_record

NYFED_RRP_URL = ("https://markets.newyorkfed.org/api/rp/reverserepo/"
                 "propositions/search.json")
FRED_RRP_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

RRP_SERIES = "us-rrp-daily"  # 命名约定：以 SERIES 结尾的大写常量=序列 id
SERIES_NAME = "美联储隔夜逆回购（ON RRP）用量"

FRED_HYOAS_ID = "BAMLH0A0HYM2"
HY_SERIES = "us-hy-oas"
HY_SERIES_NAME = "美国高收益债期权调整利差（HY OAS）"


def fetch_rrp_rows_nyfed(start: str, end: str) -> list[dict[str, Any]]:
    """NY Fed markets API → [{date, value}]（value=十亿美元，正序）。

    日期参数带连字符；响应 repo.operations 倒序（最新在前）；同日多轮按日聚合。
    """
    resp = requests.get(
        NYFED_RRP_URL,
        params={"startDate": start, "endDate": end},
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    ops = (payload.get("repo") or {}).get("operations")
    if not isinstance(ops, list):
        raise RuntimeError(f"NY Fed RRP 响应缺 repo.operations: {type(payload).__name__}")
    by_day: dict[str, float] = {}
    for item in ops:
        day = str(item.get("operationDate") or "")[:10]
        amount = item.get("totalAmtAccepted")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) \
                and isinstance(amount, (int, float)) and not isinstance(amount, bool):
            by_day[day] = by_day.get(day, 0.0) + float(amount)
    return [{"date": day, "value": round(total / 1e9, 3)}
            for day, total in sorted(by_day.items())]


def fetch_rrp_rows_fred(start: str, end: str) -> list[dict[str, Any]]:
    """FRED fredgraph.csv → [{date, value}]（值即十亿美元，正序；窗口外/缺失剔除）。"""
    resp = requests.get(
        FRED_RRP_CSV_URL,
        timeout=DEFAULT_TIMEOUT,
        # cosd 限定起始日=窗口起点，不拉全量历史（RRPONTSYD 2003 年起 5800+ 行；
        # sibling fetch_market_data 2026-10-31 判例同款，r3 I-2 补齐同族换位形态）。
        params={"id": "RRPONTSYD", "cosd": start},
    )
    resp.raise_for_status()
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        day = str(row.get("observation_date") or "")[:10]
        raw = row.get("RRPONTSYD")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or raw in (None, "", "."):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if start <= day <= end:
            rows.append({"date": day, "value": round(value, 3)})
    rows.sort(key=lambda r: r["date"])
    return rows


def fetch_hy_oas_rows_fred(start: str, end: str) -> list[dict[str, Any]]:
    """FRED BAMLH0A0HYM2 → [{date, value}]（value=bp，FRED % ×100，正序；窗口外剔除）。

    cosd 限定起始日（同 fetch_rrp_rows_fred，不拉 1996 年起全量）；
    「.」=FRED 缺失标记剔除。"""
    resp = requests.get(
        FRED_RRP_CSV_URL,
        timeout=DEFAULT_TIMEOUT,
        params={"id": FRED_HYOAS_ID, "cosd": start},
    )
    resp.raise_for_status()
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        day = str(row.get("observation_date") or "")[:10]
        raw = row.get(FRED_HYOAS_ID)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or raw in (None, "", "."):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if start <= day <= end:
            rows.append({"date": day, "value": round(value * 100, 1)})
    rows.sort(key=lambda r: r["date"])
    return rows


def update_hy_oas(data_root: Path, *, days: int = 500,
                  sink: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    """HY OAS 滚动窗拉取幂等落盘（单源 FRED；降级语义由 main 承担）。"""
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()
    rows = fetch_hy_oas_rows_fred(start, end)
    if not rows:
        raise RuntimeError("FRED BAMLH0A0HYM2 返回 0 条有效行")
    stats = {"imported": 0, "skipped": 0}
    for item in rows:
        try:
            path = append_record(data_root, series=HY_SERIES, name=HY_SERIES_NAME,
                                 date=item["date"], value=item["value"],
                                 unit="bp", source="fred-bamlh0a0hym2")
            stats["imported"] += 1
            if sink is not None:
                sink.append((path, item["date"]))
        except ValueError as exc:
            if "已有" in str(exc):
                stats["skipped"] += 1
            else:
                raise
    stats["source"] = "fred-bamlh0a0hym2"
    log(f"{HY_SERIES}[fred]: {stats}")
    return stats


def update_rrp(data_root: Path, *, days: int = 500, source: str = "auto",
               sink: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    """拉 RRP 滚动窗并幂等落盘。auto：NY Fed 失败（含 1 次重试）降 FRED，双败上抛。"""
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()

    rows: list[dict[str, Any]] = []
    used_source = ""
    errors: list[str] = []
    for label, fetch in (("nyfed", lambda: fetch_rrp_rows_nyfed(start, end)),
                         ("fred", lambda: fetch_rrp_rows_fred(start, end))):
        if source != "auto" and source != label:
            continue
        try:
            if label == "nyfed":  # 主源 1 次重试（网络抖动）；FRED 不重试（备份位）
                for attempt in range(2):
                    try:
                        rows = fetch()
                        break
                    except (requests.RequestException, ValueError):
                        if attempt == 0:
                            time.sleep(1.0)
                            continue
                        raise
            else:
                rows = fetch()
            if rows:
                used_source = label
                break
            errors.append(f"{label}: 返回 0 条有效行")
        except Exception as exc:  # noqa: BLE001 — 降级链逐源收集，双败统一上抛
            errors.append(f"{label}: {exc}")
    if not rows:
        raise RuntimeError(f"RRP 双源均失败（source={source}）: {'; '.join(errors)}")
    if errors:
        log(f"Warning: RRP 部分源失败已降级: {'; '.join(errors)}")

    source_tag = {"nyfed": "nyfed-markets-api", "fred": "fred-rrpontsyd"}[used_source]
    stats = {"imported": 0, "skipped": 0}
    for item in rows:
        try:
            path = append_record(data_root, series=RRP_SERIES, name=SERIES_NAME,
                                 date=item["date"], value=item["value"],
                                 unit="十亿美元", source=source_tag)
            stats["imported"] += 1
            if sink is not None:
                sink.append((path, item["date"]))
        except ValueError as exc:
            if "已有" in str(exc):
                stats["skipped"] += 1
            else:
                raise
    stats["source"] = source_tag  # 供 main 账本记源（实际写入才记，见 main）
    log(f"{RRP_SERIES}[{used_source}]: {stats}")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="美元流动性时序更新（ON RRP 每日用量 + HY OAS，Q-20261123-04 双系列）")
    parser.add_argument("--days", type=int, default=500,
                        help="滚动窗天数（默认 500，约两年）")
    parser.add_argument("--source", choices=["auto", "nyfed", "fred"], default="auto",
                        help="RRP 降级链选择（HY OAS 恒走 FRED，不受此参数影响）")
    args = parser.parse_args(argv)
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    from batch_ledger import close_batch, open_batch

    run_id = open_batch("batch-us-liquidity", data_root)
    written: list[tuple[Path, str]] = []
    missing: list[dict] = []
    used: set[str] = set()
    fail = False
    try:
        stats = update_rrp(data_root, days=args.days, source=args.source, sink=written)
        # 实际写入才记源（sibling update_market_series 口径）：全 skip 幂等重跑
        # 不虚记 nyfed；FRED 降级成功记 fred-rrpontsyd 而非主源名。
        if stats["imported"] > 0:
            used.add(stats["source"])
    except Exception as exc:  # noqa: BLE001 — 主系列失败=非零（同 Shibor 语义）
        fail = True
        missing.append({"item": RRP_SERIES, "reason": str(exc)})
        log(f"Warning: ON RRP 更新失败: {exc}")
    # HY OAS（Q-20261123-04）：降级语义同社融——失败告警+missing，不置非零，
    # 不阻塞 RRP（三灯 1c 数据源晚一天到不致命，18:25 档次日自愈）。
    try:
        hy_stats = update_hy_oas(data_root, days=args.days, sink=written)
        if hy_stats["imported"] > 0:
            used.add(hy_stats["source"])
    except Exception as exc:  # noqa: BLE001
        missing.append({"item": HY_SERIES, "reason": str(exc)})
        log(f"Warning: HY OAS 更新失败: {exc}")
    close_batch(run_id, written, data_root, sources=sorted(used), missing=missing)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
