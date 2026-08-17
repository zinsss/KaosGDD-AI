from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import socket
import tempfile
import unittest

from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.system_status import (
    EMBED_COLOR_DOWN,
    EMBED_COLOR_HEALTHY,
    EMBED_COLOR_UNKNOWN,
    DEFAULT_HTTP_PROBES,
    DiscordServiceStatusSurface,
    SERVICES,
    ServiceProbeResult,
    ServiceStatusView,
    check_service,
    default_http_probe,
    check_tcp,
    render_service_embed,
    render_service_message,
    restart_service_sync,
)


class FakeMessage:
    def __init__(self, message_id, *, content="", embed=None, view=None):
        self.id = message_id
        self.content = content
        self.embeds = [embed] if embed is not None else []
        self.view = view
        self.edits = []
        self.deleted = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        self.content = kwargs.get("content", self.content)
        if "embed" in kwargs:
            self.embeds = [kwargs["embed"]] if kwargs["embed"] is not None else []
        self.view = kwargs.get("view", self.view)
        return self

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.messages = {}
        self.next_id = 700

    async def send(self, **kwargs):
        message = FakeMessage(self.next_id, content=kwargs.get("content", ""), embed=kwargs.get("embed"), view=kwargs.get("view"))
        self.next_id += 1
        self.sent.append(kwargs)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


class FakeBot:
    def __init__(self, channel):
        self.channel = channel
        self.user = SimpleNamespace(id=900)

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        return self.channel


class DiscordServiceStatusTests(unittest.IsolatedAsyncioTestCase):
    def make_surface(self, path: Path, channel: FakeChannel | None = None) -> DiscordServiceStatusSurface:
        channel = channel or FakeChannel()
        surface = DiscordServiceStatusSurface(
            FakeBot(channel),  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            state_path=path,
            environment={"SERVICE_STATUS_DEFAULT_PROBES_ENABLED": "false"},
        )
        surface.message_refresh_delay_seconds = 0
        return surface

    def test_service_rows_match_requested_buttons(self) -> None:
        labels = [item.label for item in SERVICES]

        self.assertEqual(
            labels,
            [
                "KaosBrain",
                "KaosGovernor",
                "KaosPACS",
                "KaosInj",
                "Radicale",
                "Memos",
                "Paperless",
                "StirlingPDF",
                "Vaultwarden",
                "Rustdesk",
            ],
        )
        self.assertEqual(SERVICES[0].description, "Brain of KaosGDD on Odroid H4 Ultra")
        self.assertEqual(SERVICES[1].description, "Rules and controller of KaosGDD")

    async def test_ensure_message_creates_one_status_message_per_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 10)
            self.assertEqual(channel.sent[0]["content"], "")
            self.assertEqual(channel.sent[0]["embed"].title, "KaosBrain")
            self.assertIn("Unknown", channel.sent[0]["embed"].description)
            self.assertIsNone(channel.sent[0]["view"])
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["messageIds"]["kaosbrain"], 700)
            self.assertEqual(state["messageIds"]["rustdesk"], 709)

    async def test_ensure_message_edits_existing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            message = FakeMessage(777)
            channel.messages[777] = message
            path = Path(temporary) / "status.json"
            path.write_text('{"messageIds": {"kaosbrain": 777}}', encoding="utf-8")
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 9)
            self.assertEqual(len(message.edits), 1)
            self.assertEqual(message.edits[0]["content"], "")
            self.assertEqual(message.edits[0]["embed"].title, "KaosBrain")
            self.assertIn("Unknown", message.edits[0]["embed"].description)

    async def test_ensure_message_skips_unchanged_existing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path, channel)
            await surface.ensure_message()

            messages = list(channel.messages.values())
            await surface.ensure_message()

            self.assertEqual(channel.next_id, 710)
            self.assertTrue(all(not message.edits for message in messages))

    async def test_ensure_message_deletes_legacy_combined_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            legacy = FakeMessage(777)
            channel.messages[777] = legacy
            path = Path(temporary) / "status.json"
            path.write_text('{"messageId": 777}', encoding="utf-8")
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertTrue(legacy.deleted)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("messageId", state)
            self.assertEqual(len(state["messageIds"]), 10)

    async def test_restart_request_is_recorded_for_future_down_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path)

            await surface.request_restart("memos")
            await surface.request_restart("memos")

            self.assertEqual(surface.status()["restartRequests"], {"memos": 2})
            self.assertEqual(surface.status()["restartResults"], {"memos": "not_allowed"})

    def test_restart_service_requires_allowlist(self) -> None:
        result = restart_service_sync(
            "memos",
            {"SERVICE_STATUS_MEMOS_RESTART_COMMAND": "/bin/true"},
        )

        self.assertEqual(result.state, "not_allowed")

    def test_restart_service_requires_configured_command(self) -> None:
        result = restart_service_sync(
            "memos",
            {"SERVICE_STATUS_RESTART_ALLOWED_KEYS": "memos"},
        )

        self.assertEqual(result.state, "not_configured")

    def test_restart_service_executes_allowlisted_command(self) -> None:
        result = restart_service_sync(
            "memos",
            {
                "SERVICE_STATUS_RESTART_ALLOWED_KEYS": "memos",
                "SERVICE_STATUS_MEMOS_RESTART_COMMAND": "/bin/true",
            },
        )

        self.assertEqual(result.state, "executed")

    def test_restart_service_records_command_failure(self) -> None:
        result = restart_service_sync(
            "memos",
            {
                "SERVICE_STATUS_RESTART_ALLOWED_KEYS": "memos",
                "SERVICE_STATUS_MEMOS_RESTART_COMMAND": "/bin/false",
            },
        )

        self.assertEqual(result.state, "failed")

    def test_render_service_message_includes_health_state(self) -> None:
        content = render_service_message(
            SERVICES[1],
            ServiceProbeResult("kaosgovernor", "healthy", "09:15:00", "HTTP 200"),
        )
        embed = render_service_embed(
            SERVICES[1],
            ServiceProbeResult("kaosgovernor", "healthy", "09:15:00", "HTTP 200"),
        )

        self.assertEqual(content, "")
        self.assertEqual(embed.title, "KaosGovernor")
        self.assertIn("Healthy", embed.description)
        self.assertNotIn("09:15:00", embed.description)
        self.assertIn("HTTP 200", embed.description)
        self.assertEqual(embed.color.value, EMBED_COLOR_HEALTHY)

    def test_service_embed_colors_match_state(self) -> None:
        self.assertEqual(
            render_service_embed(SERVICES[1], ServiceProbeResult("kaosgovernor", "healthy", "", "")).color.value,
            EMBED_COLOR_HEALTHY,
        )
        self.assertEqual(
            render_service_embed(SERVICES[1], ServiceProbeResult("kaosgovernor", "down", "", "")).color.value,
            EMBED_COLOR_DOWN,
        )
        self.assertEqual(
            render_service_embed(SERVICES[1], ServiceProbeResult("kaosgovernor", "unknown", "", "")).color.value,
            EMBED_COLOR_UNKNOWN,
        )

    def test_service_view_only_contains_restart_button(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "status.json")
            view = ServiceStatusView(
                surface,
                SERVICES[1],
                ServiceProbeResult("kaosgovernor", "down", "09:15:00", "Connection refused"),
            )

            self.assertEqual(len(view.children), 1)
            self.assertEqual(view.children[0].label, "Restart")

    def test_unconfigured_service_is_unknown(self) -> None:
        result = check_service(
            SERVICES[0],
            {"SERVICE_STATUS_DEFAULT_PROBES_ENABLED": "false"},
            0.5,
        )

        self.assertEqual(result.state, "unknown")
        self.assertIn("No health probe", result.detail)

    def test_default_probes_cover_local_backend_services(self) -> None:
        self.assertEqual(DEFAULT_HTTP_PROBES["radicale"], "http://radicale:5232/")
        self.assertEqual(DEFAULT_HTTP_PROBES["memos"], "http://memos:5230/")
        self.assertEqual(DEFAULT_HTTP_PROBES["vaultwarden"], "http://vaultwarden/alive")
        self.assertEqual(DEFAULT_HTTP_PROBES["stirlingpdf"], "http://stirlingpdf:8080/")
        self.assertEqual(
            default_http_probe({"PAPERLESS_BASE_URL": "http://paperless:8000"}, "paperless"),
            "http://paperless:8000",
        )

    def test_tcp_probe_reports_healthy_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            host, port = server.getsockname()

            state, detail = check_tcp(f"{host}:{port}", 0.5)

        self.assertEqual(state, "healthy")
        self.assertIn(str(port), detail)


if __name__ == "__main__":
    unittest.main()
