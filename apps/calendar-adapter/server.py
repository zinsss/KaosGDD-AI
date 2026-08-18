#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORT = int(os.environ.get("PORT", "8091"))
STATE_DIR = os.environ.get("CALENDAR_ADAPTER_STATE_DIR", "/data/calendar-adapter-state")
EVENT_PRESETS_FILE = os.path.join(STATE_DIR, "event-presets.json")
RECURRING_TASKS_FILE = os.path.join(STATE_DIR, "recurring-tasks.json")
RADICALE_URL = os.environ.get("RADICALE_INTERNAL_URL", "http://100.94.208.16:5232").rstrip("/")
RADICALE_USERNAME = os.environ.get("RADICALE_USERNAME", "")
RADICALE_PASSWORD = os.environ.get("RADICALE_PASSWORD", "")
RADICALE_FAMILY_USERNAME = os.environ.get("RADICALE_FAMILY_USERNAME", "")
RADICALE_FAMILY_PASSWORD = os.environ.get("RADICALE_FAMILY_PASSWORD", "")
RADICALE_WIFE_USERNAME = os.environ.get("RADICALE_WIFE_USERNAME", "")
RADICALE_WIFE_PASSWORD = os.environ.get("RADICALE_WIFE_PASSWORD", "")
RADICALE_SUPPLIES_USERNAME = os.environ.get("RADICALE_SUPPLIES_USERNAME", "")
RADICALE_SUPPLIES_PASSWORD = os.environ.get("RADICALE_SUPPLIES_PASSWORD", "")
RADICALE_SYSTEM_USERNAME = os.environ.get("RADICALE_SYSTEM_USERNAME", "")
RADICALE_SYSTEM_PASSWORD = os.environ.get("RADICALE_SYSTEM_PASSWORD", "")
RADICALE_SYSTEM_WEATHER_JOURNAL_NAME = os.environ.get("RADICALE_SYSTEM_WEATHER_JOURNAL_NAME", "Kaos_Weather")
RADICALE_SYSTEM_CAREGIVER_JOURNAL_NAME = os.environ.get("RADICALE_SYSTEM_CAREGIVER_JOURNAL_NAME", "Kaos_Caregiver")
RADICALE_SYSTEM_LOGS_JOURNAL_NAME = os.environ.get("RADICALE_SYSTEM_LOGS_JOURNAL_NAME", "Kaos_Logs")
RADICALE_FAMILY_CALENDAR_NAME = os.environ.get("RADICALE_FAMILY_CALENDAR_NAME", "Family")
RADICALE_GDD_CALENDAR_NAME = os.environ.get("RADICALE_GDD_CALENDAR_NAME", "Kaos_Calendar")
TIMEOUT = float(os.environ.get("KAOSGDD_ADAPTER_TIMEOUT_SECONDS", "30"))
LOCAL_TIMEZONE = timezone(timedelta(hours=int(os.environ.get("KAOSGDD_LOCAL_UTC_OFFSET_HOURS", "9"))))
LOCAL_TZID = os.environ.get("KAOSGDD_LOCAL_TZID", "Asia/Seoul")
MAX_POST_BYTES = 20000
WEATHER_CITIES = {
    "pohang": "포항",
    "daegu": "대구",
    "yeongcheon": "영천",
    "yeonghae": "영해",
    "yeongdeok": "영덕",
}
WEATHER_LOCATIONS = {
    "pohang": {"label": "포항", "latitude": 36.0190, "longitude": 129.3435},
    "daegu": {"label": "대구", "latitude": 35.8714, "longitude": 128.6014},
    "yeongcheon": {"label": "영천", "latitude": 35.9733, "longitude": 128.9389},
    "yeonghae": {"label": "영해", "latitude": 36.5372, "longitude": 129.3878},
    "yeongdeok": {"label": "영덕", "latitude": 36.4151, "longitude": 129.3650},
}
WEATHER_DEFAULT_CITY_KEYS = ("pohang", "daegu", "yeongcheon", "yeonghae")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
NOMINATIM_REVERSE_URL = os.environ.get(
    "KAOSGDD_NOMINATIM_REVERSE_URL",
    "https://nominatim.openstreetmap.org/reverse",
)
WEATHER_DAYPARTS = [
    ("Morning", range(6, 12)),
    ("Afternoon", range(12, 18)),
    ("Evening", range(18, 22)),
    ("Night", (*range(0, 6), *range(22, 24))),
]
WEATHER_CONDITION_SEVERITY = {
    "unknown": 0,
    "clear": 1,
    "partly_cloudy": 2,
    "cloudy": 3,
    "fog": 4,
    "rain": 5,
    "snow": 6,
    "thunderstorm": 7,
}
WEATHER_GLYPHS = {
    "clear": "☀️",
    "partly_cloudy": "🌤️",
    "cloudy": "☁️",
    "rain": "🌧️",
    "snow": "❄️",
    "thunderstorm": "⛈️",
    "fog": "🌫️",
    "unknown": "·",
}
OPEN_METEO_FORECAST_MAX_DAYS = 16
GOOGLE_HOLIDAY_CATEGORY = "KAOS-GOOGLE-HOLIDAY"
SYSTEM_EVENT_CATEGORY = "KAOS-SYSTEM"
PUBLIC_HOLIDAY_CATEGORY = "KAOS-PUBLIC-HOLIDAY"
OBSERVANCE_CATEGORY = "KAOS-OBSERVANCE"
GENERATED_EVENT_CATEGORY = "KAOS-GENERATED-CALENDAR"
MARKET_DAY_CATEGORY = "KAOS-MARKET-DAY"
MARKET_SATURDAY_CATEGORY = "KAOS-MARKET-SATURDAY"
CLAIM_DAY_CATEGORY = "KAOS-CLAIM-DAY"

SEOUL_VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Asia/Seoul
BEGIN:STANDARD
DTSTART:19881009T030000
TZNAME:GMT+9
TZOFFSETFROM:+1000
TZOFFSETTO:+0900
END:STANDARD
END:VTIMEZONE"""


def account(key, username, password, label):
    return {
        "key": key,
        "username": username,
        "password": password,
        "label": label,
        "configured": bool(RADICALE_URL and username and password),
    }


ACCOUNTS = {
    "zin": account("zin", RADICALE_USERNAME, RADICALE_PASSWORD, "GDD_ZiN"),
    "family": account("family", RADICALE_FAMILY_USERNAME, RADICALE_FAMILY_PASSWORD, "Family"),
    "wife": account("wife", RADICALE_WIFE_USERNAME, RADICALE_WIFE_PASSWORD, "Wife"),
    "supplies": account("supplies", RADICALE_SUPPLIES_USERNAME, RADICALE_SUPPLIES_PASSWORD, "Supplies"),
    "system": account("system", RADICALE_SYSTEM_USERNAME, RADICALE_SYSTEM_PASSWORD, "Kaos"),
}


def configured(profile="main"):
    return any(item["configured"] for item in profile_accounts(profile))


def profile_from_headers(headers):
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(":", 1)[0].lower()
    if host == "family.kaosgdd.net":
        return "family"
    if host == "supplies.kaosgdd.net":
        return "supplies"
    return "main"


def profile_accounts(profile):
    if profile == "family":
        keys = ["family"]
    elif profile == "supplies":
        keys = ["supplies"]
    else:
        keys = ["zin", "family"]
    return [ACCOUNTS[key] for key in keys if ACCOUNTS[key]["configured"]]


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_request(handler):
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0 or length > MAX_POST_BYTES:
        raise ValueError("invalid_body_length")
    body = handler.rfile.read(length).decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("invalid_json_payload")
    return payload


def radicale_request(account, method, path, body="", headers=None):
    url = urllib.parse.urljoin(f"{RADICALE_URL}/", path.lstrip("/"))
    request = urllib.request.Request(url, data=body.encode("utf-8"), method=method)
    token = base64.b64encode(f"{account['username']}:{account['password']}".encode("utf-8")).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("User-Agent", "KaosGDD-CalendarAdapter/0.1")
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def propfind_collections(account):
    body = """<?xml version="1.0" encoding="utf-8" ?>
<propfind xmlns="DAV:" xmlns:cs="http://calendarserver.org/ns/" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <prop>
    <displayname />
    <resourcetype />
    <cs:getctag />
    <cal:supported-calendar-component-set />
  </prop>
</propfind>"""
    _, xml = radicale_request(
        account,
        "PROPFIND",
        f"/{account['username']}/",
        body,
        {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
    )
    return parse_collections(xml, account)


def parse_collections(xml, account):
    root = ET.fromstring(xml)
    namespace = {"d": "DAV:", "cal": "urn:ietf:params:xml:ns:caldav", "cs": "http://calendarserver.org/ns/"}
    collections = []

    for response in root.findall("d:response", namespace):
        href = text_of(response, "d:href", namespace)
        if not href or href.rstrip("/") == f"/{account['username']}":
            continue

        resourcetype = response.find(".//d:resourcetype", namespace)
        if resourcetype is None:
            continue

        is_calendar = resourcetype.find("cal:calendar", namespace) is not None or resourcetype.find("d:collection", namespace) is not None
        if not is_calendar:
            continue

        collection_id = href.strip("/").split("/")[-1] or href.strip("/")
        display_name = text_of(response, ".//d:displayname", namespace) or collection_id
        components = [
            (item.attrib.get("name") or "").upper()
            for item in response.findall(".//cal:supported-calendar-component-set/cal:comp", namespace)
            if item.attrib.get("name")
        ]
        collections.append(
            {
                "id": f"{account['key']}:{collection_id}",
                "rawId": collection_id,
                "name": display_name,
                "owner": account["key"],
                "ownerLabel": account["label"],
                "href": href,
                "components": components,
            }
        )

    return collections


def text_of(element, selector, namespace):
    item = element.find(selector, namespace)
    if item is None or item.text is None:
        return ""
    return item.text.strip()


def report_collection(account, href):
    body = """<?xml version="1.0" encoding="utf-8" ?>
<calendar-query xmlns="urn:ietf:params:xml:ns:caldav" xmlns:d="DAV:">
  <d:prop>
    <d:getetag />
    <calendar-data />
  </d:prop>
  <filter>
    <comp-filter name="VCALENDAR" />
  </filter>
</calendar-query>"""
    _, xml = radicale_request(
        account,
        "REPORT",
        href,
        body,
        {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
    )
    return parse_calendar_data(xml)


def parse_calendar_data(xml):
    root = ET.fromstring(xml)
    namespace = {"d": "DAV:", "cal": "urn:ietf:params:xml:ns:caldav"}
    calendars = []
    for response in root.findall("d:response", namespace):
        href = text_of(response, "d:href", namespace)
        etag = text_of(response, ".//d:getetag", namespace)
        calendar_data = text_of(response, ".//cal:calendar-data", namespace)
        if calendar_data:
            calendars.extend(parse_ics(calendar_data, href, etag))
    return calendars


def parse_ics(data, href, etag=""):
    lines = unfold_ics(data)
    items = []
    current = None
    alarm_depth = 0
    alarm_lines = None

    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {"component": "VEVENT", "href": href, "etag": etag, "_raw_properties": [], "_subcomponents": []}
        elif line == "BEGIN:VTODO":
            current = {"component": "VTODO", "href": href, "etag": etag, "_raw_properties": [], "_subcomponents": []}
        elif line == "BEGIN:VJOURNAL":
            current = {"component": "VJOURNAL", "href": href, "etag": etag, "_raw_properties": [], "_subcomponents": []}
        elif current is not None and line == "BEGIN:VALARM":
            alarm_depth = 1
            alarm_lines = [line]
        elif alarm_depth:
            alarm_lines.append(line)
            if line.startswith("BEGIN:"):
                alarm_depth += 1
            elif line.startswith("END:"):
                alarm_depth = max(0, alarm_depth - 1)
                if alarm_depth == 0:
                    current["_subcomponents"].append(alarm_lines)
                    alarm_lines = None
        elif line in {"END:VEVENT", "END:VTODO", "END:VJOURNAL"}:
            if current:
                items.append(current)
            current = None
        elif current is not None:
            current["_raw_properties"].append(line)
            name, value = parse_property(line)
            if name:
                current[name] = value

    return items


def unfold_ics(data):
    unfolded = []
    for raw in data.splitlines():
        if raw.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += raw[1:]
        else:
            unfolded.append(raw.rstrip("\r"))
    return unfolded


def parse_property(line):
    if ":" not in line:
        return "", ""
    name, value = line.split(":", 1)
    name = name.split(";", 1)[0].upper()
    return name, unescape_ics(value)


def unescape_ics(value):
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def escape_ics(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold_ics_line(line):
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    folded = []
    current = ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > 75:
            folded.append(current)
            current = f" {char}"
        else:
            current = candidate
    folded.append(current)
    return "\r\n".join(folded)


def calendar_body(lines):
    return "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"


def normalize_event(item, collection):
    start = item.get("DTSTART", "")
    parsed = parse_ics_datetime(start)
    all_day = property_has_parameter(item, "DTSTART", "VALUE", "DATE") or bool(start and "T" not in start)
    parsed_end = parse_ics_datetime(item.get("DTEND", ""))
    end_date = parsed_end["date"]
    if all_day and end_date:
        end_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    repeat, preserve_repeat = normalized_repeat(item.get("RRULE", ""))
    has_recurrence_exceptions = bool(property_lines(item, "RDATE") or property_lines(item, "EXDATE"))
    if has_recurrence_exceptions:
        repeat = "custom"
        preserve_repeat = True
    alarm_time, preserve_alarm = normalized_alarm(item)
    start_timezone = property_parameter(item, "DTSTART", "TZID")
    editable_timezone = all_day or not start_timezone or start_timezone == LOCAL_TZID
    unsupported_duration = bool(item.get("DURATION") and not item.get("DTEND"))
    categories = [part.strip() for part in item.get("CATEGORIES", "").split(",") if part.strip()]
    system_managed = SYSTEM_EVENT_CATEGORY in categories or GOOGLE_HOLIDAY_CATEGORY in categories
    editable = (
        bool(parsed["date"])
        and not item.get("_unsafe_multiple")
        and not item.get("RECURRENCE-ID")
        and not has_recurrence_exceptions
        and not unsupported_duration
        and editable_timezone
        and not system_managed
    )
    return {
        "uid": item.get("UID") or item.get("href"),
        "collection": collection["id"],
        "summary": item.get("SUMMARY", "Untitled event"),
        "description": item.get("DESCRIPTION", ""),
        "dtstart": parsed["iso"] or start,
        "dtend": parsed_end["iso"],
        "startDate": parsed["date"],
        "startTime": "" if all_day else parsed["time"],
        "endDate": end_date or parsed["date"],
        "endTime": "" if all_day else parsed_end["time"],
        "allDay": all_day,
        "repeat": repeat,
        "preserveRepeat": preserve_repeat,
        "alarmTime": alarm_time,
        "preserveAlarm": preserve_alarm,
        "editable": editable,
        "editReason": "" if editable else ("system_event_readonly" if system_managed else "event_requires_native_client"),
        "location": item.get("LOCATION", ""),
        "status": item.get("STATUS", ""),
        "created": parse_ics_datetime(item.get("CREATED", ""))["iso"],
        "lastModified": parse_ics_datetime(item.get("LAST-MODIFIED", ""))["iso"],
        "categories": categories,
        "systemManaged": system_managed,
        "publicHoliday": PUBLIC_HOLIDAY_CATEGORY in categories,
        "observance": OBSERVANCE_CATEGORY in categories,
    }


def property_lines(item, property_name):
    expected = property_name.upper()
    return [line for line in item.get("_raw_properties", []) if parse_property(line)[0] == expected]


def property_parameter(item, property_name, parameter_name):
    expected_property = property_name.upper()
    expected_parameter = parameter_name.upper()
    for line in item.get("_raw_properties", []):
        if ":" not in line:
            continue
        head = line.split(":", 1)[0]
        parts = head.split(";")
        if parts[0].upper() != expected_property:
            continue
        for part in parts[1:]:
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            if name.upper() == expected_parameter:
                return value.strip('"')
    return ""


def property_has_parameter(item, property_name, parameter_name, expected_value):
    return property_parameter(item, property_name, parameter_name).upper() == expected_value.upper()


def normalized_repeat(rrule):
    raw = str(rrule or "").strip().upper()
    simple = {
        "FREQ=WEEKLY": "weekly",
        "FREQ=MONTHLY": "monthly",
        "FREQ=YEARLY": "yearly",
    }
    if not raw:
        return "", False
    if raw in simple:
        return simple[raw], False
    return "custom", True


def normalized_alarm(item):
    subcomponents = item.get("_subcomponents", [])
    if not subcomponents:
        return "", False
    if len(subcomponents) != 1:
        return "", True
    for line in subcomponents[0]:
        if parse_property(line)[0] != "TRIGGER":
            continue
        trigger = parse_property(line)[1]
        if not re.fullmatch(r"\d{8}T\d{6}Z?", trigger):
            return "", True
        parsed = parse_ics_datetime(trigger)
        if parsed["time"]:
            return parsed["time"], False
        return "", True
    return "", True


def normalize_task(item, collection):
    categories = [part.strip() for part in item.get("CATEGORIES", "").split(",") if part.strip()]
    due = parse_ics_datetime(item.get("DUE", ""))
    return {
        "uid": item.get("UID") or item.get("href"),
        "collection": collection["id"],
        "summary": item.get("SUMMARY", "Untitled task"),
        "description": item.get("DESCRIPTION", ""),
        "due": due["date"],
        "dueTime": due["time"],
        "priority": item.get("PRIORITY", ""),
        "status": item.get("STATUS", "NEEDS-ACTION"),
        "completed": parse_ics_datetime(item.get("COMPLETED", ""))["iso"],
        "created": parse_ics_datetime(item.get("CREATED", ""))["iso"],
        "lastModified": parse_ics_datetime(item.get("LAST-MODIFIED", ""))["iso"],
        "categories": categories,
    }


def normalize_journal(item, collection):
    start = parse_ics_datetime(item.get("DTSTART", ""))
    return {
        "uid": item.get("UID") or item.get("href"),
        "collection": collection["id"],
        "summary": item.get("SUMMARY", "Untitled journal"),
        "description": item.get("DESCRIPTION", ""),
        "date": start["date"],
        "time": start["time"],
        "created": parse_ics_datetime(item.get("CREATED", ""))["iso"],
        "lastModified": parse_ics_datetime(item.get("LAST-MODIFIED", ""))["iso"],
        "categories": [part.strip() for part in item.get("CATEGORIES", "").split(",") if part.strip()],
    }


def parse_weather_description(description):
    try:
        parsed = json.loads(description or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_weather_journal(item, collection):
    journal = normalize_journal(item, collection)
    payload = parse_weather_description(journal["description"])
    return {
        "uid": journal["uid"],
        "collection": journal["collection"],
        "city": payload.get("city") or "",
        "cityName": payload.get("cityName") or "",
        "date": payload.get("date") or journal["date"],
        "minTemp": payload.get("minTemp"),
        "maxTemp": payload.get("maxTemp"),
        "glyph": payload.get("glyph") or "",
        "condition": payload.get("condition") or "",
        "source": payload.get("source") or "",
        "created": journal["created"],
        "lastModified": journal["lastModified"],
    }


def parse_ics_datetime(value):
    raw = value or ""
    is_utc = raw.endswith("Z")
    clean = re.sub(r"Z$", "", raw)
    if "T" in clean:
        if is_utc:
            local = datetime.strptime(clean[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone(LOCAL_TIMEZONE)
            iso = local.strftime("%Y-%m-%dT%H:%M:%S")
            return {"date": iso[:10], "time": iso[11:16], "iso": iso}
        return {"date": f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}", "time": f"{clean[9:11]}:{clean[11:13]}", "iso": f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}T{clean[9:11]}:{clean[11:13]}:00"}
    if len(clean) >= 8:
        return {"date": f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}", "time": "", "iso": f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"}
    return {"date": "", "time": "", "iso": ""}


def system_configured():
    return ACCOUNTS["system"]["configured"]


def system_collection(collection_name, component="VJOURNAL"):
    if not system_configured():
        raise ValueError("system_account_not_configured")
    account_item = ACCOUNTS["system"]
    collections = propfind_collections(account_item)
    for collection in collections:
        if collection.get("name") == collection_name and component in collection.get("components", []):
            return collection
    raise ValueError("system_collection_not_found")


def build_vjournal(payload):
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("summary_required")

    description = str(payload.get("description") or payload.get("memo") or "").strip()
    category = str(payload.get("category") or "system").strip()
    now_dt = datetime.now(timezone.utc)
    now = utc_stamp(now_dt)
    local_now = now_dt.astimezone(LOCAL_TIMEZONE).strftime("%Y%m%dT%H%M%S")
    uid = str(payload.get("uid") or uuid.uuid4()).upper()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "PRODID:-//KaosGDD//System Journal//EN",
        *SEOUL_VTIMEZONE.splitlines(),
        "BEGIN:VJOURNAL",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"CREATED:{now}",
        f"LAST-MODIFIED:{now}",
        f"DTSTART;TZID={LOCAL_TZID}:{local_now}",
        f"SUMMARY:{escape_ics(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{escape_ics(description)}")
    if category:
        lines.append(f"CATEGORIES:{escape_ics(category)}")
    lines.extend(["END:VJOURNAL", "END:VCALENDAR"])
    return uid, calendar_body(lines)


def list_system_logs():
    collection = system_collection(RADICALE_SYSTEM_LOGS_JOURNAL_NAME)
    logs = []
    for item in report_collection(ACCOUNTS["system"], collection["href"]):
        if item.get("component") == "VJOURNAL":
            logs.append(normalize_journal(item, collection))
    logs.sort(key=lambda item: f"{item.get('date', '')}T{item.get('time', '')}", reverse=True)
    return {"configured": True, "live": True, "collection": collection, "logs": logs}


def create_system_log(payload):
    collection = system_collection(RADICALE_SYSTEM_LOGS_JOURNAL_NAME)
    uid, body = build_vjournal(payload)
    href = urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    radicale_request(
        ACCOUNTS["system"],
        "PUT",
        href,
        body,
        {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
    )
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def validate_weather_city(value):
    city = str(value or "").strip().lower()
    if city not in WEATHER_CITIES:
        raise ValueError("invalid_weather_city")
    return city


def validate_temperature(value, field_name):
    if value is None or value == "":
        raise ValueError(f"{field_name}_required")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field_name}") from exc


def compact_number(value):
    number = float(value)
    return int(number) if number.is_integer() else number


def build_weather_vjournal(payload):
    city = validate_weather_city(payload.get("city"))
    date_value = validate_date(payload.get("date") or datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d"))
    min_temp = compact_number(validate_temperature(payload.get("minTemp"), "minTemp"))
    max_temp = compact_number(validate_temperature(payload.get("maxTemp"), "maxTemp"))
    glyph = str(payload.get("glyph") or "").strip()
    condition = str(payload.get("condition") or "").strip()
    source = str(payload.get("source") or "manual").strip()
    city_name = WEATHER_CITIES[city]
    uid = f"KAOS-WEATHER-{city.upper()}-{date_value.replace('-', '')}"
    now = utc_stamp(datetime.now(timezone.utc))
    description = json.dumps(
        {
            "type": "weather.daily",
            "city": city,
            "cityName": city_name,
            "date": date_value,
            "minTemp": min_temp,
            "maxTemp": max_temp,
            "glyph": glyph,
            "condition": condition,
            "source": source,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    summary = f"{city_name} {min_temp}-{max_temp}{(' ' + glyph) if glyph else ''}".strip()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "PRODID:-//KaosGDD//Weather Journal//EN",
        "BEGIN:VJOURNAL",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"CREATED:{now}",
        f"LAST-MODIFIED:{now}",
        f"DTSTART;VALUE=DATE:{compact_date(date_value)}",
        f"SUMMARY:{escape_ics(summary)}",
        f"DESCRIPTION:{escape_ics(description)}",
        f"CATEGORIES:weather,{city}",
        "END:VJOURNAL",
        "END:VCALENDAR",
    ]
    return uid, calendar_body(lines)


def list_weather_history():
    collection = system_collection(RADICALE_SYSTEM_WEATHER_JOURNAL_NAME)
    entries = []
    for item in report_collection(ACCOUNTS["system"], collection["href"]):
        if item.get("component") == "VJOURNAL":
            weather = normalize_weather_journal(item, collection)
            if weather["city"]:
                entries.append(weather)
    entries.sort(key=lambda item: f"{item.get('date', '')}:{item.get('city', '')}", reverse=True)
    return {"configured": True, "live": True, "collection": collection, "cities": WEATHER_CITIES, "weather": entries}


def create_weather_history(payload):
    collection = system_collection(RADICALE_SYSTEM_WEATHER_JOURNAL_NAME)
    uid, body = build_weather_vjournal(payload)
    href = urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    radicale_request(
        ACCOUNTS["system"],
        "PUT",
        href,
        body,
        {"Content-Type": "text/calendar; charset=utf-8"},
    )
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def validate_caregiver_month(value):
    month = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("invalid_caregiver_month")
    year, month_number = (int(part) for part in month.split("-", 1))
    if year < 2000 or year > 2200 or month_number < 1 or month_number > 12:
        raise ValueError("invalid_caregiver_month")
    return month


def validate_caregiver_time(value):
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        raise ValueError("invalid_caregiver_time")
    parsed = datetime.strptime(raw, "%H:%M")
    return raw, parsed.hour * 60 + parsed.minute


def normalize_caregiver_sessions(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 24:
        raise ValueError("invalid_caregiver_sessions")
    sessions = []
    for session in value:
        if not isinstance(session, dict):
            raise ValueError("invalid_caregiver_session")
        start, start_minutes = validate_caregiver_time(session.get("start"))
        end, end_minutes = validate_caregiver_time(session.get("end"))
        if end_minutes <= start_minutes:
            raise ValueError("caregiver_end_before_start")
        sessions.append({"start": start, "end": end})
    return sessions


def caregiver_amount(value, field_name):
    if value in (None, ""):
        return 0
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field_name}") from exc
    if amount < 0 or amount > 100_000_000:
        raise ValueError(f"invalid_{field_name}")
    return amount


def normalize_caregiver_extras(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 24:
        raise ValueError("invalid_caregiver_extras")
    extras = []
    for extra in value:
        if not isinstance(extra, dict):
            raise ValueError("invalid_caregiver_extra")
        label = str(extra.get("label") or "").strip()[:80]
        amount = caregiver_amount(extra.get("amount"), "caregiver_extra_amount")
        if label or amount:
            extras.append({"label": label, "amount": amount})
    return extras


def caregiver_journal_body(uid, date_value, summary, payload, categories):
    now = utc_stamp(datetime.now(timezone.utc))
    description = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return calendar_body(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "CALSCALE:GREGORIAN",
            "PRODID:-//KaosGDD//Caregiver Journal//EN",
            "BEGIN:VJOURNAL",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"CREATED:{now}",
            f"LAST-MODIFIED:{now}",
            f"DTSTART;VALUE=DATE:{date_value.replace('-', '')}",
            f"SUMMARY:{escape_ics(summary)}",
            f"DESCRIPTION:{escape_ics(description)}",
            f"CATEGORIES:{categories}",
            "END:VJOURNAL",
            "END:VCALENDAR",
        ]
    )


def build_caregiver_day_vjournal(payload):
    date_value = validate_date(payload.get("date"))
    if not date_value:
        raise ValueError("caregiver_date_required")
    sessions = normalize_caregiver_sessions(payload.get("sessions"))
    extras = normalize_caregiver_extras(payload.get("extras"))
    uid = f"KAOS-CAREGIVER-DAY-{date_value.replace('-', '')}"
    data = {
        "type": "caregiver.day",
        "date": date_value,
        "sessions": sessions,
        "extras": extras,
    }
    return uid, caregiver_journal_body(uid, date_value, f"돌봄 {date_value}", data, "caregiver,day")


def build_caregiver_settings_vjournal(payload):
    month = validate_caregiver_month(payload.get("month"))
    hourly_wage = caregiver_amount(payload.get("hourlyWage"), "caregiver_hourly_wage")
    transport_fee = caregiver_amount(payload.get("transportFee"), "caregiver_transport_fee")
    uid = f"KAOS-CAREGIVER-SETTINGS-{month.replace('-', '')}"
    data = {
        "type": "caregiver.settings",
        "month": month,
        "hourlyWage": hourly_wage,
        "transportFee": transport_fee,
    }
    return uid, caregiver_journal_body(
        uid,
        f"{month}-01",
        f"돌봄 설정 {month}",
        data,
        "caregiver,settings",
    )


def parse_caregiver_journal(item, collection):
    journal = normalize_journal(item, collection)
    try:
        payload = json.loads(journal.get("description") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") not in {"caregiver.day", "caregiver.settings"}:
        return None
    return {
        **payload,
        "uid": journal["uid"],
        "created": journal["created"],
        "lastModified": journal["lastModified"],
    }


def list_caregiver_journals(month=""):
    selected_month = validate_caregiver_month(month) if month else ""
    collection = system_collection(RADICALE_SYSTEM_CAREGIVER_JOURNAL_NAME)
    days = []
    settings = []
    for item in report_collection(ACCOUNTS["system"], collection["href"]):
        if item.get("component") != "VJOURNAL":
            continue
        record = parse_caregiver_journal(item, collection)
        if not record:
            continue
        if record["type"] == "caregiver.day":
            if not selected_month or str(record.get("date") or "").startswith(f"{selected_month}-"):
                days.append(record)
        elif record["type"] == "caregiver.settings":
            settings.append(record)
    days.sort(key=lambda item: item.get("date", ""))
    settings.sort(key=lambda item: item.get("month", ""))
    return {
        "configured": True,
        "live": True,
        "month": selected_month,
        "days": days,
        "settings": settings,
    }


def put_caregiver_journal(payload, builder):
    collection = system_collection(RADICALE_SYSTEM_CAREGIVER_JOURNAL_NAME)
    uid, body = builder(payload)
    href = urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    radicale_request(
        ACCOUNTS["system"],
        "PUT",
        href,
        body,
        {"Content-Type": "text/calendar; charset=utf-8"},
    )
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def put_caregiver_day(payload):
    return put_caregiver_journal(payload, build_caregiver_day_vjournal)


def put_caregiver_settings(payload):
    return put_caregiver_journal(payload, build_caregiver_settings_vjournal)


def delete_caregiver_day(payload):
    date_value = validate_date(payload.get("date"))
    if not date_value:
        raise ValueError("caregiver_date_required")
    collection = system_collection(RADICALE_SYSTEM_CAREGIVER_JOURNAL_NAME)
    uid = f"KAOS-CAREGIVER-DAY-{date_value.replace('-', '')}"
    href = urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    radicale_request(ACCOUNTS["system"], "DELETE", href)
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def weather_code_to_condition(weather_code):
    try:
        code = int(weather_code)
    except (TypeError, ValueError):
        return "unknown"
    if code == 0:
        return "clear"
    if code in {1, 2}:
        return "partly_cloudy"
    if code == 3:
        return "cloudy"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "thunderstorm"
    return "unknown"


def weather_glyph_for_condition(condition):
    return WEATHER_GLYPHS.get(condition, WEATHER_GLYPHS["unknown"])


def round_celsius(value):
    return round(float(value))


def parse_date_or_default(value, default):
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return default


def date_range(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def weather_history_map(city, start_date, end_date):
    try:
        payload = list_weather_history()
    except Exception:
        return {}
    entries = {}
    for item in payload.get("weather", []):
        item_date = str(item.get("date") or "")
        if item.get("city") == city and start_date <= item_date <= end_date:
            entries[item_date] = {
                "city": item["city"],
                "cityName": item.get("cityName") or WEATHER_CITIES.get(city, city),
                "date": item_date,
                "glyph": item.get("glyph") or "",
                "condition": item.get("condition") or "",
                "minTemp": item.get("minTemp"),
                "maxTemp": item.get("maxTemp"),
                "source": item.get("source") or "history",
                "dayparts": [],
            }
    return entries


def fetch_open_meteo_forecast_coordinates(latitude, longitude, start_date, end_date):
    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "weather_code,temperature_2m_min,temperature_2m_max",
            "hourly": "weather_code,temperature_2m",
            "timezone": LOCAL_TZID,
            "start_date": start_date,
            "end_date": end_date,
        }
    )
    with urllib.request.urlopen(f"{OPEN_METEO_URL}?{query}", timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def fetch_open_meteo_forecast(city, start_date, end_date):
    location = WEATHER_LOCATIONS[city]
    return fetch_open_meteo_forecast_coordinates(
        location["latitude"],
        location["longitude"],
        start_date,
        end_date,
    )


def fetch_open_meteo_archive(city, start_date, end_date):
    location = WEATHER_LOCATIONS[city]
    query = urllib.parse.urlencode(
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "daily": "weather_code,temperature_2m_min,temperature_2m_max",
            "timezone": LOCAL_TZID,
            "start_date": start_date,
            "end_date": end_date,
        }
    )
    with urllib.request.urlopen(f"{OPEN_METEO_ARCHIVE_URL}?{query}", timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def forecast_daily_items(city, payload, city_name=""):
    daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    min_values = daily.get("temperature_2m_min") or []
    max_values = daily.get("temperature_2m_max") or []
    items = {}
    for index, date_value in enumerate(times):
        try:
            condition = weather_code_to_condition(codes[index])
            items[str(date_value)] = {
                "city": city,
                "cityName": city_name or WEATHER_CITIES[city],
                "date": str(date_value),
                "glyph": weather_glyph_for_condition(condition),
                "condition": condition,
                "minTemp": round_celsius(min_values[index]),
                "maxTemp": round_celsius(max_values[index]),
                "source": "forecast",
                "dayparts": [],
            }
        except (IndexError, TypeError, ValueError):
            continue
    return items


def validate_weather_coordinate(value, field_name, minimum, maximum):
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field_name}") from exc
    if not minimum <= coordinate <= maximum:
        raise ValueError(f"invalid_{field_name}")
    return coordinate


def reverse_geocode_location(latitude, longitude, language):
    query = urllib.parse.urlencode(
        {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "addressdetails": 1,
            "zoom": 10,
            "accept-language": language,
        }
    )
    request = urllib.request.Request(
        f"{NOMINATIM_REVERSE_URL}?{query}",
        headers={"User-Agent": "KaosGDD/2.0 (https://kaosgdd.net)"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    address = payload.get("address") if isinstance(payload, dict) and isinstance(payload.get("address"), dict) else {}
    for key in ("city", "town", "village", "municipality", "county", "state_district", "state"):
        value = str(address.get(key) or "").strip()
        if value:
            return value
    return ""


def current_location_weather_payload(payload):
    latitude = validate_weather_coordinate(payload.get("latitude"), "latitude", -90, 90)
    longitude = validate_weather_coordinate(payload.get("longitude"), "longitude", -180, 180)
    today = datetime.now(LOCAL_TIMEZONE).date()
    raw_date = str(payload.get("date") or today.isoformat()).strip()
    try:
        target_date = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError("invalid_weather_date") from exc
    if target_date < today:
        raise ValueError("current_location_weather_future_only")

    date_value = target_date.isoformat()
    language = "ko" if str(payload.get("language") or "").lower() == "ko" else "en"
    location_name = "현재 위치" if language == "ko" else "Current location"
    location_attribution = ""
    try:
        resolved_name = reverse_geocode_location(latitude, longitude, language)
        if resolved_name:
            location_name = resolved_name
            location_attribution = "© OpenStreetMap contributors"
    except (json.JSONDecodeError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        pass

    forecast = fetch_open_meteo_forecast_coordinates(latitude, longitude, date_value, date_value)
    items = forecast_daily_items("current", forecast, location_name)
    dayparts_by_date = forecast_dayparts(forecast)
    item = items.get(date_value)
    if item:
        item["dayparts"] = dayparts_by_date.get(date_value, [])
        item["locationAttribution"] = location_attribution
    return {
        "ok": bool(item),
        "date": date_value,
        "item": item,
    }


def save_missing_weather_history(city, items):
    for item in items.values():
        create_weather_history(
            {
                "city": city,
                "date": item["date"],
                "minTemp": item["minTemp"],
                "maxTemp": item["maxTemp"],
                "glyph": item["glyph"],
                "condition": item["condition"],
                "source": "open-meteo-archive",
            }
        )


def forecast_dayparts(payload):
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") or []
    codes = hourly.get("weather_code") or []
    temperatures = hourly.get("temperature_2m") or []
    by_date = {}
    for index, timestamp in enumerate(times):
        try:
            parsed = datetime.fromisoformat(str(timestamp))
            temp_c = round_celsius(temperatures[index])
            weather_code = int(codes[index])
        except (IndexError, TypeError, ValueError):
            continue
        by_date.setdefault(parsed.date().isoformat(), {})[parsed.hour] = {"temp": temp_c, "weatherCode": weather_code}

    results = {}
    for date_value, by_hour in by_date.items():
        parts = []
        for label, hours in WEATHER_DAYPARTS:
            rows = [by_hour[hour] for hour in hours if hour in by_hour]
            if not rows:
                continue
            representative_code = max(
                [row["weatherCode"] for row in rows],
                key=lambda code: WEATHER_CONDITION_SEVERITY.get(weather_code_to_condition(code), 0),
            )
            condition = weather_code_to_condition(representative_code)
            temps = [row["temp"] for row in rows]
            parts.append(
                {
                    "label": label,
                    "glyph": weather_glyph_for_condition(condition),
                    "condition": condition,
                    "weatherCode": representative_code,
                    "minTemp": min(temps),
                    "maxTemp": max(temps),
                }
            )
        results[date_value] = parts
    return results


def month_weather_payload(query):
    city = validate_weather_city(query.get("city", ["pohang"])[0])
    today = datetime.now(LOCAL_TIMEZONE).date()
    start = parse_date_or_default(query.get("start", [""])[0], today.replace(day=1))
    end = parse_date_or_default(query.get("end", [""])[0], start + timedelta(days=41))
    if end < start:
        raise ValueError("invalid_weather_range")
    if (end - start).days > 62:
        raise ValueError("weather_range_too_large")

    history_end = min(end, today - timedelta(days=1))
    items = weather_history_map(city, start.isoformat(), history_end.isoformat())
    history_error = ""
    if start <= history_end:
        missing_dates = [day.isoformat() for day in date_range(start, history_end) if day.isoformat() not in items]
        if missing_dates:
            try:
                payload = fetch_open_meteo_archive(city, missing_dates[0], missing_dates[-1])
                archive_items = forecast_daily_items(city, payload)
                missing_items = {date_value: archive_items[date_value] for date_value in missing_dates if date_value in archive_items}
                for item in missing_items.values():
                    item["source"] = "open-meteo-archive"
                    item["dayparts"] = []
                save_missing_weather_history(city, missing_items)
                items.update(missing_items)
            except Exception:
                history_error = "history unavailable"

    forecast_error = ""
    if end >= today:
        forecast_start = max(start, today)
        forecast_end = min(end, today + timedelta(days=OPEN_METEO_FORECAST_MAX_DAYS - 1))
        try:
            if forecast_start <= forecast_end:
                payload = fetch_open_meteo_forecast(city, forecast_start.isoformat(), forecast_end.isoformat())
                forecast_items = forecast_daily_items(city, payload)
                dayparts_by_date = forecast_dayparts(payload)
                for date_value, item in forecast_items.items():
                    item["dayparts"] = dayparts_by_date.get(date_value, [])
                    items[date_value] = item
        except Exception:
            forecast_error = "weather unavailable"

    ordered = [items[day.isoformat()] for day in date_range(start, end) if day.isoformat() in items]
    return {
        "ok": not (forecast_error or history_error) or bool(ordered),
        "error": forecast_error or history_error,
        "city": city,
        "cityName": WEATHER_CITIES[city],
        "locations": [
            {"id": key, "label": WEATHER_LOCATIONS[key]["label"]}
            for key in WEATHER_DEFAULT_CITY_KEYS
        ],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": today.isoformat(),
        "items": ordered,
    }


def bootstrap_payload(profile="main"):
    accounts = profile_accounts(profile)
    if not accounts:
        return {
            "configured": False,
            "live": False,
            "profile": profile,
            "collections": [],
            "events": [],
            "tasks": [],
            "message": "Radicale credentials are not configured.",
        }

    collections = []
    events = []
    tasks = []

    for item_account in accounts:
        account_collections = propfind_collections(item_account)
        collections.extend(account_collections)
        for collection in account_collections:
            collection_items = report_collection(item_account, collection["href"])
            event_counts = {}
            for item in collection_items:
                if item.get("component") == "VEVENT":
                    event_counts[item.get("href")] = event_counts.get(item.get("href"), 0) + 1
            for item in collection_items:
                if item.get("component") == "VEVENT":
                    item["_unsafe_multiple"] = event_counts.get(item.get("href"), 0) > 1
                    events.append(normalize_event(item, collection))
                elif item.get("component") == "VTODO":
                    tasks.append(normalize_task(item, collection))

    return {
        "configured": True,
        "live": True,
        "profile": profile,
        "collections": collections,
        "events": events,
        "tasks": tasks,
    }


def collections_for_profile(profile):
    collections = []
    for item_account in profile_accounts(profile):
        collections.extend(propfind_collections(item_account))
    return collections


def account_for_collection(collection):
    owner = collection.get("owner")
    account_item = ACCOUNTS.get(owner)
    if not account_item or not account_item["configured"]:
        raise ValueError("collection_account_not_configured")
    return account_item


def validate_date(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("invalid_due_date")
    datetime.strptime(raw, "%Y-%m-%d")
    return raw


def validate_time(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        raise ValueError("invalid_due_time")
    datetime.strptime(raw, "%H:%M")
    return raw


def validate_priority(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw not in {"1", "5", "9"}:
        raise ValueError("invalid_priority")
    return raw


def select_collection(collections, collection_id, component):
    if collection_id:
        for collection in collections:
            if collection["id"] == collection_id:
                if collection.get("components") and component not in collection["components"]:
                    raise ValueError("collection_component_mismatch")
                return collection
        raise ValueError("collection_not_found")

    for collection in collections:
        if component in collection.get("components", []):
            return collection

    lowered = component.lower().replace("v", "")
    for collection in collections:
        if lowered in collection.get("name", "").lower():
            return collection

    raise ValueError("no_writable_collection")


def utc_stamp(value):
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def local_due_stamp(date_value, time_value):
    local = datetime.strptime(f"{date_value}T{time_value}:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=LOCAL_TIMEZONE)
    return local.strftime("%Y%m%dT%H%M%S"), utc_stamp(local)


def local_datetime(date_value, time_value):
    return datetime.strptime(f"{date_value}T{time_value}:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=LOCAL_TIMEZONE)


def local_datetime_stamp(date_value, time_value):
    return local_datetime(date_value, time_value).strftime("%Y%m%dT%H%M%S")


def compact_date(date_value):
    return date_value.replace("-", "")


def build_vtodo(payload, existing=None):
    existing = existing or {}
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("title_required")

    due_date = validate_date(payload.get("dueDate") or "")
    due_time = validate_time(payload.get("dueTime") or "")
    if due_time and not due_date:
        raise ValueError("due_time_without_date")

    priority = validate_priority(payload.get("priority") or "")
    description = str(payload.get("memo") or "").strip()
    uid = str(payload.get("uid") or existing.get("UID") or uuid.uuid4()).upper()
    alarm_uid = str(uuid.uuid4()).upper()
    now = utc_stamp(datetime.now(timezone.utc))
    created = existing.get("CREATED") or now
    try:
        sequence = int(existing.get("SEQUENCE") or -1) + 1
    except (TypeError, ValueError):
        sequence = 0
    requested_status = str(payload.get("status") or "").strip().upper()
    status = requested_status if requested_status in {"COMPLETED", "NEEDS-ACTION"} else existing.get("STATUS") or "NEEDS-ACTION"
    rebuilt_properties = {
        "UID",
        "DTSTAMP",
        "CREATED",
        "LAST-MODIFIED",
        "SEQUENCE",
        "SUMMARY",
        "DESCRIPTION",
        "DTSTART",
        "DUE",
        "STATUS",
        "COMPLETED",
        "PERCENT-COMPLETE",
        "PRIORITY",
    }
    preserved_properties = [
        line
        for line in existing.get("_raw_properties", [])
        if parse_property(line)[0] not in rebuilt_properties
    ]

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "PRODID:-//KaosGDD//Calendar Adapter//EN",
        *SEOUL_VTIMEZONE.splitlines(),
        "BEGIN:VTODO",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"CREATED:{created}",
        f"LAST-MODIFIED:{now}",
        f"SEQUENCE:{sequence}",
        f"SUMMARY:{escape_ics(title)}",
        f"STATUS:{escape_ics(status)}",
        *preserved_properties,
    ]
    if status == "COMPLETED":
        completed = existing.get("COMPLETED") or now
        lines.extend([f"COMPLETED:{completed}", "PERCENT-COMPLETE:100"])
    else:
        lines.append("PERCENT-COMPLETE:0")
    if description:
        lines.append(f"DESCRIPTION:{escape_ics(description)}")
    if priority:
        lines.append(f"PRIORITY:{priority}")
    if due_date and due_time:
        local_due, utc_due = local_due_stamp(due_date, due_time)
        lines.extend(
            [
                f"DTSTART;TZID={LOCAL_TZID}:{local_due}",
                f"DUE;TZID={LOCAL_TZID}:{local_due}",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                "DESCRIPTION:Reminder",
                f"TRIGGER;VALUE=DATE-TIME:{utc_due}",
                f"UID:{alarm_uid}",
                f"X-WR-ALARMUID:{alarm_uid}",
                "END:VALARM",
            ]
        )
    elif due_date:
        compact = due_date.replace("-", "")
        lines.append(f"DUE;VALUE=DATE:{compact}")

    lines.extend(["END:VTODO", "END:VCALENDAR"])
    return uid, calendar_body(lines)


def create_task(payload, profile="main"):
    if not configured(profile):
        raise ValueError("adapter_not_configured")
    collections = collections_for_profile(profile)
    collection = select_collection(collections, str(payload.get("collectionId") or "").strip(), "VTODO")
    item_account = account_for_collection(collection)
    uid, body = build_vtodo(payload)
    href = urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    radicale_request(
        item_account,
        "PUT",
        href,
        body,
        {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
    )
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def validate_repeat(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw not in {"weekly", "monthly", "yearly"}:
        raise ValueError("invalid_repeat")
    return raw


def rrule_for_repeat(repeat):
    return {
        "weekly": "FREQ=WEEKLY",
        "monthly": "FREQ=MONTHLY",
        "yearly": "FREQ=YEARLY",
    }.get(repeat, "")


def build_vevent(payload, existing=None):
    existing = existing or {}
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("title_required")

    start_date = validate_date(payload.get("startDate") or "")
    if not start_date:
        raise ValueError("start_date_required")
    end_date = validate_date(payload.get("endDate") or start_date)
    all_day = bool(payload.get("allDay"))
    start_time = validate_time(payload.get("startTime") or "")
    end_time = validate_time(payload.get("endTime") or "")
    alarm_time = validate_time(payload.get("alarmTime") or "")
    preserve_repeat = bool(payload.get("preserveRepeat")) and bool(existing)
    preserve_alarm = bool(payload.get("preserveAlarm")) and bool(existing)
    repeat = "" if preserve_repeat else validate_repeat(payload.get("repeat") or "")
    description = str(payload.get("memo") or "").strip()
    categories_provided = "categories" in payload
    categories = []
    if categories_provided:
        if not isinstance(payload.get("categories"), list):
            raise ValueError("invalid_categories")
        categories = sorted(
            {
                str(value or "").strip().upper()
                for value in payload.get("categories", [])
                if str(value or "").strip()
            }
        )
        if any(not re.fullmatch(r"[A-Z0-9_-]{1,64}", value) for value in categories):
            raise ValueError("invalid_categories")

    uid = str(payload.get("uid") or existing.get("UID") or uuid.uuid4()).upper()
    alarm_uid = str(uuid.uuid4()).upper()
    now = utc_stamp(datetime.now(timezone.utc))
    created = existing.get("CREATED") or now
    try:
        sequence = int(existing.get("SEQUENCE") or -1) + 1
    except (TypeError, ValueError):
        sequence = 0

    rebuilt_properties = {
        "UID",
        "DTSTAMP",
        "CREATED",
        "LAST-MODIFIED",
        "SEQUENCE",
        "SUMMARY",
        "DESCRIPTION",
        "DTSTART",
        "DTEND",
        "DURATION",
        "RRULE",
        "RDATE",
        "EXDATE",
        "RECURRENCE-ID",
    }
    if categories_provided:
        rebuilt_properties.add("CATEGORIES")
    preserved_properties = [
        line
        for line in existing.get("_raw_properties", [])
        if parse_property(line)[0] not in rebuilt_properties
    ]

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "PRODID:-//KaosGDD//Calendar Adapter//EN",
        *SEOUL_VTIMEZONE.splitlines(),
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"CREATED:{created}",
        f"LAST-MODIFIED:{now}",
        f"SEQUENCE:{sequence}",
        f"SUMMARY:{escape_ics(title)}",
        *preserved_properties,
    ]
    if description:
        lines.append(f"DESCRIPTION:{escape_ics(description)}")
    if categories:
        lines.append(f"CATEGORIES:{','.join(escape_ics(value) for value in categories)}")

    if all_day:
        start_compact = compact_date(start_date)
        end_exclusive = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        lines.extend([f"DTSTART;VALUE=DATE:{start_compact}", f"DTEND;VALUE=DATE:{end_exclusive.strftime('%Y%m%d')}"])
    else:
        start_time = start_time or "09:00"
        end_time = end_time or "10:00"
        start_dt = local_datetime(start_date, start_time)
        end_dt = local_datetime(end_date, end_time)
        if end_dt <= start_dt:
            raise ValueError("end_before_start")
        lines.extend(
            [
                f"DTSTART;TZID={LOCAL_TZID}:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={LOCAL_TZID}:{end_dt.strftime('%Y%m%dT%H%M%S')}",
            ]
        )

    if preserve_repeat:
        for property_name in ("RRULE", "RDATE", "EXDATE"):
            lines.extend(property_lines(existing, property_name))
    else:
        rrule = rrule_for_repeat(repeat)
        if rrule:
            lines.append(f"RRULE:{rrule}")

    if preserve_alarm:
        for subcomponent in existing.get("_subcomponents", []):
            lines.extend(subcomponent)
    elif alarm_time:
        alarm_dt = local_datetime(start_date, alarm_time)
        lines.extend(
            [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{escape_ics(title)}",
                f"TRIGGER;VALUE=DATE-TIME:{utc_stamp(alarm_dt)}",
                f"UID:{alarm_uid}",
                f"X-WR-ALARMUID:{alarm_uid}",
                "END:VALARM",
            ]
        )

    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return uid, calendar_body(lines)


def create_event(payload, profile="main"):
    if not configured(profile):
        raise ValueError("adapter_not_configured")
    collections = collections_for_profile(profile)
    collection = select_collection(collections, str(payload.get("collectionId") or "").strip(), "VEVENT")
    item_account = account_for_collection(collection)
    uid, body = build_vevent(payload)
    href = urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    radicale_request(
        item_account,
        "PUT",
        href,
        body,
        {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
    )
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def find_component(collections, uid, component, collection_id=""):
    if not uid:
        raise ValueError("uid_required")
    targets = [collection for collection in collections if not collection_id or collection["id"] == collection_id]
    if collection_id and not targets:
        raise ValueError("collection_not_found")

    for collection in targets:
        if collection.get("components") and component not in collection["components"]:
            continue
        item_account = account_for_collection(collection)
        collection_items = report_collection(item_account, collection["href"])
        matches = [item for item in collection_items if item.get("component") == component and item.get("UID") == uid]
        if matches:
            for item in matches:
                item["_unsafe_multiple"] = len([candidate for candidate in collection_items if candidate.get("component") == component and candidate.get("href") == item.get("href")]) > 1
                return collection, item

    raise ValueError(f"{component.lower()}_not_found")


def find_task(collections, uid, collection_id=""):
    try:
        return find_component(collections, uid, "VTODO", collection_id)
    except ValueError as exc:
        if str(exc) == "vtodo_not_found":
            raise ValueError("task_not_found") from exc
        raise


def update_task(payload, profile="main"):
    if not configured(profile):
        raise ValueError("adapter_not_configured")
    uid = str(payload.get("uid") or "").strip()
    collections = collections_for_profile(profile)
    collection, existing = find_task(collections, uid, str(payload.get("collectionId") or "").strip())
    item_account = account_for_collection(collection)
    _, body = build_vtodo(payload, existing)
    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    if existing.get("etag"):
        headers["If-Match"] = existing["etag"]
    radicale_request(
        item_account,
        "PUT",
        existing["href"],
        body,
        headers,
    )
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def update_event(payload, profile="main"):
    if not configured(profile):
        raise ValueError("adapter_not_configured")
    uid = str(payload.get("uid") or "").strip()
    collections = collections_for_profile(profile)
    try:
        collection, existing = find_component(collections, uid, "VEVENT", str(payload.get("collectionId") or "").strip())
    except ValueError as exc:
        if str(exc) == "vevent_not_found":
            raise ValueError("event_not_found") from exc
        raise
    if existing.get("_unsafe_multiple") or existing.get("RECURRENCE-ID"):
        raise ValueError("event_requires_native_client")
    if SYSTEM_EVENT_CATEGORY in item_categories(existing) or GOOGLE_HOLIDAY_CATEGORY in item_categories(existing):
        raise ValueError("system_event_readonly")
    item_account = account_for_collection(collection)
    _, body = build_vevent(payload, existing)
    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    if existing.get("etag"):
        headers["If-Match"] = existing["etag"]
    radicale_request(item_account, "PUT", existing["href"], body, headers)
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def delete_component(payload, profile, component):
    if not configured(profile):
        raise ValueError("adapter_not_configured")
    uid = str(payload.get("uid") or "").strip()
    collection_id = str(payload.get("collectionId") or "").strip()
    collections = collections_for_profile(profile)
    collection, existing = find_component(collections, uid, component, collection_id)
    if component == "VEVENT" and (
        SYSTEM_EVENT_CATEGORY in item_categories(existing)
        or GOOGLE_HOLIDAY_CATEGORY in item_categories(existing)
    ):
        raise ValueError("system_event_readonly")
    item_account = account_for_collection(collection)
    headers = {}
    if existing.get("etag"):
        headers["If-Match"] = existing["etag"]
    radicale_request(item_account, "DELETE", existing["href"], "", headers)
    return {"ok": True, "uid": uid, "collection": collection["id"]}


def delete_event(payload, profile="main"):
    try:
        return delete_component(payload, profile, "VEVENT")
    except ValueError as exc:
        if str(exc) == "vevent_not_found":
            raise ValueError("event_not_found") from exc
        raise


def delete_task(payload, profile="main"):
    try:
        return delete_component(payload, profile, "VTODO")
    except ValueError as exc:
        if str(exc) == "vtodo_not_found":
            raise ValueError("task_not_found") from exc
        raise


def item_categories(item):
    categories = item.get("categories")
    if isinstance(categories, list):
        return {str(part or "").strip().upper() for part in categories if str(part or "").strip()}
    return {part.strip().upper() for part in item.get("CATEGORIES", "").split(",") if part.strip()}


def family_holiday_collection():
    family_account = ACCOUNTS["family"]
    if not family_account["configured"]:
        raise ValueError("family_calendar_not_configured")
    collections = [
        collection
        for collection in propfind_collections(family_account)
        if not collection.get("components") or "VEVENT" in collection.get("components", [])
    ]
    for collection in collections:
        if collection.get("name", "").casefold() == RADICALE_FAMILY_CALENDAR_NAME.casefold():
            return collection
    if len(collections) == 1:
        return collections[0]
    raise ValueError("family_holiday_calendar_not_found")


def list_family_holidays():
    collection = family_holiday_collection()
    events = []
    for item in report_collection(ACCOUNTS["family"], collection["href"]):
        if item.get("component") != "VEVENT" or GOOGLE_HOLIDAY_CATEGORY not in item_categories(item):
            continue
        events.append(normalize_event(item, collection))
    events.sort(key=lambda item: (item.get("startDate", ""), item.get("summary", ""), item.get("uid", "")))
    return {"ok": True, "collection": collection, "items": events}


def put_family_holiday(payload):
    collection = family_holiday_collection()
    uid = str(payload.get("uid") or "").strip().upper()
    if not re.fullmatch(r"KAOS-HOLIDAY-[A-F0-9]{24}", uid):
        raise ValueError("invalid_holiday_uid")
    categories = {
        str(value or "").strip().upper()
        for value in payload.get("categories", [])
        if str(value or "").strip()
    }
    if not {SYSTEM_EVENT_CATEGORY, GOOGLE_HOLIDAY_CATEGORY}.issubset(categories):
        raise ValueError("invalid_holiday_categories")
    if bool(PUBLIC_HOLIDAY_CATEGORY in categories) == bool(OBSERVANCE_CATEGORY in categories):
        raise ValueError("invalid_holiday_classification")

    existing = None
    for item in report_collection(ACCOUNTS["family"], collection["href"]):
        if item.get("component") == "VEVENT" and str(item.get("UID") or "").upper() == uid:
            existing = item
            break
    event_payload = {
        "uid": uid,
        "title": payload.get("title"),
        "memo": payload.get("memo") or "Google Korea Holidays",
        "startDate": payload.get("startDate"),
        "endDate": payload.get("endDate") or payload.get("startDate"),
        "allDay": True,
        "categories": sorted(categories),
    }
    _, body = build_vevent(event_payload, existing)
    href = existing.get("href") if existing else urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    if existing and existing.get("etag"):
        headers["If-Match"] = existing["etag"]
    else:
        headers["If-None-Match"] = "*"
    radicale_request(ACCOUNTS["family"], "PUT", href, body, headers)
    return {"ok": True, "uid": uid, "collection": collection["id"], "created": existing is None}


def delete_family_holiday(payload):
    collection = family_holiday_collection()
    uid = str(payload.get("uid") or "").strip().upper()
    if not uid:
        raise ValueError("uid_required")
    for item in report_collection(ACCOUNTS["family"], collection["href"]):
        if item.get("component") != "VEVENT" or str(item.get("UID") or "").upper() != uid:
            continue
        if GOOGLE_HOLIDAY_CATEGORY not in item_categories(item):
            raise ValueError("system_event_required")
        headers = {"If-Match": item["etag"]} if item.get("etag") else {}
        radicale_request(ACCOUNTS["family"], "DELETE", item["href"], "", headers)
        return {"ok": True, "uid": uid, "deleted": True}
    return {"ok": True, "uid": uid, "deleted": False}


def public_holiday_item(item):
    categories = item_categories(item)
    return {
        "uid": item.get("uid", ""),
        "title": item.get("summary") or item.get("title") or "",
        "startDate": item.get("startDate", ""),
        "endDate": item.get("endDate") or item.get("startDate", ""),
        "publicHoliday": PUBLIC_HOLIDAY_CATEGORY in categories,
        "categories": sorted(categories),
    }


def holiday_sync_status():
    return {
        "configured": False,
        "enabled": False,
        "running": False,
        "lastAttemptAt": "",
        "lastSuccessAt": "",
        "lastError": "",
        "lastResult": {},
    }


def list_public_holidays():
    result = list_family_holidays()
    return {
        "ok": True,
        "collection": result.get("collection", {}),
        "items": [public_holiday_item(item) for item in result.get("items", [])],
        "sync": holiday_sync_status(),
    }


def sync_public_holidays():
    result = list_public_holidays()
    return {
        "ok": True,
        "configured": False,
        "enabled": False,
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "items": result.get("items", []),
        "skipped": "holiday_source_not_configured_in_calendar_adapter",
    }


def set_public_holiday(uid, public_holiday):
    normalized_uid = str(uid or "").strip().upper()
    if not re.fullmatch(r"KAOS-HOLIDAY-[A-F0-9]{24}", normalized_uid):
        raise ValueError("invalid_holiday_uid")
    result = list_family_holidays()
    current = next(
        (item for item in result.get("items", []) if str(item.get("uid") or "").upper() == normalized_uid),
        None,
    )
    if current is None:
        raise ValueError("holiday_not_found")
    categories = [SYSTEM_EVENT_CATEGORY, GOOGLE_HOLIDAY_CATEGORY]
    categories.append(PUBLIC_HOLIDAY_CATEGORY if public_holiday else OBSERVANCE_CATEGORY)
    put_family_holiday(
        {
            "uid": normalized_uid,
            "title": current.get("summary") or current.get("title"),
            "memo": current.get("description") or "Google Korea Holidays",
            "startDate": current.get("startDate"),
            "endDate": current.get("endDate") or current.get("startDate"),
            "categories": categories,
        }
    )
    return {"ok": True, "item": {**public_holiday_item(current), "publicHoliday": bool(public_holiday)}}


def gdd_generated_collection():
    zin_account = ACCOUNTS["zin"]
    if not zin_account["configured"]:
        raise ValueError("gdd_calendar_not_configured")
    collections = [
        collection
        for collection in propfind_collections(zin_account)
        if not collection.get("components") or "VEVENT" in collection.get("components", [])
    ]
    for collection in collections:
        if collection.get("name", "").casefold() == RADICALE_GDD_CALENDAR_NAME.casefold():
            return collection
    if len(collections) == 1:
        return collections[0]
    raise ValueError("gdd_generated_calendar_not_found")


def list_gdd_generated_events():
    collection = gdd_generated_collection()
    events = []
    for item in report_collection(ACCOUNTS["zin"], collection["href"]):
        categories = item_categories(item)
        if item.get("component") != "VEVENT" or not {
            SYSTEM_EVENT_CATEGORY,
            GENERATED_EVENT_CATEGORY,
        }.issubset(categories):
            continue
        events.append(normalize_event(item, collection))
    events.sort(key=lambda item: (item.get("startDate", ""), item.get("summary", ""), item.get("uid", "")))
    return {"ok": True, "collection": collection, "items": events}


def put_gdd_generated_event(payload):
    collection = gdd_generated_collection()
    uid = str(payload.get("uid") or "").strip().upper()
    if not re.fullmatch(r"KAOS-(?:MARKET|CLAIM-WEEK)-\d{4}-\d{2}-\d{2}", uid):
        raise ValueError("invalid_generated_event_uid")
    categories = {
        str(value or "").strip().upper()
        for value in payload.get("categories", [])
        if str(value or "").strip()
    }
    if not {SYSTEM_EVENT_CATEGORY, GENERATED_EVENT_CATEGORY}.issubset(categories):
        raise ValueError("invalid_generated_event_categories")
    event_types = {MARKET_DAY_CATEGORY, CLAIM_DAY_CATEGORY}.intersection(categories)
    if len(event_types) != 1:
        raise ValueError("invalid_generated_event_type")
    if MARKET_SATURDAY_CATEGORY in categories and MARKET_DAY_CATEGORY not in categories:
        raise ValueError("invalid_generated_event_categories")

    existing = None
    for item in report_collection(ACCOUNTS["zin"], collection["href"]):
        if item.get("component") == "VEVENT" and str(item.get("UID") or "").upper() == uid:
            if not {SYSTEM_EVENT_CATEGORY, GENERATED_EVENT_CATEGORY}.issubset(item_categories(item)):
                raise ValueError("generated_event_required")
            existing = item
            break
    event_payload = {
        "uid": uid,
        "title": payload.get("title"),
        "memo": payload.get("memo") or "Generated by KaosGDD Brain",
        "startDate": payload.get("startDate"),
        "endDate": payload.get("endDate") or payload.get("startDate"),
        "allDay": True,
        "categories": sorted(categories),
    }
    _, body = build_vevent(event_payload, existing)
    href = existing.get("href") if existing else urllib.parse.urljoin(collection["href"], f"{uid}.ics")
    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    if existing and existing.get("etag"):
        headers["If-Match"] = existing["etag"]
    else:
        headers["If-None-Match"] = "*"
    radicale_request(ACCOUNTS["zin"], "PUT", href, body, headers)
    return {"ok": True, "uid": uid, "collection": collection["id"], "created": existing is None}


def delete_gdd_generated_event(payload):
    collection = gdd_generated_collection()
    uid = str(payload.get("uid") or "").strip().upper()
    if not uid:
        raise ValueError("uid_required")
    for item in report_collection(ACCOUNTS["zin"], collection["href"]):
        if item.get("component") != "VEVENT" or str(item.get("UID") or "").upper() != uid:
            continue
        if not {SYSTEM_EVENT_CATEGORY, GENERATED_EVENT_CATEGORY}.issubset(item_categories(item)):
            raise ValueError("generated_event_required")
        headers = {"If-Match": item["etag"]} if item.get("etag") else {}
        radicale_request(ACCOUNTS["zin"], "DELETE", item["href"], "", headers)
        return {"ok": True, "uid": uid, "deleted": True}
    return {"ok": True, "uid": uid, "deleted": False}


def read_state_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return default
    if not isinstance(payload, type(default)):
        return default
    return payload


def write_state_file(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def clean_id(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", raw):
        raise ValueError("invalid_id")
    return raw


def short_time(value, default):
    raw = str(value or "").strip() or default
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", raw):
        raw = raw[:5]
    return validate_time(raw)


def current_utc_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def public_owner_for_profile(profile):
    return "family" if profile == "family" else "zin"


def share_family_for_owner(owner):
    return owner == "family"


def event_preset_store():
    payload = read_state_file(EVENT_PRESETS_FILE, {"items": []})
    items = payload.get("items") if isinstance(payload, dict) else []
    normalized = [normalize_event_preset(item) for item in items]
    return [item for item in normalized if item]


def save_event_preset_store(items):
    write_state_file(EVENT_PRESETS_FILE, {"items": items})


def normalize_event_preset(item):
    if not isinstance(item, dict):
        return None
    item_id = clean_id(item.get("id") or "")
    name = str(item.get("name") or item.get("title") or "").strip()
    title = str(item.get("title") or "").strip()
    if not item_id or not name or not title:
        return None
    owner = str(item.get("owner") or ("family" if item.get("shareFamily") else "zin")).strip()
    if owner not in {"zin", "wife", "family"}:
        owner = "family" if item.get("shareFamily") else "zin"
    return {
        "id": item_id,
        "owner": owner,
        "name": name,
        "title": title,
        "allDay": item.get("allDay") is not False,
        "startTime": short_time(item.get("startTime"), "09:00"),
        "endTime": short_time(item.get("endTime"), "10:00"),
        "alarm": short_time(item.get("alarm"), "") if str(item.get("alarm") or "").strip() else "",
        "memo": str(item.get("memo") or "").strip(),
        "shareFamily": share_family_for_owner(owner),
        "createdAt": str(item.get("createdAt") or current_utc_iso()),
        "updatedAt": str(item.get("updatedAt") or current_utc_iso()),
    }


def event_preset_from_payload(payload, profile, existing=None):
    existing = existing or {}
    now = current_utc_iso()
    owner = existing.get("owner") or (
        "family" if payload.get("shareFamily") is True or profile == "family" else public_owner_for_profile(profile)
    )
    item = {
        "id": clean_id(existing.get("id") or payload.get("id") or str(uuid.uuid4())),
        "owner": owner,
        "name": payload.get("name") or payload.get("presetName") or payload.get("title") or existing.get("name") or "",
        "title": payload.get("title") or existing.get("title") or "",
        "allDay": payload.get("allDay", existing.get("allDay", True)),
        "startTime": payload.get("startTime", existing.get("startTime", "09:00")),
        "endTime": payload.get("endTime", existing.get("endTime", "10:00")),
        "alarm": payload.get("alarm", existing.get("alarm", "")),
        "memo": payload.get("memo", existing.get("memo", "")),
        "shareFamily": owner == "family",
        "createdAt": existing.get("createdAt") or now,
        "updatedAt": now,
    }
    normalized = normalize_event_preset(item)
    if not normalized:
        raise ValueError("invalid_event_preset")
    return normalized


def list_event_presets(profile):
    owner = public_owner_for_profile(profile)
    items = [item for item in event_preset_store() if item["owner"] in {owner, "family"}]
    items.sort(key=lambda item: (item.get("name", ""), item.get("title", ""), item.get("id", "")))
    return {"ok": True, "items": items}


def upsert_event_preset(payload, profile, item_id=""):
    items = event_preset_store()
    target_id = clean_id(item_id or payload.get("id") or "")
    existing = None
    if target_id:
        existing = next((item for item in items if item["id"] == target_id), None)
        if existing is None and item_id:
            raise ValueError("event_preset_not_found")
    saved = event_preset_from_payload({**payload, "id": target_id or payload.get("id")}, profile, existing)
    items = [item for item in items if item["id"] != saved["id"]]
    items.append(saved)
    save_event_preset_store(items)
    return saved


def delete_event_preset(item_id):
    target_id = clean_id(item_id)
    items = event_preset_store()
    kept = [item for item in items if item["id"] != target_id]
    save_event_preset_store(kept)
    return {"ok": True, "id": target_id, "deleted": len(kept) != len(items)}


def recurring_task_store():
    payload = read_state_file(RECURRING_TASKS_FILE, {"items": []})
    items = payload.get("items") if isinstance(payload, dict) else []
    normalized = [normalize_recurring_task(item) for item in items]
    return [item for item in normalized if item]


def save_recurring_task_store(items):
    write_state_file(RECURRING_TASKS_FILE, {"items": items})


def normalize_recurring_task(item):
    if not isinstance(item, dict):
        return None
    item_id = clean_id(item.get("id") or "")
    title = str(item.get("title") or "").strip()
    if not item_id or not title:
        return None
    owner = str(item.get("owner") or ("family" if item.get("shareFamily") else "zin")).strip()
    if owner not in {"zin", "wife", "family"}:
        owner = "family" if item.get("shareFamily") else "zin"
    frequency = str(item.get("frequency") or "weekly").strip().lower()
    if frequency not in {"daily", "weekly", "monthly", "yearly"}:
        frequency = "weekly"
    priority = str(item.get("priority") or "").strip()
    if priority not in {"", "1", "5", "9"}:
        priority = ""
    first_due = validate_date(item.get("firstDueDate") or item.get("first_due_date") or "")
    return {
        "id": item_id,
        "owner": owner,
        "adapterProfile": "family" if owner == "family" else "main",
        "collectionId": str(item.get("collectionId") or item.get("collection_id") or "").strip(),
        "title": title,
        "memo": str(item.get("memo") or "").strip(),
        "firstDueDate": first_due,
        "dueTime": short_time(item.get("dueTime") or item.get("due_time"), "10:00"),
        "priority": priority,
        "frequency": frequency,
        "creationPolicy": str(item.get("creationPolicy") or item.get("creation_policy") or "on_schedule"),
        "enabled": item.get("enabled") is not False,
        "shareFamily": owner == "family",
        "activeUid": str(item.get("activeUid") or item.get("active_uid") or "").strip(),
        "activeCollectionId": str(item.get("activeCollectionId") or item.get("active_collection_id") or "").strip(),
        "activeDueDate": str(item.get("activeDueDate") or item.get("active_due_date") or "").strip(),
        "nextDueDate": str(item.get("nextDueDate") or item.get("next_due_date") or "").strip(),
        "lastCompletedUid": str(item.get("lastCompletedUid") or item.get("last_completed_uid") or "").strip(),
        "lastCompletedAt": str(item.get("lastCompletedAt") or item.get("last_completed_at") or "").strip(),
        "error": str(item.get("error") or item.get("lastError") or item.get("last_error") or "").strip(),
        "createdAt": str(item.get("createdAt") or current_utc_iso()),
        "updatedAt": str(item.get("updatedAt") or current_utc_iso()),
    }


def recurring_task_from_payload(payload, profile, existing=None):
    existing = existing or {}
    now = current_utc_iso()
    owner = existing.get("owner") or (
        "family" if payload.get("shareFamily") is True or profile == "family" else public_owner_for_profile(profile)
    )
    item = {
        **existing,
        "id": clean_id(existing.get("id") or payload.get("id") or str(uuid.uuid4())),
        "owner": owner,
        "collectionId": payload.get("collectionId") or existing.get("collectionId") or "",
        "title": payload.get("title") or existing.get("title") or "",
        "memo": payload.get("memo", existing.get("memo", "")),
        "firstDueDate": payload.get("firstDueDate") or existing.get("firstDueDate") or "",
        "dueTime": payload.get("dueTime") or existing.get("dueTime") or "10:00",
        "priority": payload.get("priority", existing.get("priority", "")),
        "frequency": payload.get("frequency") or existing.get("frequency") or "weekly",
        "creationPolicy": payload.get("creationPolicy") or existing.get("creationPolicy") or "on_schedule",
        "enabled": payload.get("enabled", existing.get("enabled", True)) is not False,
        "shareFamily": owner == "family",
        "createdAt": existing.get("createdAt") or now,
        "updatedAt": now,
    }
    normalized = normalize_recurring_task(item)
    if not normalized:
        raise ValueError("invalid_recurring_task")
    return ensure_recurring_occurrence(normalized)


def add_frequency(value, frequency):
    current = date.fromisoformat(value)
    if frequency == "daily":
        return current + timedelta(days=1)
    if frequency == "weekly":
        return current + timedelta(days=7)
    if frequency == "yearly":
        try:
            return current.replace(year=current.year + 1)
        except ValueError:
            return current.replace(year=current.year + 1, day=28)
    month = current.month + 1
    year = current.year
    if month > 12:
        month = 1
        year += 1
    next_month_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    last_day = (date(next_month_year, next_month, 1) - timedelta(days=1)).day
    return date(year, month, min(current.day, last_day))


def next_due_on_or_after(first_due, frequency, today):
    current = date.fromisoformat(first_due)
    while current < today:
        current = add_frequency(current.isoformat(), frequency)
    return current


def recurring_occurrence_uid(item, due_date):
    digest = hashlib.sha1(item["id"].encode("utf-8")).hexdigest()[:32].upper()
    return f"KAOSGDD-REPEAT-{digest}-{due_date.strftime('%Y%m%d')}"


def ensure_recurring_occurrence(item):
    if not item["enabled"]:
        return item
    today = date.today()
    if item.get("activeUid") and item.get("activeDueDate"):
        return item
    due_date = next_due_on_or_after(item["firstDueDate"], item["frequency"], today)
    profile = item["adapterProfile"]
    collections = collections_for_profile(profile)
    collection = select_collection(collections, item.get("collectionId") or "", "VTODO")
    uid = recurring_occurrence_uid(item, due_date)
    try:
        find_task(collections, uid, collection["id"])
    except ValueError:
        create_task(
            {
                "uid": uid,
                "collectionId": collection["id"],
                "title": item["title"],
                "memo": item["memo"],
                "dueDate": due_date.isoformat(),
                "dueTime": item["dueTime"],
                "priority": item["priority"],
            },
            profile,
        )
    item = dict(item)
    item["collectionId"] = collection["id"]
    item["activeUid"] = uid
    item["activeCollectionId"] = collection["id"]
    item["activeDueDate"] = due_date.isoformat()
    item["nextDueDate"] = ""
    item["error"] = ""
    return item


def list_recurring_tasks(profile):
    owner = public_owner_for_profile(profile)
    items = [item for item in recurring_task_store() if item["owner"] in {owner, "family"}]
    items.sort(key=lambda item: (not item.get("enabled", True), item.get("title", ""), item.get("id", "")))
    return {"ok": True, "items": items}


def upsert_recurring_task(payload, profile, item_id=""):
    items = recurring_task_store()
    target_id = clean_id(item_id or payload.get("id") or "")
    existing = None
    if target_id:
        existing = next((item for item in items if item["id"] == target_id), None)
        if existing is None and item_id:
            raise ValueError("recurring_task_not_found")
    saved = recurring_task_from_payload({**payload, "id": target_id or payload.get("id")}, profile, existing)
    items = [item for item in items if item["id"] != saved["id"]]
    items.append(saved)
    save_recurring_task_store(items)
    return saved


def delete_recurring_task(item_id):
    target_id = clean_id(item_id)
    items = recurring_task_store()
    kept = [item for item in items if item["id"] != target_id]
    save_recurring_task_store(kept)
    return {"ok": True, "id": target_id, "deleted": len(kept) != len(items)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        profile = profile_from_headers(self.headers)
        if path == "/health":
            json_response(self, 200, {"ok": True, "configured": configured(profile), "provider": "radicale", "profile": profile})
            return
        if path == "/api/calendar/bootstrap":
            try:
                json_response(self, 200, bootstrap_payload(profile))
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": configured(profile), "live": False, "profile": profile, "error": type(exc).__name__})
            return
        if path == "/internal/system/logs":
            try:
                json_response(self, 200, list_system_logs())
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        if path == "/internal/system/weather":
            try:
                json_response(self, 200, list_weather_history())
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        if path == "/internal/system/caregiver":
            try:
                json_response(self, 200, list_caregiver_journals((query.get("month") or [""])[0]))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        if path == "/internal/family/holidays":
            try:
                json_response(self, 200, list_family_holidays())
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/internal/zin/generated-events":
            try:
                json_response(self, 200, list_gdd_generated_events())
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/api/weather/month":
            try:
                json_response(self, 200, month_weather_payload(query))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/api/holidays":
            try:
                json_response(self, 200, list_public_holidays())
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/api/event-presets":
            try:
                json_response(self, 200, list_event_presets(profile))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        if path == "/api/recurring-tasks":
            try:
                json_response(self, 200, list_recurring_tasks(profile))
            except (ValueError, ET.ParseError) as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        json_response(self, 404, {"error": "not_found"})

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        profile = profile_from_headers(self.headers)
        if path == "/internal/system/caregiver/day":
            try:
                json_response(self, 200, put_caregiver_day(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        if path == "/internal/system/caregiver/settings":
            try:
                json_response(self, 200, put_caregiver_settings(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        if path == "/internal/family/holidays":
            try:
                json_response(self, 200, put_family_holiday(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/internal/zin/generated-events":
            try:
                json_response(self, 200, put_gdd_generated_event(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/api/calendar/events":
            try:
                json_response(self, 200, update_event(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": configured(profile), "live": False, "profile": profile, "error": type(exc).__name__})
            return
        if path == "/api/calendar/tasks":
            try:
                json_response(self, 200, update_task(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": configured(profile), "live": False, "profile": profile, "error": type(exc).__name__})
            return
        if path.startswith("/api/event-presets/"):
            try:
                json_response(self, 200, upsert_event_preset(read_json_request(self), profile, path.rsplit("/", 1)[-1]))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        if path.startswith("/api/recurring-tasks/"):
            try:
                json_response(self, 200, upsert_recurring_task(read_json_request(self), profile, path.rsplit("/", 1)[-1]))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        holiday_match = re.fullmatch(r"/api/holidays/(KAOS-HOLIDAY-[A-Fa-f0-9]{24})", path)
        if holiday_match:
            try:
                payload = read_json_request(self)
                if not isinstance(payload.get("publicHoliday"), bool):
                    raise ValueError("public_holiday_boolean_required")
                json_response(self, 200, set_public_holiday(holiday_match.group(1), payload["publicHoliday"]))
            except ValueError as exc:
                status = 404 if str(exc) == "holiday_not_found" else 400
                json_response(self, status, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        json_response(self, 404, {"error": "not_found"})

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        profile = profile_from_headers(self.headers)
        if path == "/internal/system/caregiver/day":
            try:
                json_response(self, 200, delete_caregiver_day(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        if path == "/internal/family/holidays":
            try:
                json_response(self, 200, delete_family_holiday(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/internal/zin/generated-events":
            try:
                json_response(self, 200, delete_gdd_generated_event(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/api/calendar/events":
            try:
                json_response(self, 200, delete_event(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": configured(profile), "live": False, "profile": profile, "error": type(exc).__name__})
            return
        if path == "/api/calendar/tasks":
            try:
                json_response(self, 200, delete_task(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": configured(profile), "live": False, "profile": profile, "error": type(exc).__name__})
            return
        if path.startswith("/api/event-presets/"):
            try:
                json_response(self, 200, delete_event_preset(path.rsplit("/", 1)[-1]))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        if path.startswith("/api/recurring-tasks/"):
            try:
                json_response(self, 200, delete_recurring_task(path.rsplit("/", 1)[-1]))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        json_response(self, 404, {"error": "not_found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        profile = profile_from_headers(self.headers)
        if path == "/api/weather/current":
            try:
                json_response(self, 200, current_location_weather_payload(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/api/calendar/events":
            try:
                json_response(self, 201, create_event(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": configured(profile), "live": False, "profile": profile, "error": type(exc).__name__})
            return
        if path == "/api/calendar/tasks":
            try:
                json_response(self, 201, create_task(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": configured(profile), "live": False, "profile": profile, "error": type(exc).__name__})
            return
        if path == "/api/event-presets":
            try:
                json_response(self, 201, upsert_event_preset(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        if path == "/api/recurring-tasks":
            try:
                json_response(self, 201, upsert_recurring_task(read_json_request(self), profile))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/api/holidays/sync":
            try:
                json_response(self, 200, sync_public_holidays())
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"ok": False, "error": type(exc).__name__})
            return
        if path == "/internal/system/logs":
            try:
                json_response(self, 201, create_system_log(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        if path == "/internal/system/weather":
            try:
                json_response(self, 201, create_weather_history(read_json_request(self)))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (ET.ParseError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                json_response(self, 502, {"configured": system_configured(), "live": False, "error": type(exc).__name__})
            return
        json_response(self, 404, {"error": "not_found"})

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"KaosGDD calendar adapter listening on {PORT}", flush=True)
    server.serve_forever()
