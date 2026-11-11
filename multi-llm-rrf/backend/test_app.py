"""Offline API regressions. Run: python -m unittest discover -s multi-llm-rrf/backend -v"""
import json
import os
import unittest
from unittest.mock import patch

import httpx

# Import the real app without reading local credentials or contacting providers.
with patch.dict(os.environ, {
    "OPENAI_API_KEY": "test-openai", "ANTHROPIC_API_KEY": "test-anthropic",
    "ANTHROPIC_MODEL": "claude-sonnet-5-5",
}), patch("dotenv.load_dotenv"):
    import app


AsyncClient = httpx.AsyncClient


class AskTests(unittest.IsolatedAsyncioTestCase):
    async def ask(self, openai, anthropic, *, query="수도", blocks=None, stop="end_turn", finish="stop"):
        self.requests = {}

        def respond(request):
            provider = "openai" if request.url.host == "api.openai.com" else "anthropic"
            self.requests[provider] = json.loads(request.content)
            answer = openai if provider == "openai" else anthropic
            if answer is None:
                return httpx.Response(503, json={"error": {"message": "unavailable"}})
            text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
            if provider == "openai":
                data = {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]}
            else:
                data = {"content": blocks or [{"type": "text", "text": text}], "stop_reason": stop}
            return httpx.Response(200, json=data)

        transport = httpx.MockTransport(respond)
        with patch.object(app.httpx, "AsyncClient", side_effect=lambda **kw: AsyncClient(transport=transport, **kw)):
            async with AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test") as client:
                return await client.post("/ask", json={"query": query})

    async def test_normal_answers_use_two_ranking_criteria(self):
        response = await self.ask(
            {"answer": "수도", "notes": "ok"},
            {"answer": "다른 긴 응답입니다", "notes": "ok"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"query", "winner", "fused", "all"})
        self.assertEqual(data["winner"]["provider"], "openai")
        self.assertEqual([r["id"] for r in data["fused"]], ["openai", "anthropic"])
        self.assertAlmostEqual(data["fused"][0]["score"], 2 / 61)
        self.assertAlmostEqual(data["fused"][1]["score"], 2 / 62)
        for provider, payload in self.requests.items():
            with self.subTest(provider=provider):
                self.assertNotIn("confidence", payload["messages"][0]["content"])
        self.assertEqual(set(data["winner"]), {"provider", "answer", "notes"})
        for answer in data["all"]:
            self.assertEqual(set(answer), {"provider", "answer", "notes"})

    async def test_failed_provider_never_enters_ranking(self):
        good = {"answer": "서울입니다. 서울은 한국의 정치와 문화의 중심지입니다."}
        for failed in ("openai", "anthropic"):
            with self.subTest(failed=failed):
                response = await self.ask(None if failed == "openai" else good,
                                          None if failed == "anthropic" else good,
                                          query="대한민국의 수도는?")
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertNotEqual(data["winner"]["provider"], failed)
                self.assertEqual(len(data["all"]), 1)
                self.assertEqual(len(data["fused"]), 1)

    async def test_all_failed_returns_error(self):
        response = await self.ask(None, None)
        self.assertEqual(response.status_code, 500)
        self.assertIn("detail", response.json())

    async def test_legacy_confidence_does_not_affect_ranking(self):
        first = await self.ask({"answer": "수도", "confidence": 0},
                               {"answer": "다른 긴 응답입니다", "confidence": 100})
        second = await self.ask({"answer": "수도", "confidence": 100},
                                {"answer": "다른 긴 응답입니다", "confidence": 0})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["winner"]["provider"], "openai")

    async def test_legacy_confidence_is_ignored_and_not_returned(self):
        for value in (0, 100, "90", None, True, "bad", "NaN", "Infinity", -1, 101, [90], {"value": 90}):
            with self.subTest(value=value):
                response = await self.ask({"answer": "수도", "confidence": value}, None)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(set(data["winner"]), {"provider", "answer", "notes"})
                for answer in data["all"]:
                    self.assertNotIn("confidence", answer)

    async def test_model_cannot_override_provider_or_add_fields(self):
        response = await self.ask({"provider": "spoofed", "answer": "수도",
                                   "notes": "ok", "extra": "untrusted"}, None)
        winner = response.json()["winner"]
        self.assertEqual(winner["provider"], "openai")
        self.assertEqual(set(winner), {"provider", "answer", "notes"})

    async def test_invalid_answer_is_not_a_candidate(self):
        for value in ({"answer": " "}, {"answer": 123}, {"answer": None}, [], {"notes": "missing"}, ""):
            with self.subTest(value=value):
                response = await self.ask(value, None)
                self.assertEqual(response.status_code, 500)

    async def test_plain_text_keeps_existing_fallback(self):
        response = await self.ask("서울입니다.", None)
        self.assertEqual(response.json()["winner"], {
            "provider": "openai", "answer": "서울입니다.", "notes": "raw",
        })

    async def test_claude_model_payload_and_text_blocks(self):
        response = await self.ask(None, "unused", blocks=[
            {"type": "thinking", "thinking": "", "signature": "test"},
            {"type": "text", "text": '{"answer":"서울입니다.",'},
            {"type": "text", "text": '"notes":"ok"}'},
        ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["winner"]["answer"], "서울입니다.")
        payload = self.requests["anthropic"]
        self.assertEqual(payload["model"], "claude-sonnet-5-5")
        self.assertEqual(payload["thinking"], {"type": "between_tools"})
        self.assertEqual(payload["max_tokens"], 1024)

    async def test_claude_config_override_does_not_send_model_specific_thinking(self):
        with patch.object(app, "ANTHROPIC_MODEL", "claude-sonnet-4-6", create=True):
            response = await self.ask(None, {"answer": "서울"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.requests["anthropic"]["model"], "claude-sonnet-4-6")
        self.assertNotIn("thinking", self.requests["anthropic"])

    async def test_claude_incomplete_output_is_not_a_candidate(self):
        for stop in ("max_tokens", "refusal", "model_context_window_exceeded"):
            with self.subTest(stop=stop):
                response = await self.ask(None, {"answer": "잘린 답변"}, stop=stop)
                self.assertEqual(response.status_code, 500)

    async def test_openai_incomplete_output_is_not_a_candidate(self):
        for finish in ("length", "content_filter"):
            with self.subTest(finish=finish):
                response = await self.ask('{"answer":"서울', None, finish=finish)
                self.assertEqual(response.status_code, 500)
                response = await self.ask('{"answer":"서울', {"answer": "서울입니다."}, finish=finish)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["winner"]["provider"], "anthropic")
                self.assertEqual(len(response.json()["all"]), 1)

    async def test_whitespace_query_does_not_call_providers(self):
        response = await self.ask(None, None, query="  \n ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.requests, {})


if __name__ == "__main__":
    unittest.main()
