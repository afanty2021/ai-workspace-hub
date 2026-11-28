"""美国 3-2-1 裂解价差派生序列（us-321-crack，Q-20261128-04 能源腿接线，2026-11-28）。

- 公式：crack = (2×RB + HO)×42 − 3×CL，再 ÷3（$/bbl 原油；RBOB/取暖油期货报价
  $/gal ×42 换算 $/bbl，42 gal=1 bbl）。3 桶原油 → 2 桶汽油 + 1 桶馏分油的炼厂毛利
  读数——Mills（Ahead of the Herd 2026-11-25）引为「能源腿降温领先指示器」：
  裂解价差六周 -36%、汽油期货两月 -45%。
- 三腿统一 yfinance 前月连续 RB=F / HO=F / CL=F（ET 日切、同源同滚合约口径）。
  **禁止与本地 data/market/series/CL=F.jsonl 跨源拼腿**：该序列混装新浪 hf 北京
  日切快照与东财 kline（2026-11-28 探针对拍：11-27 yahoo CL=F 收 83.08 vs 本地
  sina 行 85.817，同日错位一天+滚合约口径不同），错配即系统性毒化派生值
  （PAT-20261128-02 语境错位同族——修根=消灭混源，不做对齐补丁）。
- 守卫（PAT-20261128-01/02 全形态）：
  ① 三腿同日齐全才算行（日期交集，无 ffill）；缺腿逐日计 missing，不写行；
  ② 单位毒带可见化：RB/HO 落进 $/bbl 量级（20~150）= $/gal 源断裂成 $/bbl 的
  单位断裂特征（HG00Y 修根案同族），逐行拒收 + 计数 + 原因落 diag，不静默削波；
  ③ 裂解价差毒带 [-20, 80] $/bbl：越带=某腿坏数据，拒收可见；
  ④ 全部行被拒 / 0 行可算 → 退出码 1（I-1 语义：fail loud，不 warn-only）。
- 幂等：同 (series,date) 已有即 skip（save_custom_data.append_record 语义）；
  毒行/缺腿聚合进 batch 账本 missing（口径断裂属 missing 词表，object-model）。
- 手工档无 cron（12-09 FOMC 三分支复盘观察清单数据源，复盘窗前手工跑；
  series 名已入 tests/test_registration_contract.py DISCOVERY_SCRIPTS 发现网，
  改名会被三文档契约测试抓）。
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mootdx_source import log
from save_custom_data import append_record

RB_SYMBOL = "RB=F"  # NYMEX RBOB 汽油前月连续（$/gal）
HO_SYMBOL = "HO=F"  # NYMEX 取暖油（馏分油）前月连续（$/gal）
CL_SYMBOL = "CL=F"  # NYMEX WTI 前月连续（$/bbl）

CRACK_SERIES = "us-321-crack"
CRACK_SERIES_NAME = "美国 3-2-1 裂解价差（RBOB×2+取暖油−WTI×3，÷3）"
CRACK_SOURCE_TAG = "yfinance-rbf-hof-clf"

GAL_TO_BBL = 42.0

# 字面量毒带（PAT-20261128-05：夹具/断言不得引用被测常量构造输入；带值依据见行尾）
RB_GAL_BAND = (0.5, 5.0)   # $/gal 历史极值带（2020 谷 ~0.3 仅危机瞬间，拒收可接受）
HO_GAL_BAND = (0.5, 5.5)   # 馏分油价差高于汽油（本世界线战争扰动下 ~3.7）
CL_BBL_BAND = (20.0, 200.0)  # $/bbl（2020-04 负油价 excluded，本带拒收属正确）
UNIT_BREAK_BAND = (20.0, 150.0)  # RB/HO 报价若落此带=$/gal 源断裂成 $/bbl 量级特征
CRACK_BBL_BAND = (-20.0, 80.0)  # 3-2-1 历史带：2022 峰 ~$55、需求崩塌可短暂负值


def fetch_product_closes(days: int) -> dict[str, dict[str, float]]:
    """yfinance 三腿日线收盘 → {\"rb\"/\"ho\"/\"cl\": {YYYY-MM-DD: close}}。

    yfinance 懒加载（I-2 同族：缺依赖不炸模块导入）；NaN/inf 收盘剔除。
    """
    import yfinance as yf  # noqa: PLC0415 — 可选依赖懒加载

    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=days + 1)
    out: dict[str, dict[str, float]] = {}
    for key, symbol in (("rb", RB_SYMBOL), ("ho", HO_SYMBOL), ("cl", CL_SYMBOL)):
        frame = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(),
                                          interval="1d", auto_adjust=False)
        closes: dict[str, float] = {}
        for ts, row in frame.iterrows():  # 逐行 try（torn 行跳过不整段降级）
            try:
                close = float(row["Close"])
                day = ts.date().isoformat()
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if math.isfinite(close):
                closes[day] = close
        out[key] = closes
    return out


def compute_crack_rows(legs: dict[str, dict[str, float]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """三腿日期交集派生 3-2-1 裂解价差行 + 诊断（毒行/缺腿全可见）。

    返回 (rows, diag)：rows=[{date, rb, ho, cl, value}]；diag={missing: [...],
    poisoned: [...]}，元素 {date, reason}。纯函数无 IO。
    """
    rb, ho, cl = legs.get("rb") or {}, legs.get("ho") or {}, legs.get("cl") or {}
    common = sorted(set(rb) & set(ho) & set(cl))
    rows: list[dict[str, Any]] = []
    diag: dict[str, Any] = {"missing": [], "poisoned": []}
    for day in sorted(set(rb) | set(ho) | set(cl)):
        if day not in common:
            which = [name for name, m in (("rb", rb), ("ho", ho), ("cl", cl)) if day not in m]
            diag["missing"].append({"date": day, "reason": f"缺腿: {','.join(which)}"})
            continue
        r, h, c = rb[day], ho[day], cl[day]
        for label, val, band in (("rb", r, RB_GAL_BAND), ("ho", h, HO_GAL_BAND),
                                 ("cl", c, CL_BBL_BAND)):
            if label in ("rb", "ho") and UNIT_BREAK_BAND[0] <= val <= UNIT_BREAK_BAND[1]:
                diag["poisoned"].append(
                    {"date": day, "reason": f"{label}={val} 落 $/bbl 量级带——$/gal 源单位断裂，拒收"})
                break
            if not band[0] <= val <= band[1]:
                diag["poisoned"].append(
                    {"date": day, "reason": f"{label}={val} 越毒带 {band}，拒收"})
                break
        else:
            value = round(((2.0 * r + h) * GAL_TO_BBL - 3.0 * c) / 3.0, 2)
            if not CRACK_BBL_BAND[0] <= value <= CRACK_BBL_BAND[1]:
                diag["poisoned"].append(
                    {"date": day, "reason": f"crack={value} 越毒带 {CRACK_BBL_BAND}，拒收"})
            else:
                rows.append({"date": day, "rb": r, "ho": h, "cl": c, "value": value})
    rows.sort(key=lambda x: x["date"])
    return rows, diag


def update_crack(data_root: Path, *, days: int = 500,
                 sink: list[tuple[Path, str]] | None = None) -> dict[str, Any]:
    """派生序列滚动窗幂等落盘。任何硬失败（缺依赖/全源空/0 行可算）上抛给 main。"""
    legs = fetch_product_closes(days)
    if not any(legs.values()):
        raise RuntimeError(f"yfinance 三腿全空（RB/HO/CL {days}d 窗）")
    rows, diag = compute_crack_rows(legs)
    if not rows:
        raise RuntimeError(
            f"0 行可算（rb={len(legs.get('rb') or {})} ho={len(legs.get('ho') or {})} "
            f"cl={len(legs.get('cl') or {})}；missing={len(diag['missing'])} "
            f"poisoned={len(diag['poisoned'])}）")
    stats: dict[str, Any] = {"imported": 0, "skipped": 0,
                             "poisoned": len(diag["poisoned"]),
                             "missing": len(diag["missing"])}
    for row in rows:
        try:
            path = append_record(data_root, series=CRACK_SERIES, name=CRACK_SERIES_NAME,
                                 date=row["date"], value=row["value"], unit="美元/桶",
                                 source=CRACK_SOURCE_TAG)
            stats["imported"] += 1
            if sink is not None:
                sink.append((path, row["date"]))
        except ValueError as exc:
            if "已有" in str(exc):
                stats["skipped"] += 1
            else:
                raise
    last = rows[-1]
    stats["last_date"], stats["last_value"] = last["date"], last["value"]
    stats["last_legs"] = (last["rb"], last["ho"], last["cl"])
    base = [x for x in rows if x["date"] <= (date.fromisoformat(last["date"])
                                             - timedelta(days=42)).isoformat()]
    if base:
        prev = base[-1]["value"]
        stats["chg_42d"] = round(last["value"] - prev, 2)
        stats["chg_42d_pct"] = round((last["value"] / prev - 1.0) * 100.0, 1) if prev else None
    else:
        stats["chg_42d"] = stats["chg_42d_pct"] = None  # 样本不足：missing 语义，不冒充 0
    if diag["poisoned"] or diag["missing"]:
        for item in diag["poisoned"][:5]:
            log(f"Warning: {CRACK_SERIES} 毒行: {item['date']} {item['reason']}")
        if len(diag["poisoned"]) > 5:
            log(f"Warning: {CRACK_SERIES} 毒行另有 {len(diag['poisoned']) - 5} 条")
        log(f"Warning: {CRACK_SERIES} 缺腿 {stats['missing']} 日（三腿交集制，不写行）")
    log(f"{CRACK_SERIES}[{CRACK_SOURCE_TAG}]: "
        f"imported={stats['imported']} skipped={stats['skipped']}")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="美国 3-2-1 裂解价差派生序列更新（us-321-crack，Q-20261128-04 能源腿）")
    parser.add_argument("--days", type=int, default=500,
                        help="滚动窗天数（默认 500，约两年）")
    args = parser.parse_args(argv)
    from market_data_io import resolve_data_root

    data_root = resolve_data_root()
    from batch_ledger import close_batch, open_batch

    run_id = open_batch("batch-crack-spread", data_root)
    written: list[tuple[Path, str]] = []
    try:
        stats = update_crack(data_root, days=args.days, sink=written)
    except Exception as exc:  # noqa: BLE001 — 主序列失败=非零（I-1：fail loud）
        close_batch(run_id, written, data_root,
                    missing=[{"item": CRACK_SERIES, "reason": str(exc)}])
        log(f"Error: {CRACK_SERIES} 更新失败: {exc}")
        return 1
    missing: list[dict] = []
    if stats["poisoned"] or stats["missing"]:
        missing.append({"item": CRACK_SERIES,
                        "reason": f"poisoned={stats['poisoned']} missing_legs={stats['missing']}"
                                  "（毒行/缺腿日未写行，见脚本 Warning）"})
    close_batch(run_id, written, data_root,
                sources=[CRACK_SOURCE_TAG] if stats["imported"] > 0 else [],
                missing=missing)
    chg = stats.get("chg_42d")
    chg_pct = stats.get("chg_42d_pct")
    rb, ho, cl = stats["last_legs"]
    print(f"latest: {stats['last_date']} crack={stats['last_value']} $/bbl "
          f"(rb={rb:.4f} ho={ho:.4f} cl={cl:.2f})")
    print(f"42d change: {chg if chg is not None else '—（样本不足）'} $/bbl"
          + (f" ({chg_pct:+.1f}%)" if chg_pct is not None else ""))
    print(f"stats: imported={stats['imported']} skipped={stats['skipped']} "
          f"poisoned={stats['poisoned']} missing_legs={stats['missing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
