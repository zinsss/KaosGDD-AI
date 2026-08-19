from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import shlex
import subprocess
from typing import Callable, Mapping

from .markdown import escape_text


DEFAULT_MAINTENANCE_TIMEOUT_SECONDS = 12.0
DEFAULT_TARGETS = "kaosgdd=local:/srv/projects/KaosGDD-AI,kaosbrain=ssh:zin@kaosbrain:/srv/projects/KaosGDD-AI,kaosclinic=ssh:zin@kaosclinic:"


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


Runner = Callable[[MaintenanceTarget, str, float], subprocess.CompletedProcess[str]]


async def collect_maintenance_reports(
    env: Mapping[str, str] | None = None,
    *,
    runner: Runner | None = None,
) -> list[MaintenanceReport]:
    source = os.environ if env is None else env
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


def render_maintenance_reports(reports: list[MaintenanceReport]) -> str:
    sections = ["## System maintenance"]
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
    return "\n".join(lines)


def stable_error(exc: BaseException) -> str:
    return str(exc)[:200] or exc.__class__.__name__
