from __future__ import annotations

import hmac
import re
from typing import Any, Mapping

from aiohttp import web

from .config import Settings
from .kaos_ai import KaosAIConfig, KaosAIError, OpenClawKaosAIPlanner


MAX_CALENDAR_PREVIEW_TEXT = 4000


def validate_calendar_preview_request(body: Mapping[str, Any]) -> str:
    if str(body.get("profile") or "family").strip() != "family":
        return "calendar_preview_family_profile_required"
    text = str(body.get("text") or "").strip()
    if not text:
        return "calendar_preview_text_required"
    if len(text) > MAX_CALENDAR_PREVIEW_TEXT:
        return "calendar_preview_text_too_long"
    date_value = str(body.get("date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
        return "calendar_preview_date_required"
    grammar_events = body.get("grammarEvents")
    if grammar_events is not None and not isinstance(grammar_events, list):
        return "calendar_preview_grammar_events_invalid"
    return ""


class BrainCalendarPreviewServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.kaosai = OpenClawKaosAIPlanner(
            KaosAIConfig(
                enabled=settings.kaosai_enabled,
                provider=settings.kaosai_provider,
                base_url=settings.kaosai_base_url,
                model=settings.kaosai_model,
                api_token=settings.kaosai_api_token,
                timeout_seconds=settings.kaosai_timeout_seconds,
            )
        )

    async def preview(self, request: web.Request) -> web.Response:
        if not _authorized(request, self.settings.calendar_preview_api_token):
            return web.json_response({"ok": False, "error": "kaosbrain_calendar_preview_unauthorized"}, status=401)
        if not self.settings.kaosai_enabled:
            return web.json_response({"ok": False, "error": "kaosbrain_openai_disabled"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        error = validate_calendar_preview_request(body)
        if error:
            return web.json_response({"ok": False, "error": error}, status=400)
        try:
            events = await self.kaosai.preview_calendar_events(body)
        except KaosAIError as exc:
            return web.json_response(
                {
                    "ok": False,
                    "error": "kaosbrain_calendar_preview_unavailable",
                    "detail": str(exc),
                },
                status=502,
            )
        return web.json_response(
            {
                "ok": True,
                "source": "ai",
                "events": events,
                "ai": {"configured": True, "used": True, "error": ""},
            }
        )


def _authorized(request: web.Request, token: str) -> bool:
    if not token:
        return False
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
