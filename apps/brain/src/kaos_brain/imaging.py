from __future__ import annotations

import base64
import binascii
import hmac
from typing import Any, Mapping

from aiohttp import web

from .config import Settings
from .kaos_ai import KaosAIConfig, KaosAIError, OpenClawKaosAIPlanner
from .ollama import OllamaClient, OllamaConfig, OllamaError


SECOND_LOOK_ALLOWED_SOURCES = {"kaospacs-aio", "kaosaio"}


def validate_second_look_request(body: Mapping[str, Any]) -> str:
    if str(body.get("source") or "").strip() not in SECOND_LOOK_ALLOWED_SOURCES:
        return "imaging_second_look_invalid_source"
    for name in ("requestId", "modality", "aiDomain", "question"):
        if not str(body.get(name) or "").strip():
            return "imaging_second_look_missing_required_field"
    safety = body.get("safety")
    if not isinstance(safety, Mapping):
        return "imaging_second_look_missing_safety"
    required_safety = {
        "temporary": True,
        "storedInAioReports": False,
        "dicomMetadataSent": False,
        "orthancReadOnly": True,
        "dicomModified": False,
        "pacsFinalReport": False,
        "renderedPreview": True,
    }
    for name, expected in required_safety.items():
        if safety.get(name) is not expected:
            return "imaging_second_look_safety_rejected"
    images = body.get("images")
    if not isinstance(images, list) or not images:
        return "imaging_second_look_missing_image"
    if len(images) > 4:
        return "imaging_second_look_too_many_images"
    for image in images:
        if not isinstance(image, Mapping):
            return "imaging_second_look_invalid_image"
        if str(image.get("format") or "").strip().lower() not in {"png", "jpg", "jpeg"}:
            return "imaging_second_look_unsupported_image_format"
        content = str(image.get("contentBase64") or "").strip()
        if not content:
            return "imaging_second_look_missing_image"
        try:
            decoded = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            return "imaging_second_look_invalid_image_base64"
        if not decoded or len(decoded) > 8 * 1024 * 1024:
            return "imaging_second_look_image_size_rejected"
    return ""


class BrainImagingServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ollama = OllamaClient(
            OllamaConfig(
                base_url=settings.ollama_base_url,
                chat_model=settings.chat_model,
                deep_model=settings.deep_model,
                imaging_model=settings.imaging_model,
                timeout_seconds=settings.request_timeout_seconds,
            )
        )
        self.kaosai = (
            OpenClawKaosAIPlanner(
                KaosAIConfig(
                    enabled=settings.kaosai_enabled,
                    provider=settings.kaosai_provider,
                    base_url=settings.kaosai_base_url,
                    model=settings.kaosai_model,
                    api_token=settings.kaosai_api_token,
                    timeout_seconds=settings.kaosai_timeout_seconds,
                )
            )
            if settings.imaging_provider == "kaosai"
            else None
        )

    async def second_look(self, request: web.Request) -> web.Response:
        if not self.settings.imaging_enabled:
            return web.json_response({"error": "kaosbrain_imaging_disabled"}, status=503)
        if not _authorized(request, self.settings.imaging_api_token):
            return web.json_response({"error": "kaosbrain_imaging_unauthorized"}, status=401)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        error = validate_second_look_request(body)
        if error:
            return web.json_response({"error": error}, status=400)
        try:
            if self.kaosai is not None:
                try:
                    return web.json_response(
                        {
                            "status": "completed",
                            "result": await self.kaosai.second_look(body),
                        }
                    )
                except KaosAIError as exc:
                    return web.json_response(
                        {
                            "error": "kaosai_second_look_unavailable",
                            "message": "KaosBrain-OpenAI 인증 갱신이 필요하거나 이미지 보조 검토 제공자가 응답하지 않습니다.",
                            "detail": str(exc),
                        },
                        status=502,
                    )
            else:
                result = await self.ollama.second_look(dict(body))
        except OllamaError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        return web.json_response(
            {
                "status": "completed",
                "result": result,
            }
        )


def _authorized(request: web.Request, token: str) -> bool:
    if not token:
        return False
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
