from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

from .discord_content_views import (
    BrainCombinedSearchView,
    BrainDocumentSearchView,
    BrainMemoSearchView,
    BrainOpenedMemoView,
    _linked_document_results,
)
from .discord_formatting import (
    _payload_count,
    _render_document_list_message,
    _task_results,
)
from .discord_task_views import BrainActiveTasksView, BrainCompletedTasksView
from .governor_tools import (
    GovernorToolClient,
    GovernorToolError,
    document_public_url,
    memo_public_url,
    render_combined_search_context,
    render_memo_opened,
    render_tool_context,
    SEARCH_RESULT_LIMIT,
    search_results,
)
from .ollama import OllamaError
from .tool_intent import ToolKind, ToolRequest

LOGGER = logging.getLogger(__name__)


def _tool_unavailable() -> str:
    return "Governor 연결이 아직 없어요."


def _tool_failed(action: str) -> str:
    return f"{action} 실패했어요."


async def answer_with_governor_tool(
    *,
    governor_tools: GovernorToolClient | None,
    settings: Any,
    ollama: Any,
    user_text: str,
    tool_request: ToolRequest,
    actor_id: int,
    logger: logging.Logger = LOGGER,
) -> tuple[str, discord.ui.View | None]:
    if governor_tools is None:
        return _tool_unavailable(), None
    if tool_request.kind is ToolKind.SEARCH_ALL:
        try:
            memo_payload, document_payload = await asyncio.gather(
                governor_tools.fetch(ToolRequest(ToolKind.MEMO_SEARCH, tool_request.query)),
                governor_tools.fetch(ToolRequest(ToolKind.DOCUMENT_SEARCH, tool_request.query)),
            )
        except GovernorToolError as exc:
            logger.warning("Governor combined search failed: %s", exc)
            return _tool_failed("조회"), None
        document_results = [
            {
                **item,
                "url": item.get("url")
                or item.get("publicUrl")
                or document_public_url(_settings_value(settings, "paperless_public_url"), item.get("id")),
            }
            for item in search_results(document_payload)
        ]
        document_payload = {**document_payload, "results": document_results}
        memo_results = search_results(memo_payload)
        view = (
            BrainCombinedSearchView(
                governor_tools,
                actor_id,
                tool_request.query,
                memo_results,
                document_results,
                memo_count=_payload_count(memo_payload, "resultCount", "count", fallback=len(memo_results)),
                memo_total=_payload_count(memo_payload, "totalCount", fallback=len(memo_results)),
                document_count=_payload_count(document_payload, "resultCount", "count", fallback=len(document_results)),
                document_total=_payload_count(document_payload, "totalCount", "total", fallback=len(document_results)),
                paperless_public_url=_settings_value(settings, "paperless_public_url"),
                memos_public_url=_settings_value(settings, "memos_public_url"),
            )
            if memo_results or document_results
            else None
        )
        return render_combined_search_context(tool_request.query, memo_payload, document_payload), view
    try:
        payload = await governor_tools.fetch(tool_request)
    except GovernorToolError as exc:
        logger.warning("Governor tool failed kind=%s: %s", tool_request.kind.value, exc)
        return _tool_failed("조회"), None
    if tool_request.kind is ToolKind.MEMO_SEARCH:
        context = render_tool_context(tool_request, payload)
        results = search_results(payload)
        if len(results) == 1:
            item = results[0]
            content = render_memo_opened(tool_request.query, item)
            view = BrainOpenedMemoView(
                governor_tools,
                actor_id,
                str(item.get("name") or ""),
                content,
                memo_public_url(_settings_value(settings, "memos_public_url"), str(item.get("name") or "")),
            )
            return content, view
        view = (
            BrainMemoSearchView(
                governor_tools,
                actor_id,
                tool_request.query,
                results,
                result_count=_payload_count(payload, "resultCount", "count", fallback=len(results)),
                total_count=_payload_count(payload, "totalCount", fallback=len(results)),
                memos_public_url=_settings_value(settings, "memos_public_url"),
            )
            if len(results) > 1
            else None
        )
        if view is not None:
            context = view.content(searched=True)
        return context, view
    if tool_request.kind is ToolKind.DOCUMENT_SEARCH:
        results = search_results(payload)
        paperless_public_url = _settings_value(settings, "paperless_public_url")
        linked_results = _linked_document_results(results, paperless_public_url)
        payload = {**payload, "results": linked_results}
        view = (
            BrainDocumentSearchView(
                governor_tools,
                actor_id,
                tool_request.query,
                linked_results,
                result_count=_payload_count(payload, "resultCount", "count", fallback=len(linked_results)),
                total_count=_payload_count(payload, "totalCount", "total", fallback=len(linked_results)),
                page=_payload_count(payload, "page", fallback=1),
                page_size=_payload_count(payload, "pageSize", "page_size", fallback=SEARCH_RESULT_LIMIT),
                searched=True,
                paperless_public_url=paperless_public_url,
            )
            if linked_results
            else None
        )
        context = (
            view.content(searched=True)
            if view is not None
            else _render_document_list_message(
                tool_request.query,
                linked_results,
                result_count=_payload_count(payload, "resultCount", "count", fallback=len(linked_results)),
                total_count=_payload_count(payload, "totalCount", "total", fallback=len(linked_results)),
                page=_payload_count(payload, "page", fallback=1),
                page_size=_payload_count(payload, "pageSize", "page_size", fallback=SEARCH_RESULT_LIMIT),
                searched=True,
            )
        )
        return context, view
    context = render_tool_context(tool_request, payload)
    if tool_request.kind is ToolKind.COMPLETED_TASKS:
        tasks = _task_results(payload)
        view = BrainCompletedTasksView(governor_tools, actor_id, tool_request, tasks) if tasks else None
        return context, view
    if tool_request.kind is ToolKind.ACTIVE_TASKS:
        tasks = _task_results(payload)
        view = BrainActiveTasksView(governor_tools, actor_id, tool_request, tasks) if tasks else None
        return context, view
    if tool_request.kind in {ToolKind.TODAY, ToolKind.WEATHER}:
        return context, None
    try:
        if ollama is None:
            return context, None
        return await ollama.summarize_tool_result(user_text, context), None
    except OllamaError:
        return context, None


def _settings_value(settings: Any, name: str) -> str:
    return str(getattr(settings, name, "") or "").strip().rstrip("/")
