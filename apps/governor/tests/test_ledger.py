from __future__ import annotations

import importlib.util
import importlib
from pathlib import Path
import sys
import unittest


def load_module(name: str, relative: str):
    test_path = Path(__file__).resolve()
    path = next(
        (
            parent / relative
            for parent in test_path.parents
            if (parent / relative).exists()
        ),
        None,
    )
    if path is None:
        package_name = relative.removeprefix("src/").removesuffix(".py").replace("/", ".")
        return importlib.import_module(package_name)
    src_path = next((parent / "src" for parent in path.parents if (parent / "src").exists()), None)
    if src_path is not None and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{relative} unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LedgerServiceTests(unittest.TestCase):
    def test_category_deltas_match_family_ledger_contract(self) -> None:
        service = load_module("kaos_ledger_service", "src/kaos_governor/ledger/service.py")

        self.assertEqual(service.deltas_for("계좌 수입", "10,000"), ("계좌 수입", 10000, (10000, 0, 0)))
        self.assertEqual(service.deltas_for("현금 인출", 5000), ("현금 인출", 5000, (-5000, 5000, 0)))
        self.assertEqual(service.deltas_for("상품권 사용", 3000), ("상품권 사용", 3000, (0, 0, -3000)))

    def test_balances_are_running_totals(self) -> None:
        service = load_module("kaos_ledger_service", "src/kaos_governor/ledger/service.py")

        entries, balances = service._with_balances(
            [
                {"accountDelta": 10000, "cashDelta": 0, "giftDelta": 0},
                {"accountDelta": -3000, "cashDelta": 3000, "giftDelta": 0},
                {"accountDelta": 0, "cashDelta": 0, "giftDelta": -1000},
            ]
        )

        self.assertEqual(entries[0]["account"], 10000)
        self.assertEqual(entries[1]["account"], 7000)
        self.assertEqual(entries[1]["cash"], 3000)
        self.assertEqual(entries[2]["gift"], -1000)
        self.assertEqual(balances, {"account": 7000, "cash": 3000, "gift": -1000})

    def test_invalid_payloads_raise_stable_error_codes(self) -> None:
        service = load_module("kaos_ledger_service", "src/kaos_governor/ledger/service.py")

        with self.assertRaisesRegex(ValueError, "invalid_ledger_category"):
            service.normalize_payload({"date": "2026-08-18", "category": "기타", "amount": 1})
        with self.assertRaisesRegex(ValueError, "invalid_ledger_amount"):
            service.normalize_payload({"date": "2026-08-18", "category": "계좌 수입", "amount": -1})
        with self.assertRaisesRegex(ValueError, "invalid_ledger_date"):
            service.normalize_payload({"date": "2026-99-99", "category": "계좌 수입", "amount": 1})

    def test_family_ledger_migration_declares_required_tables(self) -> None:
        migration = next(
            (
                parent / "migrations" / "004_family_ledger.sql"
                for parent in Path(__file__).resolve().parents
                if (parent / "migrations" / "004_family_ledger.sql").exists()
            ),
            None,
        )

        self.assertIsNotNone(migration)
        text = migration.read_text(encoding="utf-8") if migration else ""
        for required in [
            "CREATE TABLE IF NOT EXISTS family_ledger_entries",
            "CREATE TABLE IF NOT EXISTS family_ledger_audit",
            "family_ledger_active_order_idx",
            "family_ledger_audit_created_idx",
        ]:
            self.assertIn(required, text)

    def test_api_maps_family_ledger_errors_to_public_status_codes(self) -> None:
        api = load_module("kaos_governor_api", "src/kaos_governor/api.py")

        self.assertEqual(api.ledger_status_for_error(ValueError("ledger_entry_not_found")), 404)
        self.assertEqual(api.ledger_status_for_error(Exception("ledger_revision_conflict")), 409)
        self.assertEqual(api.ledger_status_for_error(ValueError("family_profile_required")), 404)
        self.assertEqual(api.ledger_status_for_error(ValueError("invalid_ledger_date")), 400)


if __name__ == "__main__":
    unittest.main()
