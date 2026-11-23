"""科技回补三灯读数（Q-20261123-04 接线）：本地序列只读计算 + 人工槽位。

清单与预注册定义：`workspace/monitoring/tech-reentry-three-lights.md`（v1.0，
2026-11-23 用户拍板）。本模块只计算与标注灯状态，不判断「能否建仓」——
建仓规则（全 AND/分支A 分批变体）在清单里，由人执行。

数据面（全部本地只读，零网络，盘前/盘后安全共用）：
- data/market/series/{^IXIC,DX-Y.NYB,^TNX,XAUUSD=X,^SOX}.jsonl（跨资产历史管道，
  update_cross_asset_history 18:10 档回补）
- data/custom/us-hy-oas.jsonl（FRED BAMLH0A0HYM2，update_us_liquidity 18:25 档）
- FedWatch / BTC 两槽位=人工补读（清单口径：FedWatch=会前重定价读数、BTC=周一
  周读佐证），渲染占位行由报告生成会话补填。

阈值常量=清单 v1.0 预注册值的唯一代码落点；改阈值走 review-queue 改版清单 v1.1+
并同步此处（修订纪律）。
"""

from __future__ import annotations

import json
import math
from datetime import date as _date
from pathlib import Path
from typing import Any

# ── 预注册阈值（清单 v1.0；改这里必须先改清单） ──
USD_NEW_HIGH_WINDOW = 60      # 1a：60 日新高窗
RATE_NEW_HIGH_WINDOW = 20     # 1b：20 日新高窗
STREAK_NEED = 5               # 1a/1b：连续 5 个交易日
RATE_CEILING = 5.12           # 1b：11-16~18 峰值平台，未收复=腿不破
HYOAS_VETO_BP = 380.0         # 1c：基线 352 走阔 ≥8%（≈380）连续 2 日=一票否决
RV_WINDOW = 20                # 1d：20 日实现波动率
RV_THRESHOLD = 30.0           # 1d：<30 连续 5 日（年化 %，VIX 可比口径）
RV_ANNUALIZE = 252
GOLD_WEEKLY_LEVEL = 3534.64   # 灯2：11-20 崩盘收盘=体温计位，周收盘收复
EMA_FAST = 8                  # 3c：金叉快线
EMA_SLOW = 21                 # 3a/3b：主灯均线
FLAT_PCT = 0.005              # 3a：21EMA 五日累计 |Δ|<0.5%
FLAT_WINDOW = 5               # 3a：连续 5 日
HOLD_DAYS = 3                 # 3b：收盘 >21EMA 连续 3 日

SERIES_DIR = "market/series"
CUSTOM_DIR = "custom"

IXIC = "^IXIC"
USD = "DX-Y.NYB"
RATE = "^TNX"
GOLD = "XAUUSD=X"
SOX = "^SOX"
HY_OAS_SERIES = "us-hy-oas"


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """容错读 jsonl（torn 行跳过）：显示用途，权威读写走 market_data_io/save_custom_data。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _closes(rows: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for row in rows:
        try:
            v = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(v) and v > 0:
            out.append(v)
    return out


def streak_not_new_high(closes: list[float], window: int) -> int:
    """尾部连续「收盘未创 window 日新高」天数（最新一天创新高则 0）。

    判定日 d 需 d >= window（有完整前窗）；不足样本的天不计入连续段——
    样本不足返回 0，由调用方另以样本数标注「样本不足」。"""
    count = 0
    for d in range(len(closes) - 1, window - 1, -1):
        if closes[d] >= max(closes[d - window:d]):
            break
        count += 1
    return count


def compute_rv_annpct(closes: list[float], window: int = RV_WINDOW,
                      annualize: int = RV_ANNUALIZE) -> float | None:
    """window 日实现波动率（日对数收益样本标准差 ×√annualize×100，年化 %，VIX 可比）。"""
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(len(closes) - window, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(annualize) * 100.0


def rv_below_streak(closes: list[float], threshold: float = RV_THRESHOLD,
                    window: int = RV_WINDOW) -> int:
    """尾部连续「RV(window)<threshold」天数（RV 算不出不计入）。"""
    count = 0
    for d in range(len(closes), window, -1):
        rv = compute_rv_annpct(closes[:d], window=window)
        if rv is None or rv >= threshold:
            break
        count += 1
    return count


def ema_series(values: list[float], span: int) -> list[float]:
    """标准 EMA（种子=首 span 个的 SMA，α=2/(span+1)）；样本 <span 返回 []。"""
    if len(values) < span:
        return []
    alpha = 2.0 / (span + 1)
    out = [sum(values[:span]) / span]
    for v in values[span:]:
        out.append(out[-1] * (1 - alpha) + v * alpha)
    return out


def trend_state(closes: list[float]) -> dict[str, Any]:
    """灯3 状态：21EMA 走平/站稳连续天数 + 8/21 金叉状态。

    - flat_streak：尾部连续 |EMA21[t]/EMA21[t-FLAT_WINDOW]-1| < FLAT_PCT 天数
    - hold_streak：尾部连续 收盘>EMA21 天数
    - cross：'golden'/'dead' + 最近交叉距今天数（EMA8/21 相对位置翻转点）
    - 对齐：ema_fast[t+F] 与 ema_slow[t] 收在同一根收盘（F=EMA_SLOW-EMA_FAST），
      两序列种子起点不同（span-1 个 SMA 丢弃），直接同下标比较差 13 根 bar
      （2026-11-23 冒烟实证：崩盘死叉被误报成金叉 23 日前）。"""
    ema_fast = ema_series(closes, EMA_FAST)
    ema_slow = ema_series(closes, EMA_SLOW)
    if not ema_slow:
        return {"ok": False, "reason": f"样本 <{EMA_SLOW} 日"}
    flat_streak = 0
    for t in range(len(ema_slow) - 1, FLAT_WINDOW - 1, -1):
        base = ema_slow[t - FLAT_WINDOW]
        if base <= 0 or abs(ema_slow[t] / base - 1.0) >= FLAT_PCT:
            break
        flat_streak += 1
    offset = EMA_SLOW - 1  # ema_slow[t] ↔ closes[offset+t]
    hold_streak = 0
    for t in range(len(ema_slow) - 1, -1, -1):
        if closes[offset + t] <= ema_slow[t]:
            break
        hold_streak += 1
    cross = "dead"
    cross_days_ago: int | None = None
    fast_step = EMA_SLOW - EMA_FAST
    for t in range(len(ema_slow) - 1, 0, -1):
        f_prev, s_prev = ema_fast[t - 1 + fast_step], ema_slow[t - 1]
        f_now, s_now = ema_fast[t + fast_step], ema_slow[t]
        if (f_prev - s_prev) * (f_now - s_now) < 0 or (
                f_prev == s_prev and f_now != s_now):
            cross_days_ago = (len(closes) - 1) - (offset + t)
            cross = "golden" if f_now > s_now else "dead"
            break
    else:
        cross = "golden" if ema_fast[-1] > ema_slow[-1] else "dead"
        cross_days_ago = None
    return {"ok": True, "flat_streak": flat_streak, "hold_streak": hold_streak,
            "cross": cross, "cross_days_ago": cross_days_ago,
            "ema21": ema_slow[-1], "close": closes[-1]}


def weekly_closes(rows: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    """日行 → ISO 周分组尾行 {（年,周）: {week_end, close}}。

    周内最后一行未必是周五（假日/缺行），以周内实际尾行收盘/日期为准。"""
    by_week: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        try:
            day = _date.fromisoformat(str(row["date"])[:10])
            close = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        iso = day.isocalendar()
        by_week[(iso[0], iso[1])] = {"week_end": day.isoformat(), "close": close}
    return by_week


def gold_state(rows: list[dict[str, Any]], level: float = GOLD_WEEKLY_LEVEL,
               today: _date | None = None) -> dict[str, Any]:
    """灯2：最近完整周收盘 vs 体温计位。

    「完整周」判定=分组周键 != today 所在 ISO 周，或 today 为周六/日（周五 ET 收盘
    要到北京周六盘前才可得——周一~周五本 ISO 周不判完整周，周六起末组转正）。
    today 注入供测试，勿在模块内取 date.today()——时间炸弹纪律。
    贴线=|周收-level|/level ≤ 0.5%（破位中/收复的人工判断只作标注不作灯）。"""
    if today is None:
        today = _date.today()
    current_key = today.isocalendar()[:2]
    week_finalized = today.weekday() >= 5  # 周六/日=5/6
    by_week = weekly_closes(rows)
    if not by_week:
        return {"ok": False, "reason": "无可解析周行"}
    completed = {k: v for k, v in by_week.items()
                 if k != current_key or week_finalized}
    current = by_week[max(by_week)]
    if not completed:
        return {"ok": False, "reason": "无完整周（样本仅本周）",
                "current_close": current["close"],
                "current_week_end": current["week_end"]}
    last = completed[max(completed)]
    return {"ok": True, "week_end": last["week_end"], "weekly_close": last["close"],
            "above": last["close"] >= level,
            "near_level": abs(last["close"] - level) / level <= 0.005,
            "current_close": current["close"],
            "current_week_end": current["week_end"]}


def hy_oas_state(rows: list[dict[str, Any]],
                 veto_bp: float = HYOAS_VETO_BP) -> dict[str, Any]:
    """灯1c：HY OAS 最新值（bp）+ 否决判定（≥veto 连续 2 日）。"""
    pts: list[tuple[str, float]] = []
    for row in rows:
        try:
            v = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        pts.append((str(row.get("date", "")), v))
    if not pts:
        return {"ok": False, "reason": "us-hy-oas 无有效行"}
    pts.sort()
    veto_streak = 0
    for _, v in reversed(pts):
        if v < veto_bp:
            break
        veto_streak += 1
    return {"ok": True, "date": pts[-1][0], "value_bp": pts[-1][1],
            "veto": veto_streak >= 2, "veto_streak": veto_streak}


def assess_three_lights(data_root: Path) -> dict[str, Any]:
    """汇总各灯状态（子项失败彼此隔离，不炸整段）。"""
    def _series(ticker: str) -> tuple[list[float], str | None]:
        rows = _read_rows(data_root / SERIES_DIR / f"{ticker}.jsonl")
        dated = [str(r.get("date", ""))[:10] for r in rows if r.get("date")]
        return _closes(rows), (dated[-1] if dated else None)

    ixic, ixic_date = _series(IXIC)
    usd, usd_date = _series(USD)
    rate, rate_date = _series(RATE)
    sox, _sox_date = _series(SOX)
    gold_rows = _read_rows(data_root / SERIES_DIR / f"{GOLD}.jsonl")
    hy_rows = _read_rows(data_root / CUSTOM_DIR / f"{HY_OAS_SERIES}.jsonl")
    return {
        "usd": {"closes_n": len(usd), "latest_date": usd_date,
                "streak": streak_not_new_high(usd, USD_NEW_HIGH_WINDOW),
                "latest": usd[-1] if usd else None},
        "rate": {"closes_n": len(rate), "latest_date": rate_date,
                 "streak": streak_not_new_high(rate, RATE_NEW_HIGH_WINDOW),
                 "latest": rate[-1] if rate else None},
        "rv": {"closes_n": len(ixic), "latest_date": ixic_date,
               "rv": compute_rv_annpct(ixic),
               "streak": rv_below_streak(ixic)},
        "hy_oas": hy_oas_state(hy_rows),
        "gold": gold_state(gold_rows),
        "ixic_trend": trend_state(ixic) if ixic else {"ok": False, "reason": "^IXIC 无行"},
        "sox_trend": trend_state(sox) if sox else {"ok": False, "reason": "^SOX 无行"},
    }


def _fmt(v: float | None, nd: int = 2, suffix: str = "") -> str:
    if v is None:
        return "—"
    return f"{v:.{nd}f}{suffix}"


def _streak_cell(streak: int | None, need: int, n: int, min_samples: int) -> str:
    if n < min_samples or streak is None:
        return f"样本不足（{n}<{min_samples}）"
    mark = "✅" if streak >= need else "⬜"
    return f"{mark} N={streak}/{need}"


def format_three_lights(state: dict[str, Any], report_day: str) -> str:
    """评估结果 → 日报 markdown 段（含两人工槽位）。子项样本不足显式标注。"""
    usd, rate, rv = state["usd"], state["rate"], state["rv"]
    hy, gold = state["hy_oas"], state["gold"]
    ixic_t, sox_t = state["ixic_trend"], state["sox_trend"]

    rate_ok = (rate["latest"] is not None and rate["latest"] < RATE_CEILING)
    rate_streak = _streak_cell(rate["streak"], STREAK_NEED, rate["closes_n"],
                               RATE_NEW_HIGH_WINDOW + STREAK_NEED)
    rate_cell = (f"{_fmt(rate['latest'])}%（{rate.get('latest_date') or '—'}，"
                 f"{'未收复' if rate_ok else '**已收复**'} {RATE_CEILING}）｜{rate_streak}")

    rv_cell = _streak_cell(rv["streak"], STREAK_NEED, rv["closes_n"],
                           RV_WINDOW + STREAK_NEED)
    rv_value = f"RV20={_fmt(rv['rv'])}%" if rv["rv"] is not None else "RV20=—"

    if hy["ok"]:
        hy_status = "🚫 **否决触发**" if hy["veto"] else "未否决"
        hy_cell = f"{hy['value_bp']:.1f}bp（{hy['date']}）｜{hy_status}（≥{HYOAS_VETO_BP:.0f}×2 日）"
    else:
        hy_cell = f"—（{hy.get('reason', '无数据')}）"

    if gold["ok"]:
        mark = "✅" if gold["above"] else "⬜"
        near = "｜**贴线**（破位中/收复人工判）" if gold["near_level"] else ""
        gold_cell = (f"{mark} 完整周收 {_fmt(gold['weekly_close'])}（{gold['week_end']}）"
                     f"{'≥' if gold['above'] else '<'} {GOLD_WEEKLY_LEVEL}{near}"
                     f"｜最新 {_fmt(gold['current_close'])}（{gold['current_week_end']}）")
    else:
        gold_cell = f"—（{gold.get('reason', '无数据')}"
        if gold.get("current_close") is not None:
            gold_cell += f"；最新 {_fmt(gold['current_close'])}（{gold['current_week_end']}）"
        gold_cell += "）"

    def _trend_cell(t: dict[str, Any]) -> str:
        if not t.get("ok"):
            return f"—（{t.get('reason', '无数据')}）"
        if t["cross"] == "golden":
            cross_txt = f"✅ 金叉（{t['cross_days_ago']} 日前）"
        elif t["cross"] == "dead":
            cross_txt = "⬜ 无金叉"
        else:
            cross_txt = "—"
        flat_mark = "✅" if t["flat_streak"] >= FLAT_WINDOW else "⬜"
        hold_mark = "✅" if t["hold_streak"] >= HOLD_DAYS else "⬜"
        return (f"收 {_fmt(t['close'])}｜EMA21 {_fmt(t['ema21'])}｜"
                f"走平 {flat_mark} N={t['flat_streak']}/{FLAT_WINDOW}｜"
                f"站稳 {hold_mark} N={t['hold_streak']}/{HOLD_DAYS}｜{cross_txt}")

    # 四灯总览（清单预注册组合：灯1=1a∧1b∧1d 且 1c 未否决；灯2=完整周收 ≥ 体温计位；
    # 灯3=IXIC 3a∧3b ∧ SOX 3a∧3b（科技专项）；灯1.5=人工读数不参与机械总览）
    usd_ok = usd["streak"] >= STREAK_NEED and usd["closes_n"] >= USD_NEW_HIGH_WINDOW + STREAK_NEED
    rate_ok_streak = (rate["streak"] >= STREAK_NEED
                      and rate["closes_n"] >= RATE_NEW_HIGH_WINDOW + STREAK_NEED)
    rv_ok = rv["streak"] >= STREAK_NEED and rv["closes_n"] >= RV_WINDOW + STREAK_NEED
    hy_clear = bool(hy.get("ok")) and not hy.get("veto", True)
    light1 = usd_ok and rate_ok_streak and rate_ok and rv_ok and hy_clear
    light2 = bool(gold.get("ok")) and bool(gold.get("above"))

    def _light3(t: dict[str, Any]) -> bool:
        return (bool(t.get("ok")) and t["flat_streak"] >= FLAT_WINDOW
                and t["hold_streak"] >= HOLD_DAYS)

    light3 = _light3(ixic_t) and _light3(sox_t)

    def _mark(on: bool | None) -> str:
        return "—" if on is None else ("✅" if on else "⬜")

    lines = [
        "### 科技回补三灯读数（Q-20261123-04）",
        "",
        f"> 清单 v1.0：`workspace/monitoring/tech-reentry-three-lights.md`；本段=本地序列"
        f"只读计算（零网络，{report_day}）+ 两槽位人工补读。**12-09 FOMC 前为观察期："
        f"只记读数不建仓**；建仓规则（全 AND/分支A 分批变体）见清单，由人执行。",
        "",
        "| 灯 | 子项 | 读数 | 状态 |",
        "|---|---|---|---|",
        f"| **总览** | 灯1/灯1.5/灯2/灯3 | — | {_mark(light1)} / 人工 / {_mark(light2)} / {_mark(light3)} |",
        f"| 1 双因子 | 1a 美元腿（60 日新高窗） | {_fmt(usd['latest'])}（{usd.get('latest_date') or '—'}） | "
        f"{_streak_cell(usd['streak'], STREAK_NEED, usd['closes_n'], USD_NEW_HIGH_WINDOW + STREAK_NEED)} |",
        f"| 1 双因子 | 1b 利率腿（20 日新高窗 ∧<{RATE_CEILING}） | {rate_cell} | — |",
        f"| 1 双因子 | 1d 波动率（RV20<{RV_THRESHOLD:.0f} 年化%） | {rv_value} | {rv_cell} |",
        f"| 1 信用 | 1c HY OAS（否决线 {HYOAS_VETO_BP:.0f}bp） | {hy_cell} | {'🚫 灯1 熄灭' if hy.get('ok') and hy['veto'] else '—'} |",
        "| 1.5 政策 | FedWatch 12-09 加息定价 | （人工补读：CME FedWatch 快照，<50%=灯亮） | — |",
        f"| 2 黄金 | 周收盘收复 {GOLD_WEEKLY_LEVEL} | {gold_cell} | — |",
        f"| 3 趋势 | 3a/3b/3c ^IXIC 21EMA | {_trend_cell(ixic_t)} | — |",
        f"| 3 趋势 | 3d ^SOX（科技专项） | {_trend_cell(sox_t)} | — |",
        "| 佐证 | BTC 周线（非灯） | （人工周读：周一读上周收盘，仅记录） | — |",
        "",
    ]
    return "\n".join(lines)
