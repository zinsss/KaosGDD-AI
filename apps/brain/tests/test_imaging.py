from __future__ import annotations

import base64
import unittest

from aiohttp.test_utils import TestClient, TestServer
from kaos_brain.config import Settings
from kaos_brain.imaging import BrainImagingServer, validate_second_look_request


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSBRAIN_IMAGING_ENABLED": "true",
    "KAOSBRAIN_IMAGING_API_TOKEN": "imaging-token",
}


class FakeOllama:
    def __init__(self) -> None:
        self.requests = []

    async def second_look(self, request):
        self.requests.append(request)
        return {
            "summary": "검토 완료",
            "checklist": ["폐야 확인"],
            "cautions": ["최종 판단은 진료자가 합니다."],
            "recommendation": "임상 소견과 대조",
            "disclaimer": "AI 보조 검토입니다. 최종 판단은 진료자가 합니다.",
            "model": "qwen3:8b",
        }


def second_look_payload(*, stored: bool = False) -> dict:
    return {
        "source": "kaosaio",
        "requestId": "kaosaio-second-look-1",
        "modality": "DX",
        "bodyPart": "CHEST",
        "viewPosition": "PA",
        "aiDomain": "cxr",
        "images": [{"format": "png", "contentBase64": base64.b64encode(b"png").decode("ascii")}],
        "question": "눈에 띄는 이상 소견이나 놓치기 쉬운 포인트를 체크해주세요.",
        "safety": {
            "temporary": True,
            "storedInAioReports": stored,
            "dicomMetadataSent": False,
            "orthancReadOnly": True,
            "dicomModified": False,
            "pacsFinalReport": False,
            "renderedPreview": True,
        },
    }


class BrainImagingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = BrainImagingServer(Settings.from_env(BASE_ENV))
        self.ollama = FakeOllama()
        self.server.ollama = self.ollama  # type: ignore[assignment]
        self.client = TestClient(TestServer(self._app()))
        await self.client.start_server()

    def _app(self):
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/imaging/second-look", self.server.second_look)
        return app

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_second_look_requires_bearer_token(self) -> None:
        response = await self.client.post("/imaging/second-look", json=second_look_payload())

        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "kaosbrain_imaging_unauthorized")

    async def test_second_look_returns_ollama_result(self) -> None:
        response = await self.client.post(
            "/imaging/second-look",
            headers={"Authorization": "Bearer imaging-token"},
            json=second_look_payload(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["summary"], "검토 완료")
        self.assertEqual(payload["result"]["model"], "qwen3:8b")
        self.assertEqual(len(self.ollama.requests), 1)

    async def test_second_look_rejects_non_temporary_safety(self) -> None:
        response = await self.client.post(
            "/imaging/second-look",
            headers={"Authorization": "Bearer imaging-token"},
            json=second_look_payload(stored=True),
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "imaging_second_look_safety_rejected")


class BrainImagingValidationTests(unittest.TestCase):
    def test_validate_accepts_expected_payload(self) -> None:
        self.assertEqual(validate_second_look_request(second_look_payload()), "")


if __name__ == "__main__":
    unittest.main()
