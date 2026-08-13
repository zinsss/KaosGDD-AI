from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import re
from typing import Literal


AgendaMode = Literal["upcoming", "day"]
CommandKind = Literal["month", "day", "year", "invalid"]


@dataclass(frozen=True)
class CalendarViewState:
    visible_year: int
    visible_month: int
    agenda_mode: AgendaMode = "upcoming"
    agenda_date: date | None = None


@dataclass(frozen=True)
class CalendarCommand:
    kind: CommandKind
    year: int | None = None
    month: int | None = None
    day: int | None = None
    delete_user_message: bool = True


def parse_calendar_command(raw: str, *, state: CalendarViewState, today: date) -> CalendarCommand:
    value = str(raw or "").strip()
    if not value:
        return CalendarCommand(kind="invalid")

    if re.fullmatch(r"0?[1-9]|1[0-2]", value):
        return CalendarCommand(kind="month", year=state.visible_year, month=int(value))

    if re.fullmatch(r"1[3-9]|[2-9]\d", value):
        return CalendarCommand(kind="invalid")

    match = re.fullmatch(r"\.(\d{1,2})", value)
    if match:
        return _day_command(state.visible_year, state.visible_month, int(match.group(1)))

    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", value)
    if match:
        return _day_command(today.year, int(match.group(1)), int(match.group(2)))

    match = re.fullmatch(r"(\d{2}|\d{4})\.(\d{1,2})\.(\d{1,2})", value)
    if match:
        year = int(match.group(1))
        if year < 100:
            year += 2000
        return _day_command(year, int(match.group(2)), int(match.group(3)))

    if re.fullmatch(r"\d{4}", value):
        return CalendarCommand(kind="year", year=int(value))

    return CalendarCommand(kind="invalid")


def apply_calendar_command(state: CalendarViewState, command: CalendarCommand) -> CalendarViewState:
    if command.kind == "month" and command.year and command.month:
        return replace(state, visible_year=command.year, visible_month=command.month)
    if command.kind == "day" and command.year and command.month and command.day:
        target = date(command.year, command.month, command.day)
        return replace(
            state,
            visible_year=target.year,
            visible_month=target.month,
            agenda_mode="day",
            agenda_date=target,
        )
    if command.kind == "year" and command.year:
        return replace(state, visible_year=command.year)
    return state


def reset_idle_state(*, today: date) -> CalendarViewState:
    return CalendarViewState(
        visible_year=today.year,
        visible_month=today.month,
        agenda_mode="upcoming",
        agenda_date=None,
    )


def _day_command(year: int, month: int, day: int) -> CalendarCommand:
    try:
        date(year, month, day)
    except ValueError:
        return CalendarCommand(kind="invalid")
    return CalendarCommand(kind="day", year=year, month=month, day=day)
