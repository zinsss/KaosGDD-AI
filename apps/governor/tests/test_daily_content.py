from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from kaos_governor.daily_content import DailyContentLibrary


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def bible_payload() -> dict[str, object]:
    return {
        "books": [
            {
                "id": "PSA",
                "name": "시편",
                "chapters": [
                    {
                        "chapter": {
                            "number": 1,
                            "content": [
                                {
                                    "type": "verse",
                                    "number": index,
                                    "text": f"시험용으로 충분히 긴 성경 말씀 {index}",
                                }
                                for index in range(1, 121)
                            ],
                        }
                    }
                ],
            }
        ]
    }


def quotes_payload() -> list[dict[str, object]]:
    return [
        {
            "_id": f"quote-{index}",
            "content": f"A sufficiently useful inspirational quote number {index}.",
            "author": f"Author {index}",
            "tags": ["Inspirational"],
        }
        for index in range(120)
    ]


class DailyContentTests(unittest.TestCase):
    def test_refresh_downloads_validates_and_caches_hundreds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            calls = []

            def urlopen(request, **_kwargs):
                calls.append(request.full_url)
                payload = bible_payload() if "bible" in request.full_url else quotes_payload()
                return Response(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

            library = DailyContentLibrary(
                cache_path=Path(temporary) / "content.json",
                bible_url="https://example.test/bible.json",
                quotes_url="https://example.test/quotes.json",
                urlopen=urlopen,
            )

            status = library.refresh(now=datetime(2026, 8, 29, tzinfo=timezone.utc))
            bible, quote = library.for_day(0)

            self.assertEqual(len(calls), 2)
            self.assertEqual(status["webBibleCount"], 120)
            self.assertEqual(status["webQuoteCount"], 120)
            self.assertEqual(bible.reference, "시편 1:1")
            self.assertEqual(quote.author, "Author 0")
            self.assertTrue((Path(temporary) / "content.json").exists())

    def test_fresh_cache_is_reused_without_web_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "content.json"

            def first_urlopen(request, **_kwargs):
                payload = bible_payload() if "bible" in request.full_url else quotes_payload()
                return Response(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

            first = DailyContentLibrary(
                cache_path=cache_path,
                bible_url="https://example.test/bible.json",
                quotes_url="https://example.test/quotes.json",
                urlopen=first_urlopen,
            )
            now = datetime(2026, 8, 29, tzinfo=timezone.utc)
            first.refresh(now=now)

            def unexpected_urlopen(*_args, **_kwargs):
                raise AssertionError("fresh cache should not use the web")

            second = DailyContentLibrary(
                cache_path=cache_path,
                bible_url="https://example.test/bible.json",
                quotes_url="https://example.test/quotes.json",
                urlopen=unexpected_urlopen,
            )
            status = second.refresh(now=now)

            self.assertEqual(status["webBibleCount"], 120)
            self.assertEqual(status["webQuoteCount"], 120)
            self.assertEqual(status["lastError"], "")

    def test_failed_web_refresh_keeps_local_fallback(self) -> None:
        def failing_urlopen(*_args, **_kwargs):
            raise OSError("offline")

        with tempfile.TemporaryDirectory() as temporary:
            library = DailyContentLibrary(
                cache_path=Path(temporary) / "content.json",
                urlopen=failing_urlopen,
                fallback_bible=(("시편 1:1", "fallback bible"),),
                fallback_quotes=("fallback quote",),
            )

            status = library.refresh(force=True)
            bible, quote = library.for_day(0)

        self.assertEqual(status["bibleCount"], 1)
        self.assertEqual(status["quoteCount"], 1)
        self.assertIn("fetch_failed", str(status["lastError"]))
        self.assertEqual(bible.text, "fallback bible")
        self.assertEqual(quote.text, "fallback quote")

    def test_next_items_cycle_and_wrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = DailyContentLibrary(
                cache_path=Path(temporary) / "content.json",
                fallback_bible=(("시편 1:1", "first"), ("시편 1:2", "second")),
                fallback_quotes=("first quote", "second quote"),
            )

            second_bible = library.next_bible("시편 1:1 — first")
            wrapped_bible = library.next_bible("시편 1:2 — second")
            second_quote = library.next_quote("“first quote”")

        self.assertEqual(second_bible.reference, "시편 1:2")
        self.assertEqual(wrapped_bible.reference, "시편 1:1")
        self.assertEqual(second_quote.text, "second quote")


if __name__ == "__main__":
    unittest.main()
