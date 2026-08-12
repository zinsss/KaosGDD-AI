# H3 backend secrets

`kaos-h3 setup` creates these files locally:

- `discord_bot_token`
- `governor_api_token`
- `memos_access_token`
- `naver_mail_password`

They are mounted read-only into Governor and ignored by Git. Store one secret
per file with no quotes. Empty optional files are allowed only while their
corresponding feature is disabled.
