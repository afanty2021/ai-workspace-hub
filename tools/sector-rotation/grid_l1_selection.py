# tools/sector-rotation/grid_l1_selection.py
"""v2-L1 选择窗网格驱动（R20261105-02 方案 A §5 V2-2）。

6 格 = window {8,13,26} × variant {joint,independent}，每格一次
backtest.py --pre-oos --exploratory（选择窗 2018-10-26→2020-07-03，不碰 OOS）。
判据事前声明（与 spec §3.8 v2 协议第 4 条同纪律）：格胜者 = 选择窗基准档
净 CAGR（闸门路径）→ 平手取裸路径基准档净 CAGR → 再平手取 Sharpe。
消费保护（v2 协议第 7 条草案，Q-20261105-06 拍板项二）：胜者裸路径 ≤0
→ 不跑 OOS，直接按「选择窗内无信号边际」负结果结案（exit 2）。
sweep 自检（S6 网格教训，friction-log 2026-11-05）：6 份报告齐全、配置行
逐格含 window/l1_variant（CLI 注入有效性）、主策略 CAGR 六格不全相同。

用法：python grid_l1_selection.py [--parse-only]（parse-only 只重读已有报告）
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
CELLS = [(w, v) for w in (8, 13, 26) for v in ("joint", "independent")]

GATE_ROW = re.compile(r"^\| L1 \| ([+-]?[\d.]+)% \| (-?[\d.]+) \|", re.M)
BARE = re.compile(r"裸路径（基准档成本）CAGR ([+-][\d.]+)% / Sharpe (-?[\d.]+)")


def parse(text: str) -> dict:
    g = GATE_ROW.search(text)
    b = BARE.search(text)
    if not g or not b:
        raise SystemExit("解析失败：报告缺少 L1 主行或裸诊断行")
    return {"gate_cagr": float(g.group(1)) / 100,
            "sharpe": float(g.group(2)),
            "bare_cagr": float(b.group(1)) / 100,
            "bare_sharpe": float(b.group(2))}


def main(argv: list[str] | None = None) -> int:
    parse_only = bool(argv and "--parse-only" in argv)
    rows = []
    for w, v in CELLS:
        tag = f"L1-momentum-k3-lb1-w{w}-{v}-preoos"
        hits = sorted(Path(REPO, "output/sector-rotation").glob(f"*/backtest-{tag}.md"))
        if not parse_only or not hits:
            print(f"[grid] window={w} variant={v} …", flush=True)
            subprocess.run([PY, "tools/sector-rotation/backtest.py", "--level", "L1",
                            "--window", str(w), "--l1-variant", v,
                            "--pre-oos", "--exploratory"], cwd=REPO, check=True)
            hits = sorted(Path(REPO, "output/sector-rotation").glob(
                f"*/backtest-{tag}.md"))
        text = hits[-1].read_text(encoding="utf-8")
        cfg_m = re.search(r"配置：(.+)", text)      # sweep 自检：注入有效性
        if cfg_m is None:
            raise SystemExit(f"解析失败：{hits[-1].name} 缺少「配置：」行")
        cfg = cfg_m.group(1)
        assert f"window={w}" in cfg and f"l1_variant={v}" in cfg, f"配置行错配：{cfg}"
        rows.append({"w": w, "v": v, **parse(text), "path": hits[-1].name})
    assert len({r["gate_cagr"] for r in rows}) > 1, \
        "sweep 自检失败：六格主策略 CAGR 全相同（参数未注入？）"
    winner = sorted(rows, key=lambda r: (r["gate_cagr"], r["bare_cagr"],
                                         r["sharpe"]))[-1]
    print("\n| window | variant | 闸门净CAGR(基准) | 裸CAGR(基准) | Sharpe |")
    print("|---|---|---|---|---|")
    for r in rows:
        mark = " ←胜者" if r is winner else ""
        print(f"| {r['w']} | {r['v']} | {r['gate_cagr']:+.2%} | "
              f"{r['bare_cagr']:+.2%} | {r['sharpe']:.2f} |{mark}")
    if winner["bare_cagr"] <= 0:
        print(f"\n消费保护触发：胜者裸路径 {winner['bare_cagr']:+.2%} ≤ 0"
              "——不跑 OOS，按「选择窗内无信号边际」负结果结案（v2 协议第 7 条草案）。")
        return 2
    print(f"\n胜者 w={winner['w']}/{winner['v']}，裸路径 {winner['bare_cagr']:+.2%} > 0"
          "——消费保护放行，进 V2-3 预注册。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))   # 评审 v2 I-1：argv 必须显式传入，
    # 否则 --parse-only 死开关（main 默认参 None → 恒重跑、静默覆盖 artifact）
