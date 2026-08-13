import json
import unittest
from unittest import mock
import urllib.error

from kaos_governor.calendar import adapter


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok":true}', headers=None):
        self.status = status
        self.body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class CalendarAdapterBoundaryTests(unittest.TestCase):
    def config(self) -> adapter.CalendarAdapterConfig:
        return adapter.CalendarAdapterConfig(base_url="http://adapter:8091", timeout_seconds=7)

    def test_portal_host_keeps_only_known_profiles(self) -> None:
        self.assertEqual(adapter.portal_host({"Host": "family.kaosgdd.net"}), "family.kaosgdd.net")
        self.assertEqual(adapter.portal_host({"Host": "supplies.kaosgdd.net"}), "supplies.kaosgdd.net")
        self.assertEqual(adapter.portal_host({"X-Forwarded-Host": "kaosgdd.net"}), "kaosgdd.net")
        self.assertEqual(adapter.portal_host({"Host": "paperless.kaosgdd.net"}), "kaosgdd.net")

    def test_profile_host_rejects_unknown_profile(self) -> None:
        self.assertEqual(adapter.profile_host("main"), "kaosgdd.net")
        self.assertEqual(adapter.profile_host("family"), "family.kaosgdd.net")
        self.assertEqual(adapter.profile_host("supplies"), "supplies.kaosgdd.net")
        with self.assertRaisesRegex(adapter.CalendarAdapterError, "calendar_adapter_profile_invalid"):
            adapter.profile_host("clinic")

    def test_upstream_url_allows_only_calendar_routes_for_each_method(self) -> None:
        self.assertEqual(
            adapter.upstream_url("http://adapter:8091", "GET", "/api/calendar/bootstrap"),
            "http://adapter:8091/api/calendar/bootstrap",
        )
        self.assertEqual(
            adapter.upstream_url("http://adapter:8091", "GET", "/api/weather/month?city=pohang"),
            "http://adapter:8091/api/weather/month?city=pohang",
        )
        self.assertEqual(
            adapter.upstream_url("http://adapter:8091", "POST", "/api/calendar/tasks"),
            "http://adapter:8091/api/calendar/tasks",
        )
        with self.assertRaisesRegex(adapter.CalendarAdapterError, "calendar_adapter_route_not_allowed"):
            adapter.upstream_url("http://adapter:8091", "GET", "/api/calendar/tasks")
        with self.assertRaisesRegex(adapter.CalendarAdapterError, "calendar_adapter_route_not_allowed"):
            adapter.upstream_url("http://adapter:8091", "POST", "/internal/system/logs")

    def test_request_preserves_write_contract(self) -> None:
        urlopen = mock.Mock(return_value=FakeResponse(status=201, body=b'{"uid":"task-1"}'))
        client = adapter.CalendarAdapterClient(self.config(), urlopen=urlopen)

        status, body = client.request(
            "family",
            "POST",
            "/api/calendar/tasks",
            body=b'{"title":"test"}',
        )

        request = urlopen.call_args.args[0]
        self.assertEqual(status, 201)
        self.assertEqual(body, b'{"uid":"task-1"}')
        self.assertEqual(request.full_url, "http://adapter:8091/api/calendar/tasks")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b'{"title":"test"}')
        self.assertEqual(request.get_header("Host"), "family.kaosgdd.net")
        self.assertEqual(request.get_header("X-forwarded-host"), "family.kaosgdd.net")
        self.assertEqual(request.get_header("User-agent"), "KaosGovernor/calendar-adapter")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7)

    def test_list_tasks_reads_live_bootstrap_tasks(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(
                body=b'{"ok":true,"live":true,"tasks":[{"uid":"task-1"},{"uid":"task-2"}]}',
            )
        )
        client = adapter.CalendarAdapterClient(self.config(), urlopen=urlopen)

        self.assertEqual(client.list_tasks("main"), [{"uid": "task-1"}, {"uid": "task-2"}])

    def test_create_task_requires_uid_in_adapter_response(self) -> None:
        client = adapter.CalendarAdapterClient(self.config(), urlopen=mock.Mock(return_value=FakeResponse(body=b'{"ok":true}')))

        with self.assertRaisesRegex(adapter.CalendarAdapterError, "calendar_adapter_missing_uid"):
            client.create_task("main", {"uid": "task-1"})

    def test_update_and_delete_task_use_existing_adapter_routes(self) -> None:
        urlopen = mock.Mock(
            side_effect=[
                FakeResponse(status=200, body=b'{"ok":true,"uid":"TASK-1","collection":"zin:tasks"}'),
                FakeResponse(status=200, body=b'{"ok":true,"uid":"TASK-1","collection":"zin:tasks"}'),
            ]
        )
        client = adapter.CalendarAdapterClient(self.config(), urlopen=urlopen)

        self.assertEqual(client.update_task("main", {"uid": "TASK-1", "title": "Task"})["uid"], "TASK-1")
        self.assertTrue(client.delete_task("main", "TASK-1", "zin:tasks")["ok"])
        methods = [call.args[0].get_method() for call in urlopen.call_args_list]
        bodies = [json.loads(call.args[0].data.decode("utf-8")) for call in urlopen.call_args_list]
        self.assertEqual(methods, ["PUT", "DELETE"])
        self.assertEqual(bodies[1], {"uid": "TASK-1", "collectionId": "zin:tasks"})

    def test_request_json_raises_adapter_error_body_for_http_error(self) -> None:
        error = urllib.error.HTTPError(
            "http://adapter:8091/api/calendar/tasks",
            409,
            "Conflict",
            {},
            mock.Mock(read=mock.Mock(return_value=b'{"error":"duplicate_uid"}')),
        )
        client = adapter.CalendarAdapterClient(self.config(), urlopen=mock.Mock(side_effect=error))

        with self.assertRaisesRegex(adapter.CalendarAdapterError, "duplicate_uid"):
            client.request_json("main", "POST", "/api/calendar/tasks", payload={"uid": "task-1"})

    def test_health_reports_ok_and_masks_connection_errors(self) -> None:
        ok_client = adapter.CalendarAdapterClient(
            self.config(),
            urlopen=mock.Mock(return_value=FakeResponse(body=b'{"ok":true,"profile":"main","configured":true}')),
        )
        failed_client = adapter.CalendarAdapterClient(
            self.config(),
            urlopen=mock.Mock(side_effect=urllib.error.URLError("refused")),
        )

        self.assertTrue(ok_client.health("main")["ok"])
        failed = failed_client.health("main")
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"], "URLError")


if __name__ == "__main__":
    unittest.main()
