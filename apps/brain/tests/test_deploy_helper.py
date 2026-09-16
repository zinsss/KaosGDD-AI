from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


def _deploy_helper() -> Path:
    container_path = Path("/tmp/brain/deploy/kaosbrain")
    if container_path.is_file():
        return container_path
    return Path(__file__).resolve().parents[3] / "deploy" / "kaosbrain" / "kaosbrain"


class KaosBrainDeployHelperTests(unittest.TestCase):
    def test_headless_migration_preserves_backup_and_moves_health_to_tools_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / "kaosbrain.env"
            env_file.write_text(
                "\n".join(
                    (
                        "DISCORD_BOT_TOKEN_FILE=/run/secrets/retired",
                        "DISCORD_GUILD_ID=123",
                        "KAOSBRAIN_TOKEN_FILE=/srv/retired-token",
                        "KAOSAI_CHAT_ENABLED=false",
                        "KAOSBRAIN_HEALTH_ENABLED=true",
                        "KAOSBRAIN_GOVERNOR_HEALTH_URL=http://100.64.0.8:8097/health",
                        "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED=true",
                        "UNRELATED_SETTING=kept",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            env_file.chmod(0o640)
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
ENV_FILE="$2"
unset KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL KAOSBRAIN_GOVERNOR_HEALTH_URL
ensure_upgrade_defaults
'''
            result = subprocess.run(
                ["bash", "-c", command, "_", str(_deploy_helper()), str(env_file)],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "KAOSBRAIN_ENV_FILE": str(env_file)},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            migrated = env_file.read_text(encoding="utf-8")
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o640)
            self.assertIn("KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL=http://100.64.0.8:8098", migrated)
            self.assertIn("UNRELATED_SETTING=kept", migrated)
            self.assertNotIn("DISCORD_", migrated)
            self.assertNotIn("KAOSAI_CHAT_ENABLED", migrated)
            self.assertNotIn("KAOSBRAIN_HEALTH_ENABLED", migrated)
            self.assertNotIn("KAOSBRAIN_GOVERNOR_HEALTH_URL", migrated)
            self.assertNotIn("KAOSBRAIN_TOKEN_FILE", migrated)
            self.assertIn(
                "KAOSBRAIN_AI_TASK_API_TOKEN_FILE=/run/secrets/governor_api_token",
                migrated,
            )

            backup = Path(f"{env_file}.pre-headless-discord-retirement")
            self.assertTrue(backup.is_file())
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o640)
            original = backup.read_text(encoding="utf-8")
            self.assertIn("DISCORD_GUILD_ID=123", original)
            self.assertIn("KAOSBRAIN_TOKEN_FILE=/srv/retired-token", original)
            self.assertIn("KAOSBRAIN_GOVERNOR_HEALTH_URL=http://100.64.0.8:8097/health", original)

    def test_prospective_preflight_migrates_only_a_temporary_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / "kaosbrain.env"
            original = "\n".join(
                (
                    "DISCORD_GUILD_ID=123",
                    "KAOSBRAIN_GOVERNOR_HEALTH_URL=http://100.64.0.9:8097/health",
                    "UNRELATED_SETTING=kept",
                    "",
                )
            )
            env_file.write_text(original, encoding="utf-8")
            env_file.chmod(0o640)
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
ENV_FILE="$2"
preflight() {
  grep -q '^KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL=http://100.64.0.9:8098$' "${ENV_FILE}"
  grep -q '^KAOSBRAIN_AI_TASK_API_TOKEN_FILE=/run/secrets/governor_api_token$' "${ENV_FILE}"
  ! grep -q '^DISCORD_' "${ENV_FILE}"
}
prospective_preflight
'''
            result = subprocess.run(
                ["bash", "-c", command, "_", str(_deploy_helper()), str(env_file)],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "KAOSBRAIN_ENV_FILE": str(env_file)},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_file.read_text(encoding="utf-8"), original)
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o640)
            self.assertFalse(Path(f"{env_file}.pre-headless-discord-retirement").exists())

    def test_discord_tokens_are_quarantined_idempotently_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            canonical_secrets = root / "canonical-secrets"
            legacy_root = root / "legacy"
            legacy_secrets = legacy_root / "secrets"
            canonical_env = root / "runtime" / "kaosbrain"
            canonical_secrets.mkdir()
            legacy_secrets.mkdir(parents=True)
            canonical_source = canonical_secrets / "kaosbrain_discord_bot_token"
            legacy_source = legacy_secrets / "kaosbrain_discord_bot_token"
            canonical_source.write_text("canonical-secret-value", encoding="utf-8")
            legacy_source.write_text("legacy-secret-value", encoding="utf-8")
            canonical_source.chmod(0o640)
            legacy_source.chmod(0o600)
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
sudo() { "$@"; }
CANONICAL_SECRETS_DIR="$2"
LEGACY_ROOT="$3"
CANONICAL_ENV_DIR="$4"
quarantine_retired_discord_secrets
quarantine_retired_discord_secrets
'''
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "_",
                    str(_deploy_helper()),
                    str(canonical_secrets),
                    str(legacy_root),
                    str(canonical_env),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("canonical-secret-value", result.stdout + result.stderr)
            self.assertNotIn("legacy-secret-value", result.stdout + result.stderr)
            self.assertFalse(canonical_source.exists())
            self.assertFalse(legacy_source.exists())
            retired = canonical_env / "retired-secrets"
            canonical_retired = retired / "canonical-kaosbrain_discord_bot_token"
            legacy_retired = retired / "legacy-kaosbrain_discord_bot_token"
            self.assertEqual(stat.S_IMODE(retired.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(canonical_retired.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(legacy_retired.stat().st_mode), 0o600)
            self.assertEqual(canonical_retired.read_text(encoding="utf-8"), "canonical-secret-value")
            self.assertEqual(legacy_retired.read_text(encoding="utf-8"), "legacy-secret-value")

            canonical_source.write_text("replacement-must-not-overwrite", encoding="utf-8")
            collision = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "_",
                    str(_deploy_helper()),
                    str(canonical_secrets),
                    str(legacy_root),
                    str(canonical_env),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ,
            )
            self.assertNotEqual(collision.returncode, 0)
            self.assertTrue(canonical_source.is_file())
            self.assertEqual(canonical_retired.read_text(encoding="utf-8"), "canonical-secret-value")

    def test_custom_discord_token_paths_are_translated_and_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            custom_secrets = root / "custom-secrets"
            canonical_secrets = root / "canonical-secrets"
            legacy_root = root / "legacy"
            canonical_env = root / "runtime" / "kaosbrain"
            custom_secrets.mkdir()
            canonical_secrets.mkdir()
            (legacy_root / "secrets").mkdir(parents=True)
            host_override = custom_secrets / "host-override"
            runtime_override = custom_secrets / "runtime-override"
            host_override.write_text("host-override-value", encoding="utf-8")
            runtime_override.write_text("runtime-override-value", encoding="utf-8")
            host_override.chmod(0o600)
            runtime_override.chmod(0o640)
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
sudo() { "$@"; }
SECRETS_DIR="$2"
CANONICAL_SECRETS_DIR="$3"
LEGACY_ROOT="$4"
CANONICAL_ENV_DIR="$5"
KAOSBRAIN_TOKEN_FILE=/run/secrets/host-override
DISCORD_BOT_TOKEN_FILE=/run/secrets/runtime-override
quarantine_retired_discord_secrets
'''
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "_",
                    str(_deploy_helper()),
                    str(custom_secrets),
                    str(canonical_secrets),
                    str(legacy_root),
                    str(canonical_env),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("host-override-value", result.stdout + result.stderr)
            self.assertNotIn("runtime-override-value", result.stdout + result.stderr)
            self.assertFalse(host_override.exists())
            self.assertFalse(runtime_override.exists())
            retired = canonical_env / "retired-secrets"
            retired_host = retired / "configured-host-kaosbrain_discord_bot_token"
            retired_runtime = retired / "configured-runtime-kaosbrain_discord_bot_token"
            self.assertEqual(stat.S_IMODE(retired_host.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(retired_runtime.stat().st_mode), 0o640)

    def test_discord_token_symlink_is_rejected_without_moving_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            canonical_secrets = root / "canonical-secrets"
            legacy_root = root / "legacy"
            canonical_env = root / "runtime" / "kaosbrain"
            canonical_secrets.mkdir()
            (legacy_root / "secrets").mkdir(parents=True)
            target = root / "real-secret"
            target.write_text("must-stay-put", encoding="utf-8")
            source = canonical_secrets / "kaosbrain_discord_bot_token"
            source.symlink_to(target)
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
sudo() { "$@"; }
SECRETS_DIR="$2"
CANONICAL_SECRETS_DIR="$2"
LEGACY_ROOT="$3"
CANONICAL_ENV_DIR="$4"
quarantine_retired_discord_secrets
'''
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "_",
                    str(_deploy_helper()),
                    str(canonical_secrets),
                    str(legacy_root),
                    str(canonical_env),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(source.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), "must-stay-put")
            self.assertFalse((canonical_env / "retired-secrets").exists())

    def test_shared_governor_token_path_is_never_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            secrets = root / "secrets"
            legacy_root = root / "legacy"
            canonical_env = root / "runtime" / "kaosbrain"
            secrets.mkdir()
            (legacy_root / "secrets").mkdir(parents=True)
            governor_token = secrets / "governor_api_token"
            governor_token.write_text("still-active-secret", encoding="utf-8")
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
sudo() { "$@"; }
SECRETS_DIR="$2"
CANONICAL_SECRETS_DIR="$2"
LEGACY_ROOT="$3"
CANONICAL_ENV_DIR="$4"
GOVERNOR_TOKEN_FILE="$2/governor_api_token"
DISCORD_BOT_TOKEN_FILE=/run/secrets/governor_api_token
quarantine_retired_discord_secrets
'''
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "_",
                    str(_deploy_helper()),
                    str(secrets),
                    str(legacy_root),
                    str(canonical_env),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(governor_token.read_text(encoding="utf-8"), "still-active-secret")
            self.assertNotIn("still-active-secret", result.stdout + result.stderr)
            self.assertFalse((canonical_env / "retired-secrets").exists())

    def test_authenticated_smoke_accepts_disabled_reauth_but_rejects_unauthorized(self) -> None:
        command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
curl() {
  local supplied_header
  IFS= read -r supplied_header
  [[ "${supplied_header}" == 'Authorization: Bearer smoke-secret-value' ]] || return 9
  printf '%s' "${FAKE_HTTP_STATUS}"
}
KAOSBRAIN_AI_TASK_API_TOKEN=smoke-secret-value
smoke_authenticated_headless_route http://127.0.0.1:8099
'''
        accepted = subprocess.run(
            ["bash", "-c", command, "_", str(_deploy_helper())],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "FAKE_HTTP_STATUS": "503"},
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertNotIn("smoke-secret-value", accepted.stdout + accepted.stderr)

        unauthorized = subprocess.run(
            ["bash", "-c", command, "_", str(_deploy_helper())],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "FAKE_HTTP_STATUS": "401"},
        )
        self.assertNotEqual(unauthorized.returncode, 0)
        self.assertNotIn("smoke-secret-value", unauthorized.stdout + unauthorized.stderr)

    def test_health_smoke_requires_headless_payload_shape(self) -> None:
        command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
headless_health_payload_is_valid "$2"
'''
        valid = '{"status":"ok","service":"kaos-brain","runtime":"headless","httpReady":true}'
        invalid = '{"status":"ok","service":"kaos-brain","runtime":"discord","httpReady":true}'
        for payload, expected in ((valid, 0), (invalid, 1)):
            with self.subTest(payload=payload):
                result = subprocess.run(
                    ["bash", "-c", command, "_", str(_deploy_helper()), payload],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=os.environ,
                )
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_up_orders_staging_snapshot_cutover_and_rollback(self) -> None:
        source = _deploy_helper().read_text(encoding="utf-8")
        up_body = source.split("\nup() {\n", 1)[1].split("\n}\n\ndeploy()", 1)[0]
        prospective = up_body.index("  prospective_preflight")
        build = up_body.index('  build_image "${CANDIDATE_IMAGE_NAME}"')
        snapshot = up_body.index('  if ! sudo cp -p "${ENV_FILE}"')
        preserve = up_body.index("  if ! preserve_pre_headless_rollback_artifacts")
        migrate = up_body.index("    ensure_upgrade_defaults")
        retag = up_body.index('    docker image tag "${CANDIDATE_IMAGE_NAME}"')
        install = up_body.index("    install_service_unit")
        quarantine = up_body.index("    if ! quarantine_retired_discord_secrets")
        restart = up_body.index('      sudo systemctl restart "${SERVICE_NAME}"')
        smoke = up_body.index("      smoke")
        rollback = up_body.index("    if rollback_headless_cutover")
        self.assertLess(prospective, build)
        self.assertLess(build, snapshot)
        self.assertLess(snapshot, preserve)
        self.assertLess(preserve, migrate)
        self.assertLess(migrate, retag)
        self.assertLess(retag, install)
        self.assertLess(install, quarantine)
        self.assertLess(quarantine, restart)
        self.assertLess(restart, smoke)
        self.assertLess(smoke, rollback)

    def test_pre_retirement_image_env_and_unit_are_persistently_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            env_file = root / "kaosbrain.env"
            unit_file = root / "kaosbrain.service"
            action_log = root / "actions.log"
            env_file.write_text("OLD_ENV=true\n", encoding="utf-8")
            unit_file.write_text("old unit\n", encoding="utf-8")
            env_file.chmod(0o640)
            unit_file.chmod(0o644)
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
sudo() { "$@"; }
docker() {
  if [[ "$1 $2" == 'image inspect' ]]; then
    return 1
  fi
  printf 'docker %s\n' "$*" >>"${ACTION_LOG}"
}
ENV_FILE="$2"
ROLLBACK_IMAGE_NAME=kaos-brain:pre-headless-discord-retirement
ACTION_LOG="$4"
preserve_pre_headless_rollback_artifacts sha256:old-image "$3" true
'''
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "_",
                    str(_deploy_helper()),
                    str(env_file),
                    str(unit_file),
                    str(action_log),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            env_backup = Path(f"{env_file}.pre-headless-discord-retirement")
            unit_backup = Path(f"{env_file}.unit.pre-headless-discord-retirement")
            self.assertEqual(env_backup.read_text(encoding="utf-8"), "OLD_ENV=true\n")
            self.assertEqual(unit_backup.read_text(encoding="utf-8"), "old unit\n")
            self.assertEqual(stat.S_IMODE(env_backup.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(unit_backup.stat().st_mode), 0o644)
            self.assertIn(
                "docker image tag sha256:old-image kaos-brain:pre-headless-discord-retirement",
                action_log.read_text(encoding="utf-8"),
            )

    def test_rollback_restores_env_unit_image_secrets_and_running_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            env_file = root / "kaosbrain.env"
            unit_dir = root / "units"
            rollback = root / "rollback"
            action_log = root / "actions.log"
            unit_dir.mkdir()
            rollback.mkdir()
            env_file.write_text("CUTOVER_ENV=true\n", encoding="utf-8")
            (unit_dir / "kaosbrain.service").write_text("new unit\n", encoding="utf-8")
            (rollback / "kaosbrain.env").write_text("OLD_ENV=true\n", encoding="utf-8")
            (rollback / "kaosbrain.service").write_text("old unit\n", encoding="utf-8")
            command = r'''
source <(awk '/^case "\$\{1:-\}" in$/{exit} {print}' "$1")
sudo() { "$@"; }
systemctl() { printf 'systemctl %s\n' "$*" >>"${ACTION_LOG}"; }
docker() { printf 'docker %s\n' "$*" >>"${ACTION_LOG}"; }
restore_quarantined_discord_secrets() { printf 'restore-secrets\n' >>"${ACTION_LOG}"; }
ENV_FILE="$2"
SYSTEMD_UNIT_DIR="$3"
ACTION_LOG="$5"
SERVICE_NAME=kaosbrain.service
IMAGE_NAME=kaos-brain:current
rollback_headless_cutover "$4" sha256:old-image true true
'''
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "_",
                    str(_deploy_helper()),
                    str(env_file),
                    str(unit_dir),
                    str(rollback),
                    str(action_log),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=os.environ,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_file.read_text(encoding="utf-8"), "OLD_ENV=true\n")
            self.assertEqual(
                (unit_dir / "kaosbrain.service").read_text(encoding="utf-8"),
                "old unit\n",
            )
            actions = action_log.read_text(encoding="utf-8")
            self.assertIn("systemctl stop kaosbrain.service", actions)
            self.assertIn("docker image tag sha256:old-image kaos-brain:current", actions)
            self.assertIn("restore-secrets", actions)
            self.assertIn("systemctl daemon-reload", actions)
            self.assertIn("systemctl restart kaosbrain.service", actions)


if __name__ == "__main__":
    unittest.main()
