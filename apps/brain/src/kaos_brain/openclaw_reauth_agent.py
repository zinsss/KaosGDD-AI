from __future__ import annotations

import asyncio
import hmac
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


ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
DEVICE_VERIFICATION_URL_RE = re.compile(
    r"https://auth\.openai\.com/codex/device(?:\?[A-Za-z0-9._~!$&'()*+,;=:@/?%\-]+)?"
)
DEVICE_CODE_RE = re.compile(r"\bCode:\s*([A-Z0-9][A-Z0-9-]{2,63})\b", re.IGNORECASE)
CALLBACK_RE = re.compile(r"http://localhost:1455/auth/callback\?\S+")
CODE_RE = re.compile(r"ac_[A-Za-z0-9_.-]+")
TOKEN_FIELD_RE = re.compile(
    r"(?i)([\"']?(?:access_token|refresh_token|id_token|token)[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9._~+/=-]{8,})"
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _secret(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise SystemExit(f"set either {name} or {name}_FILE, not both")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return value


def strip_terminal_control_sequences(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def parse_device_pairing(value: str) -> tuple[str, str]:
    clean = strip_terminal_control_sequences(value)
    url_match = DEVICE_VERIFICATION_URL_RE.search(clean)
    code_match = DEVICE_CODE_RE.search(clean)
    return (
        url_match.group(0) if url_match else "",
        code_match.group(1) if code_match else "",
    )


def redact_auth_text(value: str) -> str:
    value = strip_terminal_control_sequences(value)
    value = CALLBACK_RE.sub("http://localhost:1455/auth/callback?[redacted]", value)
    value = CODE_RE.sub("ac_[redacted]", value)
    value = DEVICE_CODE_RE.sub("Code: [redacted]", value)
    value = TOKEN_FIELD_RE.sub(r"\1[redacted]", value)
    return BEARER_RE.sub("Bearer [redacted]", value)


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
    verification_url: str = ""
    user_code: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    message: str = ""
    process: subprocess.Popen[bytes] | None = None
    master_fd: int | None = None
    verification_event: threading.Event = field(default_factory=threading.Event)


class OpenClawReauthAgent:
    def __init__(self, config: ReauthConfig) -> None:
        self.config = config
        self.state = ReauthState()
        self._lock = threading.Lock()

    def payload(self, *, include_user_code: bool = True) -> dict[str, Any]:
        with self._lock:
            return self._payload_unlocked(include_user_code=include_user_code)

    def _payload_unlocked(self, *, include_user_code: bool = True) -> dict[str, Any]:
        payload = {
            "status": self.state.status,
            # Keep oauthUrl as a transition alias for existing clients.
            "oauthUrl": self.state.verification_url,
            "verificationUrl": self.state.verification_url,
            "startedAt": self.state.started_at,
            "completedAt": self.state.completed_at,
            "message": self.state.message,
        }
        if include_user_code:
            payload["userCode"] = self.state.user_code
        return payload

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.state.status in {"starting", "waiting_for_device"}:
                return self._payload_unlocked()
            self.state = ReauthState(
                status="starting",
                started_at=time.time(),
                message="Starting OpenClaw device login.",
            )
            try:
                master_fd, slave_fd = pty.openpty()
            except OSError:
                self._fail_start_unlocked("Unable to create the OpenClaw login terminal.")
                return self._payload_unlocked()
            self.state.master_fd = master_fd
            command = self._shell_command()
            env = {
                **os.environ,
                "OPENCLAW_STATE_DIR": self.config.openclaw_state_dir,
                "OPENCLAW_CONFIG_PATH": self.config.openclaw_config_path,
            }
            try:
                self.state.process = subprocess.Popen(
                    ["bash", "-lc", command],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    env=env,
                    close_fds=True,
                )
            except OSError:
                _close_fd(slave_fd)
                _close_fd(master_fd)
                self.state.master_fd = None
                self._fail_start_unlocked("Unable to start the OpenClaw login process.")
                return self._payload_unlocked()
            _close_fd(slave_fd)
            threading.Thread(target=self._reader, daemon=True).start()
        return self.payload()

    def _fail_start_unlocked(self, message: str) -> None:
        self.state.status = "failed"
        self.state.message = message
        self.state.process = None
        self.state.master_fd = None
        self.state.user_code = ""
        self.state.completed_at = time.time()
        self.state.verification_event.set()

    def submit_callback(self, callback_or_code: str) -> dict[str, Any]:
        value = callback_or_code.strip()
        if not value:
            raise web.HTTPBadRequest(text="callback_required")
        with self._lock:
            if self.state.status in {"starting", "waiting_for_device"}:
                raise web.HTTPConflict(text="reauth_uses_device_code")
        raise web.HTTPConflict(text="reauth_not_waiting")

    def _shell_command(self) -> str:
        nvm = shlex.quote(self.config.nvm_sh)
        node_version = shlex.quote(self.config.node_version)
        return (
            f"source {nvm} && "
            f"nvm use {node_version} >/dev/null && "
            "openclaw models auth login --provider openai --method device-code --force"
        )

    def _reader(self) -> None:
        with self._lock:
            master_fd = self.state.master_fd
            proc = self.state.process
        if master_fd is None or proc is None:
            return
        output = ""
        try:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                output = (output + text)[-12_000:]
                verification_url, user_code = parse_device_pairing(output)
                with self._lock:
                    if verification_url:
                        self.state.verification_url = verification_url
                    if user_code:
                        self.state.user_code = user_code
                    if self.state.verification_url and self.state.user_code:
                        self.state.status = "waiting_for_device"
                        self.state.message = "Waiting for device authorization."
                        self.state.verification_event.set()
                    else:
                        self.state.message = "Waiting for OpenClaw device-pairing details."
                if proc.poll() is not None:
                    break
        finally:
            code, wait_failed = _wait_for_process(proc)
            _close_fd(master_fd)
            if wait_failed:
                status = "failed"
                message = "OpenClaw login process did not exit cleanly."
            elif code == 0:
                try:
                    restart = subprocess.run(
                        ["systemctl", "--user", "restart", self.config.gateway_service],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=30,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    status = "failed"
                    message = "OpenClaw login renewed, but the gateway restart failed."
                else:
                    if restart.returncode == 0:
                        status = "succeeded"
                        message = f"OpenClaw OAuth renewed. Restarted {self.config.gateway_service}."
                    else:
                        status = "failed"
                        message = "OpenClaw login renewed, but the gateway restart failed."
            else:
                status = "failed"
                message = f"OpenClaw device login failed (exit {code if code is not None else 'unknown'})."
            with self._lock:
                if self.state.master_fd == master_fd:
                    self.state.master_fd = None
                if self.state.process is proc:
                    self.state.process = None
                self.state.user_code = ""
                self.state.completed_at = time.time()
                self.state.status = status
                self.state.message = message
                self.state.verification_event.set()


def _close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _wait_for_process(proc: subprocess.Popen[bytes]) -> tuple[int | None, bool]:
    try:
        return proc.wait(timeout=5), False
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
        return None, True


def _authorized(config: ReauthConfig, request: web.Request) -> bool:
    header = request.headers.get("Authorization", "")
    return hmac.compare_digest(header, f"Bearer {config.token}")


def create_app(config: ReauthConfig) -> web.Application:
    agent = OpenClawReauthAgent(config)
    app = web.Application()

    async def health(request: web.Request) -> web.Response:
        # Health is intentionally unauthenticated for the local service manager.
        # Keep it free of pairing state; authenticated callers use /status.
        return web.json_response({"status": "ok"})

    async def start(request: web.Request) -> web.Response:
        if not _authorized(config, request):
            raise web.HTTPUnauthorized(text="unauthorized")
        payload = agent.start()
        await asyncio.to_thread(agent.state.verification_event.wait, 20)
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
