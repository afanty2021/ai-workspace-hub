"""宇宙 spec（config/sector-rotation-universe.md）读写：候选集映射 + 簇代表。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HEADER = "type: sector-rotation-universe"
MEMBER_COLS = ["index_code", "index_name", "etf_candidates", "limit_pct"]
CLUSTER_COLS = ["generation", "index_code", "cluster"]


@dataclass(frozen=True)
class Member:
    index_code: str
    index_name: str
    etf_candidates: tuple[str, ...]
    limit_pct: float


@dataclass(frozen=True)
class UniverseSpec:
    members: list[Member]
    clusters: dict[int, dict[str, str]]


def load_universe(path: Path) -> UniverseSpec:
    text = path.read_text(encoding="utf-8")
    if HEADER not in text:
        raise ValueError(f"{path} 缺 frontmatter 标记 {HEADER}")
    members: list[Member] = []
    clusters: dict[int, dict[str, str]] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if section.startswith("成员") or section == "":
            if cells == MEMBER_COLS or cells[0] == "index_code":
                continue
            if len(cells) != len(MEMBER_COLS):
                raise ValueError(f"成员表列数不符：{line}")
            members.append(Member(cells[0], cells[1],
                                  tuple(cells[2].split(";")), float(cells[3])))
        elif section.startswith("簇"):
            if cells == CLUSTER_COLS or cells[0] == "generation":
                continue
            if len(cells) != len(CLUSTER_COLS):
                raise ValueError(f"簇表列数不符：{line}")
            clusters.setdefault(int(cells[0]), {})[cells[1]] = cells[2]
    if not members:
        raise ValueError(f"{path} 未解析到任何成员")
    return UniverseSpec(members, clusters)


def write_universe(path: Path, spec: UniverseSpec, *, status: str) -> None:
    lines = ["---", HEADER, f"status: {status}", "---", "",
             "## 成员（指数 → ETF 候选集，point-in-time 引擎每周择一）",
             "", "| " + " | ".join(MEMBER_COLS) + " |",
             "|" + "---|" * len(MEMBER_COLS)]
    for m in spec.members:
        lines.append(f"| {m.index_code} | {m.index_name} | "
                     f"{';'.join(m.etf_candidates)} | {m.limit_pct} |")
    lines += ["", "## 簇代（滞后滚动窗：代 g 用 [g, g+1] 年收益聚类，g+2 年起可用）",
              "", "| " + " | ".join(CLUSTER_COLS) + " |",
              "|" + "---|" * len(CLUSTER_COLS)]
    for gen in sorted(spec.clusters):
        for code in sorted(spec.clusters[gen]):
            lines.append(f"| {gen} | {code} | {spec.clusters[gen][code]} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cluster_for(spec: UniverseSpec, friday: str) -> dict[str, str] | None:
    year = int(friday[:4])
    usable = [g for g in spec.clusters if g + 2 <= year]
    return spec.clusters[max(usable)] if usable else None
