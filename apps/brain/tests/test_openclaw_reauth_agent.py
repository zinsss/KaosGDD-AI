import asyncio
import json
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from kaos_brain.openclaw_reauth_agent import (
    OpenClawReauthAgent,
    ReauthConfig,
    create_app,
    parse_device_pairing,
    redact_auth_text,
)


class OpenClawReauthAgentTests(unittest.TestCase):
    def test_redacts_callback_urls_and_authorization_codes(self) -> None:
        text = (
            "paste http://localhost:1455/auth/callback?code=ac_secret.token&state=abc "
            "or ac_another-secret.value Code: ABCD-EFGH "
            "Bearer bearer-secret-value access_token=oauth-secret-value"
        )

        redacted = redact_auth_text(text)

        self.assertNotIn("ac_secret", redacted)
        self.assertNotIn("ac_another", redacted)
        self.assertNotIn("ABCD-EFGH", redacted)
        self.assertNotIn("bearer-secret-value", redacted)
        self.assertNotIn("oauth-secret-value", redacted)
        self.assertIn("callback?[redacted]", redacted)

    def test_parses_ansi_decorated_device_pairing_output(self) -> None:
        output = (
            "\x1b[36mOpenAI Codex device code\x1b[0m\n"
            "URL: https://auth.openai.com/codex/device\n"
            "\x1b[2mCode:\x1b[0m ABCD-EFGH\n"
        )

        verification_url, user_code = parse_device_pairing(output)

        self.assertEqual(verification_url, "https://auth.openai.com/codex/device")
        self.assertEqual(user_code, "ABCD-EFGH")

    def test_agent_uses_explicit_device_code_method(self) -> None:
        agent = OpenClawReauthAgent(ReauthConfig(token="secret-token"))

        command = agent._shell_command()

        self.assertIn("--provider openai --method device-code --force", command)

    def test_start_failure_closes_terminal_and_returns_only_fixed_error(self) -> None:
        agent = OpenClawReauthAgent(ReauthConfig(token="secret-token"))
        master_fd, slave_fd = pty.openpty()

        with (
            patch("kaos_brain.openclaw_reauth_agent.pty.openpty", return_value=(master_fd, slave_fd)),
            patch(
                "kaos_brain.openclaw_reauth_agent.subprocess.Popen",
                side_effect=OSError("sensitive process detail"),
            ),
        ):
            payload = agent.start()

        self.assertEqual(payload["status"], "failed")
        self.assertNotIn("sensitive process detail", str(payload))
        self.assertIsNone(agent.state.process)
        self.assertIsNone(agent.state.master_fd)
        self.assertEqual(agent.state.user_code, "")
        self.assertTrue(agent.state.verification_event.is_set())
        for fd in (master_fd, slave_fd):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_reader_cleans_up_after_gateway_restart_timeout_or_oserror(self) -> None:
        for failure in (
            subprocess.TimeoutExpired(["systemctl"], 30),
            OSError("sensitive restart detail"),
        ):
            with self.subTest(failure=type(failure).__name__):
                agent = OpenClawReauthAgent(ReauthConfig(token="secret-token"))
                master_fd, writer_fd = os.pipe()
                os.close(writer_fd)
                process = Mock()
                process.wait.return_value = 0
                process.poll.return_value = 0
                agent.state.status = "waiting_for_device"
                agent.state.master_fd = master_fd
                agent.state.process = process
                agent.state.user_code = "ABCD-EFGH"

                with patch("kaos_brain.openclaw_reauth_agent.subprocess.run", side_effect=failure):
                    agent._reader()

                payload = agent.payload()
                self.assertEqual(payload["status"], "failed")
                self.assertNotIn("sensitive restart detail", str(payload))
                self.assertIsNone(agent.state.process)
                self.assertIsNone(agent.state.master_fd)
                self.assertEqual(agent.state.user_code, "")
                self.assertTrue(agent.state.verification_event.is_set())
                with self.assertRaises(OSError):
                    os.fstat(master_fd)

    def test_reader_terminates_hung_login_and_clears_pairing_code(self) -> None:
        agent = OpenClawReauthAgent(ReauthConfig(token="secret-token"))
        master_fd, writer_fd = os.pipe()
        os.close(writer_fd)
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = (
            subprocess.TimeoutExpired(["openclaw"], 5),
            subprocess.TimeoutExpired(["openclaw"], 2),
            0,
        )
        agent.state.status = "waiting_for_device"
        agent.state.master_fd = master_fd
        agent.state.process = process
        agent.state.user_code = "ABCD-EFGH"

        with patch("kaos_brain.openclaw_reauth_agent.subprocess.run") as restart:
            agent._reader()

        self.assertEqual(agent.state.status, "failed")
        self.assertIsNone(agent.state.process)
        self.assertIsNone(agent.state.master_fd)
        self.assertEqual(agent.state.user_code, "")
        self.assertTrue(agent.state.verification_event.is_set())
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        restart.assert_not_called()

    def test_public_payload_never_exposes_device_code(self) -> None:
        agent = OpenClawReauthAgent(ReauthConfig(token="secret-token"))
        agent.state.status = "waiting_for_device"
        agent.state.verification_url = "https://auth.openai.com/codex/device"
        agent.state.user_code = "ABCD-EFGH"

        private_payload = agent.payload()
        public_payload = agent.payload(include_user_code=False)

        self.assertEqual(private_payload["userCode"], "ABCD-EFGH")
        self.assertNotIn("userCode", public_payload)
        self.assertNotIn("secret-token", str(private_payload))
        self.assertNotIn("secret-token", str(public_payload))

    def test_public_health_exposes_no_reauth_state(self) -> None:
        app = create_app(ReauthConfig(token="secret-token"))
        route = next(
            route
            for route in app.router.routes()
            if route.method == "GET" and route.resource.canonical == "/health"
        )

        async def request_health() -> dict[str, object]:
            response = await route.handler(make_mocked_request("GET", "/health", app=app))
            return json.loads(response.text)

        self.assertEqual(asyncio.run(request_health()), {"status": "ok"})

    def test_legacy_callback_route_rejects_device_code_flow(self) -> None:
        agent = OpenClawReauthAgent(ReauthConfig(token="secret-token"))
        agent.state.status = "waiting_for_device"

        with self.assertRaises(web.HTTPConflict) as context:
            agent.submit_callback("http://localhost:1455/auth/callback?code=ac_old")

        self.assertEqual(context.exception.text, "reauth_uses_device_code")

    def test_config_reads_token_from_file_without_exposing_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token"
            token_file.write_text("secret-token\n", encoding="utf-8")

            config = ReauthConfig.from_env({"KAOSAI_REAUTH_TOKEN_FILE": str(token_file)})

        self.assertEqual(config.token, "secret-token")
        self.assertEqual(config.bind_host, "127.0.0.1")
        self.assertEqual(config.port, 18997)


if __name__ == "__main__":
    unittest.main()
