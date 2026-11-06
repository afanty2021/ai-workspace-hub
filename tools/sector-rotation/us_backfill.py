# tools/sector-rotation/us_backfill.py
"""美股 11 行业 ETF 深回补（R20261106-02 §6 U2，spec §3.8 第 8 条新宇宙路径）。

主源 yfinance 复权价（auto_adjust=True）——研究域存储，偏离 daily-watch
「不复权」铁律，理由：论文口径（Yahoo adjusted close）+ 分红必须计入 TR 基准
（SPY 2022 TR ≈ -18.1% vs 价格 -19.4%，提案 §3 基准条）。布局镜像 A 股
data/ 根：成员 ETF 复权 close 同写 sector/series（信号价）与 market/series
（执行价 OHLC+amount≈close×volume）；SPY/^GSPC 只写 market/series。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from market_data_io import series_lock, upsert_series_rows  # noqa: E402

US_MEMBERS = ["XLK", "XLV", "XLY", "VOX", "XLF", "XLI",
              "XLP", "XLU", "XLB", "IYR", "XLE"]   # 论文顺序（spec §1.1）
BENCH = ["SPY", "^GSPC"]
START = "2009-01-01"
DATA_ROOT = REPO_ROOT / "data" / "us-sector"
SOURCE = "yfinance"
# 锚点带（提案 §6 verify）：SPY 复权=TR 口径，^GSPC 价格口径；带宽 ±2pp 级
SPY_ANCHORS = {2013: (0.30, 0.34), 2018: (-0.08, -0.04),
               2020: (0.16, 0.20), 2022: (-0.205, -0.16)}
GSPC_2022 = (-0.215, -0.175)


def _download(tickers: list[str], *, start: str = START, auto_adjust: bool = True,
              attempts: int = 5):
    """批量单次调用（13 标的合一下载降 429 风险），指数退避重试；仍失败抛出。
    本机对 Yahoo 有 429 限流史（friction-log 2026-10-28/10-31）——失败如实停。"""
    import yfinance as yf
    last = None
    for k in range(attempts):
        try:
            df = yf.download(tickers, start=start, auto_adjust=auto_adjust,
                             group_by="ticker", progress=False, threads=False)
            if df is not None and not df.empty:
                return df
            last = RuntimeError("empty frame")
        except Exception as exc:                     # noqa: BLE001
            last = exc
        time.sleep(min(2 ** k * 10, 120))
    raise RuntimeError(f"yfinance 拉取失败（退避 {attempts} 次）: {tickers} —— {last}")


def df_to_rows(sym: str, df) -> list[dict]:
    sub = df[sym].dropna(subset=["Close"])
    rows = []
    for d, r in sub.iterrows():
        close, vol = float(r["Close"]), float(r.get("Volume") or 0.0)
        rows.append({"date": d.date().isoformat(), "open": float(r["Open"]),
                     "high": float(r["High"]), "low": float(r["Low"]),
                     "close": close, "volume": vol,
                     "amount": close * vol, "source": SOURCE})
    return rows


def _write_series(rel_dir: str, sym: str, rows: list[dict]) -> None:
    path = DATA_ROOT / rel_dir / f"{sym}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with series_lock(DATA_ROOT, f"us-{sym}"):
        upsert_series_rows(path, rows, "batch")


def run_fetch() -> None:
    df = _download(US_MEMBERS + BENCH)
    for sym in US_MEMBERS:
        rows = df_to_rows(sym, df)
        _write_series("sector/series", sym, rows)   # 信号价 = 执行价同源（退化情形）
        _write_series("market/series", sym, rows)
        print(f"{sym}: {len(rows)} 行 ({rows[0]['date']} → {rows[-1]['date']})")
    for sym in BENCH:
        rows = df_to_rows(sym, df)
        _write_series("market/series", sym, rows)
        print(f"{sym}: {len(rows)} 行")


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def annual_close_returns(rows: list[dict]) -> dict[int, float]:
    by_year: dict[int, float] = {}
    for r in rows:                                   # rows 已按 date 升序
        by_year[int(r["date"][:4])] = float(r["close"])
    years = sorted(by_year)
    return {y: by_year[y] / by_year[prev] - 1.0
            for prev, y in zip(years, years[1:])}


def check_anchors(annual: dict[int, float],
                  anchors: dict[int, tuple[float, float]]) -> list[str]:
    """锚点年缺失即报错（计划评审 M-6）——数据不完整必须硬警报，不静默跳过。"""
    errs = []
    for y, (lo, hi) in anchors.items():
        if y not in annual:
            errs.append(f"锚点年 {y} 缺失（数据不完整）")
        elif not (lo <= annual[y] <= hi):
            errs.append(f"{y} 年收益 {annual[y]:.4f} 超出锚点带 {lo}~{hi}")
    return errs


def split_residues(rows: list[dict],
                   threshold: float = 0.30) -> list[tuple[str, float]]:
    out = []
    for prev, cur in zip(rows, rows[1:]):
        c0, c1 = float(prev["close"]), float(cur["close"])
        if c0 > 0 and abs(c1 / c0 - 1) > threshold:
            out.append((cur["date"], c1 / c0 - 1.0))
    return out


def run_verify(*, raw_compare: bool = False) -> int:
    errors = []
    print(f"{'symbol':8} {'首行':12} {'末行':12} {'行数':>6}  拆分残留(>30%)")
    for sym in US_MEMBERS + BENCH:
        rows = _read_rows(DATA_ROOT / "market" / "series" / f"{sym}.jsonl")
        if not rows:
            errors.append(f"{sym} 无数据（先跑 fetch）")
            continue
        res = split_residues(rows)
        print(f"{sym:8} {rows[0]['date']:12} {rows[-1]['date']:12} "
              f"{len(rows):>6}  {len(res)}{res[:2] if res else ''}")
        if sym in US_MEMBERS:
            if rows[0]["date"] > "2010-06-01":
                errors.append(f"{sym} 首行 {rows[0]['date']} 过晚（2012 交易需 "
                              "≥2 年训练史，MIMOModel fit）")
            if res:
                errors.append(f"{sym} 复权后仍有 {len(res)} 处 >30% 跳变，数据可疑")
    spy = annual_close_returns(_read_rows(DATA_ROOT / "market" / "series" / "SPY.jsonl"))
    errors += check_anchors(spy, SPY_ANCHORS)
    print("SPY 复权逐年收益: " + " ".join(f"{y}:{v:+.1%}" for y, v in spy.items()))
    gspc = annual_close_returns(_read_rows(DATA_ROOT / "market" / "series" / "^GSPC.jsonl"))
    errors += check_anchors(gspc, {2022: GSPC_2022})
    if raw_compare:
        raw = _download(US_MEMBERS + BENCH, auto_adjust=False)
        spy_raw = annual_close_returns(df_to_rows("SPY", raw))
        print("SPY 未复权 vs 复权年收益差（分红贡献披露）: "
              + " ".join(f"{y}:{spy_raw.get(y, float('nan')) - spy.get(y, float('nan')):+.2%}"
                         for y in sorted(spy)))
    if errors:
        print("\n".join(f"[FAIL] {e}" for e in errors))
        return 1
    print("[OK] 深度/拆分/锚点全部通过")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["fetch"]:
        run_fetch()
        return 0
    if argv[:1] == ["verify"]:
        return run_verify(raw_compare="--raw-compare" in argv)
    print("用法: us_backfill.py fetch | verify [--raw-compare]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
