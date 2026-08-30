# H3 backend secrets

`kaos-h3 setup` creates these files locally:

- `discord_bot_token`
- `governor_api_token`
- `ios_shortcuts_token`
- `memos_access_token`
- `naver_mail_password`
- `paperless_api_token`
- `fax_connector_token`
- `pushover_app_token`
- `pushover_user_key`

They are mounted read-only into Governor and ignored by Git. Store one secret
per file with no quotes. Empty optional files are allowed only while their
corresponding feature is disabled.

Durable Governor proposals use the separately managed environment file
`/srv/kaos/secrets/governor-postgres.env`, shared with the existing
`governor-postgres` and `governor-api` services. It must contain non-empty
`POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` values and must never be
committed. `kaos-h3 preflight` requires it whenever
`GOVERNOR_OPERATION_STORE=postgres`.

`ios_shortcuts_token` authenticates only the read-only `/shortcuts/...`
routes. It is intentionally separate from the powerful Governor API token and
is safe to store in a personal iOS Shortcut.

For Apple Watch text alerts, `pushover_app_token` is the API token for the
KaosGDD Notifications application and `pushover_user_key` is the recipient key
shown on the Pushover dashboard. Both are required only when
`PUSHOVER_ENABLED=true`.
