import importlib
from pathlib import Path
import unittest

import kaos_governor
import kaos_governor_discord
import kaosdiscoord
from kaos_governor_discord.bot import GovernorBot as LegacyGovernorBot
from kaos_governor_discord.health import HealthServer as LegacyHealthServer
from kaosdiscoord.bot import GovernorBot
from kaosdiscoord.health import HealthServer


LEGACY_MODULES = (
    "access",
    "bot",
    "calendar",
    "config",
    "fax",
    "governor_api",
    "health",
    "inbox",
    "inbox_formatting",
    "mail",
    "main",
    "maintenance",
    "markdown",
    "memos",
    "organizer",
    "paperless_search_view",
    "search",
    "system_status",
    "tasks",
    "tools",
)


class KaosDiscoordCompatibilityTests(unittest.TestCase):
    def test_legacy_namespace_reexports_canonical_implementations(self) -> None:
        self.assertEqual(kaos_governor_discord.__version__, kaosdiscoord.__version__)
        self.assertIs(LegacyGovernorBot, GovernorBot)
        self.assertIs(LegacyHealthServer, HealthServer)

    def test_every_legacy_module_remains_importable(self) -> None:
        for module_name in LEGACY_MODULES:
            with self.subTest(module=module_name):
                importlib.import_module(f"kaos_governor_discord.{module_name}")


class GovernorDependencyBoundaryTests(unittest.TestCase):
    def test_governor_has_no_discord_adapter_imports(self) -> None:
        governor_root = Path(kaos_governor.__file__).resolve().parent
        forbidden = (
            "import discord",
            "from discord",
            "import kaosdiscoord",
            "from kaosdiscoord",
            "import kaos_governor_discord",
            "from kaos_governor_discord",
        )
        violations: list[str] = []

        for source_file in governor_root.rglob("*.py"):
            source = source_file.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in source:
                    violations.append(f"{source_file.relative_to(governor_root)}: {marker}")

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
