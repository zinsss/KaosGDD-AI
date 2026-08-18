from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import threading
from typing import Any

from .calendar import GeneratedCalendarSettings


class GovernorSettingsError(ValueError):
    """Raised when a settings payload is invalid."""


@dataclass(frozen=True)
class CalendarSettingsRecord:
    settings: GeneratedCalendarSettings
    version: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "calendar",
            "version": self.version,
            "settings": self.settings.as_settings_payload(),
        }


class MemoryGovernorSettingsStore:
    """Deterministic settings store used until PostgreSQL wiring is active."""

    def __init__(self, calendar: GeneratedCalendarSettings | None = None) -> None:
        self._lock = threading.RLock()
        self._calendar = CalendarSettingsRecord(calendar or GeneratedCalendarSettings())

    def get_calendar(self) -> CalendarSettingsRecord:
        with self._lock:
            return self._calendar

    def update_calendar(self, payload: Mapping[str, Any]) -> CalendarSettingsRecord:
        current = self.get_calendar().settings.as_settings_payload()
        next_payload = {**current, **dict(payload)}
        settings = GeneratedCalendarSettings.from_mapping(next_payload)
        with self._lock:
            self._calendar = CalendarSettingsRecord(settings=settings, version=self._calendar.version + 1)
            return self._calendar
