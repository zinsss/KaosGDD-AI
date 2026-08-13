from datetime import date
from io import BytesIO
import unittest

from PIL import Image

from kaos_governor.calendar.render import MonthDayMarkers, MonthRenderTheme, _day_number_color, render_month_png


class CalendarRenderTests(unittest.TestCase):
    def test_month_renderer_returns_png_for_month_image_only(self) -> None:
        png = render_month_png(year=2026, month=8, today=date(2026, 8, 13))

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (1200, 900))
            self.assertEqual(image.mode, "RGB")

    def test_month_renderer_falls_back_when_font_files_are_absent(self) -> None:
        png = render_month_png(
            year=2026,
            month=8,
            today=date(2026, 8, 13),
            font_dir="/tmp/kaos-missing-fonts",
        )

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_day_number_color_priority_matches_legacy_calendar(self) -> None:
        theme = MonthRenderTheme(
            text="#ffffff",
            saturday="#0000ff",
            holiday="#ff0000",
            muted_day="#888888",
        )
        self.assertEqual(
            _day_number_color(date(2026, 8, 12), True, MonthDayMarkers(date(2026, 8, 12)), theme),
            "#ffffff",
        )
        self.assertEqual(
            _day_number_color(date(2026, 8, 15), True, MonthDayMarkers(date(2026, 8, 15)), theme),
            "#0000ff",
        )
        self.assertEqual(
            _day_number_color(date(2026, 8, 16), True, MonthDayMarkers(date(2026, 8, 16)), theme),
            "#ff0000",
        )
        self.assertEqual(
            _day_number_color(date(2026, 8, 17), True, MonthDayMarkers(date(2026, 8, 17), public_holiday=True), theme),
            "#ff0000",
        )
        self.assertEqual(
            _day_number_color(date(2026, 7, 31), False, MonthDayMarkers(date(2026, 7, 31)), theme),
            "#888888",
        )

    def test_markers_render_without_agenda_content(self) -> None:
        png = render_month_png(
            year=2026,
            month=8,
            today=date(2026, 8, 13),
            markers=[
                MonthDayMarkers(
                    value=date(2026, 8, 4),
                    duty=True,
                ),
                MonthDayMarkers(
                    value=date(2026, 8, 13),
                    weather="☁",
                    market_day=True,
                    family_events=2,
                    zin_events=1,
                    tasks=3,
                )
            ],
        )

        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size[1], 900)
            august_13_x = 62 + 4 * 154
            august_13_y = 120 + 2 * 121
            august_4_x = 62 + 2 * 154
            august_4_y = 120 + 1 * 121

            self.assertEqual(image.getpixel((august_13_x + 126, august_13_y + 28)), (136, 192, 208))
            self.assertNotEqual(image.getpixel((august_13_x + 58, august_13_y + 29)), (136, 192, 208))
            self.assertEqual(
                image.getpixel((august_4_x + 126, august_4_y + 28)),
                image.getpixel((august_4_x + 95, august_4_y + 28)),
            )
            self.assertEqual(image.getpixel((72, 830)), (52, 59, 73))
            self.assertEqual(image.getpixel((72, 860)), (59, 66, 82))


if __name__ == "__main__":
    unittest.main()
