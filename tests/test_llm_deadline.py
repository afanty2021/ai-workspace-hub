"""LLM 调用总时长守卫与 tagger 外层重试收紧的回归测试（2026-11-20 修根+r3 补刀）。

背景：wiki_tagger 经 llm_client.chat 调用 GLM API 出现 8 分钟挂死——
requests 的 read timeout 只约束相邻字节间隔，trickle 响应可无限存活；
tagger.request_tags 外层 range(2) × 内层 max_attempts=3 × 120s 构成 ~12
分钟放大器。修根三处：chat() 加 max_total_seconds 硬 deadline；外层
except 收紧为网络层 LLMError 直接上抛（内层已重试，外层只放大挂死窗口）；
r3 复查补两刀——deadline 检查下沉到读循环（_drain 封顶 trickle）+
网络层/校验层拆 try（形状校验 LLMError 不再被连带吞掉、保留外层重试）。

变异区分度（2026-11-20 实测）：删除 chat() 的 deadline 检查分支 →
DeadlineTests::test_deadline_stops_retry_loop 红；删除 _drain 读循环
deadline 检查 → DeadlineTests::test_trickle_body_aborted_by_deadline 红；
恢复 request_tags 外层「LLMError 吞掉重试」形态 →
OuterRetryTests::test_llm_error_not_retried_outer 红；恢复合并 try（形状
校验 LLMError 归网络层上抛）→ OuterRetryTests::test_shape_error_still_retried_outer 红。
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import _test_paths  # noqa: F401

import requests

from llm_client import LLMError, chat  # noqa: E402
from system.lib import llm_client
from system.scripts import wiki_tagger

ENV = {
    "LLM_API_KEY": "test-key",
    "LLM_PROVIDER": "openai",
    "LLM_BASE_URL": "https://example.invalid/v1",
    "LLM_MODEL": "test-model",
}


def _ok_response() -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.iter_content.return_value = iter(
        [b'{"choices": [{"message": {"content": "ok"}}]}']
    )
    response.__enter__.return_value = response  # chat() 以 with 读 stream 响应
    return response


class DeadlineTests(unittest.TestCase):
    """chat() 的 max_total_seconds 必须封顶全部尝试与 backoff 的总时长。"""

    def test_deadline_stops_retry_loop(self) -> None:
        """慢速 transient 失败在 deadline 耗尽时停止重试并抛错。"""

        def slow_transient(*_args, **_kwargs):
            time.sleep(0.2)
            raise requests.ConnectionError("connection stalled by server")

        with patch.dict("os.environ", ENV, clear=True), patch.object(
            llm_client.requests, "Session"
        ) as session_cls:
            session_cls.return_value.post.side_effect = slow_transient
            started = time.monotonic()
            with self.assertRaises(LLMError) as ctx:
                chat(
                    [{"role": "user", "content": "hi"}],
                    timeout=10,
                    max_attempts=5,
                    max_total_seconds=0.3,
                )
            elapsed = time.monotonic() - started
        self.assertIn("deadline", str(ctx.exception))
        self.assertLess(elapsed, 2.0, "deadline 必须真正封顶总时长")
        self.assertLessEqual(
            session_cls.return_value.post.call_count, 2,
            "deadline 耗尽后不得继续第 3 次尝试",
        )

    def test_timeout_capped_by_remaining(self) -> None:
        """单次请求 timeout 取 min(timeout, 剩余 deadline)。"""
        captured: dict[str, float] = {}

        def capture(*_args, **kwargs):
            captured["timeout"] = kwargs["timeout"]
            return _ok_response()

        with patch.dict("os.environ", ENV, clear=True), patch.object(
            llm_client.requests, "Session"
        ) as session_cls:
            session_cls.return_value.post.side_effect = capture
            chat(
                [{"role": "user", "content": "hi"}],
                timeout=120,
                max_attempts=1,
                max_total_seconds=5,
            )
        self.assertLess(
            captured["timeout"], 120,
            "剩余 deadline 不足 timeout 时必须收窄单次 timeout",
        )
        self.assertGreater(captured["timeout"], 0)

    def test_slow_success_within_deadline_passes(self) -> None:
        """deadline 不误伤窗内完成的慢响应。"""

        def slow_ok(*_args, **_kwargs):
            time.sleep(0.1)
            return _ok_response()

        with patch.dict("os.environ", ENV, clear=True), patch.object(
            llm_client.requests, "Session"
        ) as session_cls:
            session_cls.return_value.post.side_effect = slow_ok
            result = chat(
                [{"role": "user", "content": "hi"}],
                max_total_seconds=5,
            )
        self.assertEqual(result, "ok")

    def test_trickle_body_aborted_by_deadline(self) -> None:
        """滴流响应（字节间隔小于 read timeout）在读循环内被 deadline 封顶。

        post 本身立刻返回，字节在 iter_content 里以小于 read timeout 的
        间隔滴出——单靠 read timeout 杀不掉（每滴一次重置计时），必须由
        _drain 的字节边界 deadline 检查中断（r3 修根第二刀）。
        """
        response = MagicMock()
        response.status_code = 200
        response.__enter__.return_value = response  # chat() 以 with 读 stream 响应

        def trickle(_chunk_size=None):
            yield b'{"choices": '
            time.sleep(0.4)  # 间隔 < timeout=10，read timeout 永不触发
            yield b'[{"message": {"content": "ok"}}]}'

        response.iter_content.return_value = trickle()

        with patch.dict("os.environ", ENV, clear=True), patch.object(
            llm_client.requests, "Session"
        ) as session_cls:
            session_cls.return_value.post.return_value = response
            started = time.monotonic()
            with self.assertRaises(LLMError) as ctx:
                chat(
                    [{"role": "user", "content": "hi"}],
                    timeout=10,
                    max_attempts=1,
                    max_total_seconds=0.3,
                )
            elapsed = time.monotonic() - started
        self.assertIn("trickling", str(ctx.exception))
        self.assertLess(elapsed, 2.0, "滴流不得拖到第二个 read timeout")


class OuterRetryTests(unittest.TestCase):
    """request_tags 外层重试只服务校验失败，LLMError 直接上抛。"""

    def test_llm_error_not_retried_outer(self) -> None:
        calls = []

        def failing_chat(*_args, **_kwargs):
            calls.append(1)
            raise LLMError("LLM request failed: total deadline 300s exceeded")

        with self.assertRaises(LLMError):
            wiki_tagger.request_tags(
                [{"role": "user", "content": "hi"}],
                provider=None,
                model=None,
                chat_func=failing_chat,
            )
        self.assertEqual(
            len(calls), 1,
            "LLMError 内层已重试，外层再试只会放大挂死窗口（11-20 修根）",
        )

    def test_validation_error_still_retried_outer(self) -> None:
        calls = []

        def bad_json_chat(*_args, **_kwargs):
            calls.append(1)
            return "not-json-at-all"

        with self.assertRaises(wiki_tagger.TaggingError):
            wiki_tagger.request_tags(
                [{"role": "user", "content": "hi"}],
                provider=None,
                model=None,
                chat_func=bad_json_chat,
            )
        self.assertEqual(
            len(calls), 2, "JSON 解析失败仍走外层重试（原语义保留）"
        )

    def test_shape_error_still_retried_outer(self) -> None:
        """合法 JSON 非对象（extract_json 形状校验 LLMError）保留外层重试。

        r3 修复：合并 try 时 _ensure_json_object 的 LLMError 被网络层
        「直接上抛」连带吞掉、整个文件提前终止——校验层失败换一次采样
        可能自愈，与网络层失败不同族。
        """
        calls = []

        def list_chat(*_args, **_kwargs):
            calls.append(1)
            return "[1, 2]"

        with self.assertRaises(wiki_tagger.TaggingError):
            wiki_tagger.request_tags(
                [{"role": "user", "content": "hi"}],
                provider=None,
                model=None,
                chat_func=list_chat,
            )
        self.assertEqual(
            len(calls), 2, "形状校验失败须重试（换采样可能得到对象）"
        )


if __name__ == "__main__":
    unittest.main()
