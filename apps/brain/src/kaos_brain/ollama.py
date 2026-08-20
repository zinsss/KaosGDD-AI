from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import aiohttp

from .intent import Route
from .prompt import ROUTER_SYSTEM_PROMPT, TOOL_SUMMARY_SYSTEM_PROMPT, system_prompt
from .router import RouteDecision, parse_route_decision


class OllamaError(RuntimeError):
    """Raised when Ollama cannot produce a usable response."""


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    chat_model: str
    deep_model: str
    timeout_seconds: int
    imaging_model: str = ""


class OllamaClient:
    def __init__(self, config: OllamaConfig) -> None:
        self.config = config

    async def generate(self, route: Route, user_text: str) -> str:
        model = self.config.deep_model if route is Route.DEEP else self.config.chat_model
        return await self._complete(
            model,
            [
                {"role": "system", "content": system_prompt(route)},
                {"role": "user", "content": user_text},
            ],
            num_predict=512,
        )

    async def generate_auto(self, user_text: str) -> str:
        decision = await self.route(user_text)
        route = Route.DEEP if decision is RouteDecision.DEEP else Route.CHAT
        return await self.generate(route, user_text)

    async def summarize_tool_result(self, user_text: str, tool_context: str) -> str:
        return await self._complete(
            self.config.chat_model,
            [
                {"role": "system", "content": TOOL_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": f"User request:\n{user_text}\n\nGovernor data:\n{tool_context}"},
            ],
            num_predict=512,
        )

    async def second_look(self, request: dict[str, Any]) -> dict[str, Any]:
        images = [
            str(image.get("contentBase64") or "")
            for image in request.get("images", [])
            if isinstance(image, dict) and str(image.get("contentBase64") or "")
        ]
        if not images:
            raise OllamaError("second-look request did not include images")
        prompt = _second_look_prompt(request)
        model = self.imaging_model()
        raw = await self._complete(
            model,
            [
                {
                    "role": "system",
                    "content": SECOND_LOOK_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                    "images": images[:4],
                },
            ],
            num_predict=700,
        )
        return _parse_second_look_response(raw, model=model)

    def imaging_model(self) -> str:
        return self.config.imaging_model or self.config.chat_model

    async def route(self, user_text: str) -> RouteDecision:
        try:
            raw = await self._complete(
                self.config.chat_model,
                [
                    {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                num_predict=8,
            )
        except OllamaError:
            return RouteDecision.ANSWER
        return parse_route_decision(raw)

    async def _complete(self, model: str, messages: list[dict[str, Any]], *, num_predict: int) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": 0.2,
                "num_predict": num_predict,
            },
        }
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.post(f"{self.config.base_url.rstrip('/')}/api/chat", json=payload) as response:
                    if response.status >= 400:
                        body = await response.text()
                        raise OllamaError(f"Ollama returned HTTP {response.status}: {body[:200]}")
                    data = await response.json()
            except TimeoutError as exc:
                raise OllamaError("Ollama request timed out") from exc
            except aiohttp.ClientError as exc:
                raise OllamaError("Ollama request failed") from exc
        message = data.get("message")
        if not isinstance(message, dict):
            raise OllamaError("Ollama response did not include a message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama response was empty")
        return content.strip()


SECOND_LOOK_SYSTEM_PROMPT = """You are KaosAI providing a temporary medical image second-look checklist.
Return exactly one JSON object and no markdown.
Do not diagnose, do not claim certainty, and do not provide a final report.
Use Korean unless the user question is clearly in another language.

Allowed schema:
{
  "summary": "...",
  "checklist": ["..."],
  "cautions": ["..."],
  "recommendation": "..."
}

Rules:
- Focus on visible, general image-quality and review-checklist observations.
- Use second-look wording such as possible, consider, visible concern, and needs physician review.
- Avoid final diagnosis language and never phrase the output as a clinical report.
- Mention that the final judgment belongs to the clinician.
- Do not infer hidden DICOM metadata.
- Do not suggest that PACS, Orthanc, or medical records were modified."""


def _second_look_prompt(request: dict[str, Any]) -> str:
    fields = {
        "modality": request.get("modality", ""),
        "bodyPart": request.get("bodyPart", ""),
        "viewPosition": request.get("viewPosition", ""),
        "aiDomain": request.get("aiDomain", ""),
        "question": request.get("question", ""),
    }
    return "\n".join(f"{key}: {value}" for key, value in fields.items() if str(value or "").strip())


def _parse_second_look_response(raw: str, *, model: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"summary": raw, "checklist": [], "cautions": [], "recommendation": ""}
    if not isinstance(payload, dict):
        payload = {"summary": raw, "checklist": [], "cautions": [], "recommendation": ""}
    summary = str(payload.get("summary") or "").strip() or raw.strip()[:1000]
    checklist = _string_list(payload.get("checklist"), limit=8)
    cautions = _string_list(payload.get("cautions"), limit=5)
    recommendation = str(payload.get("recommendation") or "").strip()
    if not cautions:
        cautions = ["AI 보조 검토입니다. 최종 판단은 진료자가 합니다."]
    return {
        "summary": summary[:1400],
        "checklist": checklist,
        "cautions": cautions,
        "recommendation": recommendation[:800],
        "disclaimer": "AI 보조 검토입니다. 최종 판단은 진료자가 합니다.",
        "model": model,
    }


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text[:500])
        if len(items) >= limit:
            break
    return items
