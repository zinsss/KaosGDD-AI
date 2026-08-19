from pathlib import Path
import tempfile
import unittest

from kaos_brain.openclaw_reauth_agent import ReauthConfig, redact_auth_text


class OpenClawReauthAgentTests(unittest.TestCase):
    def test_redacts_callback_urls_and_authorization_codes(self) -> None:
        text = (
            "paste http://localhost:1455/auth/callback?code=ac_secret.token&state=abc "
            "or ac_another-secret.value"
        )

        redacted = redact_auth_text(text)

        self.assertNotIn("ac_secret", redacted)
        self.assertNotIn("ac_another", redacted)
        self.assertIn("callback?[redacted]", redacted)

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
