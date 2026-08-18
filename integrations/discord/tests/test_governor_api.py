import json
import unittest
from unittest import mock

from kaos_governor_discord.governor_api import GovernorApiClient, GovernorApiConfig, GovernorApiError


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok":true}'):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class GovernorApiClientTests(unittest.TestCase):
    def test_sync_recurring_tasks_uses_governor_api_with_profile_host(self) -> None:
        urlopen = mock.Mock(return_value=FakeResponse(body=b'{"ok":true,"changed":false}'))
        with mock.patch("urllib.request.urlopen", urlopen):
            payload = GovernorApiClient(
                GovernorApiConfig("http://governor-api:8096", "secret", timeout_seconds=7)
            ).sync_recurring_tasks("family")

        request = urlopen.call_args.args[0]
        self.assertEqual(payload["changed"], False)
        self.assertEqual(request.full_url, "http://governor-api:8096/api/recurring-tasks/sync")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b"{}")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.get_header("Host"), "family.kaosgdd.net")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7)

    def test_sync_recurring_tasks_rejects_non_ok_payload(self) -> None:
        urlopen = mock.Mock(return_value=FakeResponse(body=json.dumps({"ok": False, "error": "nope"}).encode()))
        with mock.patch("urllib.request.urlopen", urlopen):
            with self.assertRaisesRegex(GovernorApiError, "nope"):
                GovernorApiClient(GovernorApiConfig("http://governor-api:8096", "secret")).sync_recurring_tasks("main")
