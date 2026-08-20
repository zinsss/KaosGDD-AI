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
    ServiceRestartConfirmView,
    ServiceStatusView,
    brain_health_detail,
    check_service,
    check_tcp,
    default_http_probe,
    render_service_embed,
    render_service_message,
    render_summary_embed,
    restart_service_sync,
    service_status_secret,
    second_look_health_detail,
    second_look_health_url,
    second_look_status_detail,
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
        self.registered_views = []

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        return self.channel

    def add_view(self, view, *, message_id=None):
        self.registered_views.append((view, message_id))


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
                "KaosAI Second-Look",
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
        self.assertEqual(SERVICES[1].description, "Temporary AIO image second-look provider path")
        self.assertEqual(SERVICES[2].description, "Rules and controller of KaosGDD")

    async def test_ensure_message_creates_one_status_message_per_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 11)
            self.assertEqual(channel.sent[0]["content"], "")
            self.assertEqual(channel.sent[0]["embed"].title, "KaosBrain")
            self.assertIn("Unknown", channel.sent[0]["embed"].description)
            self.assertIsNone(channel.sent[0]["view"])
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["messageIds"]["issue:kaosbrain"], 700)
            self.assertEqual(state["messageIds"]["summary:planned"], 710)

    async def test_ensure_message_migrates_existing_service_message_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            message = FakeMessage(777)
            channel.messages[777] = message
            path = Path(temporary) / "status.json"
            path.write_text('{"messageIds": {"kaosbrain": 777}}', encoding="utf-8")
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 10)
            self.assertEqual(len(message.edits), 1)
            self.assertEqual(message.edits[0]["content"], "")
            self.assertEqual(message.edits[0]["embed"].title, "KaosBrain")
            self.assertIn("Unknown", message.edits[0]["embed"].description)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["messageIds"]["issue:kaosbrain"], 777)
            self.assertNotIn("kaosbrain", state["messageIds"])

    async def test_ensure_message_skips_unchanged_existing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path, channel)
            await surface.ensure_message()

            messages = list(channel.messages.values())
            await surface.ensure_message()

            self.assertEqual(channel.next_id, 711)
            self.assertTrue(all(not message.edits for message in messages))

    async def test_ensure_message_registers_restart_view_for_unchanged_down_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            bot = FakeBot(channel)
            path = Path(temporary) / "status.json"
            surface = DiscordServiceStatusSurface(
                bot,  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                state_path=path,
                environment={"SERVICE_STATUS_DEFAULT_PROBES_ENABLED": "false"},
            )
            surface.message_refresh_delay_seconds = 0

            async def fake_check_services():
                return {
                    item.key: ServiceProbeResult(
                        item.key,
                        "down" if item.key == "memos" else "unknown",
                        "09:00",
                        "connection refused" if item.key == "memos" else "",
                    )
                    for item in SERVICES
                }

            surface.check_services = fake_check_services  # type: ignore[method-assign]
            await surface.ensure_message()
            bot.registered_views = []

            await surface.ensure_message()

            memos_message_id = surface.state.message_ids["issue:memos"]  # type: ignore[index]
            registered_message_ids = {message_id for _view, message_id in bot.registered_views}
            self.assertIn(memos_message_id, registered_message_ids)
            self.assertTrue(all(not message.edits for message in channel.messages.values()))

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
            self.assertEqual(len(state["messageIds"]), 11)

    async def test_ensure_message_groups_healthy_services_into_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path, channel)

            async def fake_check_services():
                return {
                    item.key: ServiceProbeResult(
                        item.key,
                        "down" if item.key == "memos" else "planned" if item.key == "kaosinj" else "healthy",
                        "09:00",
                        "connection refused" if item.key == "memos" else "",
                    )
                    for item in SERVICES
                }

            surface.check_services = fake_check_services  # type: ignore[method-assign]
            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 3)
            self.assertEqual(channel.sent[0]["embed"].title, "Healthy")
            self.assertIn("KaosBrain", channel.sent[0]["embed"].description)
            self.assertIn("Brain of KaosGDD", channel.sent[0]["embed"].description)
            self.assertEqual(channel.sent[0]["embed"].footer.text, "Updated at 09:00")
            self.assertEqual(channel.sent[1]["embed"].title, "Memos")
            self.assertIsInstance(channel.sent[1]["view"], ServiceStatusView)
            self.assertEqual(channel.sent[2]["embed"].title, "Planned")
            self.assertIn("KaosInj", channel.sent[2]["embed"].description)
            self.assertIn("Clinic injection workflow support", channel.sent[2]["embed"].description)
            self.assertEqual(channel.sent[2]["embed"].footer.text, "Updated at 09:00")
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(state["messageIds"]), {"summary:healthy", "issue:memos", "summary:planned"})

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
                "SERVICE_STATUS_RESTART_MODE": "execute",
            },
        )

        self.assertEqual(result.state, "executed")

    def test_restart_service_defaults_to_dry_run(self) -> None:
        result = restart_service_sync(
            "memos",
            {
                "SERVICE_STATUS_RESTART_ALLOWED_KEYS": "memos",
                "SERVICE_STATUS_MEMOS_RESTART_COMMAND": "/bin/true",
            },
        )

        self.assertEqual(result.state, "dry_run")
        self.assertEqual(result.detail, "/bin/true")

    def test_restart_service_records_command_failure(self) -> None:
        result = restart_service_sync(
            "memos",
            {
                "SERVICE_STATUS_RESTART_ALLOWED_KEYS": "memos",
                "SERVICE_STATUS_MEMOS_RESTART_COMMAND": "/bin/false",
                "SERVICE_STATUS_RESTART_MODE": "execute",
            },
        )

        self.assertEqual(result.state, "failed")

    def test_render_service_message_includes_health_state(self) -> None:
        content = render_service_message(
            SERVICES[2],
            ServiceProbeResult("kaosgovernor", "healthy", "09:15:00", "HTTP 200"),
        )
        embed = render_service_embed(
            SERVICES[2],
            ServiceProbeResult("kaosgovernor", "healthy", "09:15:00", "HTTP 200"),
        )

        self.assertEqual(content, "")
        self.assertEqual(embed.title, "KaosGovernor")
        self.assertIn("Healthy", embed.description)
        self.assertNotIn("09:15:00", embed.description)
        self.assertIn("HTTP 200", embed.description)
        self.assertEqual(embed.footer.text, "Updated at 09:15:00")
        self.assertEqual(embed.color.value, EMBED_COLOR_HEALTHY)

    def test_service_embed_colors_match_state(self) -> None:
        self.assertEqual(
            render_service_embed(SERVICES[2], ServiceProbeResult("kaosgovernor", "healthy", "", "")).color.value,
            EMBED_COLOR_HEALTHY,
        )
        self.assertEqual(
            render_service_embed(SERVICES[2], ServiceProbeResult("kaosgovernor", "down", "", "")).color.value,
            EMBED_COLOR_DOWN,
        )
        self.assertEqual(
            render_service_embed(SERVICES[2], ServiceProbeResult("kaosgovernor", "unknown", "", "")).color.value,
            EMBED_COLOR_UNKNOWN,
        )
        self.assertEqual(
            render_service_embed(SERVICES[4], ServiceProbeResult("kaosinj", "planned", "", "")).color.value,
            EMBED_COLOR_UNKNOWN,
        )

    def test_summary_embed_lists_service_labels(self) -> None:
        embed = render_summary_embed("Healthy", [SERVICES[0], SERVICES[2]], EMBED_COLOR_HEALTHY, updated_at="09:15")

        self.assertEqual(embed.title, "Healthy")
        self.assertIn("KaosBrain", embed.description)
        self.assertIn("Brain of KaosGDD", embed.description)
        self.assertIn("KaosGovernor", embed.description)
        self.assertIn("Rules and controller", embed.description)
        self.assertEqual(embed.footer.text, "Updated at 09:15")
        self.assertEqual(embed.color.value, EMBED_COLOR_HEALTHY)

    def test_service_view_only_contains_restart_button(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "status.json")
            view = ServiceStatusView(
                surface,
                SERVICES[2],
                ServiceProbeResult("kaosgovernor", "down", "09:15:00", "Connection refused"),
            )

            self.assertEqual(len(view.children), 1)
            self.assertEqual(view.children[0].label, "Restart")

    def test_restart_confirm_view_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "status.json")
            view = ServiceRestartConfirmView(surface, SERVICES[2], 200)

            self.assertEqual([child.label for child in view.children], ["Confirm Restart", "Cancel"])

    def test_unconfigured_service_is_unknown(self) -> None:
        result = check_service(
            SERVICES[0],
            {"SERVICE_STATUS_DEFAULT_PROBES_ENABLED": "false"},
            0.5,
        )

        self.assertEqual(result.state, "unknown")
        self.assertIn("No health probe", result.detail)

    def test_second_look_probe_derives_health_url_and_reports_provider(self) -> None:
        self.assertEqual(
            second_look_health_url("http://100.113.169.46:8099/imaging/second-look"),
            "http://100.113.169.46:8099/health",
        )
        detail = second_look_health_detail(
            200,
            json.dumps({"imagingProvider": "kaosai", "imagingModel": "openai/gpt-5.6-sol"}).encode("utf-8"),
        )

        self.assertIn("provider=kaosai", detail)
        self.assertIn("model=openai/gpt-5.6-sol", detail)

    def test_second_look_status_detail_summarizes_last_result(self) -> None:
        detail = second_look_status_detail(
            json.dumps(
                {
                    "secondLook": {
                        "requestCount": 3,
                        "completedCount": 2,
                        "failedCount": 1,
                        "rateLimitedCount": 1,
                        "lastCompletedAt": "2026-08-20T19:05:00",
                        "lastStatus": "completed",
                        "lastModel": "openai/gpt-5.6-sol",
                    }
                }
            ).encode("utf-8")
        )

        self.assertIn("last completed 2026-08-20T19:05:00", detail)
        self.assertIn("model openai/gpt-5.6-sol", detail)
        self.assertIn("requests 3", detail)
        self.assertIn("rate-limited 1", detail)

    def test_second_look_status_detail_reports_empty_state(self) -> None:
        detail = second_look_status_detail(json.dumps({"secondLook": {"requestCount": 0}}).encode("utf-8"))

        self.assertEqual(detail, "no second-look requests yet")

    def test_service_status_secret_reads_file_backed_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token_path = Path(temporary) / "token"
            token_path.write_text("secret-value\n", encoding="utf-8")

            self.assertEqual(
                service_status_secret({"GOVERNOR_API_TOKEN_FILE": str(token_path)}, "GOVERNOR_API_TOKEN"),
                "secret-value",
            )

    def test_planned_service_renders_as_planned_without_probe(self) -> None:
        result = check_service(
            SERVICES[4],
            {"SERVICE_STATUS_DEFAULT_PROBES_ENABLED": "false"},
            0.5,
        )
        embed = render_service_embed(SERVICES[4], result)

        self.assertEqual(result.state, "planned")
        self.assertIn("No service is deployed yet", result.detail)
        self.assertIn("Planned", embed.description)

    def test_default_probes_cover_local_backend_services(self) -> None:
        self.assertEqual(DEFAULT_HTTP_PROBES["radicale"], "http://radicale:5232/")
        self.assertEqual(DEFAULT_HTTP_PROBES["memos"], "http://memos:5230/")
        self.assertEqual(DEFAULT_HTTP_PROBES["vaultwarden"], "http://vaultwarden/alive")
        self.assertNotIn("stirlingpdf", DEFAULT_HTTP_PROBES)
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

    def test_brain_health_detail_includes_mode_and_models(self) -> None:
        detail = brain_health_detail(
            200,
            json.dumps(
                {
                    "discordReady": True,
                    "chatModel": "gemma3:4b",
                    "deepModel": "qwen3:8b",
                    "kaosAI": {"mode": "dry-run"},
                }
            ).encode("utf-8"),
        )

        self.assertIn("HTTP 200", detail)
        self.assertIn("ready=True", detail)
        self.assertIn("KaosAI dry-run", detail)
        self.assertIn("gemma3:4b", detail)
        self.assertIn("qwen3:8b", detail)

    def test_brain_health_detail_tolerates_non_json(self) -> None:
        self.assertEqual(brain_health_detail(200, b"ok"), "HTTP 200")


if __name__ == "__main__":
    unittest.main()
