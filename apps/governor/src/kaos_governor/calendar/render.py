from __future__ import annotations

from dataclasses import dataclass
import calendar
from datetime import date
from io import BytesIO
from pathlib import Path


NORD = {
    "nord0": "#2e3440",
    "nord1": "#3b4252",
    "nord3": "#4c566a",
    "nord4": "#d8dee9",
    "nord6": "#eceff4",
    "nord8": "#88c0d0",
    "nord11": "#bf616a",
    "nord13": "#ebcb8b",
    "nord14": "#a3be8c",
    "nord15": "#b48ead",
}


@dataclass(frozen=True)
class MonthDayMarkers:
    value: date
    public_holiday: bool = False
    duty: bool = False
    weather: str = ""
    market_day: bool = False
    family_events: int = 0
    zin_events: int = 0
    tasks: int = 0
    overdue_tasks: int = 0


@dataclass(frozen=True)
class MonthRenderTheme:
    background: str = NORD["nord0"]
    panel: str = NORD["nord1"]
    surface: str = "#343b49"
    line: tuple[int, int, int, int] = (216, 222, 233, 38)
    line_strong: tuple[int, int, int, int] = (216, 222, 233, 70)
    text: str = NORD["nord6"]
    muted: str = NORD["nord4"]
    dim: str = "#a7b0c2"
    muted_day: str = "#687386"
    saturday: str = NORD["nord8"]
    holiday: str = NORD["nord11"]
    today_border: str = NORD["nord13"]
    duty: str = NORD["nord15"]
    weather: str = NORD["nord4"]
    market: str = NORD["nord8"]
    family: str = NORD["nord15"]
    zin: str = NORD["nord14"]
    task: str = NORD["nord13"]
    overdue_task: str = NORD["nord11"]


def render_month_png(
    *,
    year: int,
    month: int,
    today: date,
    markers: list[MonthDayMarkers] | None = None,
    width: int = 1200,
    height: int = 900,
    font_dir: Path | str = "/usr/share/fonts/truetype/dejavu",
    weather_font_path: Path | str | None = None,
    theme: MonthRenderTheme = MonthRenderTheme(),
) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("pillow_required_for_calendar_rendering") from exc

    marker_by_date = {item.value: item for item in markers or []}
    font_root = Path(font_dir)
    regular = font_root / "DejaVuSans.ttf"
    bold = font_root / "DejaVuSans-Bold.ttf"

    image = Image.new("RGB", (width, height), theme.background)
    draw = ImageDraw.Draw(image, "RGBA")

    day_font = _load_font(ImageFont, bold, 34)
    small_font = _load_font(ImageFont, bold, 22)
    marker_font = _load_font(ImageFont, bold, 28)
    weather_font = _load_font(ImageFont, _weather_font_path(weather_font_path), 46)

    def rounded(box, radius=8, fill=theme.surface, outline=theme.line, line_width=1):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=line_width)

    def text_at(x: int, y: int, value: object, fill=theme.text, font=small_font):
        draw.text((x, y), str(value), fill=fill, font=font)

    def dot(cx: int, cy: int, fill: str, radius: int = 5):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)

    rounded((32, 30, width - 32, height - 30), 10, theme.panel, theme.line_strong)

    left = 62
    top = 120
    gap = 6
    cell_width = (width - 124 - gap * 6) // 7
    cell_height = 115
    for index, name in enumerate(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")):
        text_at(left + index * (cell_width + gap) + cell_width // 2 - 22, 78, name, theme.dim, small_font)

    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    for row, week in enumerate(weeks):
        for col, value in enumerate(week):
            x = left + col * (cell_width + gap)
            y = top + row * (cell_height + gap)
            in_month = value.month == month
            item = marker_by_date.get(value, MonthDayMarkers(value=value))
            border = theme.line
            line_width = 1
            if value == today and in_month:
                border = theme.today_border
                line_width = 2
            elif in_month and item.duty:
                border = theme.duty
                line_width = 2
            rounded(
                (x, y, x + cell_width, y + cell_height),
                7,
                theme.surface if in_month else (67, 76, 94, 82),
                border,
                line_width,
            )

            text_at(x + 12, y + 10, value.day, _day_number_color(value, in_month, item, theme), day_font)
            day_bbox = draw.textbbox((x + 12, y + 10), str(value.day), font=day_font)
            if in_month and item.market_day:
                draw.rounded_rectangle(
                    (day_bbox[0] + 2, day_bbox[3] + 5, day_bbox[2] - 2, day_bbox[3] + 8),
                    radius=2,
                    fill=theme.market,
                )
            if in_month and item.weather:
                weather = weather_glyph(item.weather)
                if weather:
                    weather_bbox = draw.textbbox((0, 0), weather, font=weather_font)
                    weather_width = weather_bbox[2] - weather_bbox[0]
                    text_at(x + cell_width - 15 - weather_width, y + 9, weather, theme.weather, weather_font)

            markers_to_draw: list[tuple[str, str]] = []
            if in_month and item.family_events:
                markers_to_draw.append((str(item.family_events), theme.family))
            if in_month and item.zin_events:
                markers_to_draw.append((str(item.zin_events), theme.zin))
            if in_month and item.tasks:
                markers_to_draw.append((str(item.tasks), _task_marker_color(item, theme)))

            marker_width = sum(28 if value == "dot" else 36 for value, _color in markers_to_draw)
            marker_x = x + cell_width // 2 - marker_width // 2
            marker_y = y + cell_height - 40
            for marker_value, color in markers_to_draw:
                if marker_value == "dot":
                    dot(marker_x + 10, marker_y + 17, color, 9)
                    marker_x += 28
                else:
                    text_at(marker_x, marker_y, marker_value, color, marker_font)
                    marker_x += 36

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _day_number_color(value: date, in_month: bool, item: MonthDayMarkers, theme: MonthRenderTheme) -> str:
    if not in_month:
        return theme.muted_day
    if item.public_holiday or value.weekday() == 6:
        return theme.holiday
    if value.weekday() == 5:
        return theme.saturday
    return theme.text


def _task_marker_color(item: MonthDayMarkers, theme: MonthRenderTheme) -> str:
    return theme.overdue_task if item.overdue_tasks else theme.task


def _load_font(image_font, path: Path, size: int):
    try:
        return image_font.truetype(str(path), size)
    except OSError:
        try:
            return image_font.load_default(size=size)
        except TypeError:
            return image_font.load_default()


def _weather_font_path(path: Path | str | None) -> Path:
    if path:
        return Path(path)
    candidates = [
        Path("/usr/local/share/kaos-governor/fonts/SymbolsNerdFontMono-Regular.ttf"),
        Path(__file__).resolve().parents[5] / "apps" / "family-portal" / "fonts" / "SymbolsNerdFontMono-Regular.ttf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def weather_glyph(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if any(token in raw for token in ("⛈", "⚡", "thunder", "storm", "lightning", "번개", "천둥")):
        return "\ue31d"
    if any(token in raw for token in ("❄", "snow", "sleet", "ice", "눈")):
        return "\ue31a"
    if any(token in raw for token in ("🌧", "☔", "rain", "shower", "drizzle", "비")):
        return "\ue318"
    if any(token in raw for token in ("☁", "overcast", "cloud", "흐림", "구름")):
        return "\ue312"
    if any(token in raw for token in ("🌤", "⛅", "part", "few")):
        return "\ue302"
    if any(token in raw for token in ("🌫", "fog", "mist", "haze", "smoke", "안개")):
        return "\ue313"
    if any(token in raw for token in ("☀", "clear", "sun", "맑음", "sunny")):
        return "\ue30d"
    return "\ue371"
