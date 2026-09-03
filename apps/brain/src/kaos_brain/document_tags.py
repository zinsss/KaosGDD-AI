from __future__ import annotations

import hmac
from typing import Any, Mapping

from aiohttp import web

from .config import Settings
from .kaos_ai import (
    KaosAIConfig,
    KaosAIError,
    OpenClawKaosAIPlanner,
    _available_tags_by_normalized_name,
    _normalize_tag_name,
)


MAX_DOCUMENT_TAG_CONTEXT_CHARS = 4000
MAX_DOCUMENT_TAGS = 5


def validate_document_tag_request(body: Mapping[str, Any]) -> str:
    document = body.get("document")
    if not isinstance(document, Mapping):
        return "document_tag_document_required"
    document_id = str(document.get("id") or "").strip()
    title = str(document.get("title") or "").strip()
    filename = str(document.get("filename") or "").strip()
    content_excerpt = str(document.get("contentExcerpt") or "").strip()
    if not document_id:
        return "document_tag_document_id_required"
    if not title and not filename and not content_excerpt:
        return "document_tag_context_required"
    available_tags = body.get("availableTags")
    if available_tags is not None and not isinstance(available_tags, list):
        return "document_tag_available_tags_invalid"
    if len(content_excerpt) > MAX_DOCUMENT_TAG_CONTEXT_CHARS:
        return "document_tag_context_too_long"
    return ""


class BrainDocumentTagServer:
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

    async def suggest(self, request: web.Request) -> web.Response:
        token = self.settings.document_tag_api_token or self.settings.calendar_preview_api_token
        if not _authorized(request, token):
            return web.json_response({"ok": False, "error": "kaosbrain_document_tag_unauthorized"}, status=401)
        if not self.settings.kaosai_enabled:
            return web.json_response({"ok": False, "error": "kaosbrain_openai_disabled"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        error = validate_document_tag_request(body)
        if error:
            return web.json_response({"ok": False, "error": error}, status=400)
        try:
            tags = await self.kaosai.suggest_document_tags(body)
        except KaosAIError as exc:
            return web.json_response(
                {
                    "ok": False,
                    "error": "kaosbrain_document_tag_unavailable",
                    "detail": str(exc),
                },
                status=502,
            )
        existing_tags = _filter_existing_tags(body, tags)
        return web.json_response(
            {
                "ok": True,
                "source": "ai",
                "tags": existing_tags,
                "ai": {"configured": True, "used": True, "error": ""},
            }
        )


def _filter_existing_tags(context: Mapping[str, Any], tags: tuple[str, ...]) -> list[str]:
    available = _available_tags_by_normalized_name(context)
    selected: list[str] = []
    for tag in tags:
        existing = available.get(_normalize_tag_name(tag))
        if existing and existing not in selected:
            selected.append(existing)
        if len(selected) >= MAX_DOCUMENT_TAGS:
            break
    return selected


def _authorized(request: web.Request, token: str) -> bool:
    if not token:
        return False
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
