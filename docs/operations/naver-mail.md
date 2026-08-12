# Naver mail migration to KaosGovernor

KaosMail is deterministic Governor infrastructure. It does not use KaosBrain,
OpenClaw, an LLM, or conversational state.

## Preserved behavior

- Naver IMAP over TLS remains authoritative.
- `각종공문`, `세무사`, and every descendant folder are discovered using IMAP
  modified UTF-7 names.
- Mailboxes are selected read-only and messages use `BODY.PEEK[]`; polling does
  not mark mail read.
- State is keyed by mailbox UIDVALIDITY and last delivered UID.
- A new mailbox or changed UIDVALIDITY establishes a current baseline by default.
- Summary delivery and each attachment are checkpointed separately so a failed
  attachment retry does not duplicate the summary.
- The message parser preserves received date in KST, cleans sender quoting,
  prefers plain text, falls back to sanitized HTML text, and limits previews.

## Discord delivery

New mail is sent to the explicitly allowlisted `MAIL_DISCORD_CHANNEL_ID` as a
Markdown summary followed by eligible attachments. Dynamic mail content is
escaped and Discord mentions are disabled. Naver remains the only mail source of
truth; Governor state contains UID checkpoints and delivery IDs, not mail bodies.

## Cutover procedure

1. Copy the current archive checkpoint into the Governor state directory.
2. Run one read-only scan with delivery disabled and verify no historical replay.
3. Enable Governor Discord delivery while leaving the legacy poller running long
   enough to compare folder counts and errors.
4. After live mail is observed in Discord, disable only the legacy mail workers.
5. Do not remove unrelated Telegram, fax, document, or Brain services as part of
   this cutover.

## Configuration

Production secrets stay in the host `.env`, never Git:

```text
MAIL_NAVER_ENABLED=true
MAIL_NAVER_HOST=imap.naver.com
MAIL_NAVER_PORT=993
MAIL_NAVER_USERNAME=
MAIL_NAVER_PASSWORD=
MAIL_NAVER_FOLDERS=각종공문,세무사
MAIL_NAVER_STATE_PATH=/data/mail/naver-discord.json
MAIL_NAVER_POLL_SECONDS=60
MAIL_NAVER_TIMEOUT_SECONDS=20
MAIL_NAVER_MAX_ATTACHMENT_MB=20
MAIL_NAVER_PREVIEW_CHARS=2200
MAIL_NAVER_MARK_EXISTING_ON_FIRST_RUN=true
MAIL_DISCORD_CHANNEL_ID=
```
