"""货币ETF场内折溢价温度计（Q-20261127-01，2026-11-27 用户拍板接线）。

定位：**A股资金面温度计——只记读数+触发标注，不设自动多空灯**（与 ERP/RRP
同型）。折溢价三解（方向必须联动语境判定，2026-11-27 会话核查）：
- risk-on：卖货基腾钱买股票（折价+股指放量上涨）；
- risk-off：货基自身遭挤赎——2016-12 赎回潮型（折价+资金利率飙升+债跌+股跌），
  **反向信号，不是做多**；
- 机制性噪声：分红除权/节假日申赎节奏。

口径（2026-11-27 实测）：
- 511880 银华日利（**净值漂移型**，每年 12 月末分红除权归位 100）：溢价率 =
  mootdx 收盘 ÷ 单位净值 − 1。净值源链：pingzhongdata（Data_netWorthTrend，
  全史一次拉）→ 天天基金 lsjz（分页）双源 auto 降级，双源对 511880 逐位一致。
  **F10/pingzhongdata 除权日标签比场内价格除权提前一交易日**（2023-12-28
  +174bp / 2024-12-30 +155bp / 2025-12-30 +115bp 三年假溢价实锤）→ 除权修复：
  净值回落日改用前一日净值对价，修复后三年除权日读数全部回到 ±3bp；修复后
  仍 |溢价|>50bp 的行=口径断裂毒行，弃用不落盘。
- 511990 华宝添益（**固定净值型**，原 511988 已换码）：溢价率 = 收盘 ÷ 100
  （固定净值锚近似）。**天天基金 lsjz/fundmobapi 对固定净值型货基的 DWJZ
  字段返回万份收益（~0.26 元≈年化 0.95%）非单位净值**——不得跨基金复用
  解析；100 锚偏差 = 真实净值对 100 的偏离（11 月实测收盘 99.992~100.012，
  ±1.2bp 与噪声同量级，可忽略；真净值接口待验证项见 skill）。
- 触发线（量具纪律：标定窗 2025-06~2026-11 基线 P5=-0.8bp/P95=+2.8bp、样本内
  从未出现，阈值与标定窗分离留待验证期检验）：**连续 2 个交易日 < -5bp 且
  双基金同向**；511880 末 2 日任一含除权修复行 → 触发静默（除权窗剔除）。
- 时滞：货币基金净值 T+1 披露 → 18:10 批量跑出的溢价读数截至上一交易日，
  日报段显式标注。

写入 save_custom_data.append_record（同 us-liquidity 模式）：series=
cn-money-etf-prem-511880 / cn-money-etf-prem-511990，unit=bp，note 存
close/nav 原始数（除权修复行加 exdiv-repair 标记）。幂等 skip 同 (series,date)。

性质标注联动（零网络，只读本地）：上证指数日涨跌（data/index/series/
000001.jsonl）+ Shibor 1W 日变动（data/custom/shibor-1w.jsonl）：
- 触发 + 股指跌 ≥0.5% 或 Shibor 上行 ≥3bp → risk-off 挤赎嫌疑（非做多）；
- 触发 + 股指涨 ≥0.5% 且 Shibor 变动 ≤+1bp → risk-on 卖货基买股嫌疑；
- 其余 → 方向不明（人工复核）。均为「嫌疑/待归因」级，不裁决。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

from fetch_market_data import DEFAULT_TIMEOUT
from mootdx_source import _MOOTDX_LOCK, _get_mootdx_client, log
from save_custom_data import append_record, show_series

PINGZHONG_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"

FUND_511880 = "511880"
FUND_511990 = "511990"
SERIES_511880 = "cn-money-etf-prem-511880"
SERIES_511990 = "cn-money-etf-prem-511990"
NAME_511880 = "银华日利ETF(511880)场内溢价率（bp，vs 单位净值）"
NAME_511990 = "华宝添益ETF(511990)场内溢价率（bp，vs 100元固定净值锚）"

NAV_511990_ANCHOR = 100.0  # 固定净值型锚（偏差与噪声同量级，见 docstring）
ALERT_THRESH_BP = -5.0     # 连续 2 日 < -5bp 且双基金同向才触发（标定窗内未出现）
CONSEC_DAYS = 2
POISON_PREM_BP = 50.0      # 除权修复后仍超 ±50bp = 口径断裂行，弃用不落盘
EXDIV_MARK = "exdiv-repair"
EXDIV_QUIET_DAYS = 2       # 末 N 日内含除权修复行 → 触发静默
ROUND_BP = 2

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _mootdx_bars(code: str, offset: int) -> list[dict[str, Any]]:
    """mootdx 日线 → [{date, close}] 正序（日期升序）。"""
    with _MOOTDX_LOCK:
        client = _get_mootdx_client()
        df = client.bars(symbol=code, frequency=9, offset=offset)
    if df is None or len(df) == 0:
        raise RuntimeError(f"mootdx {code} 返回空 K 线")
    df = df.reset_index(drop=True)
    dcol = "datetime" if "datetime" in df.columns else df.columns[0]
    dates = _to_dates(df[dcol])
    rows = [{"date": d, "close": float(r["close"])}
            for d, r in zip(dates, df.to_dict("records"))]
    rows.sort(key=lambda r: r["date"])
    return rows


def _to_dates(series) -> list[Any]:
    out = []
    for value in series:
        text = str(value)
        m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
        out.append(m.group(1) if m else text)
    return out


def fetch_nav_rows_pingzhong(code: str) -> list[dict[str, Any]]:
    """pingzhongdata Data_netWorthTrend → [{date, nav}]（全史，正序）。"""
    from datetime import datetime, timedelta, timezone

    resp = requests.get(PINGZHONG_URL.format(code=code),
                        headers={"User-Agent": UA,
                                 "Referer": "https://fund.eastmoney.com/"},
                        timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", resp.text)
    if not m:
        raise RuntimeError(f"pingzhongdata {code} 无 Data_netWorthTrend")
    arr = json.loads(m.group(1))
    rows: list[dict[str, Any]] = []
    for item in arr:
        ts = datetime.fromtimestamp(item["x"] / 1000, tz=timezone.utc) \
            + timedelta(hours=8)
        day = ts.strftime("%Y-%m-%d")
        nav = item.get("y")
        if isinstance(nav, (int, float)) and nav > 0:
            rows.append({"date": day, "nav": float(nav)})
    rows.sort(key=lambda r: r["date"])
    if not rows:
        raise RuntimeError(f"pingzhongdata {code} 净值行数为 0")
    return rows


def fetch_nav_rows_lsjz(code: str, pages: int) -> list[dict[str, Any]]:
    """天天基金 F10 lsjz 分页 → [{date, nav}]（正序）。

    注意：固定净值型货基（511990/159001）此接口 DWJZ=万份收益非单位净值，
    本函数只允许用于净值漂移型（511880）。"""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        resp = requests.get(
            LSJZ_URL,
            params={"fundCode": code, "pageIndex": page, "pageSize": 20},
            headers={"User-Agent": UA,
                     "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html"},
            timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        arr = ((resp.json().get("Data") or {}).get("LSJZList")) or []
        if not arr:
            break
        fresh = 0
        for item in arr:
            day = str(item.get("FSRQ") or "")
            raw = item.get("DWJZ")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or raw in (None, ""):
                continue
            if day in seen:
                continue
            try:
                nav = float(raw)
            except (TypeError, ValueError):
                continue
            if nav <= 0:
                continue
            rows.append({"date": day, "nav": nav})
            seen.add(day)
            fresh += 1
        if fresh == 0:
            break  # 翻到已拉过的页=到头
        time.sleep(0.4)
    rows.sort(key=lambda r: r["date"])
    if not rows:
        raise RuntimeError(f"lsjz {code} 净值行数为 0")
    return rows


def compute_premiums(closes: list[dict[str, Any]], navs: list[dict[str, Any]],
                     *, fixed_nav: float | None = None) -> list[dict[str, Any]]:
    """合并价/净值 → 逐日溢价(bp)行，含除权修复与毒行守卫。

    - 净值漂移型（fixed_nav=None）：净值回落日（nav[t] < nav[t-1]，货币基金
      净值只在该日回落）= F10 除权标签日，价格实际次日才除权 → 改用前一日
      净值对价，行 note 标 exdiv-repair。
    - 固定净值型（fixed_nav=100.0）：无净值序列，恒锚。
    - 修复后 |溢价| > POISON_PREM_BP 的行丢弃（口径断裂不落盘、不毒化序列）。
    """
    nav_by_date = {r["date"]: r["nav"] for r in navs}
    ordered_dates = sorted(nav_by_date)
    out: list[dict[str, Any]] = []
    for row in closes:
        day = row["date"]
        if fixed_nav is not None:
            nav_eff, repaired = fixed_nav, False
        else:
            if day not in nav_by_date:
                continue  # 净值未披露（T+1）或停披，跳过
            nav_eff = nav_by_date[day]
            idx = ordered_dates.index(day)
            repaired = False
            if idx > 0:
                nav_prev = nav_by_date[ordered_dates[idx - 1]]
                if nav_eff < nav_prev:  # 净值回落=除权标签日 → 前一日净值对价
                    nav_eff = nav_prev
                    repaired = True
        prem_bp = (row["close"] / nav_eff - 1.0) * 10000.0
        if abs(prem_bp) > POISON_PREM_BP:
            continue  # 毒行守卫：修复失效/口径断裂，弃用
        note = f"close={row['close']} nav={nav_eff:g}"
        if repaired:
            note += f" {EXDIV_MARK}"
        out.append({"date": day, "prem_bp": round(prem_bp, ROUND_BP),
                    "close": row["close"], "nav": nav_eff,
                    "exdiv": repaired, "note": note})
    return out


def upsert_premiums(data_root: Path, series: str, name: str, source: str,
                    rows: list[dict[str, Any]],
                    sink: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    stats = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            path = append_record(data_root, series=series, name=name,
                                 date=row["date"], value=row["prem_bp"],
                                 unit="bp", source=source, note=row["note"])
            stats["imported"] += 1
            if sink is not None:
                sink.append((path, row["date"]))
        except ValueError as exc:
            if "已有" in str(exc):
                stats["skipped"] += 1
            else:
                raise
    log(f"{series}[{source}]: {stats}")
    return stats


def update_511880(data_root: Path, *, days: int,
                  sink: list[tuple[Path, str]] | None = None) -> dict[str, Any]:
    """银华日利：净值链 auto（pingzhongdata→lsjz）+ mootdx 收盘 → 溢价落盘。"""
    closes = _mootdx_bars(FUND_511880, offset=max(days + 40, 80))
    cutoff = closes[0]["date"]
    navs: list[dict[str, Any]] = []
    used_source = ""
    errors: list[str] = []
    for label, fetch in (("pingzhongdata", lambda: fetch_nav_rows_pingzhong(FUND_511880)),
                         ("lsjz", lambda: fetch_nav_rows_lsjz(
                             FUND_511880, pages=max(days // 20 + 2, 4)))):
        try:
            navs = [r for r in fetch() if r["date"] >= cutoff]
            if navs:
                used_source = label
                break
            errors.append(f"{label}: 窗内 0 行")
        except Exception as exc:  # noqa: BLE001 — 降级链逐源收集，双败统一上抛
            errors.append(f"{label}: {exc}")
    if not navs:
        raise RuntimeError(f"511880 净值双源均失败: {'; '.join(errors)}")
    if len(errors) == 1:
        log(f"Warning: 511880 净值部分源失败已降级: {errors[0]}")
    rows = compute_premiums(closes, navs)
    source_tag = {"pingzhongdata": "pingzhongdata+mootdx",
                  "lsjz": "lsjz+mootdx"}[used_source]
    stats = upsert_premiums(data_root, SERIES_511880, NAME_511880,
                            source_tag, rows, sink=sink)
    return {**stats, "source": source_tag}


def update_511990(data_root: Path, *, days: int,
                  sink: list[tuple[Path, str]] | None = None) -> dict[str, Any]:
    """华宝添益：mootdx 收盘 ÷ 100 固定净值锚 → 溢价落盘（降级语义=告警不阻塞）。"""
    closes = _mootdx_bars(FUND_511990, offset=max(days + 40, 80))
    rows = compute_premiums(closes, [], fixed_nav=NAV_511990_ANCHOR)
    stats = upsert_premiums(data_root, SERIES_511990, NAME_511990,
                            "mootdx+nav100anchor", rows, sink=sink)
    return {**stats, "source": "mootdx+nav100anchor"}


def _read_series(data_root: Path, series: str, tail: int) -> list[dict[str, Any]]:
    return show_series(data_root, series, tail=tail)


def _index_daily_chg(data_root: Path) -> dict[str, Any] | None:
    """上证指数末两行 → 最新日涨跌 %（零网络；缺序列/行数不足返回 None）。"""
    path = data_root / "index" / "series" / "000001.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(x) for x in
            path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows) < 2:
        return None
    prev, last = rows[-2], rows[-1]
    try:
        chg = (float(last["close"]) / float(prev["close"]) - 1.0) * 100.0
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return {"date": last.get("date"), "chg_pct": round(chg, 2)}


def _shibor_1w_move(data_root: Path) -> dict[str, Any] | None:
    """Shibor 1W 末两行 → 最新值与日变动 bp（零网络）。"""
    rows = _read_series(data_root, "shibor-1w", tail=2)
    if len(rows) < 2:
        return None
    try:
        prev, last = float(rows[-2]["value"]), float(rows[-1]["value"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"date": rows[-1].get("date"), "value_pct": last,
            "chg_bp": round((last - prev) * 100.0, 1)}


def money_etf_state(data_root: Path, today: str | None = None) -> dict[str, Any]:
    """只读本地序列 → 温度计状态（触发判定+语境标注原料）。零网络。

    对齐基准 = **511880 的末 CONSEC_DAYS 个日期**（净值 T+1 披露，读数天然
    滞后 511990 一天——511990 走 100 锚无净值依赖，按各自末行比较会永久
    错位）：511990 在同日期有行才参与触发；触发 = 两基金在同日期的值全 <
    ALERT_THRESH_BP。511880 该窗口任一行含 exdiv-repair 标记 → 静默。"""
    rows_880 = _read_series(data_root, SERIES_511880, tail=CONSEC_DAYS)
    rows_990_all = _read_series(data_root, SERIES_511990,
                                tail=CONSEC_DAYS + 2)  # 511990 天然超前，多读兜对齐
    full_880 = _read_series(data_root, SERIES_511880, tail=None) or []
    by990 = {r["date"]: r for r in rows_990_all}
    asof = rows_880[-1]["date"] if rows_880 else (
        rows_990_all[-1]["date"] if rows_990_all else None)
    rows_990 = [by990.get(r["date"]) for r in rows_880]

    exdiv_recent = any(EXDIV_MARK in (r.get("note") or "") for r in rows_880)
    triggered = False
    silent = False
    reason = ""
    if len(rows_880) < CONSEC_DAYS:
        reason = "样本不足（511880 行数 <2）"
    elif any(x is None for x in rows_990):
        missing = [r["date"] for r, x in zip(rows_880, rows_990) if x is None]
        reason = f"511990 在对齐日期缺行：{'/'.join(missing)}"
    else:
        below_880 = all(float(r["value"]) < ALERT_THRESH_BP for r in rows_880)
        below_990 = all(float(x["value"]) < ALERT_THRESH_BP for x in rows_990
                        if x is not None)
        if below_880 and below_990:
            if exdiv_recent:
                silent = True
                reason = f"触发但末 {CONSEC_DAYS} 日含除权修复行 → 除权窗静默"
            else:
                triggered = True
        elif below_880 or below_990:
            reason = "单基金越线（不同向），未触发"
    return {
        "asof": asof,
        "rows_880": rows_880,
        "rows_990": [x for x in rows_990 if x is not None],
        "n_rows_880": len(full_880),
        "triggered": triggered,
        "silent": silent,
        "reason": reason,
        "index": _index_daily_chg(data_root),
        "shibor": _shibor_1w_move(data_root),
        "today": today,
    }


def classify_state(state: dict[str, Any]) -> str:
    """触发时的性质标注（嫌疑级，联动股指/Shibor；不触发返回常规文案）。"""
    if not state["triggered"]:
        if state["silent"]:
            return f"静默：{state['reason']}"
        if state["reason"]:
            return f"未触发（{state['reason']}）"
        return "正常噪声区间（基线 P5=-0.8bp/P95=+2.8bp；触发线连续2日<-5bp且双基金同向）"
    index = state.get("index")
    shibor = state.get("shibor")
    index_chg = index["chg_pct"] if index else None
    shibor_d = shibor["chg_bp"] if shibor else None
    risk_off = (index_chg is not None and index_chg <= -0.5) or \
               (shibor_d is not None and shibor_d >= 3.0)
    risk_on = (index_chg is not None and index_chg >= 0.5) and \
              (shibor_d is not None and shibor_d <= 1.0)
    ctx = (f"上证{index_chg:+.2f}%（{index['date']}）"
           if index else "上证读数缺") + \
          ("；Shibor 1W {:.3f}%（{:+.1f}bp）".format(
              shibor["value_pct"], shibor_d) if shibor else "；Shibor 读数缺")
    if risk_off:
        return (f"⚠️ 触发，{ctx} → risk-off 挤赎嫌疑（2016-12 型：货基遭赎回应对"
                "流动性紧张，非做多信号）——人工复核")
    if risk_on:
        return (f"⚠️ 触发，{ctx} → risk-on 嫌疑（卖货基腾钱买股）——人工复核")
    return f"⚠️ 触发，{ctx} → 方向不明（语境中性）——人工复核"


def format_money_etf_section(state: dict[str, Any]) -> str:
    """日报段渲染（两行读数 + 一行状态；数据滞后一交易日显式标注）。"""
    def _brief(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "无数据"
        return "；".join(
            "{} {:+.2f}bp".format(r["date"][5:], float(r["value"])) for r in rows)

    lines = [
        "> 货币ETF场内折溢价（A股资金面温度计，只记读数不设灯；净值 T+1 披露，"
        "读数截至上一交易日）：",
        f"> - 银华日利 511880（vs 净值）：{_brief(state['rows_880'])}"
        f"｜华宝添益 511990（vs 100锚）：{_brief(state['rows_990'])}",
        f"> - 状态：{classify_state(state)}",
    ]
    if state.get("today") and state.get("asof"):
        gap = (state["today"] > state["asof"])
        if gap and state["n_rows_880"] and \
                _calendar_gap_days(state["asof"], state["today"]) > 10:
            lines.append(f"> - ⚠️ 序列陈旧：末行 {state['asof']}，距今超 10 日，"
                         "通路可能异常（update_money_etf_premium.py）")
    return "\n".join(lines)


def _calendar_gap_days(older: str, newer: str) -> int:
    from datetime import date as _date
    try:
        a = _date.fromisoformat(older)
        b = _date.fromisoformat(newer)
    except ValueError:
        return 0
    return (b - a).days


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="货币ETF场内折溢价温度计更新（511880 主锚+511990 第二腿，"
                    "Q-20261127-01）")
    parser.add_argument("--days", type=int, default=60,
                        help="回看窗天数（默认 60；首拉/长缺口回补用 --days 500）")
    args = parser.parse_args(argv)
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    from batch_ledger import close_batch, open_batch

    run_id = open_batch("batch-money-etf", data_root)
    written: list[tuple[Path, str]] = []
    missing: list[dict] = []
    used: set[str] = set()
    fail = False
    # 511880 = 主锚：失败非零（同 RRP 主系列语义）；511990 = 第二腿确认：
    # 失败告警+missing 不阻塞（同 HY OAS 降级语义，次日自愈）。
    try:
        stats = update_511880(data_root, days=args.days, sink=written)
        if stats["imported"] > 0:
            used.add(stats["source"])
    except Exception as exc:  # noqa: BLE001
        fail = True
        missing.append({"item": SERIES_511880, "reason": str(exc)})
        log(f"Warning: 511880 溢价更新失败: {exc}")
    try:
        stats990 = update_511990(data_root, days=args.days, sink=written)
        if stats990["imported"] > 0:
            used.add(stats990["source"])
    except Exception as exc:  # noqa: BLE001
        missing.append({"item": SERIES_511990, "reason": str(exc)})
        log(f"Warning: 511990 溢价更新失败: {exc}")
    close_batch(run_id, written, data_root, sources=sorted(used), missing=missing)
    try:
        state = money_etf_state(data_root)
        log("state: asof={} triggered={} silent={} n={}".format(
            state["asof"], state["triggered"], state["silent"],
            state["n_rows_880"]))
    except Exception as exc:  # noqa: BLE001 — 状态汇总失败不影响更新判定
        log(f"Warning: 温度计状态汇总失败: {exc}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
