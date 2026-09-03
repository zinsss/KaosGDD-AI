from __future__ import annotations

from datetime import UTC, datetime
import hmac
import json
import re
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from aiohttp import web

from .config import Settings


MAX_WEB_TASK_PROMPT_CHARS = 1600
MAX_WEB_TASK_OUTPUT_CHARS = 12000
MAX_WEB_TASK_SOURCES = 10
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class WebTaskError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_web_task_request(body: Mapping[str, Any]) -> str:
    prompt = " ".join(str(body.get("prompt") or "").split())
    if not prompt:
        return "web_task_prompt_required"
    if len(prompt) > MAX_WEB_TASK_PROMPT_CHARS:
        return "web_task_prompt_too_long"
    return ""


class BrainWebTaskServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def preview(self, request: "web.Request") -> "web.Response":
        from aiohttp import web

        token = (
            self.settings.ai_task_api_token
            or self.settings.document_tag_api_token
            or self.settings.calendar_preview_api_token
        )
        if not _authorized(request, token):
            return web.json_response({"ok": False, "error": "kaosbrain_ai_task_unauthorized"}, status=401)
        if not self.settings.openai_api_key:
            return web.json_response({"ok": False, "error": "kaosbrain_web_search_not_configured"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        error = validate_web_task_request(body)
        if error:
            return web.json_response({"ok": False, "error": error}, status=400)
        try:
            result = await openai_web_task(
                str(body.get("prompt") or ""),
                api_key=self.settings.openai_api_key,
                model=self.settings.web_task_model,
                timeout_seconds=self.settings.web_task_timeout_seconds,
            )
        except WebTaskError as exc:
            return web.json_response({"ok": False, "error": exc.code}, status=502)
        return web.json_response({"ok": True, "source": "openai-web-search", "result": result})


async def openai_web_task(
    prompt: str,
    *,
    api_key: str,
    model: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    from aiohttp import ClientError, ClientSession, ClientTimeout

    checked_at = datetime.now(UTC).date().isoformat()
    request_payload = {
        "model": model or "gpt-5.6",
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.action.sources", "web_search_call.results"],
        "input": [
            {
                "role": "system",
                "content": (
                    "You are KaosBrain helping KaosGDD complete a read-only AI Task. "
                    "Use web search when current or source-backed information is needed. "
                    "Prefer official/public-authority sources for policy, medicine, law, school, government, and finance topics. "
                    "Do not claim anything was saved, written, sent, or applied. "
                    "Answer in Korean unless the user clearly asks otherwise. "
                    "Keep the answer practical and include source names or links when available."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    timeout = ClientTimeout(total=timeout_seconds)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.post(OPENAI_RESPONSES_URL, json=request_payload) as response:
                raw_text = await response.text()
                if response.status >= 400:
                    raise WebTaskError(_openai_error_code(raw_text, response.status))
        except TimeoutError as exc:
            raise WebTaskError("web_task_openai_timeout") from exc
        except ClientError as exc:
            raise WebTaskError("web_task_openai_request_failed") from exc
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise WebTaskError("web_task_openai_invalid_json") from exc
    content = _extract_response_text(payload)
    if not content:
        raise WebTaskError("web_task_openai_empty")
    sources = _extract_sources(payload)
    return {
        "title": _title_from_content(content, prompt),
        "content": content[:MAX_WEB_TASK_OUTPUT_CHARS],
        "sources": sources,
        "checkedAt": checked_at,
        "model": model or "gpt-5.6",
    }


def _openai_error_code(raw_text: str, status: int) -> str:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return f"web_task_openai_http_{status}"
    error = payload.get("error") if isinstance(payload, Mapping) else {}
    code = str(error.get("code") or error.get("type") or "").strip().lower() if isinstance(error, Mapping) else ""
    if code in {"invalid_api_key", "authentication_error"} or status in {401, 403}:
        return "web_task_openai_unauthorized"
    if code == "rate_limit_exceeded" or status == 429:
        return "web_task_openai_rate_limited"
    return f"web_task_openai_http_{status}"


def _extract_response_text(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, Mapping):
                continue
            text = content.get("text") or content.get("summary")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts).strip()


def _extract_sources(payload: Any) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []

    def visit(value: Any) -> None:
        if len(sources) >= MAX_WEB_TASK_SOURCES:
            return
        if isinstance(value, Mapping):
            url = str(value.get("url") or value.get("source_url") or value.get("uri") or "").strip()
            title = " ".join(str(value.get("title") or value.get("name") or "").split())
            if url.startswith(("https://", "http://")) and not any(item["url"] == url for item in sources):
                sources.append({"title": title[:200] or url, "url": url[:800]})
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    return sources


def _title_from_content(content: str, prompt: str) -> str:
    for line in content.splitlines():
        clean = re.sub(r"^[#*\-\s]+", "", line).strip()
        if clean:
            return clean[:120]
    return " ".join(prompt.split())[:120] or "AI Task"


def _authorized(request: web.Request, token: str) -> bool:
    if not token:
        return False
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
