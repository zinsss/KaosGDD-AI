from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Callable, Mapping

from .markdown import escape_text


DEFAULT_MAINTENANCE_TIMEOUT_SECONDS = 12.0
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
    try:
        completed = runner(target, maintenance_probe_script(target.repo_path), timeout_seconds)
    except (OSError, subprocess.SubprocessError) as exc:
        return MaintenanceReport(target, False, {}, stable_error(exc))
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        return MaintenanceReport(target, False, {}, detail[:200])
    return MaintenanceReport(target, True, parse_probe_output(completed.stdout))


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
    return f"""set +e
kv() {{ printf '%s=%s\\n' "$1" "$2"; }}
kv hostname "$(hostname 2>/dev/null)"
kv checked_at "$(date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null)"
kv uptime "$(uptime -p 2>/dev/null)"
kv reboot_required "$([ -f /var/run/reboot-required ] && echo yes || echo no)"
kv disk_root "$(df -h / 2>/dev/null | awk 'NR==2{{print $5 " used, " $4 " free"}}')"
kv memory "$(free -m 2>/dev/null | awk '/^Mem:/{{print $3 "MiB/" $2 "MiB"}}')"
if command -v apt >/dev/null 2>&1; then
  kv os_updates "$(apt list --upgradable 2>/dev/null | awk 'NR>1{{c++}} END{{print c+0}}')"
  kv docker_package_updates "$(apt list --upgradable 2>/dev/null | awk -F/ '/^(docker|docker-ce|docker.io|containerd|containerd.io|docker-compose-plugin)\\//{{c++}} END{{print c+0}}')"
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
repo={quoted_repo}
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
  kv openclaw_chatgpt_expires unknown
else
  kv openclaw_configured no
fi
kv docker_image_updates "not checked; requires explicit pull"
"""


def parse_probe_output(output: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            facts[key] = value.strip()
    return facts


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
        lines.append(
            "- OpenClaw: "
            f"model {escape_text(facts.get('openclaw_primary_model', 'unknown'))}, "
            f"gateway {escape_text(facts.get('openclaw_gateway', 'unknown'))}, "
            f"reauth {escape_text(facts.get('openclaw_reauth_agent', 'unknown'))}, "
            f"ChatGPT expires {escape_text(facts.get('openclaw_chatgpt_expires', 'unknown'))}"
        )
        lines.append(f"- OpenClaw config updated: {escape_text(facts.get('openclaw_last_touched', 'unknown'))}")
    return "\n".join(lines)


def stable_error(exc: BaseException) -> str:
    return str(exc)[:200] or exc.__class__.__name__
