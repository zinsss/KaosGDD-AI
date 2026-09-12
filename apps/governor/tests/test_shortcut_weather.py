from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import unittest
import urllib.parse

from kaos_governor.shortcut_weather import ShortcutWeatherError, WeatherComparisonService


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class WeatherComparisonServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests = []
        self.lock = threading.Lock()

    @staticmethod
    def open_meteo_payload(temperature: float, code: int) -> dict[str, object]:
        return {
            "current": {
                "time": "2026-09-12T09:00",
                "temperature_2m": temperature,
                "apparent_temperature": temperature + 1.2,
                "relative_humidity_2m": 73,
                "precipitation": 0,
                "rain": 0,
                "weather_code": code,
                "wind_speed_10m": 5.4,
            },
            "hourly": {
                "time": [
                    "2026-09-12T08:00",
                    "2026-09-12T09:00",
                    "2026-09-12T10:00",
                    "2026-09-13T00:00",
                ],
                "temperature_2m": [19, 20, 21, 18],
                "precipitation_probability": [10, 20, 30, 40],
                "weather_code": [0, 2, 61, 3],
            },
        }

    @staticmethod
    def met_payload() -> dict[str, object]:
        return {
            "properties": {
                "timeseries": [
                    {
                        "time": "2026-09-12T00:00:00Z",
                        "data": {
                            "instant": {
                                "details": {
                                    "air_temperature": 21,
                                    "relative_humidity": 80,
                                    "wind_speed": 2,
                                }
                            },
                            "next_1_hours": {
                                "summary": {"symbol_code": "partlycloudy_day"},
                                "details": {"precipitation_amount": 0.2},
                            },
                        },
                    }
                ]
            }
        }

    def urlopen(self, request, timeout):
        with self.lock:
            self.requests.append((request, timeout))
        parsed = urllib.parse.urlparse(request.full_url)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.netloc == "api.met.no":
            return FakeResponse(self.met_payload())
        model = query.get("models", [""])[0]
        if model == "kma_seamless":
            return FakeResponse(self.open_meteo_payload(19.5, 2))
        if model == "ecmwf_ifs025":
            return FakeResponse(self.open_meteo_payload(22, 3))
        return FakeResponse(self.open_meteo_payload(20.5, 0))

    def service(self) -> WeatherComparisonService:
        return WeatherComparisonService(
            urlopen=self.urlopen,
            now=lambda: datetime(2026, 9, 12, 0, 15, tzinfo=timezone.utc),
        )

    def test_compares_sources_and_returns_shortcut_ready_korean_text(self) -> None:
        payload = self.service().compare(36.019, 129.343, "포항")

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["readOnly"])
        self.assertEqual([source["id"] for source in payload["sources"]], [
            "open_meteo",
            "kma",
            "ecmwf",
            "met_norway",
        ])
        self.assertEqual(payload["temperatureSpreadC"], 2.5)
        self.assertIn("🌦️ 현재 위치 날씨 비교", payload["text"])
        self.assertIn("📍 포항", payload["text"])
        self.assertIn(
            "• Open-Meteo ☀️ 20.5°C // KMA ⛅ 19.5°C // ECMWF ☁️ 22°C // MET ⛅ 21°C",
            payload["text"],
        )
        self.assertNotIn("Open-Meteo Best Match:", payload["text"])
        self.assertNotIn("MET Norway:", payload["text"])
        self.assertIn("공급자 온도 차이 2.5°C", payload["text"])
        self.assertIn("금일 시간대별", payload["text"])
        self.assertIn("09:00  ⛅ 20°C · 강수 20%", payload["text"])
        self.assertIn("10:00  🌧️ 21°C · 강수 30%", payload["text"])
        self.assertNotIn("08:00  ☀️", payload["text"])
        self.assertEqual([item["hour"] for item in payload["hourly"]], ["09:00", "10:00"])
        self.assertEqual(
            [source["glyph"] for source in payload["sources"]],
            ["☀️", "⛅", "☁️", "⛅"],
        )
        self.assertTrue(all(timeout == 8 for _request, timeout in self.requests))
        met_request = next(request for request, _timeout in self.requests if "api.met.no" in request.full_url)
        self.assertIn("KaosGDD/2.0", met_request.get_header("User-agent"))

    def test_keeps_partial_results_when_one_provider_is_unavailable(self) -> None:
        def partial_urlopen(request, timeout):
            if "kma_seamless" in request.full_url:
                raise TimeoutError("provider timeout")
            return self.urlopen(request, timeout)

        service = WeatherComparisonService(urlopen=partial_urlopen)
        payload = service.compare(36.019, 129.343)

        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["sources"]), 3)
        self.assertEqual(payload["errors"], [{"id": "kma", "name": "KMA 모델", "error": "unavailable"}])
        self.assertNotIn("KMA 모델", payload["text"])
        self.assertEqual(payload["text"].splitlines()[3].count("//"), 2)

    def test_rejects_invalid_coordinates_before_fetching(self) -> None:
        with self.assertRaisesRegex(ShortcutWeatherError, "invalid_latitude"):
            self.service().compare(100, 129.343)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
