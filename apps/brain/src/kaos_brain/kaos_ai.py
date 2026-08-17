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
    timeout_seconds: int = 30


class DisabledKaosAIPlanner:
    async def plan(self, user_text: str, *, context: Mapping[str, Any]) -> dict[str, Any] | None:
        return None


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
