from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Callable, Mapping
import urllib.parse
import urllib.request


KST = timezone(timedelta(hours=9), "KST")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MET_NORWAY_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
USER_AGENT = "KaosGDD/2.0 (https://kaosgdd.net)"
CURRENT_FIELDS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,"
    "precipitation,rain,weather_code,wind_speed_10m"
)


class ShortcutWeatherError(ValueError):
    pass


def _coordinate(value: object, name: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ShortcutWeatherError(f"invalid_{name}") from exc
    if not minimum <= number <= maximum:
        raise ShortcutWeatherError(f"invalid_{name}")
    return round(number, 4)


def _number(value: object, digits: int = 1) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        result = round(float(value), digits)
    except (TypeError, ValueError):
        return None
    return int(result) if result.is_integer() else result


def _wmo_condition(value: object) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "알 수 없음"
    if code == 0:
        return "맑음"
    if code in {1, 2}:
        return "구름 조금"
    if code == 3:
        return "흐림"
    if code in {45, 48}:
        return "안개"
    if code in {51, 53, 55, 56, 57}:
        return "이슬비"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "비"
    if code in {71, 73, 75, 77, 85, 86}:
        return "눈"
    if code in {95, 96, 99}:
        return "뇌우"
    return "알 수 없음"


def _met_condition(value: object) -> str:
    symbol = str(value or "").lower()
    if "thunder" in symbol:
        return "뇌우"
    if "sleet" in symbol:
        return "진눈깨비"
    if "snow" in symbol:
        return "눈"
    if "rain" in symbol:
        return "비"
    if "drizzle" in symbol:
        return "이슬비"
    if "fog" in symbol:
        return "안개"
    if "partlycloudy" in symbol:
        return "구름 조금"
    if "cloudy" in symbol:
        return "흐림"
    if "fair" in symbol:
        return "대체로 맑음"
    if "clearsky" in symbol:
        return "맑음"
    return "알 수 없음"


def _format_number(value: object, suffix: str) -> str:
    number = _number(value)
    return f"{number}{suffix}" if number is not None else ""


def _source_text(source: Mapping[str, Any]) -> str:
    parts = [str(source.get("condition") or "알 수 없음")]
    temperature = _format_number(source.get("temperatureC"), "°C")
    apparent = _format_number(source.get("apparentTemperatureC"), "°C")
    humidity = _format_number(source.get("humidityPercent"), "%")
    wind = _format_number(source.get("windSpeedKmh"), "km/h")
    precipitation = _format_number(source.get("precipitationMm"), "mm")
    if temperature:
        parts.append(temperature)
    if apparent:
        parts.append(f"체감 {apparent}")
    if humidity:
        parts.append(f"습도 {humidity}")
    if wind:
        parts.append(f"바람 {wind}")
    if precipitation:
        parts.append(f"강수 {precipitation}")
    return " · ".join(parts)


class WeatherComparisonService:
    def __init__(
        self,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        timeout_seconds: int = 8,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._urlopen = urlopen
        self._timeout_seconds = timeout_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))

    def compare(
        self,
        latitude: object,
        longitude: object,
        location_name: object = "",
    ) -> dict[str, Any]:
        lat = _coordinate(latitude, "latitude", -90, 90)
        lon = _coordinate(longitude, "longitude", -180, 180)
        label = " ".join(str(location_name or "").split())[:100]
        providers = (
            ("open_meteo", "Open-Meteo Best Match", lambda: self._open_meteo(lat, lon)),
            ("kma", "KMA 모델", lambda: self._open_meteo(lat, lon, model="kma_seamless")),
            ("ecmwf", "ECMWF 모델", lambda: self._open_meteo(lat, lon, model="ecmwf_ifs025")),
            ("met_norway", "MET Norway", lambda: self._met_norway(lat, lon)),
        )
        completed: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="shortcut-weather") as pool:
            futures = {pool.submit(fetch): (source_id, name) for source_id, name, fetch in providers}
            for future in as_completed(futures):
                source_id, name = futures[future]
                try:
                    item = future.result()
                    item.update({"id": source_id, "name": name})
                    completed[source_id] = item
                except Exception:
                    errors[source_id] = "unavailable"

        sources = [completed[source_id] for source_id, _name, _fetch in providers if source_id in completed]
        temperatures = [float(item["temperatureC"]) for item in sources if item.get("temperatureC") is not None]
        spread = round(max(temperatures) - min(temperatures), 1) if len(temperatures) > 1 else None
        current = self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        generated_at = current.astimezone(KST)
        location_text = label or f"{lat:.4f}, {lon:.4f}"
        lines = [f"현재 위치 날씨 비교 · {generated_at:%H:%M}", f"📍 {location_text}", ""]
        for source_id, name, _fetch in providers:
            if source_id in completed:
                lines.append(f"• {name}: {_source_text(completed[source_id])}")
            else:
                lines.append(f"• {name}: 자료 없음")
        if spread is not None:
            lines.extend(("", f"공급자 온도 차이 {spread:g}°C"))
        lines.append("현재값은 관측소 실측이 아니라 각 공급자의 최신 예보 모델 값입니다.")
        return {
            "ok": bool(sources),
            "readOnly": True,
            "generatedAt": generated_at.isoformat(),
            "location": {"name": label, "latitude": lat, "longitude": lon},
            "sources": sources,
            "errors": [
                {"id": source_id, "name": name, "error": errors[source_id]}
                for source_id, name, _fetch in providers
                if source_id in errors
            ],
            "temperatureSpreadC": spread,
            "text": "\n".join(lines),
        }

    def _json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with self._urlopen(request, timeout=self._timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ShortcutWeatherError("weather_response_invalid")
        return payload

    def _open_meteo(self, latitude: float, longitude: float, *, model: str = "") -> dict[str, Any]:
        query: dict[str, object] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": CURRENT_FIELDS,
            "timezone": "auto",
            "forecast_days": 1,
        }
        if model:
            query["models"] = model
        payload = self._json(f"{OPEN_METEO_URL}?{urllib.parse.urlencode(query)}")
        current = payload.get("current")
        if not isinstance(current, Mapping) or _number(current.get("temperature_2m")) is None:
            raise ShortcutWeatherError("weather_no_data")
        return {
            "observedAt": str(current.get("time") or ""),
            "condition": _wmo_condition(current.get("weather_code")),
            "temperatureC": _number(current.get("temperature_2m")),
            "apparentTemperatureC": _number(current.get("apparent_temperature")),
            "humidityPercent": _number(current.get("relative_humidity_2m"), 0),
            "windSpeedKmh": _number(current.get("wind_speed_10m")),
            "precipitationMm": _number(current.get("precipitation")),
            "attribution": "Open-Meteo",
            "attributionUrl": "https://open-meteo.com/",
        }

    def _met_norway(self, latitude: float, longitude: float) -> dict[str, Any]:
        query = urllib.parse.urlencode({"lat": latitude, "lon": longitude})
        payload = self._json(f"{MET_NORWAY_URL}?{query}")
        properties = payload.get("properties")
        timeseries = properties.get("timeseries") if isinstance(properties, Mapping) else None
        row = timeseries[0] if isinstance(timeseries, list) and timeseries else None
        data = row.get("data") if isinstance(row, Mapping) else None
        instant = data.get("instant") if isinstance(data, Mapping) else None
        details = instant.get("details") if isinstance(instant, Mapping) else None
        if not isinstance(details, Mapping) or _number(details.get("air_temperature")) is None:
            raise ShortcutWeatherError("weather_no_data")
        next_hour = data.get("next_1_hours") if isinstance(data, Mapping) else None
        summary = next_hour.get("summary") if isinstance(next_hour, Mapping) else None
        next_details = next_hour.get("details") if isinstance(next_hour, Mapping) else None
        wind_ms = _number(details.get("wind_speed"))
        return {
            "observedAt": str(row.get("time") or "") if isinstance(row, Mapping) else "",
            "condition": _met_condition(summary.get("symbol_code") if isinstance(summary, Mapping) else ""),
            "temperatureC": _number(details.get("air_temperature")),
            "apparentTemperatureC": None,
            "humidityPercent": _number(details.get("relative_humidity"), 0),
            "windSpeedKmh": _number(float(wind_ms) * 3.6) if wind_ms is not None else None,
            "precipitationMm": _number(next_details.get("precipitation_amount")) if isinstance(next_details, Mapping) else None,
            "attribution": "MET Norway",
            "attributionUrl": "https://api.met.no/",
        }
