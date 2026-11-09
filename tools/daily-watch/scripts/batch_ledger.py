"""批量脚本的运行账本接入（friction-log 2026-11-09 三漂移修根，用户拍板选项①）。

16:30 cron 批量（update_market_series / update_finance_snapshots /
update_cross_asset_history / update_cn_liquidity）与日报是两条独立的 data/
写路径：日报钩子（persist_market_data.run_persist_hook）写账本而批量不写，
批量对 series 的改动在 run-archive verify 里成为「未申报修订」（2026-11-09
^TNX/NQ00Y 11-06 行漂移即此因）。

本模块提供与 persist 钩子同语义的记账：open_batch（kind="batch-*"）→ 批量
落盘（调用方把实际写入的 (文件, 锚定日期) 收进 sink）→ close_batch（一条
data-close）。孤儿判定接受 data-close 为下文（run_archive ORPHAN 语义），
批量无报告产物，故不写 close 行。账本任何子步骤失败只写 sentinel 不抛——
批量数据写入绝不因账本而失败（与 persist 钩子同一降级纪律）。

锚定规则（run_archive._normalize_data_targets 强制）：.jsonl 目标必须带
锚定日期（path#date，行锚定哈希=date≤anchor 的行拼接，追加新行不冲击旧锚）；
其余目标整文件哈希。close_batch 对 jsonl 缺锚条目剔除并告警（不炸批量）。

与 persist 钩子的一个已知偏差：本模块**没有 RUN_LOG_DISABLE 逃生门**（钩子有，
persist_market_data.py）——批量脚本无报告产物、账本降级已有 sentinel 兜底，
默认总该记账；若确需跳过，须在调用方自行短路，不要指望环境变量。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


def log(message: str) -> None:
    """与 tools/daily-watch 各脚本同款 stdout 直写（cron 简报可见）。"""
    print(message)


def _load_run_archive():
    """跨目录导入 system/scripts/run_archive.py（与 persist_market_data 同法）。"""
    repo_root = Path(__file__).resolve().parents[3]
    script_dir = str(repo_root / "system" / "scripts")
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import run_archive  # noqa: PLC0415 — 延迟导入：账本模块缺失不应影响批量本身
    return run_archive


def _sentinel_path(data_root: Path) -> Path:
    """sentinel 路径：优先复用 run_archive.sentinel_path，导入失败回退本地实现。"""
    try:
        return Path(_load_run_archive().sentinel_path(data_root))
    except Exception:  # noqa: BLE001 — 账本模块不可用时不能连 sentinel 都写不了
        return Path(data_root) / ".state" / "run-log.error"


def _ledger_failed(data_root: Path, step: str, exc: Exception) -> None:
    """账本子步骤失败：stdout + sentinel（时间+异常），不抛（可感知降级）。"""
    log(f"Warning: 批量运行账本 {step} 失败（写 sentinel，批量继续）: {exc}")
    try:
        sentinel = _sentinel_path(data_root)
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        with sentinel.open("a", encoding="utf-8") as fh:
            from datetime import datetime

            fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} "
                     f"batch:{step} {type(exc).__name__}: {exc}\n")
    except Exception as nested:  # noqa: BLE001 — sentinel 本身也写不进时只剩 stdout
        log(f"Warning: run-log.error sentinel 写入失败: {nested}")


def _repo_rel(data_root: Path, path: Path) -> str:
    """账本路径归一（与 persist_market_data._ledger_repo_rel 同口径）：
    data_root 父目录（仓库根）相对；出界（tmp 冒烟等）用绝对路径。"""
    try:
        rel = Path(path).resolve().relative_to(Path(data_root).resolve().parent)
        return str(Path(*rel.parts))
    except ValueError:
        return str(Path(path).resolve())


def open_batch(kind: str, data_root: Path) -> str | None:
    """批量 run 开行（RUN-YYYYMMDD-HHMM-<kind>）；失败 sentinel 后返回 None。"""
    try:
        archive = _load_run_archive()
        return archive.append_open(data_root, kind=kind,
                                   trade_date=date.today().isoformat())
    except Exception as exc:  # noqa: BLE001
        _ledger_failed(data_root, "open", exc)
        return None


def close_batch(run_id: str | None, targets: list[tuple[Path, str | None]],
                data_root: Path, sources: list[str] | None = None,
                missing: list[dict] | None = None) -> None:
    """批量 run 收尾：targets → data-close（同 path 去重取最晚锚）。

    run_id 为 None（open 已失败）时静默跳过；data-close 失败写 sentinel 不抛。
    jsonl 缺锚条目剔除并告警（run_archive 对 jsonl 强制锚定，缺锚整批提交会炸）。
    """
    if not run_id:
        return
    by_anchor: dict[str, str] = {}
    dropped: list[str] = []
    for path, anchor in targets:
        rel = _repo_rel(data_root, path)
        if str(path).endswith(".jsonl"):
            if not anchor:
                dropped.append(rel)
                continue
            if rel not in by_anchor or str(anchor) > by_anchor[rel]:
                by_anchor[rel] = str(anchor)
        else:
            by_anchor.setdefault(rel, "")
    if dropped:
        log(f"Warning: 批量账本剔除缺锚 jsonl 目标（本轮未申报）: {dropped}")
    specs = [f"{rel}#{anchor}" if anchor else rel
             for rel, anchor in sorted(by_anchor.items())]
    try:
        archive = _load_run_archive()
        archive.append_data_close(data_root, run_id, specs,
                                  list(sources or []), list(missing or []))
    except Exception as exc:  # noqa: BLE001
        _ledger_failed(data_root, "data-close", exc)
