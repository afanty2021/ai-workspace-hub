#!/usr/bin/env python3
"""run_archive —— 运行账本（data/.state/run-log.jsonl）的写入与巡检。

账本是追加式 JSONL，定位是「存在证明 + 修订痕迹」：对产物记哈希，改可以改但必须先记账
（约定全文见 system/integrations/object-model.md「运行账本」段）。本模块既是 CLI 也是库：
持久化钩子（Task 4）导入 append_open / append_data_close / append_amend / row_anchor_hash /
verify_ledger，公开函数保持 argparse 无关；CLI 薄壳供 skill 一步命令使用。

行类型（spec §3.2）：open / data-close / close / amend / amend-done / abort。
kind 十值：watch / inspect / research / screen / masters / backfill（backfill 无 close 语义，
不参与 verify 的孤儿判定）+ batch-series / batch-finance / batch-crossasset /
batch-liquidity（16:30 cron 批量，两行制 open+data-close，无 close 行——孤儿判定
接受 data-close 为下文，见 tools/daily-watch/scripts/batch_ledger.py）。

本模块拍板的实现约定（brief 未逐字规定处的最简一致口径）：

1. 行序列化：json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\\n"。
2. 尾行哈希链：每行 prev_sha256 = 前一**原始行**（含行尾换行）UTF-8 字节的 sha256，首行 null；
   verify 按当前文件逐行重算比对，断链 / 坏 JSON 行号进 chain_breaks。
3. 行锚定哈希：对文件中 date ≤ anchor_date 的行，按文件序保留原始字节（含各自换行）拼接后
   取 sha256；空行跳过；date 缺失或不可解析的行保守计入（改它必须可检）。
4. 时间戳：本地时区 ISO 8601 秒精度（如 2026-11-04T16:30:00+08:00）。
5. 路径：账本内 target / report 一律仓库根相对路径；解析根 = data_root 的父目录（默认布局
   data/.state/ 下 data_root 即 <仓库根>/data）。绝对路径原样使用。
6. run_id 终结判定：同 run_id 存在 close 或 abort 行即视为已终结；已终结的 run_id 同分钟可
   复用，未终结的同分钟重开追加 -r2 / -r3。
7. evidence 归一化哈希（I4 豁免）：review_status / direction / confidence 三个状态字段的
   合法生命周期迁移不属修订。close 不带 sha 时与 verify 重算均把 frontmatter 中这三个顶层
   字段的值归一为占位值 ``pending``（模板初始态）后再整文哈希；显式 ``E-ID:sha256`` 透传。
   无 frontmatter（或未闭合）的文件退化为整文件哈希。

verify_ledger 返回 dict，键：undeclared（未申报修订）/ unfinished_amends（未完成修订）/
orphan_opens（孤儿 open）/ sentinel / chain_breaks（断链或坏行号，1-based）+ clean（前五项
全空为 True）。CLI verify 退出码：干净 0，任一非空 1。

用法：

    python3 system/scripts/run_archive.py open --kind watch --trade-date 2026-11-04
    python3 system/scripts/run_archive.py data-close --run-id R \\
        --data-target data/market/series/300476.SZ.jsonl#2026-11-03 \\
        --sources mootdx,nasdaq --missing-json '[]'
    python3 system/scripts/run_archive.py close --run-id R \\
        --report output/daily-watch/2026-11/2026-11-03.md \\
        --evidence E-20261103-sox-break-ai-financing-h1
    python3 system/scripts/run_archive.py amend --run-id R --target P --reason TXT \\
        [--data-target path#date]...        # 第一步：intent（post_sha256=null）
    python3 system/scripts/run_archive.py amend --done --run-id R --target P  # 第二步：补哈希
    python3 system/scripts/run_archive.py amend --done --missing --run-id R --target P \\
        --reason TXT   # 产物已消亡的收口（verify 摘除该 target 的权威比对）
    python3 system/scripts/run_archive.py abort --run-id R --reason TXT
    python3 system/scripts/run_archive.py verify [--json]
    python3 system/scripts/run_archive.py ledger --from 2026-11-01 --to 2026-11-04 \\
        [--hypothesis H1] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys

try:  # POSIX 排它锁（账本追加并发防护）；Windows 无 fcntl 时降级保持无锁现状
    import fcntl
except ImportError:  # pragma: no cover - 非 POSIX 平台
    fcntl = None
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

try:  # 复用 evidence_lint 的零依赖 frontmatter reader（同目录），不另写一份
    from evidence_lint import parse_frontmatter
except ImportError:  # importlib 动态加载 / 非脚本目录执行时补路径
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from evidence_lint import parse_frontmatter

KINDS = ("watch", "inspect", "research", "screen", "masters", "backfill",
          "batch-series", "batch-finance", "batch-crossasset", "batch-liquidity")
LEDGER_REL = Path(".state") / "run-log.jsonl"
SENTINEL_REL = Path(".state") / "run-log.error"
ORPHAN_HOURS = 24
# run 终结行（同 run_id 已终结则可复用，否则同分钟重开加 -r2）；孤儿判定看有下文的三类行
TERMINAL_TYPES = ("close", "abort")
ACTIVITY_TYPES = ("data-close", "close", "abort")
# I4 归一化：evidence 三状态字段哈希前统一视作初始 pending 态（值内生命周期迁移不算修订）
EVIDENCE_STATUS_FIELDS = ("review_status", "direction", "confidence")
EVIDENCE_PLACEHOLDER = "pending"
_STATUS_LINE_RE = re.compile(r"^(%s):" % "|".join(EVIDENCE_STATUS_FIELDS))


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def ledger_path(data_root) -> Path:
    """账本文件路径：<data_root>/.state/run-log.jsonl。"""
    return Path(data_root) / LEDGER_REL


def sentinel_path(data_root) -> Path:
    return Path(data_root) / SENTINEL_REL


def _repo_root(data_root) -> Path:
    """target / report 路径的解析根：默认布局下 data_root = <仓库根>/data。"""
    return Path(data_root).resolve().parent


def _resolve_target(data_root, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _repo_root(data_root) / p


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_dt(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    # naive 时刻按本地时区补全（账本约定带时区，防御旧数据/手改行）
    return parsed if parsed.tzinfo else parsed.astimezone()


def _parse_ledger_text(text: str) -> tuple[list[dict], list[str]]:
    """严格解析账本文本：(行对象, 原始行含换行)。空白行跳过；非 JSON 行抛 ValueError。

    _read_rows_strict 与 _append 锁内读共用，保证两处解析口径永远一致。
    """
    rows: list[dict] = []
    raws: list[str] = []
    for lineno, raw in enumerate(text.splitlines(keepends=True), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"账本第 {lineno} 行不是合法 JSON：{exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"账本第 {lineno} 行不是 JSON 对象")
        rows.append(row)
        raws.append(raw)
    return rows, raws


def _read_rows_strict(ledger: Path) -> tuple[list[dict], list[str]]:
    """严格读账本：(行对象, 原始行含换行)。空白行跳过；非 JSON 行抛 ValueError（append 不吞）。"""
    if not ledger.exists():
        return [], []
    return _parse_ledger_text(ledger.read_text(encoding="utf-8"))


def _append(data_root, row: dict, guard=None) -> None:
    """追加一行并接上尾行哈希链：prev_sha256 = 前一原始行（含换行）的 sha256，首行 null。

    读全文→算 prev→写回是非原子三步，并发追加会互相覆盖尾链——整个序列在账本文件级
    fcntl.flock 排它锁内完成（锁粒度 = run-log.jsonl 单文件）；Windows 无 flock 时
    降级保持无锁现状（单写者假设，见 object-model.md「运行账本」段）。

    guard(rows)：锁内追加前对最新账本行的复检回调（抛错则本行不写）——调用方在锁外
    先读后写的 check-then-append 存在 TOCTOU 窗口（如 amend 锚 vs 权威锚检查），
    guard 让关键校验在拿到锁后对最新状态再跑一遍。
    """
    _append_prepared(data_root, lambda rows: (guard(rows) if guard is not None else None, row)[1])


def _append_prepared(data_root, prepare) -> None:
    """锁内按最新账本行构造并追加一行：prepare(rows) -> row（在 flock 锁内调用）。

    需要基于账本最新状态决定行内容的调用方（如 run_id 判重分配）用这个入口，
    把「读最新行→算内容→写」整段收进锁内，消除 check-then-append 竞态。
    锁与降级口径同 _append。
    """
    ledger = ledger_path(data_root)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a+", encoding="utf-8") as fh:
        if fcntl is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except OSError:  # pragma: no cover - 文件系统不支持 flock（如部分网络盘）
                pass
        fh.seek(0)
        rows, raws = _parse_ledger_text(fh.read())
        row = prepare(rows)
        row["prev_sha256"] = hashlib.sha256(raws[-1].encode("utf-8")).hexdigest() if raws else None
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _git_head(root: Path) -> str | None:
    """git rev-parse --short HEAD；失败（非 git 目录 / git 缺失 / 超时）返回 None。"""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _allocate_run_id(rows: list[dict], kind: str, now: datetime) -> str:
    """RUN-YYYYMMDD-HHMM-<kind>；同 run_id 已存在且未终结（无 close/abort）时追加 -r2/-r3。

    入参改为已读行：分配必须在 _append 的 flock 锁内对最新账本行做（锁外读再判重，
    同分钟并发 open 会 10/10 撞号——复查评审 Important #2）。
    """
    base = f"RUN-{now:%Y%m%d-%H%M}-{kind}"
    terminated = {
        row["run_id"] for row in rows
        if row.get("type") in TERMINAL_TYPES and row.get("run_id")
    }
    candidate, n = base, 2
    while any(row.get("run_id") == candidate for row in rows):
        if candidate in terminated:
            break  # 同 id 上一轮已终结，可复用
        candidate = f"{base}-r{n}"
        n += 1
    return candidate


def _require_run(rows: list[dict], run_id: str) -> None:
    if not any(row.get("run_id") == run_id for row in rows):
        raise ValueError(f"run_id 不存在于账本：{run_id}")


def _split_anchor_spec(spec: str) -> tuple[str, str | None]:
    """拆 `path` / `path#anchor`；# 取最后一个（路径本身不含 # 的约定下安全）。"""
    if "#" not in spec:
        return spec, None
    path, anchor = spec.rsplit("#", 1)
    if not path or not anchor:
        raise ValueError(f"目标格式非法（应为 path 或 path#date）：{spec}")
    return path, anchor


def _normalize_data_targets(data_root, data_targets) -> list[dict]:
    """统一 data 目标：.jsonl → {path, anchor_date, sha256}（行锚定）；其余 → {path, sha256}。

    入参可以是 CLI 的 `path#anchor` 字符串，或库调用的 dict（可省 sha256，缺则现算）。
    """
    entries: list[dict] = []
    for item in data_targets or []:
        if isinstance(item, str):
            path, anchor = _split_anchor_spec(item)
            src: dict = {"path": path}
            if anchor:
                src["anchor_date"] = anchor
        else:
            src = dict(item)
        path = str(src["path"])
        anchor = src.get("anchor_date")
        entry: dict = {"path": path}
        if path.endswith(".jsonl"):
            if not anchor:
                raise ValueError(f"series 目标（.jsonl）必须带锚定日期（path#date）：{path}")
            entry["anchor_date"] = str(anchor)
            entry["sha256"] = (str(src["sha256"]) if src.get("sha256")
                               else row_anchor_hash(_resolve_target(data_root, path), str(anchor)))
        else:
            if anchor:
                raise ValueError(f"仅 .jsonl 目标支持行锚定，其余整文件哈希：{path}")
            entry["sha256"] = (str(src["sha256"]) if src.get("sha256")
                               else file_sha256(_resolve_target(data_root, path)))
        entries.append(entry)
    return entries


def _evidence_root(data_root) -> Path:
    return _repo_root(data_root) / "evidence"


def _find_evidence_file(data_root, ev_id: str) -> Path | None:
    """按 id 匹配 evidence/**/*.md 的文件名（仓库约定文件名 = evidence id）。"""
    root = _evidence_root(data_root)
    if not root.is_dir():
        return None
    matches = sorted(root.glob(f"**/{ev_id}.md"))
    return matches[0] if matches else None


def _evidence_id_from_target(target: str) -> str | None:
    """target 形如 evidence/**/E-*.md（仓库根相对）时返回 E-ID（文件名约定 = id），否则 None。"""
    p = PurePosixPath(str(target))
    if (len(p.parts) >= 2 and p.parts[0] == "evidence"
            and p.suffix == ".md" and p.stem.startswith("E-")):
        return p.stem
    return None


def normalized_evidence_sha256(path) -> str:
    """I4 归一化哈希：frontmatter 三个状态字段值归一为 pending 后整文哈希。

    无 frontmatter / frontmatter 未闭合 / 字段缺失时不做替换，退化为整文件哈希。
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def normalize(raw: str) -> str:
        core = raw.rstrip("\r\n")
        match = _STATUS_LINE_RE.match(core)
        if not match:
            return raw
        return f"{match.group(1)}: {EVIDENCE_PLACEHOLDER}" + raw[len(core):]

    out = [lines[0]]
    closed = False
    for raw in lines[1:]:
        if closed:
            out.append(raw)
            continue
        out.append(normalize(raw))
        if raw.strip() == "---":
            closed = True
    if not closed:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    return hashlib.sha256("".join(out).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 库 API（Task 4 持久化钩子导入；全部失败抛异常，不吞）
# ---------------------------------------------------------------------------

def append_open(data_root, kind: str, trade_date: str, now: datetime | None = None) -> str:
    """写 open 行（started_at / git_head 如实记录），返回 run_id。

    kind 非十值、trade_date 非 YYYY-MM-DD 抛 ValueError。
    """
    if kind not in KINDS:
        raise ValueError(f"kind 非法：{kind!r}，合法值 {KINDS}")
    try:
        date.fromisoformat(str(trade_date))
    except ValueError as exc:
        raise ValueError(f"trade_date 非法：{trade_date!r}（YYYY-MM-DD）") from exc
    started = now or _now()
    result: dict[str, str] = {}

    def _open_row(rows: list[dict]) -> dict:
        # run_id 判重在锁内对最新账本行做（锁外读会撞号，复查评审 Important #2）
        run_id = _allocate_run_id(rows, kind, started)
        result["run_id"] = run_id
        return {
            "type": "open",
            "run_id": run_id,
            "kind": kind,
            "trade_date": str(trade_date),
            "started_at": _iso(started),
            "git_head": _git_head(_repo_root(data_root)),
        }

    _append_prepared(data_root, _open_row)
    return result["run_id"]


def row_anchor_hash(path, anchor_date: str) -> str:
    """行锚定哈希：date ≤ anchor_date 的行按文件序拼接（保留原始字节含换行）的 sha256。

    空行跳过；date 缺失或不可解析的行保守计入。追加 date > anchor 的行不影响本哈希。
    """
    anchor = date.fromisoformat(str(anchor_date))
    digest = hashlib.sha256()
    for raw in Path(path).read_text(encoding="utf-8").splitlines(keepends=True):
        if not raw.strip():
            continue
        try:
            row_date = date.fromisoformat(json.loads(raw)["date"])
        except (ValueError, KeyError, TypeError):
            digest.update(raw.encode("utf-8"))
            continue
        if row_date <= anchor:
            digest.update(raw.encode("utf-8"))
    return digest.hexdigest()


def append_data_close(data_root, run_id: str, data_targets, sources_used, missing) -> None:
    """写 data-close 行。series 目标记行锚定三元组，md 等其余目标记整文件哈希。

    目标文件缺失、账本损坏、run_id 未知均抛异常——调用方（persist 钩子）决定降级方式。
    """
    rows, _ = _read_rows_strict(ledger_path(data_root))
    _require_run(rows, run_id)
    _append(data_root, {
        "type": "data-close",
        "run_id": run_id,
        "at": _iso(_now()),
        "data_targets": _normalize_data_targets(data_root, data_targets),
        "sources_used": list(sources_used or []),
        "missing": list(missing or []),
    })


def append_close(data_root, run_id: str, report: str, evidence_registered=None) -> None:
    """写 close 行：报告整文件 sha256 + evidence_registered [{id, sha256}]。

    evidence 条目可以是 "E-ID" / "E-ID:sha256" 字符串或 {id, sha256?} dict；
    缺 sha256 时按 I4 归一化规则读文件现算，显式给出则透传。
    """
    rows, _ = _read_rows_strict(ledger_path(data_root))
    _require_run(rows, run_id)
    registered: list[dict] = []
    for item in evidence_registered or []:
        if isinstance(item, str):
            ev_id, _, explicit_sha = item.partition(":")
            explicit_sha = explicit_sha or None
        else:
            ev_id = str(item["id"])
            explicit_sha = item.get("sha256")
        if explicit_sha:
            sha = str(explicit_sha)
        else:
            ev_path = _find_evidence_file(data_root, ev_id)
            if ev_path is None:
                raise ValueError(f"evidence 文件未找到（evidence/**/*.md 按 id 匹配）：{ev_id}")
            sha = normalized_evidence_sha256(ev_path)
        registered.append({"id": ev_id, "sha256": sha})
    _append(data_root, {
        "type": "close",
        "run_id": run_id,
        "finished_at": _iso(_now()),
        "report": str(report),
        "report_sha256": file_sha256(_resolve_target(data_root, report)),
        "evidence_registered": registered,
    })


def _intent_anchor(rows: list[dict], run_id: str, target: str) -> str | None:
    """从最近一条同 run/target 的 amend intent 里找该 target 的锚定日期。"""
    anchor = None
    for row in rows:
        if (row.get("type") == "amend" and row.get("run_id") == run_id
                and str(row.get("target")) == target):
            for spec in row.get("data_targets") or []:
                path, spec_anchor = _split_anchor_spec(str(spec))
                if path == target and spec_anchor:
                    anchor = spec_anchor
    return anchor


def _series_authority_anchor(rows: list[dict], path: str) -> str | None:
    """账本现有 series 权威锚：data-close / amend-done 里该 path 的最晚 anchor_date。

    与 verify 顺扫建权威表同口径（_merge_series_auth 的锚更晚者保留），供 amend-done
    前置校验——本次 amend 锚比它早时 post_sha256 会被权威表静默丢弃。
    """
    anchor: str | None = None
    for row in rows:
        rtype = row.get("type")
        if rtype == "data-close":
            for t in row.get("data_targets") or []:
                if (isinstance(t, dict) and str(t.get("path")) == path
                        and t.get("anchor_date")):
                    cand = str(t["anchor_date"])
                    anchor = cand if anchor is None or cand > anchor else anchor
        elif rtype == "amend-done" and str(row.get("target")) == path and row.get("anchor_date"):
            cand = str(row["anchor_date"])
            anchor = cand if anchor is None or cand > anchor else anchor
    return anchor


def append_amend(data_root, run_id: str, target: str, reason=None, data_targets=None,
                 done: bool = False, missing: bool = False) -> None:
    """两步 amend。

    done=False 写 intent 行（data_targets 记 `path#date` 串，post_sha256=null，reason 必填）；
    done=True 写 amend-done 行——series 目标（.jsonl）按 intent 声明（或 data_targets 显式
    传入）的锚定日期算行锚定哈希并记入 anchor_date，evidence 目标（evidence/**/E-*.md）
    按 I4 归一化口径记哈希（verify 据此同步 evidence_auth），其余目标记整文件哈希。

    done=True 且 missing=True 写「产物已消亡」的 amend-done 行（带 target 与 reason，
    不算哈希）：verify 据此把该 target 从权威表摘除、跳过其哈希比对——用于 close 指向
    已删除文件的收口（如冒烟跑误入真实账本），append-only 不破（行保留，仅摘权威）。
    """
    rows, _ = _read_rows_strict(ledger_path(data_root))
    _require_run(rows, run_id)
    target = str(target)
    specs = [str(s) for s in (data_targets or [])]
    if done:
        entry: dict = {"type": "amend-done", "run_id": run_id,
                       "at": _iso(_now()), "target": target}
        if missing:
            if not reason:
                raise ValueError("amend-done --missing 必须带 reason（产物为何消亡）")
            resolved_missing = _resolve_target(data_root, target)
            if resolved_missing.exists():
                # 产物还在就不能摘除其保护（复查评审 Important #1）：--missing 只用于
                # 产物已消亡的收口，仍存在时必须走普通 amend 记新哈希
                raise ValueError(
                    f"目标仍存在：{resolved_missing}——--missing 仅用于产物已消亡的收口，"
                    f"产物存在请走普通 amend 记新哈希")
            entry["missing"] = True
            entry["reason"] = reason
            _append(data_root, entry)
            return
        if target.endswith(".jsonl"):
            anchor = None
            for spec in specs:
                path, spec_anchor = _split_anchor_spec(spec)
                if path == target and spec_anchor:
                    anchor = spec_anchor
            anchor = anchor or _intent_anchor(rows, run_id, target)
            if anchor is None:
                raise ValueError(
                    f"series 目标的 amend-done 需要锚定日期：先在 intent 里声明 "
                    f"--data-target {target}#date，或在 --done 时再次给出")
            # amend 锚早于权威锚 fail-loud：权威表「更晚锚赢」，早锚 amend-done 的
            # post_sha256 会被静默丢弃（verify 仍按旧权威比对 → 误报未申报修订）。

            def _guard_amend_anchor(latest_rows: list[dict]) -> None:
                # 锁内复检（TOCTOU）：锁外读到的权威锚可能已被并发追加推进
                _require_run(latest_rows, run_id)
                latest_auth = _series_authority_anchor(latest_rows, target)
                if latest_auth is not None and str(anchor) < latest_auth:
                    raise ValueError(
                        f"amend-done 锚 {anchor} 早于账本权威锚 {latest_auth}（path={target}）："
                        f"该行的 post_sha256 会被权威表丢弃，verify 将误报未申报修订——"
                        f"请以更晚锚（≥ {latest_auth}）重做 amend")

            auth_anchor = _series_authority_anchor(rows, target)
            if auth_anchor is not None and str(anchor) < auth_anchor:
                _guard_amend_anchor(rows)  # 锁外快路径：直接触发同一报错（不进锁）
            entry["anchor_date"] = anchor
            entry["post_sha256"] = row_anchor_hash(_resolve_target(data_root, target), anchor)
            if reason:
                entry["reason"] = reason
            _append(data_root, entry, guard=_guard_amend_anchor)
            return
        resolved = _resolve_target(data_root, target)
        if _evidence_id_from_target(target) is not None:
            # evidence 目标：按 I4 归一化口径记哈希（与 close 注册 / verify 比对一致）
            entry["post_sha256"] = normalized_evidence_sha256(resolved)
        else:
            entry["post_sha256"] = file_sha256(resolved)
        if reason:
            entry["reason"] = reason
        _append(data_root, entry)
        return
    if not reason:
        raise ValueError("amend intent 必须带 reason（--reason）")
    _append(data_root, {
        "type": "amend",
        "run_id": run_id,
        "at": _iso(_now()),
        "target": target,
        "data_targets": specs,
        "reason": reason,
        "post_sha256": None,
    })


def append_abort(data_root, run_id: str, reason: str) -> None:
    """写 abort 行：显式收口中止（verify 不再追其 close）。"""
    rows, _ = _read_rows_strict(ledger_path(data_root))
    _require_run(rows, run_id)
    if not reason:
        raise ValueError("abort 必须带 reason（--reason）")
    _append(data_root, {"type": "abort", "run_id": run_id, "at": _iso(_now()), "reason": reason})


# ---------------------------------------------------------------------------
# verify：四张清单 + 哈希链
# ---------------------------------------------------------------------------

def _merge_series_auth(series_auth: dict, path: str, anchor_date: str, sha) -> None:
    """series 权威合并（C1）：锚更晚者保留；同锚取后写。

    更晚锚的哈希覆盖行区间 ⊇ 更早锚（date ≤ anchor 的行集单调扩大），受保护区间
    因此只增不缩。早于既有锚的回填轮不再能把权威三元组整体拉回旧锚。
    """
    existing = series_auth.get(path)
    if existing is None or anchor_date >= str(existing["anchor_date"]):
        series_auth[path] = {"anchor_date": anchor_date, "sha256": sha}


def verify_ledger(data_root, now: datetime | None = None) -> dict:
    """巡检账本，返回四张清单 + 断链行号（键名见模块 docstring），不抛巡检类异常。"""
    data_root = Path(data_root)
    now = now or _now()
    result: dict = {"undeclared": [], "unfinished_amends": [], "orphan_opens": [],
                    "sentinel": [], "chain_breaks": []}

    # -- 哈希链：逐行重算 prev_sha256；空白行 / 坏 JSON 行本身就是断链证据
    rows: list[dict] = []
    if ledger_path(data_root).exists():
        prev_digest = None
        for lineno, raw in enumerate(
                ledger_path(data_root).read_text(encoding="utf-8").splitlines(keepends=True), 1):
            if not raw.strip():
                result["chain_breaks"].append(lineno)
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                result["chain_breaks"].append(lineno)
                prev_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                continue
            expected = row.get("prev_sha256") if isinstance(row, dict) else None
            if expected != prev_digest:
                result["chain_breaks"].append(lineno)
            if isinstance(row, dict):
                rows.append(row)
            prev_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # -- 顺扫建权威哈希表：同目标多 close / amend-done 合法，取最后一条
    report_auth: dict[str, str | None] = {}    # path -> 期望整文件 sha
    series_auth: dict[str, dict] = {}          # path -> {anchor_date, sha256}
    evidence_auth: dict[str, str | None] = {}  # E-ID -> 期望（归一化）sha
    intents: list[dict] = []
    done_keys: set[tuple[str, str]] = set()
    open_rows: list[dict] = []
    active_runs: set[str] = set()

    for row in rows:
        rtype = row.get("type")
        if rtype in ACTIVITY_TYPES:
            active_runs.add(str(row.get("run_id")))
        if rtype == "open":
            open_rows.append(row)
        elif rtype == "data-close":
            for t in row.get("data_targets") or []:
                if not isinstance(t, dict) or not t.get("path"):
                    continue
                if t.get("anchor_date"):
                    # C1（实施评审）：同 path 多条 series 权威取**锚更晚**的条目（同锚取后写），
                    # 不能无条件覆盖——某轮只回填迟到旧行（新锚 < 历史锚）时受保护区间会
                    # 静默回退；更晚锚的哈希覆盖行区间 ⊇ 更早锚，取 max 才单调不收缩。
                    _merge_series_auth(series_auth, str(t["path"]),
                                       str(t["anchor_date"]), t.get("sha256"))
                else:
                    report_auth[str(t["path"])] = t.get("sha256")
        elif rtype == "close":
            if row.get("report"):
                report_auth[str(row["report"])] = row.get("report_sha256")
            for ev in row.get("evidence_registered") or []:
                if isinstance(ev, dict) and ev.get("id"):
                    evidence_auth[str(ev["id"])] = ev.get("sha256")
        elif rtype == "amend":
            intents.append(row)
        elif rtype == "amend-done":
            done_keys.add((str(row.get("run_id")), str(row.get("target"))))
            target = str(row.get("target")) if row.get("target") else None
            if row.get("missing"):
                # amend-done --missing：产物已消亡的收口——从权威表**摘除**（不删行，
                # append-only 不破）：verify 跳过该 target 的哈希比对。
                report_auth.pop(target, None)
                series_auth.pop(target, None)
                ev_id = _evidence_id_from_target(target or "")
                if ev_id is not None:
                    evidence_auth.pop(ev_id, None)
            elif row.get("anchor_date"):
                _merge_series_auth(series_auth, target,
                                   str(row["anchor_date"]), row.get("post_sha256"))
            elif target:
                ev_id = _evidence_id_from_target(str(row["target"]))
                if ev_id is not None:
                    # evidence 目标的 amend-done：同步权威表三键空间的 evidence_auth 键，
                    # 哈希口径与 close 注册一致（normalized_evidence_sha256）
                    evidence_auth[ev_id] = row.get("post_sha256")
                else:
                    report_auth[str(row["target"])] = row.get("post_sha256")

    # -- ① 未申报修订
    for path, expected in report_auth.items():
        target = _resolve_target(data_root, path)
        if not target.is_file():
            result["undeclared"].append({"kind": "report", "target": path, "detail": "文件缺失"})
            continue
        actual = file_sha256(target)
        if actual != expected:
            result["undeclared"].append({
                "kind": "report", "target": path,
                "detail": f"整文件哈希不一致（期望 {str(expected)[:12]}，实际 {actual[:12]}）"})
    for path, auth in series_auth.items():
        target = _resolve_target(data_root, path)
        if not target.is_file():
            result["undeclared"].append({"kind": "series", "target": path, "detail": "文件缺失"})
            continue
        try:
            actual = row_anchor_hash(target, auth["anchor_date"])
        except ValueError as exc:
            result["undeclared"].append(
                {"kind": "series", "target": path, "detail": f"锚定日期非法：{exc}"})
            continue
        if actual != auth["sha256"]:
            result["undeclared"].append({
                "kind": "series", "target": path,
                "detail": (f"行锚定哈希不一致（anchor {auth['anchor_date']}，"
                           f"期望 {str(auth['sha256'])[:12]}，实际 {actual[:12]}）")})
    for ev_id, expected in evidence_auth.items():
        ev_path = _find_evidence_file(data_root, ev_id)
        if ev_path is None:
            result["undeclared"].append({"kind": "evidence", "target": ev_id, "detail": "文件缺失"})
            continue
        actual = normalized_evidence_sha256(ev_path)
        if actual != expected:
            result["undeclared"].append({
                "kind": "evidence", "target": ev_id,
                "detail": (f"归一化哈希不一致（期望 {str(expected)[:12]}，"
                           f"实际 {actual[:12]}；正文改动须先 amend，状态字段迁移除外）")})

    # -- ② 未完成修订（intent 无 done）
    for row in intents:
        key = (str(row.get("run_id")), str(row.get("target")))
        if key not in done_keys:
            result["unfinished_amends"].append({
                "run_id": row.get("run_id"), "target": row.get("target"),
                "reason": row.get("reason"), "at": row.get("at")})

    # -- ③ 孤儿 open（>24h 无 data-close / close / abort 下文；backfill 不参与）
    cutoff = timedelta(hours=ORPHAN_HOURS)
    for row in open_rows:
        run_id = str(row.get("run_id"))
        if row.get("kind") == "backfill":
            continue
        if run_id in active_runs:
            continue
        started = _parse_dt(row.get("started_at"))
        if started is None:
            result["orphan_opens"].append({
                "run_id": row.get("run_id"), "kind": row.get("kind"),
                "started_at": row.get("started_at"), "detail": "started_at 不可解析"})
            continue
        age = now - started
        if age > cutoff:
            result["orphan_opens"].append({
                "run_id": row.get("run_id"), "kind": row.get("kind"),
                "started_at": row.get("started_at"),
                "detail": f"open 后 {age.total_seconds() / 3600:.1f}h 无下文"})

    # -- ④ sentinel：hook 写账本失败的可感知标记
    sentinel = sentinel_path(data_root)
    if sentinel.is_file():
        result["sentinel"].append({
            "path": str(SENTINEL_REL),
            "content": sentinel.read_text(encoding="utf-8").strip()})

    result["clean"] = not any(
        result[key] for key in
        ("undeclared", "unfinished_amends", "orphan_opens", "sentinel", "chain_breaks"))
    return result


# ---------------------------------------------------------------------------
# ledger：两次运行之间变了什么（Task 5）
# ---------------------------------------------------------------------------

# 判定行文法（object-model.md「巡检判定词表」段）：八槽固定字段序，值内禁竖线，空值 —
VERDICTS = ("normal", "warn", "trigger", "missing")
VERDICT_KEYS = ("check", "verdict", "as_of", "reading", "evidence", "补数", "reason")
_VERDICT_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \| (.+)$")


def parse_verdict_line(line: str):
    """解析一条判定行。

    返回 (fields, None)：解析成功（fields 含 date + 各槽）；
    返回 (None, None)：不是判定行（不参与文法检查）；
    返回 (None, reason)：形似判定行但文法坏了（显式降级，不静默跳过）。
    """
    match = _VERDICT_LINE_RE.match(line.strip())
    if not match:
        return None, None
    day, rest = match.groups()
    fields: dict[str, str] = {"date": day}
    for part in rest.split("|"):
        part = part.strip()
        key, sep, value = part.partition(":")
        key, value = key.strip(), value.strip()
        if not sep:
            return None, f"槽缺 ``key: value``：{part!r}"
        if key not in VERDICT_KEYS:
            return None, f"未知键 {key!r}"
        if key in fields:
            return None, f"重复键 {key!r}"
        fields[key] = value
    if not fields.get("check"):
        return None, "缺必填槽 check"
    if not fields.get("verdict"):
        return None, "缺必填槽 verdict"
    if fields["verdict"] not in VERDICTS:
        return None, f"verdict 非四值：{fields['verdict']!r}"
    if fields["verdict"] == "missing" and not fields.get("reason"):
        return None, "missing 判行缺 reason"
    return fields, None


def _hypothesis_files(data_root, hypothesis: str | None = None) -> list[Path]:
    """hypothesis/*.md；带 id 时按 frontmatter id（或文件名 H<id>- 前缀）过滤，找不到抛错。"""
    root = _repo_root(data_root) / "hypothesis"
    files = sorted(root.glob("*.md")) if root.is_dir() else []
    if hypothesis is None:
        return files
    want = str(hypothesis)
    matched = [p for p in files
               if parse_frontmatter(p.read_text(encoding="utf-8")).get("id") == want
               or p.stem == want or p.stem.startswith(f"{want}-")]
    if not matched:
        raise ValueError(f"假设文件未找到（hypothesis/*.md，id={want}）")
    return matched


def _linked_hypotheses(text: str) -> list[str]:
    """frontmatter 的 linked_hypotheses 列表（reader 只认标量，列表手工补读）。"""
    values: list[str] = []
    in_list = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_list:
            if stripped.startswith("- "):
                values.append(stripped[2:].strip())
                continue
            in_list = False
        if line.startswith("linked_hypotheses:"):
            in_list = True
            inline = line.partition(":")[2].strip().strip("'\"[]")
            if inline:
                values.append(inline)
    return values


def _row_day(row: dict, keys: tuple[str, ...]):
    """取行内首个可解析时间戳的日历日（naive 按本地时区补全，与账本口径一致）。"""
    for key in keys:
        parsed = _parse_dt(row.get(key))
        if parsed is not None:
            return parsed.date()
    return None


def build_ledger(data_root, from_day, to_day, hypothesis: str | None = None) -> dict:
    """汇总区间账：运行与修订 / 证据增量 / 判定变化，外加显式降级的坏行清单。

    - 账本行按时间戳日历日落区间（close 看 finished_at，其余看 at）；
    - evidence 按 recorded_at 落区间；带 --hypothesis 时改为 linked_hypotheses 命中该假设；
    - 假设正文判定行按行首日期落区间；文法坏行进 unparseable，不静默跳过也不中断。
    """
    result: dict = {"runs": [], "amends": [], "missing": [],
                    "evidence": [], "verdicts": [], "unparseable": []}
    rows, _ = _read_rows_strict(ledger_path(data_root))
    for row in rows:
        rtype = row.get("type")
        if rtype in ("close", "abort", "data-close"):
            day = _row_day(row, ("finished_at", "at"))
            if day is None or not from_day <= day <= to_day:
                continue
            entry = {"type": rtype, "run_id": row.get("run_id"),
                     "at": row.get("finished_at") or row.get("at")}
            if rtype == "close":
                entry["report"] = row.get("report")
            elif rtype == "abort":
                entry["reason"] = row.get("reason")
            elif rtype == "data-close":
                entry["sources_used"] = list(row.get("sources_used") or [])
                # missing 数组两种键形并存：股票侧 {ticker, source_tried, reason, fallback}
                # 与宏观侧 {item, reason}，展示层两者都要可读（T4 评审遗留约定）
                for m in row.get("missing") or []:
                    result["missing"].append({"run_id": row.get("run_id"), "entry": m})
            result["runs"].append(entry)
        elif rtype in ("amend", "amend-done"):
            day = _row_day(row, ("at",))
            if day is None or not from_day <= day <= to_day:
                continue
            result["amends"].append({"type": rtype, "run_id": row.get("run_id"),
                                     "target": row.get("target"), "reason": row.get("reason"),
                                     "at": row.get("at")})

    # -- 证据增量：evidence/**/*.md frontmatter（复用 evidence_lint reader）
    ev_root = _evidence_root(data_root)
    for path in sorted(ev_root.glob("**/*.md")) if ev_root.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        ev_id = fm.get("id") or path.stem
        if hypothesis is not None:
            if str(hypothesis) not in _linked_hypotheses(text):
                continue
        else:
            recorded = _parse_dt(fm.get("recorded_at"))
            if recorded is None or not from_day <= recorded.date() <= to_day:
                continue
        result["evidence"].append({
            "id": ev_id, "direction": fm.get("direction", "—"),
            "review_status": fm.get("review_status", "—"),
            "recorded_at": fm.get("recorded_at", "—"),
            "path": str(path.relative_to(_repo_root(data_root)))})

    # -- 判定变化：假设正文巡检行，按文法解析，坏行显式降级
    for hyp in _hypothesis_files(data_root, hypothesis):
        text = hyp.read_text(encoding="utf-8")
        hyp_id = parse_frontmatter(text).get("id") or hyp.stem
        for lineno, line in enumerate(text.splitlines(), 1):
            fields, why = parse_verdict_line(line)
            if fields is None:
                if why is not None:
                    result["unparseable"].append(
                        {"file": hyp.name, "line": lineno, "text": line.strip(),
                         "reason": why})
                continue
            if from_day <= date.fromisoformat(fields["date"]) <= to_day:
                entry = dict(fields)
                entry["hypothesis"] = hyp_id
                result["verdicts"].append(entry)
    return result


def _fmt_missing(entry) -> str:
    """missing 条目转一行文字；两种键形（股票侧 / 宏观侧）与自由文本都兼容。"""
    if not isinstance(entry, dict):
        return str(entry)
    head = entry.get("ticker") or entry.get("item") or "?"
    parts = [str(head)]
    if entry.get("source_tried"):
        parts.append(f"源 {entry['source_tried']}")
    if entry.get("reason"):
        parts.append(f"原因 {entry['reason']}")
    if entry.get("fallback"):
        parts.append(f"降级 {entry['fallback']}")
    return " / ".join(parts)


def _render_ledger(result: dict, from_day, to_day, hypothesis: str | None) -> str:
    span = f"{from_day:%Y-%m-%d} ~ {to_day:%Y-%m-%d}"
    head = f"[run-archive ledger] {span}"
    if hypothesis is not None:
        head += f"（假设过滤：{hypothesis}）"
    out = [head, ""]

    out.append("## 运行与修订")
    runs = result["runs"] + result["amends"]
    if not runs:
        out.append("- （区间内无记账行）")
    for entry in runs:
        run_id = entry.get("run_id") or "?"
        if entry["type"] == "close":
            out.append(f"- close {run_id} -> {entry.get('report') or '?'}（{entry.get('at') or '?'}）")
        elif entry["type"] == "abort":
            out.append(f"- abort {run_id}：{entry.get('reason') or '?'}（{entry.get('at') or '?'}）")
        elif entry["type"] == "data-close":
            sources = ",".join(entry.get("sources_used") or []) or "—"
            out.append(f"- data-close {run_id} 源 {sources}（{entry.get('at') or '?'}）")
        elif entry["type"] == "amend":
            out.append(f"- amend intent {run_id} -> {entry.get('target') or '?'}"
                       f"：{entry.get('reason') or '?'}（{entry.get('at') or '?'}）")
        else:  # amend-done
            out.append(f"- amend-done {run_id} -> {entry.get('target') or '?'}"
                       f"（{entry.get('at') or '?'}）")
    if result["missing"]:
        out.append(f"- 数据缺口（{len(result['missing'])}）：")
        for item in result["missing"]:
            out.append(f"  - [{item['run_id']}] {_fmt_missing(item['entry'])}")
    out.append("")

    out.append("## 证据增量")
    if not result["evidence"]:
        out.append("- （无）")
    for ev in result["evidence"]:
        out.append(f"- {ev['id']} | direction={ev['direction']} | "
                   f"review_status={ev['review_status']} | recorded_at={ev['recorded_at']}")
    out.append("")

    out.append("## 判定变化")
    if not result["verdicts"]:
        out.append("- （无）")
    for v in result["verdicts"]:
        out.append(f"- [{v['hypothesis']}] {v['date']} check={v['check']} "
                   f"verdict={v['verdict']} reading={v.get('reading', '—')}"
                   + (f" evidence={v['evidence']}" if v.get("evidence", "—") != "—" else ""))
    if result["unparseable"]:
        out.append("")
        out.append(f"✗ 无法解析的行（{len(result['unparseable'])}，人工读取）：")
        for bad in result["unparseable"]:
            out.append(f"  - {bad['file']} 第 {bad['line']} 行：{bad['text']}"
                       f"（{bad['reason']}）")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI 薄壳
# ---------------------------------------------------------------------------

def _print_verify(result: dict, ledger: Path) -> None:
    print(f"[run-archive verify] 账本：{ledger}")
    if result["clean"]:
        print("  ✓ 全部干净")
        return
    sections = (
        ("undeclared", "未申报修订"),
        ("unfinished_amends", "未完成修订"),
        ("orphan_opens", f"孤儿 open（>{ORPHAN_HOURS}h 无下文）"),
        ("sentinel", "写失败 sentinel"),
        ("chain_breaks", "哈希链断链行"),
    )
    for key, label in sections:
        items = result[key]
        print(f"  {'✗' if items else '✓'} {label}（{len(items)}）")
        for item in items:
            if isinstance(item, dict):
                tag = f"[{item['kind']}] " if "kind" in item else ""
                head = item.get("target") or item.get("path") or item.get("run_id") or ""
                detail = item.get("detail") or item.get("content") or item.get("reason") or ""
                print(f"    - {tag}{head}" + (f"：{detail}" if detail else ""))
            else:
                print(f"    - 第 {item} 行")


def _parse_missing(spec: str) -> list:
    try:
        missing = json.loads(spec) if spec.strip() else []
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--missing-json 不是合法 JSON：{exc}") from exc
    if not isinstance(missing, list):
        raise SystemExit("--missing-json 必须是 JSON 数组")
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_archive",
        description="运行账本 data/.state/run-log.jsonl 的写入与巡检（约定见 object-model.md「运行账本」段）")
    parser.add_argument("--data-root", default=None,
                        help="data 根目录（默认 <仓库根>/data；账本在 <data-root>/.state/run-log.jsonl）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_open = sub.add_parser("open", help="运行开始：写 open 行并打印 run_id")
    p_open.add_argument("--kind", required=True, choices=KINDS, help="运行类型（十值）")
    p_open.add_argument("--trade-date", required=True, help="业务交易日 YYYY-MM-DD")

    p_dc = sub.add_parser("data-close", help="数据侧收口（persist 钩子自动写；series 目标行锚定）")
    p_dc.add_argument("--run-id", required=True)
    p_dc.add_argument("--data-target", action="append", default=[], metavar="PATH[#ANCHOR]",
                      help="目标路径，可多次；.jsonl 必须带 #anchor（行锚定），其余整文件哈希")
    p_dc.add_argument("--sources", default="", help="逗号分隔的数据源清单")
    p_dc.add_argument("--missing-json", default="[]", help="结构化降级清单（JSON 数组，透传）")

    p_close = sub.add_parser("close", help="报告落盘后收口：报告哈希 + evidence 登记")
    p_close.add_argument("--run-id", required=True)
    p_close.add_argument("--report", required=True, help="报告路径（仓库根相对）")
    p_close.add_argument("--evidence", action="append", default=[], metavar="E-ID[:SHA256]",
                         help="evidence ID，可多次；不带 sha256 时按 I4 归一化规则现算，显式给出则透传")

    p_amend = sub.add_parser("amend", help="两步修订：先 intent（--reason），改完再 --done")
    p_amend.add_argument("--run-id", required=True)
    p_amend.add_argument("--target", required=True, help="修订目标路径（仓库根相对）")
    p_amend.add_argument("--reason", default=None, help="修订原因（intent 必填）")
    p_amend.add_argument("--data-target", action="append", default=[], metavar="PATH#DATE",
                         help="series 修订目标 path#date，可多次（intent 声明；--done 时可再给）")
    p_amend.add_argument("--done", action="store_true", help="第二步：写 amend-done 行（改后哈希）")
    p_amend.add_argument("--missing", action="store_true",
                         help="与 --done 同用：产物已消亡（文件不存在）的收口——"
                              "写带 missing 标记的 amend-done，verify 摘除该 target 的权威比对；"
                              "必须给 --reason 说明消亡原因")

    p_abort = sub.add_parser("abort", help="运行中止显式记账")
    p_abort.add_argument("--run-id", required=True)
    p_abort.add_argument("--reason", required=True)

    p_verify = sub.add_parser("verify", help="巡检：未申报修订/未完成修订/孤儿 open/sentinel + 哈希链")
    p_verify.add_argument("--json", action="store_true", help="输出 JSON（默认人类可读清单）")

    p_ledger = sub.add_parser("ledger", help="两次运行之间变了什么（Task 5 落地）")
    p_ledger.add_argument("--from", dest="from_date", default=None, help="区间起（YYYY-MM-DD）")
    p_ledger.add_argument("--to", dest="to_date", default=None, help="区间止（YYYY-MM-DD）")
    p_ledger.add_argument("--hypothesis", default=None, help="按假设过滤（如 H1）")
    p_ledger.add_argument("--json", action="store_true", help="输出 JSON")

    args = parser.parse_args(argv)
    data_root = (Path(args.data_root) if args.data_root
                 else Path(__file__).resolve().parents[2] / "data")

    if args.command == "verify":
        result = verify_ledger(data_root)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_verify(result, ledger_path(data_root))
        return 0 if result["clean"] else 1
    if args.command == "ledger":
        if not args.from_date or not args.to_date:
            parser.error("ledger 需要 --from 与 --to（YYYY-MM-DD）")
        try:
            from_day = date.fromisoformat(args.from_date)
            to_day = date.fromisoformat(args.to_date)
        except ValueError as exc:
            parser.error(f"日期非法（YYYY-MM-DD）：{exc}")
        if from_day > to_day:
            parser.error("--from 不能晚于 --to")
        try:
            result = build_ledger(data_root, from_day, to_day, args.hypothesis)
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(_render_ledger(result, from_day, to_day, args.hypothesis), end="")
        return 0

    try:
        if args.command == "open":
            print(append_open(data_root, args.kind, args.trade_date))
        elif args.command == "data-close":
            append_data_close(data_root, args.run_id, args.data_target,
                              [s.strip() for s in args.sources.split(",") if s.strip()],
                              _parse_missing(args.missing_json))
            print(f"data-close 已记账：{args.run_id}")
        elif args.command == "close":
            append_close(data_root, args.run_id, args.report, args.evidence)
            print(f"close 已记账：{args.run_id} -> {args.report}")
        elif args.command == "amend":
            if not args.done and not args.reason:
                parser.error("amend intent 必须带 --reason")
            append_amend(data_root, args.run_id, args.target, args.reason,
                         data_targets=args.data_target or None, done=args.done,
                         missing=args.missing)
            print("amend-done 已记账" if args.done else "amend intent 已记账")
        elif args.command == "abort":
            append_abort(data_root, args.run_id, args.reason)
            print(f"abort 已记账：{args.run_id}")
    except (ValueError, FileNotFoundError) as exc:
        # 库 API 的 fail-loud 异常转 CLI：stderr + exit 1（区别于 argparse 参数错的 exit 2）
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
