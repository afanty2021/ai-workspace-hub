"""gate70 弱票反转观察清单——全市场日扫 + 日报接入（R20261110-07 产品化）。

上游验证链：R20261110-01 事件级（gate70=CROSS(RSI5,20)∧ADX>70 严格 OOS lift ×2.1、
+2.47%/20 日 t=28.1、OOS 费后个股 +5.92pp/yr vs 单票 BH）；R20261110-02 组合级
（不可集中收割——正确载体=分散/观察）。**本脚本的岗位=筛选器：信号找票、研究定夺，
不是买入指令**；单票 20 日持有的事件级期望 ≈ +2%，分布右偏胜率 ~54%，且池依赖性
已证（强势自选池/ETF 不迁移）。

每日收盘后流程：
  1. 增量更新 data/wyckoff/daily/ 个股缓存（mootdx bars 尾部 15 根；**只追加新日期
     + 刷新近 7 日行**——历史行一律不覆盖，Q-20261110-08 静默改史教训当日落地）
  2. 全市场扫描（复用 stage_bottom.py 翻译核；尾窗 420 根计算，EWM 瞬态与全序列
     种子差 <1e-5——R20261110-01 warmup=60 已验证）
  3. 宇宙过滤对靶 sleeve U1-U4：≥250 根 / close≥2 元 / amt20≥3000 万 / 相邻 bar
     间隔≤10 日历日；只取个股（60/68xxxx.SH + 00/30xxxx.SZ；ETF/LOF/指数全剔）
     ——ST 不可从缓存判定=执行边界，名单保留由人工复核剔除
  4. 信号：gate70（主，OOS 验证臂）+ deep10=CROSS(RSI5,10)（副，每事件 ×3 但
     稀疏 sleeve 形态——只报读数不主张）
  5. 产物：output/screen/weak-reversal/{date}.md（人读）+ latest.md（日报节引用）
     + data/stage-bottom/weak-reversal-ledger.jsonl 台账（(date,sym,kind) 幂等去重，
     weak_eval.py 消费）

非交易日：探测票最新 bar ≠ 今日 → 打印一行退出 0（cron 节假日自静默）。
用法：python weak_scan.py [--no-update] [--limit N] [--probe 000001.SZ]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from stage_bottom import roll_max, roll_min, roll_sum, tdx_sma  # noqa: E402

CACHE = REPO_ROOT / "data" / "wyckoff" / "daily"
OUT_DIR = REPO_ROOT / "output" / "screen" / "weak-reversal"
LEDGER = REPO_ROOT / "data" / "stage-bottom" / "weak-reversal-ledger.jsonl"

STOCK_RE = re.compile(r"^(?:(?:60|68)\d{4}\.SH|(?:00|30)\d{4}\.SZ)$")
TAIL = 420                 # 指标计算尾窗（60 warmup + 充裕余量）
REFRESH_DAYS = 7           # 近 N 日行允许刷新（mootdx 当日 bar 可能未结算完整）
MIN_BARS, MIN_PRICE, MIN_AMT = 250, 2.0, 3e7   # U1/U2/U3（对靶 sleeve.py）
GAP_DAYS = 10              # U4
ADX_CUT = 70.0             # gate70（IS<2020 切点 70.1 → 70，R20261110-01 OOS 验证）
FETCH_OFFSET = 15          # mootdx 尾部拉取根数（覆盖周末+节假日缺口）


def load_rows(path: Path) -> list[dict]:
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _df_to_rows(df) -> list[dict]:
    """mootdx bars DataFrame → 缓存行（口径同 wyckoff/loader._df_to_rows）。"""
    import pandas as pd
    idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df["datetime"])
    rows = []
    for ts, (_, r) in zip(idx, df.iterrows()):
        vol = r.get("vol")
        amt = r.get("amount")
        rows.append({
            "date": pd.Timestamp(ts).date().isoformat(),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(vol) if vol == vol and vol else None,
            "amount": float(amt) if amt == amt and amt else None,  # 评审 M-2：None/NaN/0 与 volume 行同语义
            "source": "mootdx-weakscan",
        })
    rows.sort(key=lambda x: x["date"])
    return rows


def update_one(path: Path, code: str) -> tuple[int, str]:
    """尾部增量：新日期追加 + 近 7 日行刷新；历史行不覆盖（防静默改史）。原子写回。"""
    from mootdx_source import _mootdx_call
    df = _mootdx_call("bars", symbol=code, frequency=9, offset=FETCH_OFFSET, start=0)
    if df is None or df.empty:
        return 0, "empty"
    fresh = _df_to_rows(df)
    existing = {r["date"]: r for r in load_rows(path)}
    today_iso = date.today().isoformat()
    refresh_lb = (date.today() - timedelta(days=REFRESH_DAYS)).isoformat()
    added = 0
    for r in fresh:
        d = r["date"]
        if d not in existing:
            existing[d] = r
            added += 1
        elif d >= refresh_lb:                       # 尾部刷新窗内才允许覆盖
            existing[d] = r
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(existing[d], ensure_ascii=False)
                             for d in sorted(existing)) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return added, today_iso


def scan_one(rows: list[dict], today_iso: str) -> dict | None:
    """单票扫描：返回事件 dict 或 None。指标=尾窗计算；U 过滤对靶 sleeve。"""
    if len(rows) < MIN_BARS + 1:
        return None
    if rows[-1]["date"] != today_iso:               # 今日无 bar（停牌/退市）不扫
        return None
    tail = rows[-TAIL:]
    c = np.array([r["close"] for r in tail], float)
    h = np.array([r["high"] for r in tail], float)
    l = np.array([r["low"] for r in tail], float)
    amt = np.array([r.get("amount") or 0.0 for r in tail], float)
    di = [int(r["date"].replace("-", "")) for r in tail]

    lc = np.roll(c, 1); lc[0] = np.nan
    diff = c - lc
    up = tdx_sma(np.where(diff > 0, diff, 0.0), 5, 1)
    dn = tdx_sma(np.abs(diff), 5, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(dn > 0, up * 100.0 / dn, np.nan)
    tr = np.maximum(np.maximum(h - l, np.abs(h - lc)), np.abs(l - lc))
    tr1 = roll_sum(tr, 10)
    hd, ld = h - np.roll(h, 1), np.roll(l, 1) - l
    hd[0] = ld[0] = np.nan
    dmp = roll_sum(np.where((hd > 0) & (hd > ld), hd, 0.0), 10)
    dmm = roll_sum(np.where((ld > 0) & (ld > hd), ld, 0.0), 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(tr1 > 0, dmp * 100.0 / tr1, np.nan)
        mdi = np.where(tr1 > 0, dmm * 100.0 / tr1, np.nan)
        dx = np.where((mdi + pdi) > 0, np.abs(mdi - pdi) * 100.0 / (mdi + pdi), np.nan)
    adx = roll_sum(dx, 5) / 5.0                     # roll_sum NaN 窗语义=MA 无效同款
    hh10, ll10 = roll_max(h, 10), roll_min(l, 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        wr10 = np.where((hh10 - ll10) > 0, (hh10 - c) * 100.0 / (hh10 - ll10), np.nan)
    amt20 = roll_sum(amt, 20) / 20.0

    i = len(tail) - 1
    if np.isnan(rsi[i]) or np.isnan(adx[i]) or np.isnan(amt20[i]):
        return None
    # U4 精确日历差（YYYYMMDD 差值跨月边界不可靠——10-31→11-09 差仅 878）
    from datetime import datetime
    d0 = datetime.strptime(rows[-2]["date"], "%Y-%m-%d").date()
    d1 = datetime.strptime(rows[-1]["date"], "%Y-%m-%d").date()
    if (d1 - d0).days > GAP_DAYS:
        return None
    if c[i] < MIN_PRICE or amt20[i] < MIN_AMT:
        return None
    cross20 = rsi[i] > 20.0 and rsi[i - 1] <= 20.0 and not np.isnan(rsi[i - 1])
    cross10 = rsi[i] > 10.0 and rsi[i - 1] <= 10.0 and not np.isnan(rsi[i - 1])
    kind = None
    if cross20 and adx[i] > ADX_CUT:
        kind = "gate70"
    elif cross10:
        kind = "deep10"
    else:
        return None
    return {"sym": None, "date": today_iso, "kind": kind,
            "close": float(c[i]), "rsi5": float(rsi[i]), "adx": float(adx[i]),
            "wr10": float(wr10[i]) if not np.isnan(wr10[i]) else None,
            "amt20": float(amt20[i]), "bars": len(rows),
            "prev_close": float(c[i - 1])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-update", action="store_true", help="跳过缓存日更（只扫描）")
    ap.add_argument("--limit", type=int, default=0, help="只扫前 N 个文件（冒烟）")
    ap.add_argument("--probe", default="000001.SZ", help="交易日探测票")
    args = ap.parse_args(argv)
    today_iso = date.today().isoformat()

    files = sorted(p for p in CACHE.glob("*.jsonl") if STOCK_RE.match(p.stem))
    probe_path = CACHE / f"{args.probe}.jsonl"

    if not args.no_update:
        from mootdx_source import _mootdx_call  # noqa: F401  提前失败若环境缺 mootdx
        n, _ = update_one(probe_path, args.probe.split(".")[0])
        latest = load_rows(probe_path)[-1]["date"]
        if latest != today_iso:
            print(f"[skip] 非交易日或数据未出：{args.probe} 最新 bar {latest} ≠ {today_iso}")
            return 0
    elif not probe_path.exists() or load_rows(probe_path)[-1]["date"] != today_iso:
        # 评审 M-1：--no-update 且缓存陈旧时拒绝扫描——否则全票 rows[-1]≠today 全 None，
        # 会把「数据缺失」伪装成「今日无信号」写入 {today}.md
        print(f"[skip] --no-update 但探测票缓存最新 bar 非 {today_iso}——陈旧缓存拒绝扫描（先正常日更一次）")
        return 0

    if args.limit:
        files = files[: args.limit]

    updated, updated_fail = 0, 0
    if not args.no_update:
        for k, path in enumerate(files):
            try:
                update_one(path, path.stem.split(".")[0])
                updated += 1
            except Exception:                       # noqa: BLE001 单票失败不拖垮全扫
                updated_fail += 1
            if (k + 1) % 500 == 0:
                print(f"..update {k + 1}/{len(files)}", file=sys.stderr)

    events = []
    for k, path in enumerate(files):
        try:
            rows = load_rows(path)
        except Exception:                           # noqa: BLE001
            continue
        ev = scan_one(rows, today_iso)
        if ev:
            ev["sym"] = path.stem
            events.append(ev)
    gate = [e for e in events if e["kind"] == "gate70"]
    deep = [e for e in events if e["kind"] == "deep10"]

    # 台账（幂等：同 (date,sym,kind) 不重复追加）
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if LEDGER.exists():
        for r in load_rows(LEDGER):
            seen.add((r["date"], r["sym"], r["kind"]))
    new = [e for e in events if (e["date"], e["sym"], e["kind"]) not in seen]
    if new:
        with open(LEDGER, "a", encoding="utf-8") as fh:
            for e in new:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    # 日报节产物
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"gate70 弱票反转扫描（{today_iso}）：**{len(gate)} 只**主信号"
             + (f"，deep10 深度 {len(deep)} 只（稀疏副臂，只报读数）" if deep else "")
             + "。岗位=观察清单（R20261110-07），事件级 20 日期望 ≈ +2%（胜率 ~54%），"
               "不构成买入指令；ST/次新边界由人工复核。", ""]
    if gate:
        gate.sort(key=lambda e: -e["adx"])
        lines += ["| 代码 | 收盘 | RSI5 | ADX | WR10 | 20日均额(亿) | 前收 |",
                  "|---|---|---|---|---|---|---|"]
        for e in gate[:30]:
            wr = f"{e['wr10']:.0f}" if e["wr10"] is not None else "—"
            lines.append(f"| {e['sym']} | {e['close']:.2f} | {e['rsi5']:.1f} "
                         f"| {e['adx']:.0f} | {wr} | {e['amt20'] / 1e8:.2f} "
                         f"| {e['prev_close']:.2f} |")
        if len(gate) > 30:
            lines.append(f"| … | 另 {len(gate) - 30} 只见台账 | | | | | |")
    else:
        lines.append("今日无 gate70 信号（常态——密度约 9 事件/票/14 年，全市场日均 "
                     "~20-30 只）。")
    body = "\n".join(lines)
    (OUT_DIR / f"{today_iso}.md").write_text(body + "\n", encoding="utf-8")
    (OUT_DIR / "latest.md").write_text(body + "\n", encoding="utf-8")
    print(f"[ok] {today_iso}: gate70 {len(gate)} / deep10 {len(deep)}；"
          f"cache 更新 {updated} 失败 {updated_fail}；台账新增 {len(new)}")
    print(f"     {OUT_DIR / today_iso}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
