from __future__ import annotations

import hmac
from typing import Any, Mapping

from aiohttp import web

from .config import Settings
from .kaos_ai import KaosAIConfig, KaosAIError, OpenClawKaosAIPlanner


MAX_OFFICIAL_MEMO_PROMPT_CHARS = 1200
MAX_OFFICIAL_MEMO_SOURCE_CHARS = 20000


def validate_official_memo_request(body: Mapping[str, Any]) -> str:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return "official_memo_prompt_required"
    if len(prompt) > MAX_OFFICIAL_MEMO_PROMPT_CHARS:
        return "official_memo_prompt_too_long"
    source = body.get("source")
    if not isinstance(source, Mapping):
        return "official_memo_source_required"
    source_text = str(source.get("text") or "").strip()
    if not source_text:
        return "official_memo_source_text_required"
    if len(source_text) > MAX_OFFICIAL_MEMO_SOURCE_CHARS:
        return "official_memo_source_text_too_long"
    return ""


class BrainOfficialMemoServer:
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
        token = (
            self.settings.ai_task_api_token
            or self.settings.document_tag_api_token
            or self.settings.calendar_preview_api_token
        )
        if not _authorized(request, token):
            return web.json_response({"ok": False, "error": "kaosbrain_ai_task_unauthorized"}, status=401)
        if not self.settings.kaosai_enabled:
            return web.json_response({"ok": False, "error": "kaosbrain_openai_disabled"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        error = validate_official_memo_request(body)
        if error:
            return web.json_response({"ok": False, "error": error}, status=400)
        try:
            memo = await self.kaosai.preview_official_memo(body)
        except KaosAIError as exc:
            return web.json_response(
                {
                    "ok": False,
                    "error": "kaosbrain_official_memo_unavailable",
                    "detail": str(exc),
                },
                status=502,
            )
        return web.json_response(
            {
                "ok": True,
                "source": "ai",
                "memo": memo,
                "ai": {"configured": True, "used": True, "error": ""},
            }
        )


def _authorized(request: web.Request, token: str) -> bool:
    if not token:
        return False
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
