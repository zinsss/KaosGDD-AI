from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .intent import Route
from .prompt import system_prompt


class OllamaError(RuntimeError):
    """Raised when Ollama cannot produce a usable response."""


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    chat_model: str
    deep_model: str
    timeout_seconds: int


class OllamaClient:
    def __init__(self, config: OllamaConfig) -> None:
        self.config = config

    async def generate(self, route: Route, user_text: str) -> str:
        model = self.config.deep_model if route is Route.DEEP else self.config.chat_model
        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt(route)},
                {"role": "user", "content": user_text},
            ],
            "options": {
                "temperature": 0.2,
                "num_predict": 512,
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
