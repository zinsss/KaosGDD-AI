from __future__ import annotations

import unittest
from importlib.util import find_spec

from kaos_brain.config import Settings

AIOHTTP_AVAILABLE = find_spec("aiohttp") is not None

if AIOHTTP_AVAILABLE:
    from aiohttp.test_utils import TestClient, TestServer
    from kaos_brain.document_tags import BrainDocumentTagServer, _filter_existing_tags, validate_document_tag_request


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSBRAIN_DOCUMENT_TAG_API_TOKEN": "document-tag-token",
}


def tag_payload() -> dict:
    return {
        "document": {
            "id": 7,
            "title": "Clinic report",
            "filename": "clinic.pdf",
            "contentExcerpt": "hospital visit receipt and 보험 note",
            "currentTags": ["clinic"],
        },
        "availableTags": [
            {"id": 1, "name": "clinic"},
            {"id": 2, "name": "receipt"},
            {"id": 3, "name": "보험"},
        ],
    }


class FakeKaosAI:
    def __init__(self) -> None:
        self.requests = []

    async def suggest_document_tags(self, request):
        self.requests.append(request)
        return ("Receipt", "made-up", "보험", "receipt")


@unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for BrainDocumentTagServer tests")
class BrainDocumentTagTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = BrainDocumentTagServer(
            Settings.from_env(
                {
                    **BASE_ENV,
                    "KAOSAI_ENABLED": "true",
                    "KAOSAI_PROVIDER": "openclaw",
                    "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                    "KAOSAI_API_TOKEN": "gateway-token",
                }
            )
        )
        self.kaosai = FakeKaosAI()
        self.server.kaosai = self.kaosai  # type: ignore[assignment]
        self.client = TestClient(TestServer(self._app()))
        await self.client.start_server()

    def _app(self):
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/internal/documents/tag-suggestions/preview", self.server.suggest)
        return app

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_suggest_requires_bearer_token(self) -> None:
        response = await self.client.post("/internal/documents/tag-suggestions/preview", json=tag_payload())

        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "kaosbrain_document_tag_unauthorized")

    async def test_suggest_returns_only_existing_tags_without_writing(self) -> None:
        response = await self.client.post(
            "/internal/documents/tag-suggestions/preview",
            headers={"Authorization": "Bearer document-tag-token"},
            json=tag_payload(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "ai")
        self.assertEqual(payload["tags"], ["receipt", "보험"])
        self.assertEqual(self.kaosai.requests[0]["document"]["title"], "Clinic report")

    async def test_suggest_reports_disabled_openai(self) -> None:
        disabled = BrainDocumentTagServer(Settings.from_env(BASE_ENV))
        client = TestClient(TestServer(self._app_for(disabled)))
        await client.start_server()
        try:
            response = await client.post(
                "/internal/documents/tag-suggestions/preview",
                headers={"Authorization": "Bearer document-tag-token"},
                json=tag_payload(),
            )

            self.assertEqual(response.status, 503)
            self.assertEqual((await response.json())["error"], "kaosbrain_openai_disabled")
        finally:
            await client.close()

    def _app_for(self, server):
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/internal/documents/tag-suggestions/preview", server.suggest)
        return app


@unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for document tag validation tests")
class BrainDocumentTagValidationTests(unittest.TestCase):
    def test_validate_accepts_expected_payload(self) -> None:
        self.assertEqual(validate_document_tag_request(tag_payload()), "")

    def test_validate_requires_context(self) -> None:
        payload = tag_payload()
        payload["document"] = {"id": 7}

        self.assertEqual(validate_document_tag_request(payload), "document_tag_context_required")

    def test_filter_existing_tags_matches_case_insensitively(self) -> None:
        self.assertEqual(_filter_existing_tags(tag_payload(), ("Clinic", "new", "보험")), ["clinic", "보험"])


if __name__ == "__main__":
    unittest.main()
