from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from uuid import uuid4
from typing import Any, Mapping, Protocol

from .brain_guard import INTENT_PARAMETER_KEYS, MUTATION_INTENTS, READONLY_INTENTS


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

        if not self.config.api_token:
            raise KaosAIError("kaosai_gateway_token_required")
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.ws_connect(_openclaw_gateway_url(self.config.base_url)) as websocket:
                    await _openclaw_connect(websocket, token=self.config.api_token)
                    data = await _openclaw_agent_request(
                        websocket,
                        model=self.config.model,
                        message=f"{KAOSAI_PLAN_SYSTEM_PROMPT}\n\n{_render_plan_request(user_text, context)}",
                    )
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise KaosAIError("kaosai_request_timed_out") from exc
            except aiohttp.ClientError as exc:
                raise KaosAIError("kaosai_gateway_request_failed") from exc
            except ValueError as exc:
                raise KaosAIError("kaosai_gateway_response_not_json") from exc
        content = _extract_openclaw_text(data)
        if not content:
            raise KaosAIError("kaosai_response_empty")
        return content


def _format_intent_lines(intents: set[str]) -> str:
    return "\n".join(f"- {intent}" for intent in sorted(intents))


def _format_parameter_lines() -> str:
    lines = []
    for intent in sorted(INTENT_PARAMETER_KEYS):
        keys = ", ".join(sorted(INTENT_PARAMETER_KEYS[intent])) or "none"
        lines.append(f"- {intent}: {keys}")
    return "\n".join(lines)


KAOSAI_PLAN_SYSTEM_PROMPT = f"""You are KaosAI, the planner for KaosGDD.
Return exactly one JSON object and no markdown.
You may understand language and draft plans, but you cannot call tools.
KaosBrain will validate your plan before KaosGovernor can write anything.

Allowed schema:
{{
  "intent": "<allowed intent>",
  "scope": "personal|family|supplies",
  "parameters": {{}}
}}

Allowed read-only intents:
{_format_intent_lines(READONLY_INTENTS)}

Allowed mutation intents:
{_format_intent_lines(MUTATION_INTENTS)}

Allowed parameters by intent:
{_format_parameter_lines()}

Rules:
- Use YYYY-MM-DD dates.
- Use HH:MM 24-hour times.
- Default task due time to 10:00 when a due date has no time.
- Do not produce shell, Docker, database, restart, filesystem, SSH, or admin intents.
- For supplies, do not include dueDate or dueTime.
- If the user asks for a state change, set the matching mutation intent. KaosGovernor will ask for confirmation.
- If the request is ambiguous, return {{"intent":"clarify","scope":"personal","parameters":{{"question":"..."}}}}."""


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


async def _openclaw_connect(websocket: Any, *, token: str) -> None:
    while True:
        frame = await _receive_openclaw_json(websocket)
        if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
            break
    request_id = str(uuid4())
    await websocket.send_json(
        {
            "type": "req",
            "id": request_id,
            "method": "connect",
            "params": {
                "minProtocol": 4,
                "maxProtocol": 4,
                "client": {
                    "id": "gateway-client",
                    "displayName": "KaosBrain",
                    "version": "0.0.0",
                    "platform": "linux",
                    "deviceFamily": "server",
                    "mode": "backend",
                    "instanceId": str(uuid4()),
                },
                "caps": [],
                "auth": {"token": token},
                "role": "operator",
                "scopes": ["operator.admin"],
            },
        }
    )
    frame = await _receive_openclaw_response(websocket, request_id, expect_final=False)
    if not frame.get("ok"):
        raise KaosAIError(_openclaw_error_code(frame, "kaosai_gateway_connect_failed"))


async def _openclaw_agent_request(websocket: Any, *, model: str, message: str) -> Mapping[str, Any]:
    request_id = str(uuid4())
    session_id = f"kaosbrain-plan-{uuid4()}"
    model_name = model.strip()
    params: dict[str, Any] = {
        "message": message,
        "agentId": "main",
        "sessionId": session_id,
        "sessionKey": session_id,
        "modelRun": True,
        "promptMode": "none",
        "cleanupBundleMcpOnRunEnd": True,
        "idempotencyKey": str(uuid4()),
        "sessionEffects": "internal",
        "suppressPromptPersistence": True,
    }
    if model_name and model_name != "default":
        if "/" in model_name:
            provider, selected_model = model_name.split("/", 1)
            params["provider"] = provider
            params["model"] = selected_model
        else:
            params["model"] = model_name
    await websocket.send_json({"type": "req", "id": request_id, "method": "agent", "params": params})
    frame = await _receive_openclaw_response(websocket, request_id, expect_final=True)
    if not frame.get("ok"):
        raise KaosAIError(_openclaw_error_code(frame, "kaosai_gateway_agent_failed"))
    payload = frame.get("payload")
    if not isinstance(payload, Mapping):
        raise KaosAIError("kaosai_gateway_payload_invalid")
    return payload


async def _receive_openclaw_response(websocket: Any, request_id: str, *, expect_final: bool) -> Mapping[str, Any]:
    while True:
        frame = await _receive_openclaw_json(websocket)
        if frame.get("type") != "res" or frame.get("id") != request_id:
            continue
        if expect_final and isinstance(frame.get("payload"), Mapping) and frame["payload"].get("status") == "accepted":
            continue
        return frame


async def _receive_openclaw_json(websocket: Any) -> Mapping[str, Any]:
    import aiohttp

    message = await websocket.receive()
    if message.type == aiohttp.WSMsgType.TEXT:
        data = json.loads(message.data)
        if not isinstance(data, Mapping):
            raise KaosAIError("kaosai_gateway_frame_invalid")
        return data
    if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING}:
        raise KaosAIError("kaosai_gateway_closed")
    if message.type == aiohttp.WSMsgType.ERROR:
        raise KaosAIError("kaosai_gateway_error")
    raise KaosAIError("kaosai_gateway_frame_invalid")


def _extract_openclaw_text(data: Any) -> str:
    if not isinstance(data, Mapping):
        return ""
    result = data.get("result")
    if isinstance(result, Mapping):
        payloads = result.get("payloads")
        if isinstance(payloads, list):
            for payload in payloads:
                if isinstance(payload, Mapping) and isinstance(payload.get("text"), str):
                    return payload["text"].strip()
    for key in ("content", "response", "text", "summary"):
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _openclaw_gateway_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if value.startswith("ws://") or value.startswith("wss://"):
        return value
    if value.startswith("http://"):
        return f"ws://{value.removeprefix('http://')}"
    if value.startswith("https://"):
        return f"wss://{value.removeprefix('https://')}"
    return value


def _openclaw_error_code(frame: Mapping[str, Any], fallback: str) -> str:
    error = frame.get("error")
    if not isinstance(error, Mapping):
        return fallback
    code = str(error.get("code") or "").strip().lower()
    message = str(error.get("message") or "").strip()
    if code:
        return f"{fallback}:{code}"
    if message:
        return f"{fallback}:{message[:80]}"
    return fallback
