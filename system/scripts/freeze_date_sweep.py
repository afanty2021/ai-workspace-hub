"""冻结墙钟日期扫描：老化时间炸弹的全仓巡检（2026-11-28 max 评审 5.4 修根面）。

背景案：tests/test_us_liquidity.py 夹具写死 2026-11-19 ×脚本侧 [today−30, today]
窗口——入库当天全绿，2026-12-20 起全量必红（冻结复现：12-19 是 12 passed、
12-20 起 1 failed）。跑当日测试只能证明「今天绿」，证明不了「下月绿」；本脚本
把测试套件在冻结的未来墙钟下各跑一遍（缺省 +30/+90/+180/+365 天），暴露所有
「夹具/断言写死日期」型老化炸弹。挂周检 cron；任一冻结日红 → 非零退出。

用法：
    python3 system/scripts/freeze_date_sweep.py                    # 全量 × 4 冻结日
    python3 system/scripts/freeze_date_sweep.py --targets tests/test_money_etf_premium.py
    python3 system/scripts/freeze_date_sweep.py --offsets 30 90    # 自选前瞻天数

对照纪律（插件不伤测试的自证）：--control 用「今天」冻结跑一遍，应与不冻结同绿；
基线漂了先查插件再查测试。失败=候选炸弹，须逐个回源分诊（冻结伪影 vs 真老化），
不要见红就改断言。

只读：不写仓内文件（pytest 缓存用 -p no:cacheprovider 关掉）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent


def run_frozen(offset_days: int, targets: list[str]) -> tuple[int, str]:
    today = date.today()
    frozen = today + timedelta(days=offset_days)
    env = dict(os.environ)
    env["FREEZE_ISO"] = frozen.isoformat() + "T09:00:00"
    env["PYTHONPATH"] = str(SCRIPT_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "pytest", *targets, "-q",
           "-p", "no:cacheprovider", "-p", "_freeze_date_plugin", "--tb=line"]
    run = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    tail = [ln for ln in (run.stdout + run.stderr).strip().splitlines() if ln.strip()]
    summary = tail[-1] if tail else "(无输出)"
    return run.returncode, f"+{offset_days:>3}d ({frozen}) -> rc={run.returncode} {summary}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="冻结未来墙钟跑测试，暴露日期老化炸弹（评审 5.4 修根面）")
    ap.add_argument("--offsets", nargs="*", type=int, default=[30, 90, 180, 365],
                    help="前瞻天数档（默认 30/90/180/365）")
    ap.add_argument("--targets", nargs="*", default=["tests"],
                    help="pytest 目标（默认全量 tests/）")
    ap.add_argument("--control", action="store_true",
                    help="加跑今天冻结的对照档（应与不冻结同绿，验证插件自证）")
    args = ap.parse_args(argv)

    offsets = list(args.offsets)
    if args.control:
        offsets = [0] + offsets
    red: list[str] = []
    print(f"冻结日期扫描：targets={' '.join(args.targets)} 档位={offsets}")
    for offset in offsets:
        rc, line = run_frozen(offset, args.targets)
        print(f"  {line}")
        if rc != 0:
            red.append(line)
    if red:
        print(f"\n红 {len(red)} 档（候选老化炸弹，逐个回源分诊后处置）：")
        for line in red:
            print(f"  {line}")
        return 1
    print("\n全部冻结档绿：未发现到期炸弹。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
