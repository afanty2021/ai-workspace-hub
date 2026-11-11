from __future__ import annotations

import re
import unittest
from pathlib import Path

import _test_paths  # noqa: F401 — 先入 path，再取两个 scripts 模块的 secid 表
import fetch_market_data
import update_cross_asset_history


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_entrypoint_templates_match_public_entrypoints(self) -> None:
        pairs = (
            ("system/templates/AGENTS.md", "AGENTS.md"),
            ("system/templates/CLAUDE.md", "CLAUDE.md"),
            ("system/templates/workspace-config.md", "workspace/workspace-config.md"),
            ("system/templates/active-context.md", "workspace/meta/active-context.md"),
            ("system/templates/friction-log.md", "workspace/meta/friction-log.md"),
            ("system/templates/research-profile.md", "workspace/research-profile.md"),
            ("system/templates/review-queue.md", "workspace/review-queue.md"),
        )
        # active-context and friction-log are append-only working logs: the
        # in-repo workspace accumulates real entries the moment anyone
        # dogfoods the hub here. Only the static instructions above their
        # first append sections are contractual; entries below are usage.
        append_only = {
            "system/templates/active-context.md": "## 最近对话延续",
            "system/templates/friction-log.md": "## Log",
            # review-queue 是被跟踪的实例文件，但表格行是使用数据（agent 自动追加）：
            # 只有表头以上的静态说明是契约，分隔线以下的行不比较。
            "system/templates/review-queue.md": "|---|---|---|---|---|---|---|",
            # research-profile 的「本轮观察」同理（2026-11-06 首条观察触发此缺口）：
            # 引导句以上的静态说明与已确认偏好是契约，观察条目是使用数据不比较。
            "system/templates/research-profile.md": "> 记录用户在真实研究中的追问、删改和反驳。观察不等于偏好",
        }
        for template, public in pairs:
            public_path = REPO_ROOT / public
            if not public_path.exists():
                # Instance files (active-context / friction-log) are untracked:
                # a fresh clone has no workspace/meta yet until the installer
                # rebuilds them from templates. Nothing to compare there; the
                # tracked entrypoints below always exist.
                continue
            template_text = (REPO_ROOT / template).read_text(encoding="utf-8")
            public_text = (REPO_ROOT / public).read_text(encoding="utf-8")
            marker = append_only.get(template)
            if marker is not None:
                marker_index = template_text.find(marker)
                if marker_index != -1:
                    template_text = template_text[:marker_index]
                    public_text = public_text[: public_text.find(marker)]
            self.assertEqual(
                template_text,
                public_text,
                f"{template} and {public} diverged",
            )

    def test_all_relative_markdown_links_resolve(self) -> None:
        pattern = re.compile(r"\[[^]]*\]\(([^)]+)\)")
        broken: list[str] = []
        for markdown in REPO_ROOT.rglob("*.md"):
            if set(markdown.relative_to(REPO_ROOT).parts) & {
                ".git", "node_modules", ".venv", "venv", "dist", "build", ".next",
            }:
                continue
            for target in pattern.findall(markdown.read_text(encoding="utf-8")):
                target = target.split("#", 1)[0].strip()
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                path = (markdown.parent / target.replace("%20", " ")).resolve()
                if not path.exists():
                    broken.append(f"{markdown.relative_to(REPO_ROOT)} -> {target}")
        self.assertEqual(broken, [])

    def test_longbridge_is_not_claimed_as_builtin_env_provider(self) -> None:
        market_script = (
            REPO_ROOT / "tools/daily-watch/scripts/fetch_market_data.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("LONGBRIDGE_APP_KEY", market_script)
        self.assertNotIn("fetch_longbridge", market_script)

    def test_optional_transcription_is_not_in_base_requirements(self) -> None:
        requirements = (
            REPO_ROOT / "tools/podcast/requirements.txt"
        ).read_text(encoding="utf-8")
        active = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertFalse(any(line.startswith("faster-whisper") for line in active))
        self.assertTrue(
            (REPO_ROOT / "tools/podcast/requirements-transcribe.txt").is_file()
        )
        self.assertTrue(
            (REPO_ROOT / "tools/daily-watch/requirements-tushare.txt").is_file()
        )

    def test_example_secrets_are_treated_as_unconfigured(self) -> None:
        market_script = (
            REPO_ROOT / "tools/daily-watch/scripts/fetch_market_data.py"
        ).read_text(encoding="utf-8")
        macro_script = (
            REPO_ROOT / "tools/daily-watch/scripts/fetch_macro_data.py"
        ).read_text(encoding="utf-8")
        self.assertIn('startswith("your_")', market_script)
        self.assertIn('startswith("your_")', macro_script)

    def test_data_sources_doc_covers_entrypoint_wirings(self) -> None:
        """契约修根（friction-log 硬规则，同类第 3 案）：AGENTS.md 数据源表里
        登记的接线 token（fund_nav / jj 前缀 / 116 段 / gpcw …）必须在
        DATA-SOURCES.md 的选择表同步出现。

        历史三次漏同步（模板×2、DATA-SOURCES×1）都败在"人工记七处清单"——
        本测试把清单变成派生断言：往 AGENTS.md 加新接线 token 而
        DATA-SOURCES.md 不跟，这里直接红。锁 DATA-SOURCES.md 一处（README/
        skill 是操作手册，覆盖面天然不同，不做 token 平价）。
        """
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        # 「## 数据源」段内的表格行（| 数据源 | 市场 | env key | 费用 |）。
        section = agents.split("## 数据源", 1)[1].split("\n## ", 1)[0]
        # 空格可选：无空格写法（"jj前缀"）也要被提取成 token 并要求两处
        # 一致（复查 R-1：原 `[a-z]{2,3} 前缀` 依赖空格，无空格改写 +
        # DATA-SOURCES 删行时静默漏锁）。
        # 评审 Q-20261109-03/04 I-1：push2his 与东财 secid（124.HSTECH /
        # 103.NQ00Y）随跨资产回补接线进表但不在旧 pattern 内，变异重放
        # 证明删 DATA-SOURCES 行不红——补进 pattern 防同类第 4 案。
        token_re = re.compile(
            r"\d{3}(?:/\d{3})? ?段|[a-z]{2,3} ?前缀|[a-z]+_nav|gpcw|datacenter"
            r"|push2his|\d{3}\.[A-Z][A-Z0-9]*"
        )
        # 评审 Q-20261109-04 后续批 I-1（同族第 4 案、第 2 次补 regex）：枚举
        # 家族永远追不上新接线形态——修根为「反引号即锁」：表行内反引号包裹
        # 的 token（.TDX / .OF / env key / 新源名如 `Nasdaq 官方 historical`）
        # 一律派生进锁，登记新接线时用反引号写源名即自动受锁，无需改本测试。
        backtick_re = re.compile(r"`([^`]+)`")
        # 结构锁（同日用户拍板，复查后继建议）：第 1 列「数据源」按 / 拆分的
        # 子源名整列入锁——新源进表即受锁，不依赖作者记得写反引号，彻底
        # 消除「忘加反引号=静默不进锁」路径（反引号锁继续管第 4 列的接线
        # token 族，两层互补）。
        tokens: set[str] = set()
        for line in section.splitlines():
            if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] != "数据源":  # 表头行不入锁
                tokens.update(n.strip() for n in cells[0].split("/") if n.strip())
            tokens.update(token_re.findall(line))
            tokens.update(backtick_re.findall(line))
        # 解析失效（表挪位置/改格式）时宁可红也不静默通过。
        self.assertTrue(tokens, "AGENTS.md 数据源表解析不到任何接线 token")
        doc = (REPO_ROOT / "DATA-SOURCES.md").read_text(encoding="utf-8")
        missing = sorted(t for t in tokens if t not in doc)
        self.assertEqual(
            missing, [], f"DATA-SOURCES.md 缺少接线 token 同步: {missing}"
        )


class EastmoneySecidContractTests(unittest.TestCase):
    """跨模块契约（2026-11-11 max 评审建议落地，同日 I-1 secid 测试盲区
    的机制级收口）：东财实时表（fetch_market_data.EASTMONEY_GLOBAL_SYMBOLS，
    push2）与回补表（update_cross_asset_history.CROSS_ASSET_HISTORY_SECIDS，
    push2his）对同一票必须是**同一份 secid 事实**。此前两表各改各的，
    「新接线只进一张表 / 改一张忘另一张」无任何红灯（I-1 变异重放坐实
    过 dict 分发零覆盖）——本测试把「^GSPC/^DJI 2026-11-11 两表同 secid
    接线」的 做法 变成机制。
    """

    def test_shared_tickers_use_identical_secids(self) -> None:
        # 交集票严格相等，无白名单豁免——当前 8 票全一致；若未来出现有意的
        # 同票 secid 分叉（东财实时段与历史段对某票用不同市场段），须在此
        # 显式登记分叉及理由，不许静默。
        live = dict(fetch_market_data.EASTMONEY_GLOBAL_SYMBOLS)
        hist = dict(update_cross_asset_history.CROSS_ASSET_HISTORY_SECIDS)
        shared = sorted(set(live) & set(hist))
        mismatches = {t: (live[t], hist[t]) for t in shared if live[t] != hist[t]}
        self.assertFalse(
            mismatches,
            f"同票两表 secid 分叉（改齐一张表，或在此登记有意分叉的理由）: {mismatches}",
        )

    def test_single_sided_tickers_are_registered(self) -> None:
        # 单侧独有票=合法的源覆盖差异（实时与历史本不必同源），但必须显式
        # 登记——未登记的单侧新票 = 新接线漏接另一张表，红。
        live_only = set(fetch_market_data.EASTMONEY_GLOBAL_SYMBOLS) - set(
            update_cross_asset_history.CROSS_ASSET_HISTORY_SECIDS)
        hist_only = set(update_cross_asset_history.CROSS_ASSET_HISTORY_SECIDS) - set(
            fetch_market_data.EASTMONEY_GLOBAL_SYMBOLS)
        # 000660.KS：韩股 keyless 快照独苗（177 段），无历史回补需求。
        # DX-Y.NYB：实时主源是新浪 DINIW（SINA_GLOBAL_SYMBOLS，不走东财
        # 实时），历史才走东财 100.UDI——评审时误记为「secid 分叉需白名单」，
        # 核实后实为跨源不对称，落此登记集而非交集豁免。
        # 注意 ^SOX 不在此列：历史主源虽是 Nasdaq API，但 251.SOX 在两表
        # 同 secid 保留（东财降级路径 + --tickers 白名单），仍受交集断言约束。
        LIVE_ONLY = {"000660.KS"}
        HISTORY_ONLY = {"DX-Y.NYB"}
        self.assertEqual(
            live_only, LIVE_ONLY,
            f"实时表独有票变动 {sorted(live_only)}：新接线请同步回补表或更新登记",
        )
        self.assertEqual(
            hist_only, HISTORY_ONLY,
            f"回补表独有票变动 {sorted(hist_only)}：新接线请同步实时表或更新登记",
        )


if __name__ == "__main__":
    unittest.main()
