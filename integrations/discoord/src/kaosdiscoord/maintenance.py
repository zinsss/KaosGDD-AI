from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import inspect
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Callable, Mapping



def escape_text(value: object) -> str:
    """Load Discord-specific escaping only when rendering a Discord message.

    The host-side maintenance collector imports this module without installing
    the Discord runtime; collection itself uses only the standard library.
    """

    from .markdown import escape_text as markdown_escape_text

    return markdown_escape_text(value)


DEFAULT_MAINTENANCE_TIMEOUT_SECONDS = 12.0
DEFAULT_MAINTENANCE_REPORT_MAX_AGE = timedelta(days=2)
DEFAULT_TARGETS = "kaosgdd=local:/srv/projects/KaosGDD-AI,kaosbrain=ssh:zin@kaosbrain:/srv/projects/KaosGDD-AI,kaosclinic=ssh:zin@kaosclinic:"
DEFAULT_REPORT_PATH = "/data/discord-system/maintenance.json"


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


@dataclass(frozen=True)
class OpenClawRenewalReminder:
    key: str
    target: str
    model: str
    auth_status: str
    expires_at: str
    reminder_on: date
    expires_on: date | None
    estimated: bool = False


Runner = Callable[[MaintenanceTarget, str, float], subprocess.CompletedProcess[str]]


async def collect_maintenance_reports(
    env: Mapping[str, str] | None = None,
    *,
    runner: Runner | None = None,
) -> list[MaintenanceReport]:
    source = os.environ if env is None else env
    if not maintenance_commands_allowed(source):
        return load_stored_maintenance_reports(source)
    targets = maintenance_targets(source)
    timeout_seconds = maintenance_timeout_seconds(source)
    run = default_runner if runner is None else runner
    return await asyncio.gather(
        *(asyncio.to_thread(collect_maintenance_report, target, timeout_seconds, run) for target in targets)
    )


def collect_maintenance_report(target: MaintenanceTarget, timeout_seconds: float, runner: Runner) -> MaintenanceReport:
    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        completed = runner(target, maintenance_probe_script(target.repo_path), timeout_seconds)
    except (OSError, subprocess.SubprocessError) as exc:
        return MaintenanceReport(target, False, {}, stable_error(exc), collected_at)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        return MaintenanceReport(target, False, {}, detail[:200], collected_at)
    return MaintenanceReport(target, True, parse_probe_output(completed.stdout), collected_at=collected_at)


def load_stored_maintenance_reports(env: Mapping[str, str]) -> list[MaintenanceReport]:
    path = Path(env.get("SYSTEM_MAINTENANCE_REPORT_PATH", "").strip() or DEFAULT_REPORT_PATH)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [
            MaintenanceReport(
                MaintenanceTarget("maintenance", "file", "", str(path)),
                False,
                {},
                f"no report yet; run ./deploy/h3-backend/kaos-h3 maintenance-report",
            )
        ]
    except (OSError, json.JSONDecodeError) as exc:
        return [MaintenanceReport(MaintenanceTarget("maintenance", "file", "", str(path)), False, {}, stable_error(exc))]
    collected_at = str(payload.get("collectedAt") or "")
    reports = []
    for item in list(payload.get("reports") or []):
        if not isinstance(item, dict):
            continue
        target_payload = dict(item.get("target") or {})
        target = MaintenanceTarget(
            str(target_payload.get("name") or item.get("name") or "unknown"),
            str(target_payload.get("mode") or ""),
            str(target_payload.get("address") or ""),
            str(target_payload.get("repoPath") or ""),
        )
        facts = {
            str(key): str(value)
            for key, value in dict(item.get("facts") or {}).items()
            if str(key)
        }
        reports.append(
            MaintenanceReport(
                target,
                bool(item.get("ok")),
                facts,
                str(item.get("error") or ""),
                str(item.get("collectedAt") or collected_at),
            )
        )
    if not reports:
        return [MaintenanceReport(MaintenanceTarget("maintenance", "file", "", str(path)), False, {}, "empty report")]
    return reports


def default_runner(target: MaintenanceTarget, script: str, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
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
    return subprocess.CompletedProcess([], 2, "", f"unsupported target mode: {target.mode}")


def maintenance_probe_script(repo_path: str) -> str:
    quoted_repo = shlex.quote(repo_path)
    script = """set +e
kv() { printf '%s=%s\\n' "$1" "$2"; }
kv hostname "$(hostname 2>/dev/null)"
kv checked_at "$(date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null)"
kv uptime "$(uptime -p 2>/dev/null)"
kv reboot_required "$([ -f /var/run/reboot-required ] && echo yes || echo no)"
kv disk_root "$(df -h / 2>/dev/null | awk 'NR==2{print $5 " used, " $4 " free"}')"
kv memory "$(free -m 2>/dev/null | awk '/^Mem:/{print $3 "MiB/" $2 "MiB"}')"
if command -v apt >/dev/null 2>&1; then
  kv os_updates "$(apt list --upgradable 2>/dev/null | awk 'NR>1{c++} END{print c+0}')"
  kv docker_package_updates "$(apt list --upgradable 2>/dev/null | awk -F/ '/^(docker|docker-ce|docker.io|containerd|containerd.io|docker-compose-plugin)\\//{c++} END{print c+0}')"
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
    # OpenClaw is installed under the H4 Node 24 runtime. Suppress nvm output so
    # the maintenance report remains a strict key/value stream.
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
"""
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


OPENCLAW_AUTH_STATUSES = frozenset(("ok", "expiring", "expired", "missing", "static"))


def parse_openclaw_models_status(payload: object) -> dict[str, str]:
    """Return only the non-secret OpenAI auth status and expiry from CLI JSON."""

    providers_of_interest = ("openai", "openai-codex")
    statuses = frozenset(("ok", "expiring", "expired", "missing", "static"))
    priority = {"expired": 5, "missing": 4, "expiring": 3, "ok": 2, "static": 1, "unknown": 0}

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
                return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            numeric = float(value)
            if numeric <= 0:
                return ""
            if numeric < 100_000_000_000:
                numeric *= 1000
            return datetime.fromtimestamp(numeric / 1000, timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            )
        except (OverflowError, OSError, TypeError, ValueError):
            return ""

    def first_entries(entries: list[dict[str, object]], preferred: list[str]) -> list[dict[str, object]]:
        for candidate in preferred:
            selected = [item for item in entries if provider_id(item.get("provider")) == candidate]
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
    preferred = list(dict.fromkeys(item for item in preferred if item in providers_of_interest))

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


def _openclaw_auth_status(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in OPENCLAW_AUTH_STATUSES else "unknown"


def parse_openclaw_expiry(value: object) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        if numeric < 100_000_000_000:
            numeric *= 1000
        try:
            return datetime.fromtimestamp(numeric / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.lower() == "unknown":
        return None
    try:
        return parse_openclaw_expiry(float(text))
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_openclaw_expiry(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def maintenance_targets(env: Mapping[str, str]) -> tuple[MaintenanceTarget, ...]:
    raw = env.get("SYSTEM_MAINTENANCE_TARGETS", "").strip() or DEFAULT_TARGETS
    targets: list[MaintenanceTarget] = []
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        name, separator, spec = entry.partition("=")
        if not separator:
            continue
        mode, _, remainder = spec.partition(":")
        mode = mode.strip().lower()
        if mode == "local":
            targets.append(MaintenanceTarget(name.strip(), "local", "", remainder.strip()))
        elif mode == "ssh":
            address, _, repo_path = remainder.partition(":")
            if address.strip():
                targets.append(MaintenanceTarget(name.strip(), "ssh", address.strip(), repo_path.strip()))
    return tuple(target for target in targets if target.name)


def maintenance_timeout_seconds(env: Mapping[str, str]) -> float:
    raw = env.get("SYSTEM_MAINTENANCE_TIMEOUT_SECONDS", str(DEFAULT_MAINTENANCE_TIMEOUT_SECONDS)).strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MAINTENANCE_TIMEOUT_SECONDS
    return min(max(value, 3.0), 60.0)


def maintenance_commands_allowed(env: Mapping[str, str]) -> bool:
    return env.get("SYSTEM_MAINTENANCE_ALLOW_COMMANDS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def render_maintenance_reports(reports: list[MaintenanceReport]) -> str:
    sections = ["## System maintenance"]
    collected = next((report.collected_at for report in reports if report.collected_at), "")
    if collected:
        sections.append(f"-# Collected {escape_text(collected)}")
    for report in reports:
        sections.append(render_maintenance_report(report))
    sections.append("-# Docker image updates are not checked automatically because that requires pulling images.")
    content = "\n\n".join(sections)
    if len(content) <= 2_000:
        return content
    trimmed = "\n\n".join(sections[:3] + ["-# Report trimmed for Discord. Run from shell for full output."])
    return trimmed[:2_000]


def render_maintenance_report(report: MaintenanceReport) -> str:
    title = escape_text(report.target.name)
    if not report.ok:
        return f"### {title}\n- check failed: {escape_text(report.error or 'unknown')}"
    facts = report.facts
    lines = [
        f"### {title}",
        f"- host: {escape_text(facts.get('hostname', 'unknown'))}",
        f"- updates: OS {escape_text(facts.get('os_updates', 'unknown'))}, Docker packages {escape_text(facts.get('docker_package_updates', 'unknown'))}",
        f"- reboot required: {escape_text(facts.get('reboot_required', 'unknown'))}",
        f"- disk: {escape_text(facts.get('disk_root', 'unknown'))}",
        f"- memory: {escape_text(facts.get('memory', 'unknown'))}",
        f"- Docker: {escape_text(facts.get('docker_engine', 'unavailable'))}; compose {escape_text(facts.get('docker_compose', 'unavailable'))}",
        f"- containers: running {escape_text(facts.get('docker_running', 'unknown'))}, unhealthy {escape_text(facts.get('docker_unhealthy', 'unknown'))}, exited {escape_text(facts.get('docker_exited', 'unknown'))}",
        f"- repo: {escape_text(facts.get('repo', 'not-configured'))}; dirty {escape_text(facts.get('repo_dirty', 'unknown'))}",
    ]
    if facts.get("openclaw_configured") == "yes":
        renewal = openclaw_renewal_from_report(report)
        auth_status = renewal.auth_status if renewal else str(facts.get("openclaw_auth_status") or "unknown")
        expires = renewal.expires_at if renewal and renewal.expires_at else str(
            facts.get("openclaw_auth_expires_at") or "unknown"
        )
        remind = renewal.reminder_on.isoformat() if renewal else "unknown"
        basis = " (estimated from config update)" if renewal and renewal.estimated else ""
        lines.append(
            "- OpenClaw: "
            f"model {escape_text(facts.get('openclaw_primary_model', 'unknown'))}, "
            f"gateway {escape_text(facts.get('openclaw_gateway', 'unknown'))}, "
            f"reauth {escape_text(facts.get('openclaw_reauth_agent', 'unknown'))}, "
            f"ChatGPT auth {escape_text(auth_status)}, expires {escape_text(expires)}, "
            f"remind {escape_text(remind)}{basis}"
        )
        lines.append(f"- OpenClaw config updated: {escape_text(facts.get('openclaw_last_touched', 'unknown'))}")
    return "\n".join(lines)


def maintenance_issues(
    reports: list[MaintenanceReport],
    *,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_MAINTENANCE_REPORT_MAX_AGE,
) -> tuple[str, ...]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    issues = []
    for report in reports:
        checked_at = _maintenance_report_time(report)
        if checked_at is None or current.astimezone(timezone.utc) - checked_at > max_age:
            continue
        target = report.target.name
        if not report.ok:
            issues.append(f"{target}: check failed")
            continue
        facts = report.facts
        if facts.get("reboot_required", "").strip().lower() == "yes":
            issues.append(f"{target}: reboot required")
        for key, label in (
            ("os_updates", "OS updates"),
            ("docker_package_updates", "Docker package updates"),
            ("docker_unhealthy", "unhealthy containers"),
        ):
            count = _nonnegative_int(facts.get(key, ""))
            if count > 0:
                issues.append(f"{target}: {count} {label}")
    return tuple(issues)


def render_system_maintenance_reminder(issues: tuple[str, ...]) -> str:
    return "\n".join(("## System maintenance required", *(f"- {escape_text(issue)}" for issue in issues)))


def _maintenance_report_time(report: MaintenanceReport) -> datetime | None:
    value = str(report.collected_at or report.facts.get("checked_at") or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def due_openclaw_renewal_reminders(
    reports: list[MaintenanceReport],
    *,
    today: date | None = None,
) -> list[OpenClawRenewalReminder]:
    current = today or datetime.now(timezone(timedelta(hours=9), "KST")).date()
    reminders: list[OpenClawRenewalReminder] = []
    for report in reports:
        reminder = openclaw_renewal_from_report(report)
        if reminder is not None and current >= reminder.reminder_on:
            reminders.append(reminder)
    return reminders


def openclaw_renewal_from_report(report: MaintenanceReport) -> OpenClawRenewalReminder | None:
    facts = report.facts
    if not report.ok or facts.get("openclaw_configured") != "yes":
        return None
    model = str(facts.get("openclaw_primary_model") or "unknown")
    if "openclaw_auth_status" in facts:
        auth_status = _openclaw_auth_status(facts.get("openclaw_auth_status"))
        expires_at = parse_openclaw_expiry(facts.get("openclaw_auth_expires_at"))
        if auth_status in {"unknown", "static"}:
            return None
        if auth_status == "ok" and expires_at is None:
            return None
        observed_on = _openclaw_report_date(report)
        expires_on = expires_at.astimezone(timezone(timedelta(hours=9), "KST")).date() if expires_at else None
        if auth_status in {"missing", "expired"}:
            reminder_on = observed_on
        else:
            reminder_on = expires_on - timedelta(days=1) if expires_on else observed_on
        expires_text = _format_openclaw_expiry(expires_at) if expires_at else ""
        key_suffix = expires_text or f"{auth_status}:{observed_on.isoformat()}"
        return OpenClawRenewalReminder(
            key=f"openclaw-chatgpt:{report.target.name}:{key_suffix}",
            target=report.target.name,
            model=model,
            auth_status=auth_status,
            expires_at=expires_text,
            reminder_on=reminder_on,
            expires_on=expires_on,
        )

    # Compatibility for already-stored reports created before the CLI auth
    # probe existed. New reports always use OpenClaw's actual expiresAt value.
    last_touched = str(facts.get("openclaw_last_touched") or "").strip()
    last_touched_date = parse_openclaw_timestamp_date(last_touched)
    if last_touched_date is None:
        return None
    expires_on = last_touched_date + timedelta(days=10)
    reminder_on = last_touched_date + timedelta(days=9)
    key = f"openclaw-chatgpt:{report.target.name}:{last_touched_date.isoformat()}:{reminder_on.isoformat()}"
    return OpenClawRenewalReminder(
        key=key,
        target=report.target.name,
        model=model,
        auth_status="estimated",
        expires_at=expires_on.isoformat(),
        reminder_on=reminder_on,
        expires_on=expires_on,
        estimated=True,
    )


def _openclaw_report_date(report: MaintenanceReport) -> date:
    checked_at = _maintenance_report_time(report)
    if checked_at is None:
        return datetime.now(timezone(timedelta(hours=9), "KST")).date()
    return checked_at.astimezone(timezone(timedelta(hours=9), "KST")).date()


def parse_openclaw_timestamp_date(value: str) -> date | None:
    text = value.strip()
    if not text or text == "unknown":
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=9), "KST"))
    return parsed.date()


def render_openclaw_renewal_reminder(reminder: OpenClawRenewalReminder) -> str:
    expiry_line = (
        f"- expires at: `{reminder.expires_at}`"
        if reminder.expires_at
        else "- expires at: unavailable (authentication is missing or unusable)"
    )
    estimate_line = ["-# Expiry is estimated from a legacy report; regenerate the maintenance report."] if reminder.estimated else []
    return "\n".join(
        [
            "## KaosBrain-OpenAI ChatGPT renewal",
            f"- target: {escape_text(reminder.target)}",
            f"- model: {escape_text(reminder.model)}",
            f"- auth status: {escape_text(reminder.auth_status)}",
            f"- renew on: `{reminder.reminder_on.isoformat()}`",
            expiry_line,
            *estimate_line,
            "- Run `./deploy/kaosbrain/kaosbrain openclaw-reauth` on H4, then regenerate the maintenance report.",
        ]
    )


def stable_error(exc: BaseException) -> str:
    return str(exc)[:200] or exc.__class__.__name__
