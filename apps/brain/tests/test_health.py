from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

from kaos_brain.config import Settings
from kaos_brain.health import BrainHealthServer, snapshot


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
    "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL": "http://100.78.124.43:8098",
    "GOVERNOR_API_TOKEN": "token",
}


class BrainHealthTests(unittest.TestCase):
    def test_snapshot_reports_brain_runtime_status_without_secrets(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        bot = SimpleNamespace(is_ready=lambda: True)

        payload = snapshot(settings, bot).payload()

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["discordReady"])
        self.assertEqual(payload["chatModel"], "gemma3:4b")
        self.assertEqual(payload["deepModel"], "qwen3:8b")
        self.assertEqual(payload["imagingProvider"], "ollama")
        self.assertEqual(payload["imagingModel"], "gemma3:4b")
        self.assertEqual(payload["kaosBrainOpenAI"], {"mode": "disabled"})
        self.assertEqual(payload["kaosAI"], {"mode": "disabled"})
        self.assertEqual(payload["governorTools"], {"enabled": True})
        self.assertNotIn("token", str(payload).lower())

    def test_snapshot_reports_kaosai_modes(self) -> None:
        bot = SimpleNamespace(is_ready=lambda: True)

        diagnostic = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSAI_ENABLED": "true",
                "KAOSAI_PROVIDER": "openclaw",
                "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                "KAOSAI_API_TOKEN": "token",
            }
        )
        dry_run = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSAI_ENABLED": "true",
                "KAOSAI_PROVIDER": "openclaw",
                "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                "KAOSAI_API_TOKEN": "token",
                "KAOSAI_DRY_RUN_ENABLED": "true",
            }
        )
        chat = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSAI_ENABLED": "true",
                "KAOSAI_PROVIDER": "openclaw",
                "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                "KAOSAI_API_TOKEN": "token",
                "KAOSAI_CHAT_ENABLED": "true",
            }
        )

        self.assertEqual(snapshot(diagnostic, bot).payload()["kaosBrainOpenAI"], {"mode": "diagnostic"})
        self.assertEqual(snapshot(dry_run, bot).payload()["kaosBrainOpenAI"], {"mode": "dry-run"})
        self.assertEqual(snapshot(chat, bot).payload()["kaosBrainOpenAI"], {"mode": "chat"})
        self.assertEqual(snapshot(chat, bot).payload()["kaosAI"], {"mode": "chat"})


class BrainReauthProxyTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, *, enabled: bool = True) -> Settings:
        env = {
            **BASE_ENV,
            "KAOSBRAIN_AI_TASK_API_TOKEN": "ai-task-token",
            "KAOSAI_REAUTH_ENABLED": "true" if enabled else "false",
            "KAOSAI_REAUTH_BASE_URL": "http://127.0.0.1:18997",
            "KAOSAI_REAUTH_TOKEN": "local-agent-token",
        }
        return Settings.from_env(env)

    async def asyncSetUp(self) -> None:
        self.reauth = SimpleNamespace(start=AsyncMock(), status=AsyncMock())
        self.server = BrainHealthServer(
            self.settings(),
            SimpleNamespace(is_ready=lambda: True),
            reauth_client=self.reauth,
        )
        self.client = TestClient(TestServer(self.server.application()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_internal_reauth_routes_require_ai_task_bearer(self) -> None:
        start = await self.client.post("/internal/openclaw-auth/start")
        status = await self.client.get("/internal/openclaw-auth/status")

        self.assertEqual(start.status, 401)
        self.assertEqual(status.status, 401)
        self.reauth.start.assert_not_awaited()
        self.reauth.status.assert_not_awaited()

    async def test_start_returns_only_allowlisted_device_pairing_fields(self) -> None:
        self.reauth.start.return_value = {
            "status": "waiting_for_device",
            "verificationUrl": "https://auth.openai.com/codex/device",
            "userCode": "ABCD-EFGH",
            "startedAt": 10,
            "completedAt": 0,
            "message": "terminal output must stay on H4",
            "accessToken": "must-not-leak",
        }

        response = await self.client.post(
            "/internal/openclaw-auth/start",
            headers={"Authorization": "Bearer ai-task-token"},
        )

        payload = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(
            set(payload),
            {
                "ok",
                "status",
                "verificationUrl",
                "oauthUrl",
                "userCode",
                "startedAt",
                "completedAt",
            },
        )
        self.assertEqual(payload["userCode"], "ABCD-EFGH")
        self.assertNotIn("terminal output", str(payload))
        self.assertNotIn("must-not-leak", str(payload))

    async def test_status_proxies_safe_terminal_state(self) -> None:
        self.reauth.status.return_value = {
            "status": "succeeded",
            "verificationUrl": "https://auth.openai.com/codex/device",
            "startedAt": 10.5,
            "completedAt": 20.5,
        }

        response = await self.client.get(
            "/internal/openclaw-auth/status",
            headers={"Authorization": "Bearer ai-task-token"},
        )

        payload = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "succeeded")
        self.assertNotIn("userCode", payload)
        self.reauth.status.assert_awaited_once_with()

    async def test_invalid_agent_payload_is_not_forwarded(self) -> None:
        self.reauth.status.return_value = {
            "status": "waiting_for_device",
            "verificationUrl": "https://attacker.example/device",
            "userCode": "ABCD-EFGH",
        }

        response = await self.client.get(
            "/internal/openclaw-auth/status",
            headers={"Authorization": "Bearer ai-task-token"},
        )

        self.assertEqual(response.status, 502)
        self.assertEqual(
            await response.json(),
            {"ok": False, "error": "openclaw_reauth_unavailable"},
        )

    async def test_disabled_reauth_returns_not_configured(self) -> None:
        disabled = BrainHealthServer(
            self.settings(enabled=False),
            SimpleNamespace(is_ready=lambda: True),
        )
        client = TestClient(TestServer(disabled.application()))
        await client.start_server()
        try:
            response = await client.get(
                "/internal/openclaw-auth/status",
                headers={"Authorization": "Bearer ai-task-token"},
            )
            self.assertEqual(response.status, 503)
            self.assertEqual(
                await response.json(),
                {"ok": False, "error": "openclaw_reauth_not_configured"},
            )
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
