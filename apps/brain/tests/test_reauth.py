import unittest

from kaos_brain.reauth import ReauthError, normalize_reauth_payload


class ReauthPayloadTests(unittest.TestCase):
    def test_normalizes_device_pairing_without_forwarding_agent_output(self) -> None:
        payload = normalize_reauth_payload(
            {
                "status": "waiting_for_device",
                "verificationUrl": "https://auth.openai.com/codex/device",
                "userCode": "abcd-efgh",
                "startedAt": 100,
                "completedAt": 0,
                "message": "Code: ABCD-EFGH",
                "refreshToken": "secret",
            }
        )

        self.assertEqual(
            payload,
            {
                "status": "waiting_for_device",
                "verificationUrl": "https://auth.openai.com/codex/device",
                "oauthUrl": "https://auth.openai.com/codex/device",
                "userCode": "ABCD-EFGH",
                "startedAt": 100.0,
                "completedAt": 0.0,
            },
        )
        self.assertNotIn("secret", str(payload))

    def test_retains_legacy_oauth_url_alias_during_transition(self) -> None:
        payload = normalize_reauth_payload(
            {
                "status": "waiting_for_callback",
                "oauthUrl": "https://auth.openai.com/oauth/authorize?client_id=test",
                "startedAt": 100,
                "completedAt": 0,
            }
        )

        self.assertEqual(payload["verificationUrl"], payload["oauthUrl"])

    def test_rejects_non_openai_urls_and_incomplete_device_pairing(self) -> None:
        with self.assertRaisesRegex(ReauthError, "verification_url_invalid"):
            normalize_reauth_payload(
                {
                    "status": "waiting_for_device",
                    "verificationUrl": "https://attacker.example/codex/device",
                    "userCode": "ABCD-EFGH",
                }
            )
        with self.assertRaisesRegex(ReauthError, "device_pairing_incomplete"):
            normalize_reauth_payload(
                {
                    "status": "waiting_for_device",
                    "verificationUrl": "https://auth.openai.com/codex/device",
                }
            )

    def test_rejects_invalid_status_code_and_timestamps(self) -> None:
        with self.assertRaisesRegex(ReauthError, "status_invalid"):
            normalize_reauth_payload({"status": "debug", "startedAt": 0, "completedAt": 0})
        with self.assertRaisesRegex(ReauthError, "user_code_invalid"):
            normalize_reauth_payload(
                {
                    "status": "waiting_for_device",
                    "verificationUrl": "https://auth.openai.com/codex/device",
                    "userCode": "../../bad",
                }
            )
        with self.assertRaisesRegex(ReauthError, "started_at_invalid"):
            normalize_reauth_payload(
                {"status": "idle", "startedAt": float("nan"), "completedAt": 0}
            )


if __name__ == "__main__":
    unittest.main()
