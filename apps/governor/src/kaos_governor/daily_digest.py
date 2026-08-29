from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import urllib.parse
from zoneinfo import ZoneInfo

from .calendar import CalendarAdapterClient
from .daily_content import DailyContentLibrary, render_quote


KST = ZoneInfo("Asia/Seoul")
WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# These are original Korean paraphrases keyed to Bible references, not excerpts
# from a licensed Korean Bible translation.
VERSE_ROTATION = (
    ("여호수아 1:9", "강하고 담대하세요. 어디로 가든 하나님이 함께하십니다."),
    ("시편 23:1", "하나님이 목자가 되어 주시니 오늘 필요한 것을 맡겨도 됩니다."),
    ("이사야 41:10", "두려워하지 마세요. 하나님이 붙들고 힘을 더해 주십니다."),
    ("빌립보서 4:13", "힘을 주시는 분 안에서 오늘 맡은 일을 감당할 수 있습니다."),
    ("마태복음 11:28", "지치고 무거운 마음을 하나님께 가져가 쉼을 얻으세요."),
    ("잠언 3:5-6", "내 판단만 의지하지 말고 하나님을 신뢰하며 길을 맡기세요."),
    ("로마서 8:28", "하나님은 모든 일을 엮어 선한 방향으로 이끄십니다."),
    ("시편 46:1", "어려움 속에서도 하나님은 가까운 피난처와 힘이 되어 주십니다."),
    ("요한복음 14:27", "상황이 흔들려도 하나님이 주시는 평안을 마음에 지키세요."),
    ("베드로전서 5:7", "마음의 염려를 하나님께 맡기세요. 당신을 돌보고 계십니다."),
    ("시편 118:24", "오늘은 하나님이 주신 날입니다. 기쁨으로 한 걸음을 시작하세요."),
    ("갈라디아서 6:9", "선한 일을 하다 지치지 마세요. 때가 되면 열매를 거둡니다."),
    ("예레미야 29:11", "하나님은 평안과 소망을 향한 길을 준비하고 계십니다."),
    ("민수기 6:24-26", "하나님의 보호와 은혜와 평안이 오늘 함께하기를 바랍니다."),
)

ENCOURAGEMENT_ROTATION = (
    "완벽한 하루보다 다시 시작할 수 있는 하루가 더 강합니다.",
    "작은 한 걸음도 멈춰 있는 큰 계획보다 멀리 갑니다.",
    "오늘의 속도가 느려도 방향이 맞다면 충분히 전진하고 있습니다.",
    "할 수 있는 한 가지부터 시작하면 막막함은 길이 됩니다.",
    "쉬어 가는 것은 포기가 아니라 오래 가기 위한 선택입니다.",
    "어제보다 나아지는 데 필요한 것은 거대한 변화보다 꾸준한 반복입니다.",
    "마음이 흔들릴 때는 결과보다 오늘 지킬 한 가지에 집중하세요.",
    "용기는 두려움이 없는 상태가 아니라 두려움 속에서도 움직이는 힘입니다.",
    "좋은 하루는 모든 일이 쉬운 날이 아니라 중요한 것을 놓치지 않은 날입니다.",
    "지금 가진 것으로 시작하면 다음에 필요한 것이 보입니다.",
    "실수는 멈추라는 표지가 아니라 방법을 바꾸라는 안내입니다.",
    "비교를 내려놓으면 어제의 나보다 성장한 오늘이 보입니다.",
    "끝까지 가는 힘은 강한 의지보다 다시 돌아오는 습관에서 생깁니다.",
    "오늘 누군가에게 건넨 작은 친절은 생각보다 오래 남습니다.",
)
class DailyDigestError(ValueError):
    pass


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise DailyDigestError(f"{name} must be true or false")


def _positive_int(env: Mapping[str, str], name: str, default: int, maximum: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise DailyDigestError(f"{name} must be an integer") from exc
    if value < 1 or value > maximum:
        raise DailyDigestError(f"{name} must be between 1 and {maximum}")
    return value


def _send_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as exc:
        raise DailyDigestError("DAILY_DIGEST_TIME must be HH:MM") from exc
    if parsed.second or parsed.microsecond or len(value.strip()) != 5:
        raise DailyDigestError("DAILY_DIGEST_TIME must be HH:MM")
    return parsed


def _portal_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise DailyDigestError("DAILY_DIGEST_PORTAL_URL must be an HTTPS URL")
    return normalized


@dataclass(frozen=True)
class DailyDigestConfig:
    enabled: bool = False
    send_time: time = time(7, 0)
    profile: str = "main"
    weather_city: str = "pohang"
    portal_url: str = "https://kaosgdd.net"
    state_path: Path = Path("/data/notifications/daily-digest.json")
    content_cache_path: Path = Path("/data/notifications/daily-content.json")
    content_refresh_hours: int = 168
    content_timeout_seconds: int = 30
    poll_seconds: int = 30
    max_items: int = 5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "DailyDigestConfig":
        source = os.environ if env is None else env
        profile = source.get("DAILY_DIGEST_PROFILE", "main").strip().lower() or "main"
        if profile not in {"main", "family"}:
            raise DailyDigestError("DAILY_DIGEST_PROFILE must be main or family")
        weather_city = source.get("DAILY_DIGEST_WEATHER_CITY", "pohang").strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,40}", weather_city):
            raise DailyDigestError("DAILY_DIGEST_WEATHER_CITY invalid")
        default_portal_url = "https://family.kaosgdd.net" if profile == "family" else "https://kaosgdd.net"
        return cls(
            enabled=_bool(source, "DAILY_DIGEST_ENABLED"),
            send_time=_send_time(source.get("DAILY_DIGEST_TIME", "07:00")),
            profile=profile,
            weather_city=weather_city,
            portal_url=_portal_url(source.get("DAILY_DIGEST_PORTAL_URL", default_portal_url)),
            state_path=Path(
                source.get(
                    "DAILY_DIGEST_STATE_PATH",
                    "/data/notifications/daily-digest.json",
                )
            ),
            content_cache_path=Path(
                source.get(
                    "DAILY_DIGEST_CONTENT_CACHE_PATH",
                    "/data/notifications/daily-content.json",
                )
            ),
            content_refresh_hours=_positive_int(
                source,
                "DAILY_DIGEST_CONTENT_REFRESH_HOURS",
                168,
                8760,
            ),
            content_timeout_seconds=_positive_int(
                source,
                "DAILY_DIGEST_CONTENT_TIMEOUT_SECONDS",
                30,
                120,
            ),
            poll_seconds=_positive_int(source, "DAILY_DIGEST_POLL_SECONDS", 30, 3600),
            max_items=_positive_int(source, "DAILY_DIGEST_MAX_ITEMS", 5, 20),
        )


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _compact_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(number)) if number.is_integer() else f"{number:.1f}".rstrip("0").rstrip(".")


def _clean_title(value: object, limit: int = 72) -> str:
    title = " ".join(str(value or "").split()) or "Untitled"
    return title if len(title) <= limit else f"{title[: limit - 3]}..."


def _item_lines(
    items: list[Mapping[str, Any]],
    *,
    title_key: str,
    time_key: str,
    max_items: int,
) -> list[str]:
    ordered = sorted(
        items,
        key=lambda item: (
            str(item.get(time_key) or "99:99"),
            str(item.get(title_key) or ""),
        ),
    )
    lines = []
    for item in ordered[:max_items]:
        item_time = str(item.get(time_key) or "").strip()[:5]
        title = _clean_title(item.get(title_key))
        lines.append(f"- {item_time} {title}" if item_time else f"- {title}")
    if len(ordered) > max_items:
        lines.append(f"- +{len(ordered) - max_items} more")
    return lines or ["-"]


def render_daily_digest(
    *,
    day: date,
    weather: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    tasks: list[Mapping[str, Any]],
    max_items: int = 5,
    bible_line: str = "",
    quote_line: str = "",
) -> str:
    low = _compact_number(weather.get("minTemp"))
    high = _compact_number(weather.get("maxTemp"))
    glyph = str(weather.get("glyph") or weather.get("emoji") or "").strip()
    condition = str(weather.get("condition") or "Weather").replace("_", " ").strip()
    weather_label = " ".join(part for part in (glyph, condition) if part) or "Weather"
    temperatures = f" {low}-{high}°C" if low and high else ""
    verse_reference, verse_text = VERSE_ROTATION[day.toordinal() % len(VERSE_ROTATION)]
    selected_bible = bible_line or f"{verse_reference} — {verse_text}"
    selected_quote = quote_line or ENCOURAGEMENT_ROTATION[day.toordinal() % len(ENCOURAGEMENT_ROTATION)]
    content = ""
    for item_limit in range(max_items, 0, -1):
        event_lines = _item_lines(
            events,
            title_key="summary",
            time_key="startTime",
            max_items=item_limit,
        )
        task_lines = _item_lines(
            tasks,
            title_key="summary",
            time_key="dueTime",
            max_items=item_limit,
        )
        content = "\n".join(
            (
                f"# {day:%Y.%m.%d}({WEEKDAY_LABELS[day.weekday()]})",
                f"* {weather_label}{temperatures}",
                "",
                "### 일일 성경 말씀",
                selected_bible,
                "",
                "### 일일 힘을 주는 명언",
                selected_quote,
                "",
                "### Events",
                *event_lines,
                "",
                "### Tasks",
                *task_lines,
            )
        )
        if len(content) <= 1024:
            return content
    return f"{content[:1021]}..."


def _replace_section_line(content: str, heading: str, value: str) -> str:
    lines = content.splitlines()
    try:
        index = lines.index(heading)
    except ValueError as exc:
        raise DailyDigestError("daily_digest_section_missing") from exc
    if index + 1 >= len(lines):
        raise DailyDigestError("daily_digest_section_value_missing")
    lines[index + 1] = value
    rendered = "\n".join(lines)
    if len(rendered) > 1024:
        raise DailyDigestError("daily_digest_content_too_long")
    return rendered


def digest_day(content: str) -> date:
    first_line = content.splitlines()[0] if content.splitlines() else ""
    match = re.fullmatch(r"# (\d{4})\.(\d{2})\.(\d{2})\([A-Z][a-z]{2}\)", first_line)
    if match is None:
        raise DailyDigestError("daily_digest_date_missing")
    try:
        return date(*(int(value) for value in match.groups()))
    except ValueError as exc:
        raise DailyDigestError("daily_digest_date_invalid") from exc


def digest_events(content: str) -> list[str]:
    lines = content.splitlines()
    try:
        start = lines.index("### Events") + 1
    except ValueError:
        return []
    events = []
    for line in lines[start:]:
        if line.startswith("### "):
            break
        value = line.removeprefix("- ").strip()
        if value and value != "-" and not value.startswith("+"):
            events.append(value)
    return events


class DailyDigestService:
    def __init__(self, config: DailyDigestConfig, adapter: CalendarAdapterClient) -> None:
        self.config = config
        self.adapter = adapter
        self.content = DailyContentLibrary(
            cache_path=config.content_cache_path,
            refresh_hours=config.content_refresh_hours,
            timeout_seconds=config.content_timeout_seconds,
            fallback_bible=VERSE_ROTATION,
            fallback_quotes=ENCOURAGEMENT_ROTATION,
        )
        self._lock = threading.RLock()
        self.last_error = ""

    def _load(self) -> dict[str, object]:
        try:
            value = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _save(self, state: dict[str, object]) -> None:
        state["version"] = 1
        _atomic_json(self.config.state_path, state)

    def initialize(self, now: datetime | None = None) -> None:
        if not self.config.enabled:
            return
        current = now or datetime.now(KST)
        with self._lock:
            state = self._load()
            if state.get("initialized"):
                return
            state["initialized"] = True
            state["initializedAt"] = current.isoformat()
            if current.timetz().replace(tzinfo=None) >= self.config.send_time:
                state["lastSentDate"] = current.date().isoformat()
                state["lastStatus"] = "baselined"
            self._save(state)

    def is_due(self, now: datetime | None = None) -> bool:
        if not self.config.enabled:
            return False
        current = now or datetime.now(KST)
        if current.timetz().replace(tzinfo=None) < self.config.send_time:
            return False
        with self._lock:
            state = self._load()
        return bool(state.get("initialized")) and state.get("lastSentDate") != current.date().isoformat()

    def build(self, day: date) -> str:
        bootstrap = self.adapter.bootstrap(self.config.profile)
        weather_payload = self.adapter.month_weather(
            self.config.profile,
            start=day.isoformat(),
            end=day.isoformat(),
            city=self.config.weather_city,
        )
        weather = next(
            (
                item
                for item in weather_payload.get("items", [])
                if isinstance(item, Mapping) and str(item.get("date") or "") == day.isoformat()
            ),
            None,
        )
        if weather is None:
            raise DailyDigestError("daily_digest_weather_unavailable")
        events = [
            item
            for item in bootstrap.get("events", [])
            if isinstance(item, Mapping) and str(item.get("startDate") or "") == day.isoformat()
        ]
        tasks = [
            item
            for item in bootstrap.get("tasks", [])
            if isinstance(item, Mapping)
            and str(item.get("due") or "") == day.isoformat()
            and str(item.get("status") or "").upper() != "COMPLETED"
        ]
        bible, quote = self.content.for_day(day.toordinal())
        return render_daily_digest(
            day=day,
            weather=weather,
            events=events,
            tasks=tasks,
            max_items=self.config.max_items,
            bible_line=bible.render(),
            quote_line=render_quote(quote),
        )

    def refresh_content(self, *, force: bool = False) -> dict[str, object]:
        return self.content.refresh(force=force)

    def cycle_content(self, content: str, kind: str) -> str:
        if kind == "bible":
            heading = "### 일일 성경 말씀"
            current = _section_line(content, heading)
            return _replace_section_line(content, heading, self.content.next_bible(current).render())
        if kind == "quote":
            heading = "### 일일 힘을 주는 명언"
            current = _section_line(content, heading)
            return _replace_section_line(content, heading, render_quote(self.content.next_quote(current)))
        raise DailyDigestError("daily_digest_cycle_kind_invalid")

    def weather_url(self, day: date) -> str:
        return f"{self.config.portal_url}/#/calendar?weather={day.isoformat()}"

    def last_message_id(self) -> int:
        with self._lock:
            value = self._load().get("lastMessageId")
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def last_sent_day(self) -> date | None:
        with self._lock:
            value = str(self._load().get("lastSentDate") or "")
        try:
            return date.fromisoformat(value) if value else None
        except ValueError:
            return None

    def record_sent(self, day: date, *, message_id: int = 0) -> None:
        with self._lock:
            state = self._load()
            state["initialized"] = True
            state["lastSentDate"] = day.isoformat()
            state["lastSentAt"] = datetime.now(KST).isoformat()
            state["lastMessageId"] = str(message_id or "")
            state["lastStatus"] = "sent"
            state["lastError"] = ""
            self._save(state)
            self.last_error = ""

    def record_error(self, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            state = self._load()
            state["lastError"] = error
            state["lastStatus"] = "failed"
            self._save(state)
            self.last_error = error

    def status(self) -> dict[str, object]:
        with self._lock:
            state = self._load()
        return {
            "enabled": self.config.enabled,
            "time": self.config.send_time.strftime("%H:%M"),
            "timezone": "Asia/Seoul",
            "profile": self.config.profile,
            "weatherCity": self.config.weather_city,
            "portalUrl": self.config.portal_url,
            "statePath": str(self.config.state_path),
            "initialized": bool(state.get("initialized")),
            "lastSentDate": str(state.get("lastSentDate") or ""),
            "lastSentAt": str(state.get("lastSentAt") or ""),
            "lastMessageId": str(state.get("lastMessageId") or ""),
            "lastStatus": str(state.get("lastStatus") or ""),
            "lastError": str(state.get("lastError") or self.last_error),
            "content": self.content.status(),
        }


def _section_line(content: str, heading: str) -> str:
    lines = content.splitlines()
    try:
        index = lines.index(heading)
    except ValueError as exc:
        raise DailyDigestError("daily_digest_section_missing") from exc
    if index + 1 >= len(lines):
        raise DailyDigestError("daily_digest_section_value_missing")
    return lines[index + 1]
