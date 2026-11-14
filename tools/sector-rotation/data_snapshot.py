# tools/sector-rotation/data_snapshot.py
"""确认性消费跑数据快照（Q-20261110-08 B 案，R20261110-05 静默改史修根）。

事故链：us_backfill 全量重拉以 batch 权威写者覆盖全部历史行 → 已消费报告
绑定的数据态永久消失（git 锚代码不锚数据）→ 归档 summary 不可重放。本模块
把「运行前对依赖数据落 hash 清单」做成一行接入：manifest 记每个文件
sha256，内容态整体指纹写入报告头部——事后复盘/重放时指纹对不上即知数据
态已漂移（对拍法前置为运行时自动记录，不再依赖事后人工发现）。

快照=hash 清单而非冻结副本：KB 级开销、可 diff 定位漂移文件；需逐字节
重放时按 manifest 从备份源恢复，本层不承担存储职责。

用法（预注册类 runner main() 覆盖检查后、读数据前）：

    from data_snapshot import snapshot_data_paths, snapshot_report_line
    snap = snapshot_data_paths([US_DATA], OUT.with_name(OUT.stem + "-data-manifest.json"))
    report.insert(2, snapshot_report_line(snap))   # 或等价拼接
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _file_digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_files(base: Path) -> list[Path]:
    """目录=rglob 全文件（跳过隐藏文件与 .locks 等点前缀目录——锁/Pycache 非
    数据态）；单文件=自身。"""
    if base.is_file():
        return [base]
    out = []
    for q in sorted(base.rglob("*")):
        if not q.is_file():
            continue
        rel = q.relative_to(base)
        if any(part.startswith(".") for part in rel.parts):
            continue
        out.append(q)
    return out


def snapshot_data_paths(paths: list[Path], manifest_path: Path) -> dict:
    """对 paths（目录/单文件混合）逐文件 sha256，manifest 落盘，返回摘要 dict。

    fingerprint = sha256("\\n".join("相对路径:文件sha256"))，entries 按路径排序
    ——目录枚举顺序无关，内容态唯一。目录条目路径带 base.name 前缀（多目录
    混合时不撞名）。
    """
    entries: list[dict] = []
    for base in paths:
        prefix = "" if base.is_file() else f"{base.name}/"
        for f in _iter_files(base):
            rel = f.name if base.is_file() else f.relative_to(base).as_posix()
            entries.append({"path": f"{prefix}{rel}",
                            "bytes": f.stat().st_size,
                            "sha256": _file_digest(f)})
    entries.sort(key=lambda e: e["path"])
    digest_src = "\n".join(f"{e['path']}:{e['sha256']}" for e in entries)
    fingerprint = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()
    total_bytes = sum(e["bytes"] for e in entries)
    manifest = {
        "fingerprint": fingerprint,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": len(entries),
        "bytes": total_bytes,
        "entries": entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return {"fingerprint": fingerprint, "manifest_path": manifest_path,
            "files": len(entries), "bytes": total_bytes}


def snapshot_report_line(snap: dict) -> str:
    """报告头部快照行（含短指纹与 manifest 相对线索，供人工对拍）。"""
    mb = snap["bytes"] / (1 << 20)
    size = f"{mb:.1f} MB" if mb >= 1 else f"{snap['bytes'] / 1024:.0f} KB"
    return (f"数据快照（Q-20261110-08 B）：指纹 `{snap['fingerprint'][:16]}` · "
            f"{snap['files']} 文件 · {size} · manifest "
            f"`{snap['manifest_path']}`")
