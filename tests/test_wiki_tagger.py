from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

from system.lib import llm_client
from system.scripts import wiki_tagger

REPO_ROOT = Path(__file__).resolve().parents[1]
PODCAST_SCRIPTS = REPO_ROOT / "tools" / "podcast" / "scripts"
if str(PODCAST_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PODCAST_SCRIPTS))

import fetch_podcasts  # noqa: E402


MODEL_OUTPUT = {
    "domain": ["tech"],
    "ticker": ["NVDA"],
    "concepts": ["AI算力", "推理硬件"],
    "related": ["NVDA", "AI算力"],
    "entity_salience": {"NVDA": "core"},
    "tags": ["供给约束", "资本开支周期"],
}


def fake_chat(*_args, **_kwargs) -> str:
    return json.dumps(MODEL_OUTPUT, ensure_ascii=False)


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


class WikiTaggerValidationTests(unittest.TestCase):
    def test_model_output_is_normalized_to_public_schema(self) -> None:
        payload = {
            "domain": ["investing", "invalid-domain"],
            "tickers": ["nvda", "not a ticker", "9988.hk"],
            "concepts": ["AI算力", "AI算力"],
            "related": ["[[NVDA]]", "Anthropic"],
            "entity_salience": {"NVDA": "CORE", "9988.HK": "wrong"},
            "tags": ["#供给约束", "供给约束", "资本开支周期"],
            "unexpected": "must disappear",
        }

        result = wiki_tagger.validate_payload(payload)

        self.assertEqual(result["domain"], ["investing"])
        self.assertEqual(result["ticker"], ["NVDA", "9988.HK"])
        self.assertEqual(result["concepts"], ["AI算力"])
        self.assertEqual(result["entity_salience"], {"NVDA": "core", "9988.HK": "mention"})
        self.assertEqual(result["tags"], ["供给约束", "资本开支周期"])
        self.assertNotIn("unexpected", result)
        self.assertIn("[[Anthropic]]", result["related"])

    def test_invalid_domain_rejects_the_whole_result(self) -> None:
        with self.assertRaises(wiki_tagger.TaggingError):
            wiki_tagger.validate_payload({"domain": ["finance"]})


class WikiTaggerWriteTests(unittest.TestCase):
    def make_workspace(self, root: Path) -> Path:
        source_dir = root / "wiki" / "sources"
        concept_dir = root / "wiki" / "concepts"
        source_dir.mkdir(parents=True)
        concept_dir.mkdir(parents=True)
        (root / "workspace").mkdir()
        (root / "workspace" / "workspace-config.md").write_text("# config\n", encoding="utf-8")
        (concept_dir / "AI算力.md").write_text(
            "---\ntitle: AI算力\ntype: concept\ntags: [基础设施]\n---\n\n# AI算力\n",
            encoding="utf-8",
        )
        page = source_dir / "sample.md"
        page.write_text(
            "---\n"
            "title: Sample\n"
            "type: source-summary\n"
            "domain: [investing]\n"
            "ticker: []\n"
            "concepts: []\n"
            "related: []\n"
            "entity_salience: {}\n"
            "tags: [人工标签]\n"
            "---\n\n"
            "# Sample\n\nNVDA faces an AI accelerator supply constraint.\n",
            encoding="utf-8",
        )
        return page

    def test_apply_fills_empty_fields_and_preserves_manual_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_workspace(root)

            result = wiki_tagger.tag_file(page, root=root, apply=True, chat_func=fake_chat)
            metadata = read_frontmatter(page)

            self.assertEqual(result["status"], "updated")
            self.assertEqual(metadata["domain"], ["investing"])
            self.assertEqual(metadata["tags"], ["人工标签"])
            self.assertEqual(metadata["ticker"], ["NVDA"])
            self.assertEqual(metadata["concepts"], ["AI算力", "推理硬件"])
            self.assertEqual(metadata["entity_salience"], {"NVDA": "core"})
            self.assertEqual(metadata["tagging"], {"status": "completed", "schema_version": 1})

            def fail_if_called(*_args, **_kwargs) -> str:
                raise AssertionError("completed page must not call the LLM again")

            second = wiki_tagger.tag_file(
                page, root=root, apply=True, chat_func=fail_if_called
            )
            self.assertEqual(second["status"], "unchanged")

    def test_preview_never_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_workspace(root)
            before = page.read_text(encoding="utf-8")

            result = wiki_tagger.tag_file(page, root=root, apply=False, chat_func=fake_chat)

            self.assertEqual(result["status"], "preview")
            self.assertEqual(page.read_text(encoding="utf-8"), before)

    def test_backfill_wiki_skips_raw_and_index_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_workspace(root)
            raw = root / "wiki" / "raw" / "raw.md"
            raw.parent.mkdir()
            raw.write_text("raw", encoding="utf-8")
            index = root / "wiki" / "sources" / "_index.md"
            index.write_text("# index", encoding="utf-8")

            paths = wiki_tagger.iter_markdown_files(root / "wiki")

            self.assertIn(page, paths)
            self.assertNotIn(raw, paths)
            self.assertNotIn(index, paths)

    def test_cli_preview_cache_is_reused_by_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_workspace(root)
            before = page.read_text(encoding="utf-8")
            calls = 0

            def counting_chat(*args, **kwargs) -> str:
                nonlocal calls
                calls += 1
                return fake_chat(*args, **kwargs)

            preview_stdout = io.StringIO()
            with redirect_stdout(preview_stdout):
                preview_code = wiki_tagger.main(
                    ["--root", str(root), "--json", "tag", str(page)],
                    chat_func=counting_chat,
                )
            preview = json.loads(preview_stdout.getvalue())
            self.assertEqual(page.read_text(encoding="utf-8"), before)
            self.assertFalse(preview["results"][0]["cache_hit"])

            apply_stdout = io.StringIO()
            with redirect_stdout(apply_stdout):
                apply_code = wiki_tagger.main(
                    ["--root", str(root), "--json", "tag", str(page), "--apply"],
                    chat_func=counting_chat,
                )
            applied = json.loads(apply_stdout.getvalue())

            self.assertEqual(preview_code, 0)
            self.assertEqual(apply_code, 0)
            self.assertEqual(calls, 1)
            self.assertTrue(applied["results"][0]["cache_hit"])
            self.assertEqual(read_frontmatter(page)["ticker"], ["NVDA"])
            self.assertTrue((root / "workspace/cache/wiki_tagger.json").is_file())

    def test_external_wiki_root_reuses_its_own_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            external = Path(tmp) / "vault"
            (workspace / "wiki").mkdir(parents=True)
            concept = external / "concepts" / "External Concept.md"
            concept.parent.mkdir(parents=True)
            concept.write_text(
                "---\ntitle: External Concept\ntags: [external-tag]\n---\n",
                encoding="utf-8",
            )
            source = external / "sources" / "source.md"
            source.parent.mkdir()
            source.write_text("---\ntitle: Source\n---\n\nbody\n", encoding="utf-8")

            inferred = wiki_tagger.infer_wiki_root(source, workspace)
            tags, concepts = wiki_tagger.collect_vocabulary(workspace, inferred)

            self.assertEqual(inferred, external)
            self.assertEqual(tags, ["external-tag"])
            self.assertEqual(concepts, ["External Concept"])


class WikiTaggerTickerIdentityTests(unittest.TestCase):
    """tagger 错码案修根（2026-11-13）：裸 0 开头码被 YAML 1.1 八进制解析
    （010736→4574、002415→1293、000333→219），tagger 重写后错值固化。"""

    def make_entity(
        self,
        root: Path,
        name: str,
        ticker_lines: str,
        *,
        tagging: str | None = None,
        body: str = "sample body",
    ) -> Path:
        entities = root / "wiki" / "entities"
        entities.mkdir(parents=True, exist_ok=True)
        tagging_block = (
            f"tagging:\n  status: {tagging}\n  schema_version: 1\n" if tagging else ""
        )
        page = entities / f"{name}.md"
        page.write_text(
            "---\n"
            f"title: {name}\n"
            "type: entity\n"
            "domain: [investing]\n"
            f"ticker:\n{ticker_lines}"
            "concepts: []\n"
            "related: []\n"
            "entity_salience: {}\n"
            "tags: []\n"
            f"{tagging_block}"
            "---\n\n"
            f"# {name}\n\n{body}\n",
            encoding="utf-8",
        )
        return page

    def test_octal_polluted_ticker_rejected_before_llm_call(self) -> None:
        # 实案复刻：002415.md 裸码 `- 002415` → 解析为 int 1293 → 读侧拒绝，
        # LLM 不被调用、文件不被改写。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_entity(root, "002415", "  - 002415\n")
            before = page.read_text(encoding="utf-8")

            def fail_if_called(*_args, **_kwargs) -> str:
                raise AssertionError("错码卡必须在 LLM 调用前被拒绝")

            with self.assertRaises(wiki_tagger.TaggingError) as ctx:
                wiki_tagger.tag_file(page, root=root, apply=True, chat_func=fail_if_called)

            self.assertIn("002415", str(ctx.exception))
            self.assertEqual(page.read_text(encoding="utf-8"), before)

    def test_write_rejects_generated_ticker_missing_identity(self) -> None:
        # 实案变体：本体 ticker 为空、LLM 返回无关码 → 写侧拒绝、文件不落盘。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_entity(root, "002415", "  []\n")
            before = page.read_text(encoding="utf-8")
            payload = dict(MODEL_OUTPUT, ticker=["1293"], entity_salience={"1293": "mention"})

            with self.assertRaises(wiki_tagger.TaggingError) as ctx:
                wiki_tagger.tag_file(
                    page,
                    root=root,
                    apply=True,
                    chat_func=lambda *_a, **_k: json.dumps(payload, ensure_ascii=False),
                )

            self.assertIn("本体码 002415", str(ctx.exception))
            self.assertEqual(page.read_text(encoding="utf-8"), before)

    def test_completed_card_skips_read_check_but_scan_catches_it(self) -> None:
        # 契约：已完成卡 tagger 静默跳过（backfill 不吵），错码由 scan 暴露。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_entity(
                root, "010736", "  - 010736\n", tagging="completed"
            )  # 裸码 → 解析 4574

            result = wiki_tagger.tag_file(
                page, root=root, apply=True, chat_func=fake_chat
            )
            self.assertEqual(result["status"], "unchanged")

            with redirect_stdout(io.StringIO()) as captured:
                exit_code = wiki_tagger.main(
                    ["--root", str(root), "scan", str(root / "wiki" / "entities")]
                )
            self.assertEqual(exit_code, 1)
            self.assertIn("MISMATCH", captured.getvalue())
            self.assertIn("010736", captured.getvalue())

    def test_scan_exit_zero_when_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_entity(root, "002415", "  - '002415.SZ'\n")
            with redirect_stdout(io.StringIO()) as captured:
                exit_code = wiki_tagger.main(
                    ["--root", str(root), "scan", str(root / "wiki" / "entities")]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("0 个问题", captured.getvalue())

    def test_known_good_ticker_shapes_pass(self) -> None:
        # 全库实卡抽查：A+H 双腿、裸 A 码、跨市场符号码、基金同族份额、H 指数。
        cases = {
            "00883": ["00883.HK", "600938.SH"],
            "002594": ["002594", "1211.HK"],
            "968176": ["968176", "968075"],
            "002545": ["002545"],
            "9988": ["9988.HK", "BABA"],
            "HSTECH": ["HSTECH.HI"],
            "NVDA": ["NVDA"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, tickers in cases.items():
                page = self.make_entity(root, name, "")
                metadata = {"ticker": tickers}
                self.assertEqual(
                    wiki_tagger.ticker_filename_violations(
                        page, metadata, require_identity=True
                    ),
                    [],
                    msg=f"{name} 不应误报",
                )

    def test_wrong_foreign_codes_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = self.make_entity(root, "002415", "")
            self.assertTrue(
                wiki_tagger.ticker_filename_violations(page, {"ticker": ["1293"]})
            )  # 八进制污染实值
            self.assertTrue(
                wiki_tagger.ticker_filename_violations(page, {"ticker": ["4574"]})
            )  # 无关码
            self.assertFalse(
                wiki_tagger.ticker_filename_violations(page, {"ticker": []})
            )  # 读侧不拦空值（待填）
            self.assertTrue(
                wiki_tagger.ticker_filename_violations(page, {"ticker": []}, require_identity=True)
            )  # scan/写侧要求本体码在场

    def test_non_entity_pages_are_exempt(self) -> None:
        # sources/concepts/explorations 卡可合法多 ticker，文件名不构成身份约束。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = root / "wiki" / "sources" / "sample.md"
            page.parent.mkdir(parents=True)
            metadata = {"ticker": ["NVDA", "AMD"]}
            self.assertEqual(
                wiki_tagger.ticker_filename_violations(page, metadata, require_identity=True),
                [],
            )


class PodcastTaggingTests(unittest.TestCase):
    def test_podcast_summary_requests_tags_in_the_same_json_call(self) -> None:
        response = {
            "summary": "Summary",
            "core_views": [],
            "key_data": [],
            "related_tickers": ["NVDA"],
            "related_concepts": ["AI算力"],
            "entity_salience": {"NVDA": "core"},
            "tags": ["供给约束"],
            "predictions": [],
            "h_links": [],
            "speakers": [],
            "key_quotes": [],
        }
        item = {
            "raw_text": "NVDA accelerator supply is constrained.",
            "title": "AI supply",
            "channel": "Test",
            "url": "https://example.com",
            "date": "2026-07-16",
        }
        with patch.object(
            fetch_podcasts, "chat", return_value=json.dumps(response)
        ) as mocked_chat:
            result = fetch_podcasts.summarize_item(
                item,
                {"llm": {"max_tokens": 1000}},
                "zh-CN",
                auto_tag=True,
                tag_vocabulary=(["供给约束"], ["AI算力"]),
            )

        self.assertEqual(result["tags"], ["供给约束"])
        kwargs = mocked_chat.call_args.kwargs
        self.assertTrue(kwargs["json_mode"])
        self.assertEqual(kwargs["max_attempts"], 3)
        self.assertEqual(kwargs["max_tokens"], 8000)
        prompt = mocked_chat.call_args.args[0][1]["content"]
        self.assertIn("entity_salience, tags", prompt)
        self.assertIn("Existing tags", prompt)

    def test_podcast_source_uses_same_validated_schema_without_second_call(self) -> None:
        item = {
            "date": "2026-07-16",
            "channel": "Test Channel",
            "title": "AI supply",
            "url": "https://example.com/episode",
        }
        structured = {
            "summary": "Summary",
            "related_tickers": ["nvda", "not a ticker"],
            "related_concepts": ["AI算力"],
            "entity_salience": {"NVDA": "core"},
            "tags": ["供给约束"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            page = fetch_podcasts.write_source(
                item,
                structured,
                Path(tmp),
                "raw/podcasts/source.md",
                "investing",
                "zh-CN",
                auto_tagged=True,
            )
            metadata = read_frontmatter(page)

        self.assertEqual(metadata["domain"], ["investing"])
        self.assertEqual(metadata["ticker"], ["NVDA"])
        self.assertEqual(metadata["concepts"], ["AI算力"])
        self.assertEqual(metadata["entity_salience"], {"NVDA": "core"})
        self.assertEqual(metadata["tags"], ["供给约束"])
        self.assertEqual(metadata["tagging"]["status"], "completed")


class SharedLLMClientTests(unittest.TestCase):
    def test_real_value_from_later_file_replaces_loaded_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace").mkdir()
            (root / "workspace/workspace-config.md").write_text("# config\n", encoding="utf-8")
            config = root / "config/pod2wiki.env"
            config.parent.mkdir()
            config.write_text("LLM_API_KEY=your_api_key_here\n", encoding="utf-8")
            (root / ".env").write_text("LLM_API_KEY=real-key\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                Path, "cwd", return_value=root
            ):
                llm_client.load_dotenv(config)
                self.assertEqual(llm_client.env_value("LLM_API_KEY"), "real-key")

    def test_json_mode_and_transient_retry(self) -> None:
        class FakeResponse:
            def __init__(self, status_code: int, payload: dict | None = None):
                self.status_code = status_code
                self.text = "temporary 503" if status_code >= 400 else ""
                self._payload = payload or {}

            def json(self) -> dict:
                return self._payload

        responses = [
            FakeResponse(503),
            FakeResponse(200, {"choices": [{"message": {"content": '{"ok": true}'}}]}),
        ]
        requests_seen: list[dict] = []

        class FakeSession:
            trust_env = True

            def post(self, *_args, **kwargs):
                requests_seen.append(kwargs)
                return responses.pop(0)

        resolved = {
            "provider": "deepseek",
            "api_key": "test-key",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
        }
        with (
            patch.object(llm_client, "resolve_provider", return_value=resolved),
            patch.object(llm_client.requests, "Session", FakeSession),
            patch.object(llm_client.time, "sleep") as sleep,
        ):
            output = llm_client.chat(
                [{"role": "user", "content": "JSON"}],
                json_mode=True,
                max_attempts=2,
            )

        self.assertEqual(output, '{"ok": true}')
        self.assertEqual(len(requests_seen), 2)
        self.assertEqual(
            requests_seen[0]["json"]["response_format"], {"type": "json_object"}
        )
        sleep.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
