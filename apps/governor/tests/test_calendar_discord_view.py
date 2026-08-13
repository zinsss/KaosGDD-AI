from datetime import date
import unittest

from kaos_governor.calendar.discord_view import (
    CalendarViewState,
    apply_calendar_command,
    parse_calendar_command,
    reset_idle_state,
)


TODAY = date(2026, 8, 13)


class CalendarDiscordViewTests(unittest.TestCase):
    def state(self) -> CalendarViewState:
        return CalendarViewState(visible_year=2026, visible_month=8)

    def test_month_command_accepts_only_bare_01_to_12(self) -> None:
        command = parse_calendar_command("08", state=self.state(), today=TODAY)
        updated = apply_calendar_command(self.state(), command)

        self.assertEqual(command.kind, "month")
        self.assertEqual(updated.visible_month, 8)
        self.assertEqual(updated.agenda_mode, "upcoming")

    def test_bare_13_to_99_is_invalid_and_should_be_deleted(self) -> None:
        for value in ("13", "31", "99"):
            command = parse_calendar_command(value, state=self.state(), today=TODAY)
            self.assertEqual(command.kind, "invalid")
            self.assertTrue(command.delete_user_message)

    def test_dot_day_uses_visible_month(self) -> None:
        command = parse_calendar_command(".17", state=self.state(), today=TODAY)
        updated = apply_calendar_command(self.state(), command)

        self.assertEqual(command.kind, "day")
        self.assertEqual(updated.visible_year, 2026)
        self.assertEqual(updated.visible_month, 8)
        self.assertEqual(updated.agenda_mode, "day")
        self.assertEqual(updated.agenda_date, date(2026, 8, 17))

    def test_month_day_updates_month_grid_when_target_month_differs(self) -> None:
        command = parse_calendar_command("9.17", state=self.state(), today=TODAY)
        updated = apply_calendar_command(self.state(), command)

        self.assertEqual(command.kind, "day")
        self.assertEqual(updated.visible_year, 2026)
        self.assertEqual(updated.visible_month, 9)
        self.assertEqual(updated.agenda_date, date(2026, 9, 17))

    def test_full_and_short_year_month_day_are_supported(self) -> None:
        full = parse_calendar_command("2027.09.10", state=self.state(), today=TODAY)
        short = parse_calendar_command("27.09.10", state=self.state(), today=TODAY)

        self.assertEqual(apply_calendar_command(self.state(), full).agenda_date, date(2027, 9, 10))
        self.assertEqual(apply_calendar_command(self.state(), short).agenda_date, date(2027, 9, 10))

    def test_impossible_dates_are_invalid(self) -> None:
        command = parse_calendar_command("2.31", state=self.state(), today=TODAY)

        self.assertEqual(command.kind, "invalid")

    def test_idle_reset_returns_home_to_today_month_and_upcoming_agenda(self) -> None:
        state = reset_idle_state(today=TODAY)

        self.assertEqual(state.visible_year, 2026)
        self.assertEqual(state.visible_month, 8)
        self.assertEqual(state.agenda_mode, "upcoming")
        self.assertIsNone(state.agenda_date)


if __name__ == "__main__":
    unittest.main()
