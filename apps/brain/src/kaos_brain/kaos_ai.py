from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol


class KaosAIError(RuntimeError):
    """Raised when KaosAI cannot return a usable plan."""


class KaosAIPlanner(Protocol):
    async def plan(self, user_text: str, *, context: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return a KaosAI plan or None when planning is unavailable."""


@dataclass(frozen=True)
class KaosAIConfig:
    enabled: bool = False
    provider: str = "disabled"
    base_url: str = ""
    model: str = "default"
    api_token: str = ""
    chat_completions_path: str = "/v1/chat/completions"
    timeout_seconds: int = 30


class DisabledKaosAIPlanner:
    async def plan(self, user_text: str, *, context: Mapping[str, Any]) -> dict[str, Any] | None:
        return None


class OpenClawKaosAIPlanner:
    def __init__(self, config: KaosAIConfig) -> None:
        self.config = config

    async def plan(self, user_text: str, *, context: Mapping[str, Any]) -> dict[str, Any] | None:
        if not self.config.enabled:
            return None
        raw = await self._complete(user_text, context=context)
        return parse_kaosai_plan_response(raw)

    async def _complete(self, user_text: str, *, context: Mapping[str, Any]) -> str:
        import aiohttp

        payload: dict[str, Any] = {
            "model": self.config.model,
            "stream": False,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": KAOSAI_PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": _render_plan_request(user_text, context)},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            try:
                async with session.post(_join_url(self.config.base_url, self.config.chat_completions_path), json=payload) as response:
                    if response.status >= 400:
                        body = await response.text()
                        raise KaosAIError(f"kaosai_http_{response.status}:{body[:160]}")
                    data = await response.json()
            except TimeoutError as exc:
                raise KaosAIError("kaosai_request_timed_out") from exc
            except aiohttp.ClientError as exc:
                raise KaosAIError("kaosai_request_failed") from exc
            except ValueError as exc:
                raise KaosAIError("kaosai_response_not_json") from exc
        content = _extract_chat_content(data)
        if not content:
            raise KaosAIError("kaosai_response_empty")
        return content


KAOSAI_PLAN_SYSTEM_PROMPT = """You are KaosAI, the planner for KaosGDD.
Return exactly one JSON object and no markdown.
You may understand language and draft plans, but you cannot call tools.
KaosBrain will validate your plan before KaosGovernor can write anything.

Allowed schema:
{
  "intent": "<allowed intent>",
  "scope": "personal|family|supplies",
  "parameters": {}
}

Allowed read-only intents:
- today.get
- task.list_active
- task.list_completed
- memo.search
- document.search

Allowed mutation intents:
- task.create
- task.update_due
- task.edit
- task.complete
- task.delete
- task.reopen
- event.create
- memo.create
- memo.edit
- memo.delete

Rules:
- Use YYYY-MM-DD dates.
- Use HH:MM 24-hour times.
- Default task due time to 10:00 when a due date has no time.
- Do not produce shell, Docker, database, restart, filesystem, SSH, or admin intents.
- For supplies, do not include dueDate or dueTime.
- If the user asks for a state change, set the matching mutation intent. KaosGovernor will ask for confirmation.
- If the request is ambiguous, return {"intent":"clarify","scope":"personal","parameters":{"question":"..."}}."""


def parse_kaosai_plan_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise KaosAIError("empty_kaosai_response")
    if text.startswith("```"):
        text = _strip_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KaosAIError("invalid_kaosai_json") from exc
    if not isinstance(payload, dict):
        raise KaosAIError("kaosai_plan_must_be_object")
    intent = str(payload.get("intent") or "").strip()
    parameters = payload.get("parameters")
    if not intent:
        raise KaosAIError("kaosai_intent_required")
    if intent == "clarify":
        question = ""
        if isinstance(parameters, Mapping):
            question = str(parameters.get("question") or "").strip()
        if not question:
            raise KaosAIError("kaosai_clarify_question_required")
        return dict(payload)
    if not isinstance(parameters, Mapping):
        raise KaosAIError("kaosai_parameters_required")
    return dict(payload)


def _strip_fence(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    if not lines[0].startswith("```"):
        return text
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _render_plan_request(user_text: str, context: Mapping[str, Any]) -> str:
    safe_context = {str(key): value for key, value in context.items() if key in {"actorId", "channelId", "today"}}
    return json.dumps(
        {
            "userText": user_text,
            "context": safe_context,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _extract_chat_content(data: Any) -> str:
    if not isinstance(data, Mapping):
        return ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            message = first.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                return message["content"].strip()
            if isinstance(first.get("text"), str):
                return first["text"].strip()
    message = data.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("content"), str):
        return message["content"].strip()
    for key in ("content", "response", "text"):
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _join_url(base_url: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base_url.rstrip('/')}{normalized_path}"
