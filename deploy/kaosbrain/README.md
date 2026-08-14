# KaosBrain deployment

KaosBrain runs on the H4 Ultra as the personal language interface for KaosGDD.
It talks directly to Discord and local Ollama. Authoritative state changes
remain behind KaosGovernor APIs.

OpenClaw is intentionally not part of this deployment.

## Host prerequisites

- Debian 13 or Ubuntu 24.04 LTS
- Docker Engine
- Ollama reachable on `127.0.0.1:11434`
- Tailscale joined to the Kaos tailnet
- a separate Discord bot token from KaosGovernor

## Install

From a fresh clone or copied checkout:

```bash
cd /srv/projects/KaosGDD-AI
docker build --target runtime --tag kaos-brain:current --file apps/brain/Dockerfile .
sudo install -d -m 0750 -o "$USER" -g "$(id -gn)" /srv/kaos/brain /srv/kaos/secrets
cp deploy/kaosbrain/.env.example /srv/kaos/brain/kaosbrain.env
sed -i "s/^KAOS_HOST_UID=.*/KAOS_HOST_UID=$(id -u)/" /srv/kaos/brain/kaosbrain.env
sed -i "s/^KAOS_HOST_GID=.*/KAOS_HOST_GID=$(id -g)/" /srv/kaos/brain/kaosbrain.env
```

Create the secret file without printing it:

```bash
read -rsp "KaosBrain Discord bot token: " TOKEN; echo
printf '%s' "$TOKEN" > /srv/kaos/secrets/kaosbrain_discord_bot_token
unset TOKEN
chmod 0640 /srv/kaos/secrets/kaosbrain_discord_bot_token
```

Install the unit:

```bash
sudo cp deploy/kaosbrain/kaosbrain.service /etc/systemd/system/kaosbrain.service
sudo systemctl daemon-reload
sudo systemctl enable --now kaosbrain.service
```

## Verify

```bash
systemctl status kaosbrain.service --no-pager
docker ps --filter name=kaos-brain
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
```

Then smoke test in the configured Discord `#brain` channel:

```text
안녕
deep: 한국어로 짧게 대답해줘
```

## Rollback

```bash
sudo systemctl disable --now kaosbrain.service
docker rm -f kaos-brain
```
