"""Host-side, read-only maintenance report collector.

This file is intentionally executable as a standalone standard-library script.
SSH and Docker access stay on the host and are never granted to the Governor
worker container.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from typing import Callable, Mapping


DEFAULT_MAINTENANCE_TIMEOUT_SECONDS = 12.0
DEFAULT_TARGETS = (
    "kaosgdd=local:/srv/projects/KaosGDD-AI,"
    "kaosbrain=ssh:zin@kaosbrain:/srv/projects/KaosGDD-AI,"
    "kaosclinic=ssh:zin@kaosclinic:"
)


@dataclass(frozen=True)
class MaintenanceTarget:
    name: str
    mode: str
    address: str
    repo_path: str = ""


@dataclass(frozen=True)
class MaintenanceReport:
    target: MaintenanceTarget
    ok: bool
    facts: Mapping[str, str]
    error: str = ""
    collected_at: str = ""


Runner = Callable[[MaintenanceTarget, str, float], subprocess.CompletedProcess[str]]


def maintenance_targets(raw: str) -> tuple[MaintenanceTarget, ...]:
    targets: list[MaintenanceTarget] = []
    for part in (raw.strip() or DEFAULT_TARGETS).split(","):
        entry = part.strip()
        if not entry:
            continue
        name, separator, spec = entry.partition("=")
        if not separator:
            continue
        mode, _, remainder = spec.partition(":")
        mode = mode.strip().lower()
        if mode == "local":
            targets.append(MaintenanceTarget(name.strip(), mode, "", remainder.strip()))
        elif mode == "ssh":
            address, _, repo_path = remainder.partition(":")
            if address.strip():
                targets.append(
                    MaintenanceTarget(name.strip(), mode, address.strip(), repo_path.strip())
                )
    return tuple(target for target in targets if target.name)


def maintenance_timeout_seconds(raw: str) -> float:
    try:
        value = float(raw.strip())
    except ValueError:
        return DEFAULT_MAINTENANCE_TIMEOUT_SECONDS
    return min(max(value, 3.0), 60.0)


def collect_maintenance_report(
    target: MaintenanceTarget,
    timeout_seconds: float,
    runner: Runner,
) -> MaintenanceReport:
    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        completed = runner(target, maintenance_probe_script(target.repo_path), timeout_seconds)
    except (OSError, subprocess.SubprocessError) as exc:
        return MaintenanceReport(target, False, {}, stable_error(exc), collected_at)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        return MaintenanceReport(target, False, {}, detail[:200], collected_at)
    return MaintenanceReport(
        target,
        True,
        parse_probe_output(completed.stdout),
        collected_at=collected_at,
    )


def default_runner(
    target: MaintenanceTarget,
    script: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    if target.mode == "local":
        return subprocess.run(
            ["bash", "-s"],
            input=script,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    if target.mode == "ssh":
        return subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "StrictHostKeyChecking=accept-new",
                target.address,
                "bash -s",
            ],
            input=script,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    return subprocess.CompletedProcess(
        [],
        2,
        "",
        f"unsupported target mode: {target.mode}",
    )


def maintenance_probe_script(repo_path: str) -> str:
    quoted_repo = shlex.quote(repo_path)
    script = r'''set +e
kv() { printf '%s=%s\n' "$1" "$2"; }
kv hostname "$(hostname 2>/dev/null)"
kv checked_at "$(date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null)"
kv uptime "$(uptime -p 2>/dev/null)"
kv reboot_required "$([ -f /var/run/reboot-required ] && echo yes || echo no)"
kv disk_root "$(df -h / 2>/dev/null | awk 'NR==2{print $5 " used, " $4 " free"}')"
kv memory "$(free -m 2>/dev/null | awk '/^Mem:/{print $3 "MiB/" $2 "MiB"}')"
if command -v apt >/dev/null 2>&1; then
  kv os_updates "$(apt list --upgradable 2>/dev/null | awk 'NR>1{c++} END{print c+0}')"
  kv docker_package_updates "$(apt list --upgradable 2>/dev/null | awk -F/ '/^(docker|docker-ce|docker.io|containerd|containerd.io|docker-compose-plugin)\//{c++} END{print c+0}')"
else
  kv os_updates unknown
  kv docker_package_updates unknown
fi
if command -v docker >/dev/null 2>&1; then
  kv docker_engine "$(docker --version 2>/dev/null | sed 's/, build.*//')"
  kv docker_compose "$(docker compose version --short 2>/dev/null || echo unavailable)"
  kv docker_running "$(docker ps -q 2>/dev/null | wc -l | tr -d ' ')"
  kv docker_unhealthy "$(docker ps --filter health=unhealthy -q 2>/dev/null | wc -l | tr -d ' ')"
  kv docker_exited "$(docker ps -a --filter status=exited -q 2>/dev/null | wc -l | tr -d ' ')"
else
  kv docker_engine unavailable
  kv docker_compose unavailable
  kv docker_running unknown
  kv docker_unhealthy unknown
  kv docker_exited unknown
fi
repo=__KAOS_REPO_PATH__
if [ -n "$repo" ] && [ -d "$repo/.git" ]; then
  kv repo "$(git -C "$repo" status -sb 2>/dev/null | head -n 1)"
  kv repo_dirty "$(git -C "$repo" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
else
  kv repo not-configured
  kv repo_dirty unknown
fi
openclaw_config="/srv/kaosgdd/kaosai/openclaw/openclaw.json"
if [ -f "$openclaw_config" ]; then
  kv openclaw_configured yes
  kv openclaw_gateway "$(systemctl --user is-active openclaw-gateway.service 2>/dev/null || echo unknown)"
  kv openclaw_reauth_agent "$(systemctl --user is-active kaosai-openclaw-reauth-agent.service 2>/dev/null || echo unknown)"
  if command -v python3 >/dev/null 2>&1; then
    kv openclaw_primary_model "$(python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], encoding="utf-8")); print(str(payload.get("agents", dict()).get("defaults", dict()).get("model", dict()).get("primary") or "unknown"))' "$openclaw_config" 2>/dev/null || echo unknown)"
    kv openclaw_last_touched "$(python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], encoding="utf-8")); print(str(payload.get("meta", dict()).get("lastTouchedAt") or payload.get("wizard", dict()).get("lastRunAt") or "unknown"))' "$openclaw_config" 2>/dev/null || echo unknown)"
  else
    kv openclaw_primary_model unknown
    kv openclaw_last_touched unknown
  fi
  export OPENCLAW_STATE_DIR="$(dirname "$openclaw_config")"
  export OPENCLAW_CONFIG_PATH="$openclaw_config"
  if [ -s "$HOME/.nvm/nvm.sh" ]; then
    . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1
    nvm use 24 >/dev/null 2>&1 || true
  fi
  if command -v openclaw >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    old_umask="$(umask)"
    umask 077
    openclaw_status_file="$(mktemp 2>/dev/null)"
    umask "$old_umask"
    cleanup_openclaw_status() { [ -z "$openclaw_status_file" ] || rm -f -- "$openclaw_status_file"; }
    trap cleanup_openclaw_status EXIT HUP INT TERM
    if [ -n "$openclaw_status_file" ] && openclaw models status --json >"$openclaw_status_file" 2>/dev/null; then
      python3 - "$openclaw_status_file" <<'PY'
__OPENCLAW_STATUS_PARSER__
PY
    else
      kv openclaw_auth_probe error
      kv openclaw_auth_status unknown
      kv openclaw_auth_expires_at unknown
    fi
    cleanup_openclaw_status
    openclaw_status_file=""
    trap - EXIT HUP INT TERM
  else
    kv openclaw_auth_probe unavailable
    kv openclaw_auth_status unknown
    kv openclaw_auth_expires_at unknown
  fi
else
  kv openclaw_configured no
fi
kv docker_image_updates "not checked; requires explicit pull"
'''
    return script.replace("__KAOS_REPO_PATH__", quoted_repo).replace(
        "__OPENCLAW_STATUS_PARSER__",
        _openclaw_status_parser_program(),
    )


def parse_probe_output(output: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            facts[key] = value.strip()
    return facts


def parse_openclaw_models_status(payload: object) -> dict[str, str]:
    """Return only non-secret OpenAI auth status and expiry."""
    providers_of_interest = ("openai", "openai-codex")
    statuses = frozenset(("ok", "expiring", "expired", "missing", "static"))
    priority = {
        "expired": 5,
        "missing": 4,
        "expiring": 3,
        "ok": 2,
        "static": 1,
        "unknown": 0,
    }

    def mappings(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def provider_id(value: object) -> str:
        return str(value or "").strip().lower()

    def status(value: object) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in statuses else "unknown"

    def most_actionable(values: object) -> str:
        return max(
            (status(value) for value in values),
            key=lambda item: priority[item],
            default="unknown",
        )

    def expiry_iso(value: object) -> str:
        try:
            if isinstance(value, str) and not value.strip():
                return ""
            if isinstance(value, str) and not value.strip().replace(".", "", 1).isdigit():
                text = value.strip()
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat(
                    timespec="seconds"
                ).replace("+00:00", "Z")
            numeric = float(value)
            if numeric <= 0:
                return ""
            if numeric < 100_000_000_000:
                numeric *= 1000
            return datetime.fromtimestamp(numeric / 1000, timezone.utc).isoformat(
                timespec="seconds"
            ).replace("+00:00", "Z")
        except (OverflowError, OSError, TypeError, ValueError):
            return ""

    def first_entries(
        entries: list[dict[str, object]],
        preferred: list[str],
    ) -> list[dict[str, object]]:
        for candidate in preferred:
            selected = [
                item
                for item in entries
                if provider_id(item.get("provider")) == candidate
            ]
            if selected:
                return selected
        return []

    def earliest_expiry(entries: list[dict[str, object]]) -> str:
        values = [expiry_iso(item.get("expiresAt")) for item in entries]
        return min((value for value in values if value), default="")

    if not isinstance(payload, dict):
        return {"status": "unknown", "expires_at": ""}
    auth = payload.get("auth")
    auth = auth if isinstance(auth, dict) else {}
    oauth = auth.get("oauth")
    oauth = oauth if isinstance(oauth, dict) else {}
    routes = [
        item
        for item in mappings(auth.get("runtimeAuthRoutes"))
        if provider_id(item.get("provider")) in providers_of_interest
        or provider_id(item.get("authProvider")) in providers_of_interest
    ]
    providers = mappings(oauth.get("providers"))
    profiles = [
        item
        for item in mappings(oauth.get("profiles"))
        if str(item.get("type") or "").strip().lower() in {"oauth", "token"}
    ]

    selected_status = "unknown"
    preferred: list[str] = []
    if routes:
        selected_status = most_actionable(item.get("status") for item in routes)
        preferred.extend(provider_id(item.get("authProvider")) for item in routes)
        preferred.extend(provider_id(item.get("provider")) for item in routes)
    preferred.extend(providers_of_interest)
    preferred = list(
        dict.fromkeys(item for item in preferred if item in providers_of_interest)
    )

    selected_entries = first_entries(providers, preferred)
    if selected_status == "unknown" and selected_entries:
        selected_status = most_actionable(item.get("status") for item in selected_entries)
    profile_entries = first_entries(profiles, preferred)
    if selected_status == "unknown" and profile_entries:
        selected_status = most_actionable(item.get("status") for item in profile_entries)
    missing = {
        provider_id(item)
        for item in auth.get("missingProvidersInUse", [])
        if isinstance(item, str)
    }
    if selected_status == "unknown" and missing.intersection(providers_of_interest):
        selected_status = "missing"
    expires_at = earliest_expiry(selected_entries) or earliest_expiry(profile_entries)
    return {"status": selected_status, "expires_at": expires_at}


def _openclaw_status_parser_program() -> str:
    parser = inspect.getsource(parse_openclaw_models_status)
    return "\n".join(
        (
            "import json",
            "import sys",
            "from datetime import datetime, timezone",
            "",
            parser,
            "try:",
            '    payload = json.load(open(sys.argv[1], encoding="utf-8"))',
            "except (OSError, ValueError):",
            '    print("openclaw_auth_probe=invalid")',
            '    print("openclaw_auth_status=unknown")',
            '    print("openclaw_auth_expires_at=unknown")',
            "    raise SystemExit(0)",
            "facts = parse_openclaw_models_status(payload)",
            'print("openclaw_auth_probe=ok")',
            'print(f"openclaw_auth_status={facts[\'status\']}")',
            'print(f"openclaw_auth_expires_at={facts[\'expires_at\'] or \'unknown\'}")',
        )
    )


def report_payload(report: MaintenanceReport) -> dict[str, object]:
    return {
        "target": {
            "name": report.target.name,
            "mode": report.target.mode,
            "address": report.target.address,
            "repoPath": report.target.repo_path,
        },
        "ok": report.ok,
        "facts": dict(report.facts),
        "error": report.error,
        "collectedAt": report.collected_at,
    }


def write_report(path: Path, reports: list[MaintenanceReport]) -> None:
    payload = {
        "collectedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reports": [report_payload(report) for report in reports],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".maintenance.",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary_path.chmod(0o660)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def stable_error(exc: BaseException) -> str:
    return str(exc)[:200] or exc.__class__.__name__


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a read-only Kaos maintenance report")
    parser.add_argument("report_path", type=Path)
    parser.add_argument("targets")
    parser.add_argument("timeout")
    arguments = parser.parse_args()
    timeout = maintenance_timeout_seconds(arguments.timeout)
    reports = [
        collect_maintenance_report(target, timeout, default_runner)
        for target in maintenance_targets(arguments.targets)
    ]
    write_report(arguments.report_path, reports)
    print(arguments.report_path)


if __name__ == "__main__":
    main()
