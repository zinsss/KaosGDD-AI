from __future__ import annotations

import asyncio
import os
import pty
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web


OAUTH_URL_RE = re.compile(r"https://auth\.openai\.com/oauth/authorize\?\S+")
CALLBACK_RE = re.compile(r"http://localhost:1455/auth/callback\?\S+")
CODE_RE = re.compile(r"ac_[A-Za-z0-9_.-]+")


def _secret(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise SystemExit(f"set either {name} or {name}_FILE, not both")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return value


def redact_auth_text(value: str) -> str:
    value = CALLBACK_RE.sub("http://localhost:1455/auth/callback?[redacted]", value)
    return CODE_RE.sub("ac_[redacted]", value)


@dataclass
class ReauthConfig:
    token: str
    bind_host: str = "127.0.0.1"
    port: int = 18997
    openclaw_state_dir: str = "/srv/kaosgdd/kaosai/openclaw"
    openclaw_config_path: str = "/srv/kaosgdd/kaosai/openclaw/openclaw.json"
    gateway_service: str = "openclaw-gateway.service"
    nvm_sh: str = "/home/zin/.nvm/nvm.sh"
    node_version: str = "24"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ReauthConfig":
        source = dict(os.environ if env is None else env)
        token = _secret(source, "KAOSAI_REAUTH_TOKEN")
        if not token:
            raise SystemExit("KAOSAI_REAUTH_TOKEN or KAOSAI_REAUTH_TOKEN_FILE is required")
        return cls(
            token=token,
            bind_host=source.get("KAOSAI_REAUTH_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(source.get("KAOSAI_REAUTH_PORT", "18997")),
            openclaw_state_dir=source.get("KAOSAI_OPENCLAW_STATE_DIR", "/srv/kaosgdd/kaosai/openclaw").strip()
            or "/srv/kaosgdd/kaosai/openclaw",
            openclaw_config_path=source.get(
                "KAOSAI_OPENCLAW_CONFIG_PATH",
                "/srv/kaosgdd/kaosai/openclaw/openclaw.json",
            ).strip()
            or "/srv/kaosgdd/kaosai/openclaw/openclaw.json",
            gateway_service=source.get("KAOSAI_OPENCLAW_GATEWAY_SERVICE", "openclaw-gateway.service").strip()
            or "openclaw-gateway.service",
            nvm_sh=source.get("KAOSAI_OPENCLAW_NVM_SH", "/home/zin/.nvm/nvm.sh").strip() or "/home/zin/.nvm/nvm.sh",
            node_version=source.get("KAOSAI_OPENCLAW_NODE_VERSION", "24").strip() or "24",
        )


@dataclass
class ReauthState:
    status: str = "idle"
    oauth_url: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    message: str = ""
    process: subprocess.Popen[bytes] | None = None
    master_fd: int | None = None
    url_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)


class OpenClawReauthAgent:
    def __init__(self, config: ReauthConfig) -> None:
        self.config = config
        self.state = ReauthState()
        self._lock = threading.Lock()

    def payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self.state.status,
                "oauthUrl": self.state.oauth_url,
                "startedAt": self.state.started_at,
                "completedAt": self.state.completed_at,
                "message": self.state.message,
            }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.state.status in {"starting", "waiting_for_callback", "submitting"}:
                return {
                    "status": self.state.status,
                    "oauthUrl": self.state.oauth_url,
                    "startedAt": self.state.started_at,
                    "completedAt": self.state.completed_at,
                    "message": self.state.message,
                }
            self.state = ReauthState(status="starting", started_at=time.time(), message="Starting OpenClaw OAuth.")
            master_fd, slave_fd = pty.openpty()
            self.state.master_fd = master_fd
            command = self._shell_command()
            env = {
                **os.environ,
                "OPENCLAW_STATE_DIR": self.config.openclaw_state_dir,
                "OPENCLAW_CONFIG_PATH": self.config.openclaw_config_path,
            }
            self.state.process = subprocess.Popen(
                ["bash", "-lc", command],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
            )
            os.close(slave_fd)
            threading.Thread(target=self._reader, daemon=True).start()
        return self.payload()

    def submit_callback(self, callback_or_code: str) -> dict[str, Any]:
        value = callback_or_code.strip()
        if not value:
            raise web.HTTPBadRequest(text="callback_required")
        with self._lock:
            if self.state.status not in {"waiting_for_callback", "starting"} or self.state.master_fd is None:
                raise web.HTTPConflict(text="reauth_not_waiting")
            self.state.status = "submitting"
            self.state.message = "Submitting OAuth callback."
            os.write(self.state.master_fd, (value + "\r").encode("utf-8"))
        self.state.done_event.wait(timeout=45)
        return self.payload()

    def _shell_command(self) -> str:
        nvm = shlex.quote(self.config.nvm_sh)
        node_version = shlex.quote(self.config.node_version)
        return (
            f"source {nvm} && "
            f"nvm use {node_version} >/dev/null && "
            "openclaw models auth login --provider openai --force"
        )

    def _reader(self) -> None:
        assert self.state.master_fd is not None
        output = ""
        try:
            while True:
                try:
                    data = os.read(self.state.master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                output += text
                url_match = OAUTH_URL_RE.search(output)
                if url_match:
                    with self._lock:
                        if not self.state.oauth_url:
                            self.state.oauth_url = url_match.group(0)
                            self.state.status = "waiting_for_callback"
                            self.state.message = "Waiting for OAuth callback."
                            self.state.url_event.set()
                with self._lock:
                    self.state.message = redact_auth_text(output[-600:])
                proc = self.state.process
                if proc is not None and proc.poll() is not None:
                    break
        finally:
            proc = self.state.process
            code = proc.wait(timeout=5) if proc is not None else 1
            if self.state.master_fd is not None:
                try:
                    os.close(self.state.master_fd)
                except OSError:
                    pass
            with self._lock:
                self.state.master_fd = None
                self.state.completed_at = time.time()
                if code == 0:
                    restart = subprocess.run(
                        ["systemctl", "--user", "restart", self.config.gateway_service],
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=30,
                    )
                    if restart.returncode == 0:
                        self.state.status = "succeeded"
                        self.state.message = f"OpenClaw OAuth renewed. Restarted {self.config.gateway_service}."
                    else:
                        self.state.status = "failed"
                        self.state.message = redact_auth_text(restart.stdout[-600:])
                else:
                    self.state.status = "failed"
                    self.state.message = redact_auth_text(output[-600:] or f"OpenClaw exited with {code}.")
                self.state.done_event.set()


def _authorized(config: ReauthConfig, request: web.Request) -> bool:
    header = request.headers.get("Authorization", "")
    return header == f"Bearer {config.token}"


def create_app(config: ReauthConfig) -> web.Application:
    agent = OpenClawReauthAgent(config)
    app = web.Application()

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "reauth": agent.payload()})

    async def start(request: web.Request) -> web.Response:
        if not _authorized(config, request):
            raise web.HTTPUnauthorized(text="unauthorized")
        payload = agent.start()
        await asyncio.to_thread(agent.state.url_event.wait, 20)
        return web.json_response(agent.payload() if payload["status"] == "starting" else payload)

    async def callback(request: web.Request) -> web.Response:
        if not _authorized(config, request):
            raise web.HTTPUnauthorized(text="unauthorized")
        body = await request.json()
        value = str(body.get("callbackUrl") or body.get("code") or "")
        return web.json_response(await asyncio.to_thread(agent.submit_callback, value))

    async def status(request: web.Request) -> web.Response:
        if not _authorized(config, request):
            raise web.HTTPUnauthorized(text="unauthorized")
        return web.json_response(agent.payload())

    app.router.add_get("/health", health)
    app.router.add_post("/reauth/openai/start", start)
    app.router.add_post("/reauth/openai/callback", callback)
    app.router.add_get("/reauth/openai/status", status)
    return app


def main() -> None:
    config = ReauthConfig.from_env()
    web.run_app(create_app(config), host=config.bind_host, port=config.port)
