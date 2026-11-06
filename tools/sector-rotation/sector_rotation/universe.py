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


def point_in_time_pick(candidates: list[str], bars: dict[str, list[dict]],
                       week_end: str, *, min_list_years: int = 2,
                       min_amount_wan: float = 10000.0,
                       bypass_single: bool = False) -> str | None:
    """当时达标者：上市满 2 年 + trailing 20 日均额 ≥ 1 亿；多只取均额最大
    （规模 proxy 近似，spec §8 待验证——README 声明；上市年满 2 年按年整数差
    近似，误差 ±数日，评审 M2 注记）。

    bypass_single（R20261106-02 §7 第 5 行，设计评审 C-1）：单候选集旁路两道
    闸门直接返回该候选——美股退化宇宙每成员仅 1 只 ETF，闸门本为 A 股多候选
    择一而设，不旁路则美元口径均额/短史被静默踢出、宇宙缩水且全链路无警报；
    旁路后 valid 退化为数据齐备性（缺数防护仍在 build_weekly_frame）。"""
    if bypass_single and len(candidates) == 1:
        return candidates[0]
    best, best_amt = None, 0.0
    for sym in candidates:
        rows = [r for r in bars.get(sym, []) if r["date"] <= week_end]
        if len(rows) < 20:
            continue
        first, recent = rows[0]["date"], rows[-20:]
        listed_years = (int(week_end[:4]) - int(first[:4]))
        if listed_years < min_list_years:
            continue
        amt = sum(r["amount"] for r in recent) / 20
        if amt >= min_amount_wan * 1e4 and amt > best_amt:
            best, best_amt = sym, amt
    return best
