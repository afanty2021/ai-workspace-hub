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
  净值回落日改用前一日净值对价（回落幅度 ≥EXDIV_MIN_DROP_RATIO 才算除权——
  净值小幅下修是数据修订非除权，误标会把真触发毒化），修复后三年除权日读数
  全部回到 ±3bp；修复后仍 |溢价|>POISON_PREM_BP（±200bp）的行=口径断裂毒行，
  弃用不落盘但**必可见**（log+stats+账本 missing+日报段近期弃行提示）——
  2026-11-28 评审 C1 修根：原 ±50bp 静默守卫把 −60bp 真实折价一并吞掉（构造
  两日 -60bp 双腿实测 exit 0+「正常噪声区间」），守卫只可能吃到结构性断裂，
  ±200bp 内的真实极端读数照记（温度计的存在意义）。
  **2026-11-28 评审 A-I1 二次修根（价/净值联合判定）**：±200bp 守卫罩不住
  除权「修复失败族」四形态（修复前=静默缺行，修复后=±110bp 假读数落盘且不
  走可见化）。三层收紧、全部弃行显式缺行：①修复行 |溢价|>±30bp=修复失败
  （F-B/F-C 基准错位）；②除权调整窗（标签日后 2 个交易日）内未修复行
  |溢价|>±30bp=价未随净值归位（F-D）；③净值链过滤多带一行窗前净值（F-A
  窗头标签日的修复判据可用）。限制：调整窗内 ±30bp 外的真实极端行情会被判
  基准错位弃行（可见不静默）——除权窗本就触发静默、append-only 下假读数
  永久不可撤，显式缺行是更安全的失败模式。
- 511990 华宝添益（**固定净值型**，原 511988 已换码）：溢价率 = 收盘 ÷ 100
  （固定净值锚近似）。**天天基金 lsjz/fundmobapi 对固定净值型货基的 DWJZ
  字段返回万份收益（~0.26 元≈年化 0.95%）非单位净值**——不得跨基金复用
  解析；100 锚偏差 = 真实净值对 100 的偏离，全存量 26 个月溢价中位 +0.1bp
  ⇒ 系统性锚偏差 ≤0.1bp 量级、与噪声同量级（2026-11-28 评审 I-8 修：原引
  「11 月收盘 99.992~100.012」量的是溢价本身非净值偏离，论据作废）；
  511990 真净值接口核实=待验证项，登记 review-queue Q-20261128-02。
- 触发线（量具纪律：标定窗 2025-06~2026-11 基线 P5=-0.8bp/P95=+2.8bp、样本内
  从未出现，阈值与标定窗分离留待验证期检验）：**连续 2 个交易日 < -5bp 且
  双基金同向**（两行须相邻交易日，K6——中间缺行拼接不判触发）；
  511880 末 2 日任一含除权修复行 → 触发静默（除权窗剔除）。
- 时滞：货币基金净值 T+1 披露 → 18:10 批量跑出的溢价读数截至上一交易日，
  日报段显式标注。

写入 save_custom_data.append_record（同 us-liquidity 模式）：series=
cn-money-etf-prem-511880 / cn-money-etf-prem-511990，unit=bp，note 存
close/nav 原始数（4 位小数，2026-11-28 修 %g 截断——511880 存量 484/539 行
note 无法逐位复算的病灶；除权修复行加 exdiv-repair 标记并另存 nav_raw=当日
披露净值，修复前假溢价可精确重放）。幂等 skip 同 (series,date)。

性质标注联动（零网络，只读本地）：上证指数日涨跌（data/index/series/
000001.jsonl）+ Shibor 1W 日变动（data/custom/shibor-1w.jsonl）。**语境行
= 与 asof（读数日）同日的行及其前一行**——2026-11-28 评审 C2 修根：原取
序列末两行，净值 T+1 滞后下语境比读数日新一个交易日（11-27 实测 +3.73%
vs 对齐 +0.01%，三分支翻转率 60.3%），方向标签可被次日行情改写：
- 触发 + 股指跌 ≥0.5% 或 Shibor 上行 ≥3bp → risk-off 挤赎嫌疑（非做多）；
- 触发 + 股指涨 ≥0.5% 且 Shibor 变动 ≤+1bp → risk-on 卖货基买股嫌疑；
- 其余 → 方向不明（人工复核）。均为「嫌疑/待归因」级，不裁决。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

from fetch_market_data import DEFAULT_TIMEOUT
from mootdx_source import _mootdx_call, log
from save_custom_data import append_record, show_series

PINGZHONG_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"

FUND_511880 = "511880"
FUND_511990 = "511990"
PREM_511880_SERIES = "cn-money-etf-prem-511880"
PREM_511990_SERIES = "cn-money-etf-prem-511990"
NAME_511880 = "银华日利ETF(511880)场内溢价率（bp，vs 单位净值）"
NAME_511990 = "华宝添益ETF(511990)场内溢价率（bp，vs 100元固定净值锚）"

NAV_511990_ANCHOR = 100.0  # 固定净值型锚（系统性偏差 ≤0.1bp 量级，见 docstring）
ALERT_THRESH_BP = -5.0     # 连续 2 日 < -5bp 且双基金同向才触发（标定窗内未出现）
CONSEC_DAYS = 2
POISON_PREM_BP = 200.0     # 未修复行 |溢价| 超 ±200bp = 口径断裂行，弃用但必可见（C1 修根：
                           # ±200bp=货币基金到不了的量级，真实极端读数 ±200bp 内照记）
REPAIR_FAIL_POISON_BP = 30.0  # A-I1 二次修根：修复行单独收紧——除权标签日修复后仍
                              # 超 ±30bp=修复失败（价/净值基准错位），弃行显式缺行；
                              # 基线 P5/P95=±3bp，±30bp 已 10 倍于基线带，且除权窗
                              # 本就触发静默（限制见 docstring）
EXDIV_ADJUST_WINDOW = 2    # A-I1 F-D：标签日后 ≤2 个交易日价仍未随净值归位 →
                           # 判基准错位弃行（2024/2025 实录=提前一日，容错 2 日）
TRIGGER_MAX_DAY_GAP = 14   # K6：触发窗两行必须相邻交易日——连续交易日的日历
                           # gap 实测最长 11 天（春节+周末，2026-02-13→02-24），
                           # 超过 14=中间缺行拼接，不判触发（missing）
EXDIV_MARK = "exdiv-repair"
EXDIV_MIN_DROP_RATIO = 0.0005  # 净值回落 ≥0.05% 才算除权（I-7：下修 ~1e-5 量级
                               # 是数据修订，误标 exdiv 可毒化真触发）
BASELINE_P5_BP = -0.8      # 标定窗 2025-06~2026-11 基线（与触发线分离，验证期待检）
BASELINE_P95_BP = 2.8
STALE_GAP_DAYS = 10        # asof 距今超此日历日数 → 日报段「序列陈旧」提示
CONTEXT_MAX_STALE_DAYS = 10    # A-M9：语境行距 asof 超此日历日数 → 语境缺（None），
                               # 旧行不得照贴新标签（PAT-02 的闸）
SHIBOR_CONTEXT_TAIL = 400  # Shibor 语境读取上限行数（#12 下半：不再整读全文件；
                           # asof 早于此的语境按缺失处理）
ROUND_BP = 2

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _mootdx_bars(code: str, offset: int) -> list[dict[str, Any]]:
    """mootdx 日线 → [{date, close}] 正序（日期升序）。

    经 _mootdx_call 走统一「失败弃用服务器再抛」路径（spec §3：update/query
    类脚本禁直调 client.bars——直调会把掉线后的坏 client 留给第二腿复用，
    2026-11-28 评审 M2）。offset 上限 800=mootdx 单次拉取上限，超出截断并
    记 warning（原实现超限行为未定义）。"""
    if offset > 800:
        log(f"Warning: mootdx offset {offset} 超单次上限 800，按 800 拉"
            "（--days 过大时窗头缺行，分次拉或缩窗）")
        offset = 800
    df = _mootdx_call("bars", symbol=code, frequency=9, offset=offset)
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
        if isinstance(nav, (int, float)) and math.isfinite(nav) and nav > 0:
            # A-M6：isfinite 挡 inf（NaN 本就被 nav>0 滤掉）——上游脏值原会产出
            # NaN 行穿透到 append_record 才炸整腿
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
            if not math.isfinite(nav) or nav <= 0:  # A-M6：nan/inf 净值行拒收
                continue
            rows.append({"date": day, "nav": nav})
            seen.add(day)
            fresh += 1
        if fresh == 0:
            break  # 翻到已拉过的页=到头
        if page < pages:
            time.sleep(0.4)  # F10/M040：节流只在翻下一页前，末页不空睡
    rows.sort(key=lambda r: r["date"])
    if not rows:
        raise RuntimeError(f"lsjz {code} 净值行数为 0")
    return rows


def compute_premiums(closes: list[dict[str, Any]], navs: list[dict[str, Any]],
                     *, fixed_nav: float | None = None
                     ) -> tuple[list[dict[str, Any]], dict[str, list]]:
    """合并价/净值 → (落盘行, 弃行诊断)，含除权修复与毒行守卫（弃行可见化）。

    - 净值漂移型（fixed_nav=None）：净值回落日（nav[t] < nav[t-1] 且回落幅度
      ≥ EXDIV_MIN_DROP_RATIO，货币基金净值只在该日回落）= F10 除权标签日，
      价格实际次日才除权 → 改用前一日净值对价，行 note 标 exdiv-repair 并另存
      nav_raw=当日披露净值。回落幅度低于阈值=数据下修（非除权），不修复照常
      落行——2026-11-28 评审 I-7：下修误标 exdiv 会把末 2 日的真触发静默毒化。
    - 固定净值型（fixed_nav=100.0）：无净值序列，恒锚。
    - **A-I1 二次修根（价/净值联合判定）**：±200bp 守卫罩不住除权「修复失败族」
      四形态（原修复前=静默缺行，修复后=±110bp 假读数落盘且不走任何可见化）。
      三层收紧，全部弃行显式缺行不静默：
      ① 除权标签日修复后 |溢价| > REPAIR_FAIL_POISON_BP（±30bp）=修复失败
        （价/净值基准错位，F-B/F-C）→ 弃行；
      ② 除权调整窗（标签日后 ≤EXDIV_ADJUST_WINDOW 个交易日）内未修复行
        |溢价| > ±30bp=价未随净值归位（F-D 错位）→ 弃行；
      ③ |溢价| > POISON_PREM_BP（±200bp）=口径断裂毒行（C1 修根口径不变，
        非 ±200bp 内的真实极端读数照记）。
      **限制（硬规则要求写明）**：调整窗内 ±30bp 外的真实极端行情会被判为
      基准错位弃行（可见不静默）——除权窗本就触发静默，且 append-only 下假
      读数永久不可撤，显式缺行是更安全的失败模式。四形态中 F-A（窗口首行=
      标签日）由调用方多带一行窗前净值化解（见 update_511880）。
    - 净值缺行（T+1/停披）进 diag["nav_missing"] 不静默；close 非法（NaN/非正）
      在 compute 层拒收进 poisoned——原穿透到 append_record 才炸整腿。
    """
    nav_by_date = {r["date"]: r["nav"] for r in navs}
    ordered_dates = sorted(nav_by_date)
    pos = {d: i for i, d in enumerate(ordered_dates)}  # 原 ordered_dates.index() O(n²)
    # A-I1 联合判定原料：除权标签日集合 + 调整窗集合（标签日及其后 N 个交易日）
    exdiv_label_days: set[str] = set()
    exdiv_window_days: set[str] = set()
    for i, day in enumerate(ordered_dates):
        if i == 0:
            continue
        prev = nav_by_date[ordered_dates[i - 1]]
        cur = nav_by_date[day]
        if cur < prev and (prev - cur) / prev >= EXDIV_MIN_DROP_RATIO:
            exdiv_label_days.add(day)
            exdiv_window_days.add(day)
            lag = 0
            for j in range(i + 1, len(ordered_dates)):
                exdiv_window_days.add(ordered_dates[j])
                lag += 1
                if lag >= EXDIV_ADJUST_WINDOW:
                    break
    out: list[dict[str, Any]] = []
    diag: dict[str, list] = {"poisoned": [], "nav_missing": []}
    for row in closes:
        day = row["date"]
        close = row["close"]
        if not isinstance(close, (int, float)) or isinstance(close, bool) \
                or not math.isfinite(close) or close <= 0:
            diag["poisoned"].append({"date": day, "prem_bp": None,
                                     "reason": f"close 非法（{close!r}），不落盘"})
            continue
        if fixed_nav is not None:
            nav_eff, nav_raw, repaired = fixed_nav, None, False
        else:
            if day not in nav_by_date:
                diag["nav_missing"].append(day)  # T+1 未披露或停披——可见不静默
                continue
            nav_eff = nav_by_date[day]
            nav_raw = nav_eff
            repaired = False
            idx = pos[day]
            if day in exdiv_label_days and idx > 0:
                nav_eff = nav_by_date[ordered_dates[idx - 1]]  # 除权标签日 → 前一日净值对价
                repaired = True
        prem_bp = (close / nav_eff - 1.0) * 10000.0
        prem_r = round(prem_bp, ROUND_BP)  # A-M12：先舍入再比较——98/100 浮点尘
        if abs(prem_r) > POISON_PREM_BP:   # （200.00000000000017）不再误弃边界行
            diag["poisoned"].append({
                "date": day, "prem_bp": prem_r,
                "reason": f"|溢价|>{POISON_PREM_BP:g}bp 口径断裂毒行（价/净值口径核查后处理）"})
            continue
        if repaired and abs(prem_r) > REPAIR_FAIL_POISON_BP:
            diag["poisoned"].append({
                "date": day, "prem_bp": prem_r,
                "reason": f"除权修复后仍超 ±{REPAIR_FAIL_POISON_BP:g}bp=修复失败"
                          "（价/净值基准错位，A-I1），不落盘"})
            continue
        if not repaired and day in exdiv_window_days \
                and abs(prem_r) > REPAIR_FAIL_POISON_BP:
            diag["poisoned"].append({
                "date": day, "prem_bp": prem_r,
                "reason": f"除权调整窗（标签日后 {EXDIV_ADJUST_WINDOW} 交易日内）"
                          "异常读数=价未随净值归位（A-I1 F-D），不落盘"})
            continue
        note = f"close={close:.4f} nav={nav_eff:.4f}"
        if repaired:
            note += f" {EXDIV_MARK} nav_raw={nav_raw:.4f}"
        out.append({"date": day, "prem_bp": prem_r,
                    "close": close, "nav": nav_eff,
                    "exdiv": repaired, "note": note})
    return out, diag


def warn_diag(series: str, diag: dict[str, list],
              latest_close_date: str | None = None) -> None:
    """弃行诊断打日志（毒行+缺净值行都不静默；C1 修根的可见化半边）。

    A-M3：缺净值 Warning 分「T+1 未披露（最新交易日，常态）」与「停披/缺口
    （更早日期，异常）」——原混称一条 Warning 交易日必打，把常态当异常。"""
    for p in diag.get("poisoned", []):
        log(f"Warning: {series} 弃行（口径断裂，不落盘）: {p}")
    nav_missing = diag.get("nav_missing", [])
    latest_missing = [d for d in nav_missing if d == latest_close_date]
    older = [d for d in nav_missing if d != latest_close_date]
    if latest_missing and latest_close_date:
        log(f"Info: {series} 最新交易日 {latest_close_date} 净值未披露"
            "（T+1 常态，不落盘，明日净值到位后补算）")
    if older:
        log(f"Warning: {series} {len(older)} 行缺净值未落盘"
            f"（停披/缺口，异常）: {older}")


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
                  sink: list[tuple[Path, str]] | None = None,
                  used_sources: set[str] | None = None,
                  poison_sink: list[dict[str, Any]] | None = None
                  ) -> dict[str, Any]:
    """银华日利：净值链 auto（pingzhongdata→lsjz）+ mootdx 收盘 → 溢价落盘。

    lsjz 分页页数按「K 线根数（days+40 余量）÷pageSize(20)+2 页」起算——
    2026-11-28 评审 M11：原 days//20+2 在所有 days>40 且非 20 整倍数的窗
    （41–59/61–79/81–99…）头段缺行（余量 0 或负），缺净值行在 compute 层
    即成可见 nav_missing。
    A-I1 F-A：净值过滤 cutoff 时多带一行窗前净值——首拉窗头恰为除权标签日
    时修复判据（需前一日净值）同样可用，不再产出无标记假溢价行。"""
    closes = _mootdx_bars(FUND_511880, offset=max(days + 40, 80))
    cutoff = closes[0]["date"]
    navs: list[dict[str, Any]] = []
    used_source = ""
    errors: list[str] = []
    for label, fetch in (("pingzhongdata", lambda: fetch_nav_rows_pingzhong(FUND_511880)),
                         ("lsjz", lambda: fetch_nav_rows_lsjz(
                             FUND_511880, pages=max((days + 40) // 20 + 2, 4)))):
        try:
            nav_all = fetch()
            navs = [r for r in nav_all if r["date"] >= cutoff]
            if navs:
                # A-I1：多带一行窗前净值（修复判据原料），不影响落盘范围
                kept = {r["date"] for r in navs}
                for r in reversed(nav_all):
                    if r["date"] not in kept:
                        navs.insert(0, r)
                        break
                used_source = label
                break
            errors.append(f"{label}: 窗内 0 行")
        except Exception as exc:  # noqa: BLE001 — 降级链逐源收集，双败统一上抛
            errors.append(f"{label}: {exc}")
    if not navs:
        raise RuntimeError(f"511880 净值双源均失败: {'; '.join(errors)}")
    if len(errors) == 1:
        log(f"Warning: 511880 净值部分源失败已降级: {errors[0]}")
    rows, diag = compute_premiums(closes, navs)
    if poison_sink is not None:
        poison_sink.extend(dict(p, series=PREM_511880_SERIES)
                           for p in diag["poisoned"])  # A-M8：腿内中途失败时已
    warn_diag(PREM_511880_SERIES, diag,               # 发现的毒行也进 missing/sidecar
              latest_close_date=closes[-1]["date"])
    source_tag = {"pingzhongdata": "pingzhongdata+mootdx",
                  "lsjz": "lsjz+mootdx"}[used_source]
    leg_sink: list[tuple[Path, str]] = []
    try:
        stats = upsert_premiums(data_root, PREM_511880_SERIES, NAME_511880,
                                source_tag, rows, sink=leg_sink)
    finally:
        if sink is not None:
            sink.extend(leg_sink)
        # A-I3：记源条件=本腿确有写入（零新行日旧码也记满两源）；S6 语义不变
        # ——upsert 中途失败时 leg_sink 已含已写入行，source 照进账本
        if leg_sink and used_sources is not None:
            used_sources.add(source_tag)
    return {**stats, "source": source_tag,
            "poisoned": diag["poisoned"], "nav_missing": diag["nav_missing"]}


def update_511990(data_root: Path, *, days: int,
                  sink: list[tuple[Path, str]] | None = None,
                  used_sources: set[str] | None = None,
                  poison_sink: list[dict[str, Any]] | None = None
                  ) -> dict[str, Any]:
    """华宝添益：mootdx 收盘 ÷ 100 固定净值锚 → 溢价落盘（降级语义=告警不阻塞）。"""
    closes = _mootdx_bars(FUND_511990, offset=max(days + 40, 80))
    rows, diag = compute_premiums(closes, [], fixed_nav=NAV_511990_ANCHOR)
    if poison_sink is not None:
        poison_sink.extend(dict(p, series=PREM_511990_SERIES)
                           for p in diag["poisoned"])
    warn_diag(PREM_511990_SERIES, diag,
              latest_close_date=closes[-1]["date"])
    leg_sink: list[tuple[Path, str]] = []
    try:
        stats = upsert_premiums(data_root, PREM_511990_SERIES, NAME_511990,
                                "mootdx+nav100anchor", rows, sink=leg_sink)
    finally:
        if sink is not None:
            sink.extend(leg_sink)
        if leg_sink and used_sources is not None:  # A-I3 同主锚腿
            used_sources.add("mootdx+nav100anchor")
    return {**stats, "source": "mootdx+nav100anchor",
            "poisoned": diag["poisoned"], "nav_missing": diag["nav_missing"]}


def _read_series(data_root: Path, series: str, tail: int) -> list[dict[str, Any]]:
    return show_series(data_root, series, tail=tail)


def _index_daily_chg(data_root: Path, asof: str | None = None
                     ) -> dict[str, Any] | None:
    """上证指数日涨跌 %（零网络；缺序列/行数不足返回 None）。

    语境锚=asof（读数日）：取日期 ≤asof 的末两行——2026-11-28 评审 C2 修根：
    原取序列末两行，净值 T+1 滞后下语境比读数日新一个交易日（11-27 实测
    +3.73% vs 对齐 +0.01%，三分支翻转率 60.3%）。asof=None 保持旧口径（末两
    行）。坏行跳过不整段降级（原裸 json.loads 一行 torn 即丢整段语境）。"""
    from market_data_io import index_series_file

    path = index_series_file(data_root, "000001")
    if not path.exists():
        return None
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    if asof:
        rows = [r for r in rows if str(r.get("date", "")) <= asof]
        if rows and _calendar_gap_days(str(rows[-1].get("date")), asof) \
                > CONTEXT_MAX_STALE_DAYS:
            # A-M9：语境序列自身陈旧（缺 asof 行）→ 语境缺，旧行不得照贴新标签
            return None
    if len(rows) < 2:
        return None
    prev, last = rows[-2], rows[-1]
    try:
        chg = (float(last["close"]) / float(prev["close"]) - 1.0) * 100.0
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return {"date": last.get("date"), "chg_pct": round(chg, 2)}


def _shibor_1w_move(data_root: Path, asof: str | None = None
                    ) -> dict[str, Any] | None:
    """Shibor 1W 日变动 bp（零网络；语境锚=asof，同 _index_daily_chg C2 口径；
    A-M9 陈旧闸同款）。#12 下半：读 SHIBOR_CONTEXT_TAIL 行不再整读全文件。"""
    rows = [r for r in (_read_series(data_root, "shibor-1w",
                                     tail=SHIBOR_CONTEXT_TAIL) or [])
            if not asof or str(r.get("date", "")) <= asof]
    if rows and asof and _calendar_gap_days(str(rows[-1].get("date")), asof) \
            > CONTEXT_MAX_STALE_DAYS:
        return None
    if len(rows) < 2:
        return None
    try:
        prev, last = float(rows[-2]["value"]), float(rows[-1]["value"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"date": rows[-1].get("date"), "value_pct": last,
            "chg_bp": round((last - prev) * 100.0, 1)}


POISON_SIDECAR_RECENT_DAYS = 14  # 日报段「近期弃行」提示的回看窗（日历日）


def _record_poison_sidecar(data_root: Path, poisoned: list[dict[str, Any]],
                           today: str | None) -> None:
    """毒行弃用落 data/.state/money-etf-poison.json——日报段「近期弃行」
    提示的持久载体（弃行不落 series，state 从 sidecar 读；C1 修根）。
    失败只 log 不抛：sidecar 是提示面，不影响更新与退出码。
    A-I2：坏 JSON/截断文件当空处理（JSONDecodeError 是 ValueError 子类，原
    只接 OSError 会穿出 main）+ tmp+replace 原子写（写一半被杀不留半个文件）。
    A-M1：按 (series,date) 去重——弃行稳态下每轮重入原会滚成「近期弃行 54 条」。"""
    if not poisoned:
        return
    path = data_root / ".state" / "money-etf-poison.json"
    # 读侧自愈：坏 JSON/截断/非 list 当空（A-I2——读写同 try 会让坏文件连
    # 本轮写入一并放弃，毒行提示从此永远丢失）
    old: list = []
    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, list):
                old = parsed
        except ValueError:
            log("Warning: 毒行 sidecar 坏 JSON 当空处理（本轮照常重写）")
    try:
        merged: dict[tuple[str, str], dict] = {}
        for e in old:
            if isinstance(e, dict):
                merged[(str(e.get("series", "")), str(e.get("date", "")))] = e
        for e in poisoned:
            merged[(str(e.get("series", "")), str(e.get("date", "")))] = \
                dict(e, recorded_at=today or _today_iso())
        entries = list(merged.values())[-50:]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
        tmp_path.replace(path)  # A-I2：原子写——写一半被杀不留半个文件
    except (OSError, ValueError) as exc:
        log(f"Warning: 毒行 sidecar 写入失败（提示面缺失，不影响数据）: {exc}")


def _read_poison_sidecar(data_root: Path, today: str | None) -> list[dict[str, Any]]:
    """读 sidecar 中回看窗内的弃行记录（无文件/坏 JSON=无弃行，不抛）。
    A-M1：读侧同款 (series,date) 去重，提示条数=去重行数。"""
    path = data_root / ".state" / "money-etf-poison.json"
    if not path.exists() or not today:
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    dedup: dict[tuple[str, str], dict] = {}
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("recorded_at"), str) \
                and _calendar_gap_days(e["recorded_at"], today) <= POISON_SIDECAR_RECENT_DAYS:
            dedup[(str(e.get("series", "")), str(e.get("date", "")))] = e
    return list(dedup.values())


def money_etf_state(data_root: Path, today: str | None = None) -> dict[str, Any]:
    """只读本地序列 → 温度计状态（触发判定+语境标注原料）。零网络。

    对齐基准 = **511880 的末 CONSEC_DAYS 个日期**（净值 T+1 披露，读数天然
    滞后 511990 一天——511990 走 100 锚无净值依赖，按各自末行比较会永久
    错位）：511990 在同日期有行才参与触发；触发 = 两基金在同日期的值全 <
    ALERT_THRESH_BP。511880 该窗口任一行含 exdiv-repair 标记 → 静默。"""
    rows_880 = _read_series(data_root, PREM_511880_SERIES, tail=CONSEC_DAYS)
    rows_990_all = _read_series(data_root, PREM_511990_SERIES,
                                tail=CONSEC_DAYS + 2)  # 511990 天然超前，多读兜对齐
    # #12 下半：n_rows_880 只作真值用（B 席 M107 等价变异实证）——tail=1 探存在，
    # 不再整读全文件
    has_880 = bool(_read_series(data_root, PREM_511880_SERIES, tail=1))
    by990 = {r["date"]: r for r in rows_990_all}
    asof = rows_880[-1]["date"] if rows_880 else (
        rows_990_all[-1]["date"] if rows_990_all else None)
    rows_990 = [by990.get(r["date"]) for r in rows_880]

    exdiv_recent = any(EXDIV_MARK in (r.get("note") or "") for r in rows_880)
    triggered = False
    silent = False
    sample_ok = True  # A-M2：结构化字段——「该查没查成」不再靠 reason 子串判
    reason = ""
    if not rows_880:
        # 2026-11-28 评审 M9：主序列空时原只静默回退 asof 到 990 日期，易被读成正常
        sample_ok = False
        reason = "511880 序列空（读数日回退以 511990 末行为准，非正常态）"
    elif len(rows_880) < CONSEC_DAYS:
        sample_ok = False
        reason = "样本不足（511880 行数 <2）"
    elif len(rows_880) == CONSEC_DAYS and \
            _calendar_gap_days(rows_880[0]["date"], rows_880[-1]["date"]) \
            > TRIGGER_MAX_DAY_GAP:
        # K6：触发窗两行必须相邻交易日——中间缺行时 tail 拼接两行会假触发
        sample_ok = False
        reason = (f"触发窗日期不连续（{rows_880[0]['date']}→{rows_880[-1]['date']}，"
                  "中间缺行嫌疑，不判触发）")
    elif any(x is None for x in rows_990):
        sample_ok = False
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
        "n_rows_880": 1 if has_880 else 0,
        "sample_ok": sample_ok,
        "triggered": triggered,
        "silent": silent,
        "reason": reason,
        "poisoned_recent": _read_poison_sidecar(data_root, today or asof),
        "index": _index_daily_chg(data_root, asof=asof),
        "shibor": _shibor_1w_move(data_root, asof=asof),
        "today": today,
    }


def classify_state(state: dict[str, Any]) -> str:
    """触发时的性质标注（嫌疑级，联动股指/Shibor；不触发返回常规文案）。

    基线/触发线文案一律由常量拼装（2026-11-28 评审 M10：原写死在文案与
    常量脱钩）。「样本不足/序列空/对齐缺行/触发窗不连续」按 object-model 词表
    落 missing（该查没查成 ≠ 未触发，M13）；A-M2：归类吃 state["sample_ok"]
    结构化字段，不再吃 reason 子串——改一个词不再回退。"""
    if not state["triggered"]:
        if state["silent"]:
            return f"静默：{state['reason']}"
        if state["reason"]:
            if not state.get("sample_ok", True):
                return f"missing（该查没查成，不判读）：{state['reason']}"
            return f"未触发（{state['reason']}）"
        return (f"正常噪声区间（基线 P5={BASELINE_P5_BP:+.1f}bp/"
                f"P95={BASELINE_P95_BP:+.1f}bp；触发线连续{CONSEC_DAYS}日"
                f"<{ALERT_THRESH_BP:g}bp且双基金同向）")
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
          (f"；Shibor 1W {shibor['value_pct']:.3f}%（{shibor_d:+.1f}bp，"
           f"{shibor['date']}）" if shibor else "；Shibor 读数缺")
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
    pois = state.get("poisoned_recent") or []
    if pois:
        days = sorted({str(p.get("date")) for p in pois if p.get("date")})
        lines.append(
            f"> - ⚠️ 近期弃行 {len(pois)} 条（口径断裂毒行，未落盘）"
            f"{'，涉及 ' + '、'.join(days) if days else ''}——±{POISON_PREM_BP:g}bp 内"
            "真实极端读数照记；此提示=结构性口径断裂，人工核查价/净值口径"
            "（update_money_etf_premium.py）")
    if state.get("today") and state.get("asof"):
        gap = (state["today"] > state["asof"])
        if gap and state["n_rows_880"] and \
                _calendar_gap_days(state["asof"], state["today"]) > STALE_GAP_DAYS:
            lines.append(f"> - ⚠️ 序列陈旧：末行 {state['asof']}，距今超 "
                         f"{STALE_GAP_DAYS} 日，通路可能异常（长假连续休市期日历 "
                         "gap 自然偏大，属已知噪声；update_money_etf_premium.py）")
    return "\n".join(lines)


def _calendar_gap_days(older: str, newer: str) -> int:
    from datetime import date as _date
    try:
        a = _date.fromisoformat(older)
        b = _date.fromisoformat(newer)
    except ValueError:
        return 0
    return (b - a).days


def _today_iso() -> str:
    from datetime import date
    return date.today().isoformat()  # 仅作 sidecar recorded_at 运行时点元数据


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="货币ETF场内折溢价温度计更新（511880 主锚+511990 第二腿，"
                    "Q-20261127-01）")
    parser.add_argument("--days", type=int, default=60,
                        help="回看 K 线根数（交易日；净值链按根数+40 余量对齐，"
                             "默认 60；首拉/长缺口回补用 --days 500）")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 800:  # A-M7：负数/0 原静默当最小窗、超大值页数无上界
        parser.error(f"--days 须为 1..800（mootdx 单次拉取上限 800；得到 {args.days}）")
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    from batch_ledger import close_batch, open_batch

    run_id = open_batch("batch-money-etf", data_root)
    written: list[tuple[Path, str]] = []
    missing: list[dict] = []
    used: set[str] = set()
    poisoned_all: list[dict[str, Any]] = []
    fail = False
    # 511880 = 主锚：失败非零（同 RRP 主系列语义）；511990 = 第二腿确认：
    # 失败告警+missing 不阻塞（同 HY OAS 降级语义，次日自愈）。毒行弃用不
    # 静默：进 missing（object-model：口径断裂属 missing 词表）+ sidecar。
    # missing 条目带补数命令（object-model：missing 必须写 reason+补数，A-M2）。
    try:
        update_511880(data_root, days=args.days, sink=written,
                      used_sources=used, poison_sink=poisoned_all)
    except Exception as exc:  # noqa: BLE001
        fail = True
        missing.append({"item": PREM_511880_SERIES,
                        "reason": f"{exc}；补数=重跑 update_money_etf_premium.py "
                                  "--days 500（首拉）或等次日 18:10 自愈"})
        log(f"Warning: 511880 溢价更新失败: {exc}")
    try:
        update_511990(data_root, days=args.days, sink=written,
                      used_sources=used, poison_sink=poisoned_all)
    except Exception as exc:  # noqa: BLE001
        missing.append({"item": PREM_511990_SERIES,
                        "reason": f"{exc}；补数=次日 18:10 自愈或重跑同命令"
                                  "（第二腿失败只告警不置非零）"})
        log(f"Warning: 511990 溢价更新失败: {exc}")
    for p in poisoned_all:
        missing.append({"item": str(p.get("series", "")),
                        "reason": f"{p.get('date')} 毒行弃用不落盘"
                                  f"（{p.get('reason', '')}）；补数=人工核查该日"
                                  "价/净值口径后重跑（现无 --repair 通道，"
                                  "Q-20261128-03）"})
    close_batch(run_id, written, data_root, sources=sorted(used), missing=missing)
    if poisoned_all:
        _record_poison_sidecar(data_root, poisoned_all, today=_today_iso())
    try:
        state = money_etf_state(data_root)
        log("state: asof={} triggered={} silent={} n={} poisoned_recent={}".format(
            state["asof"], state["triggered"], state["silent"],
            state["n_rows_880"], len(state["poisoned_recent"])))
    except Exception as exc:  # noqa: BLE001 — 状态汇总失败不影响更新判定
        log(f"Warning: 温度计状态汇总失败: {exc}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
