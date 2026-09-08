"""Transport-neutral calendar presentation helpers for Governor tools."""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from .calendar import MonthDayMarkers


def visible_month_grid_range(year: int, month: int) -> tuple[date, date]:
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    return weeks[0][0], weeks[-1][-1]


def month_markers(bootstrap: Mapping[str, Any], *, now: datetime | None = None) -> list[MonthDayMarkers]:
    collections = _collections_by_id(bootstrap)
    weather_items = weather_by_date(bootstrap)
    current_time = now or datetime.now().astimezone()
    values: dict[date, dict[str, Any]] = defaultdict(
        lambda: {
            "public_holiday": False,
            "duty": False,
            "weather": "",
            "market_day": False,
            "family_events": 0,
            "zin_events": 0,
            "tasks": 0,
            "overdue_tasks": 0,
        }
    )
    for event in _items(bootstrap, "events"):
        value = _item_date(event, "startDate")
        if value is None:
            continue
        categories = {str(item).upper() for item in event.get("categories", [])}
        day_values = values[value]
        day_values["public_holiday"] = bool(day_values["public_holiday"] or event.get("publicHoliday"))
        day_values["duty"] = bool(day_values["duty"] or "당직" in str(event.get("summary") or ""))
        if "KAOS-MARKET-DAY" in categories:
            day_values["market_day"] = True
            continue
        if event.get("publicHoliday"):
            continue
        owner = collections.get(str(event.get("collection") or ""), {}).get("owner")
        if owner == "family":
            day_values["family_events"] += 1
        elif owner == "zin":
            day_values["zin_events"] += 1
    for task in _items(bootstrap, "tasks"):
        value = _item_date(task, "due")
        if value is None or str(task.get("status") or "").upper() == "COMPLETED":
            continue
        values[value]["tasks"] += 1
        if _task_is_overdue(task, current_time):
            values[value]["overdue_tasks"] += 1
    for value, marker in weather_items.items():
        values[value]["weather"] = marker
    return [
        MonthDayMarkers(
            value=value,
            public_holiday=bool(item["public_holiday"]),
            duty=bool(item["duty"]),
            weather=str(item["weather"]),
            market_day=bool(item["market_day"]),
            family_events=int(item["family_events"]),
            zin_events=int(item["zin_events"]),
            tasks=int(item["tasks"]),
            overdue_tasks=int(item["overdue_tasks"]),
        )
        for value, item in sorted(values.items())
    ]


def weather_items_by_date(bootstrap: Mapping[str, Any]) -> dict[date, Mapping[str, Any]]:
    values = {}
    for weather in _items(bootstrap, "weather"):
        value = _item_date(weather, "date")
        if value is not None:
            values[value] = weather
    return values


def weather_agenda_summary(weather: Mapping[str, Any]) -> str:
    marker = weather_marker(weather)
    temperature = weather_temperature_range(weather)
    if not marker and not temperature:
        return ""
    return " ".join(part for part in (marker, temperature) if part)


def weather_by_date(bootstrap: Mapping[str, Any]) -> dict[date, str]:
    return {value: weather_marker(weather) for value, weather in weather_items_by_date(bootstrap).items()}


def weather_temperature_range(weather: Mapping[str, Any]) -> str:
    low = compact_temperature(weather.get("minTemp"))
    high = compact_temperature(weather.get("maxTemp"))
    if low and high:
        return f"{low}-{high}℃"
    return ""


def compact_temperature(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(number)) if number.is_integer() else f"{number:.1f}".rstrip("0").rstrip(".")


def weather_marker(weather: Mapping[str, Any]) -> str:
    explicit = str(weather.get("emoji") or weather.get("icon") or "").strip()
    if explicit:
        return normalize_weather_marker(explicit) or explicit[:2]
    raw = str(
        weather.get("condition")
        or weather.get("summary")
        or weather.get("weather")
        or weather.get("code")
        or weather.get("glyph")
        or ""
    ).strip()
    if not raw:
        return ""
    return normalize_weather_marker(raw) or raw[:2]


def normalize_weather_marker(raw: str) -> str:
    value = raw.lower()
    if any(token in value for token in ("⛈", "⚡", "thunder", "storm", "lightning", "번개", "천둥")):
        return "⚡️"
    if any(token in value for token in ("❄", "snow", "sleet", "ice", "눈")):
        return "❄️"
    if any(token in value for token in ("🌧", "☔", "rain", "shower", "drizzle", "비")):
        return "🌧️"
    if any(token in value for token in ("🌫", "fog", "mist", "haze", "smoke", "안개")):
        return "🌫️"
    if any(token in value for token in ("☁", "🌤", "⛅", "cloud", "overcast", "흐림", "구름")):
        return "⛅️"
    if any(token in value for token in ("☀", "clear", "sun", "맑음", "sunny")):
        return "☀️"
    return ""


def _collections_by_id(bootstrap: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("id") or ""): item
        for item in _items(bootstrap, "collections")
        if str(item.get("id") or "")
    }


def _items(bootstrap: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    return [item for item in bootstrap.get(name, []) if isinstance(item, Mapping)]


def _item_date(item: Mapping[str, Any], key: str) -> date | None:
    try:
        raw = str(item.get(key) or "")
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def _task_is_overdue(task: Mapping[str, Any], current: datetime) -> bool:
    due = _item_date(task, "due")
    if due is None:
        return False
    today = current.date()
    if due < today:
        return True
    if due > today:
        return False
    due_time = _item_time(task, "dueTime")
    if due_time is None:
        return False
    due_at = datetime.combine(due, due_time)
    if current.tzinfo is not None:
        due_at = due_at.replace(tzinfo=current.tzinfo)
    return due_at <= current


def _item_time(item: Mapping[str, Any], key: str) -> time | None:
    raw = str(item.get(key) or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:5], "%H:%M").time()
    except ValueError:
        return None
