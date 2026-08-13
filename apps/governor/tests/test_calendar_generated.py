from datetime import date
import unittest

from kaos_governor.calendar import generated


class GeneratedCalendarDateTests(unittest.TestCase):
    def test_market_days_are_fixed_dates_on_every_weekday(self) -> None:
        values = generated.market_dates(2026)

        self.assertEqual({value.day for value in values}, {5, 10, 15, 20, 25, 30})
        self.assertTrue(any(value.weekday() == 5 for value in values))
        self.assertTrue(any(value.weekday() != 5 for value in values))

    def test_market_saturday_moves_claim_to_saturday(self) -> None:
        self.assertEqual(
            generated.claim_date_for_friday(date(2026, 1, 9)),
            date(2026, 1, 10),
        )

    def test_public_market_saturday_keeps_claim_on_friday(self) -> None:
        self.assertEqual(
            generated.claim_date_for_friday(date(2026, 1, 9), {date(2026, 1, 10)}),
            date(2026, 1, 9),
        )

    def test_public_friday_moves_claim_backward_repeatedly(self) -> None:
        public = {date(2026, 1, 1), date(2026, 1, 2)}

        self.assertEqual(generated.claim_date_for_friday(date(2026, 1, 2), public), date(2025, 12, 31))

    def test_market_display_setting_does_not_change_claim_rule(self) -> None:
        items = generated.desired_events(
            [2026],
            set(),
            {"marketDaysEnabled": False, "claimDayEnabled": True},
        )

        self.assertFalse(any(generated.MARKET_CATEGORY in item["categories"] for item in items))
        claim = next(item for item in items if item["uid"] == "KAOS-CLAIM-WEEK-2026-01-09")
        self.assertEqual(claim["startDate"], "2026-01-10")

    def test_uids_stay_compatible_with_existing_generated_events(self) -> None:
        self.assertEqual(generated.market_uid(date(2026, 8, 30)), "KAOS-MARKET-2026-08-30")
        self.assertEqual(generated.claim_uid(date(2026, 8, 28)), "KAOS-CLAIM-WEEK-2026-08-28")
        self.assertEqual(generated.uid_year("KAOS-CLAIM-WEEK-2026-08-28"), 2026)
        self.assertIsNone(generated.uid_year("KAOS-MANUAL-2026-08-28"))

    def test_event_match_accepts_adapter_field_names_and_category_order(self) -> None:
        wanted = generated.market_event(date(2026, 1, 10))
        current = {
            "uid": wanted["uid"],
            "summary": wanted["title"],
            "description": wanted["memo"],
            "startDate": wanted["startDate"],
            "categories": list(reversed(wanted["categories"])),
        }

        self.assertTrue(generated.event_matches(current, wanted))


if __name__ == "__main__":
    unittest.main()
