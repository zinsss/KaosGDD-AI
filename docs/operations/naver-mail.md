# Naver mail migration to KaosGovernor

KaosMail is deterministic Governor infrastructure. It does not use KaosBrain,
OpenClaw, an LLM, or conversational state.

## Preserved behavior

- Naver IMAP over TLS remains authoritative.
- `INBOX`, `세무사`, `영덕군보건소`, and every descendant folder under those
  configured roots are discovered using IMAP modified UTF-7 names.
- Mailboxes are selected read-only and messages use `BODY.PEEK[]`; polling does
  not mark mail read.
- State is keyed by mailbox UIDVALIDITY and last delivered UID.
- A new mailbox or changed UIDVALIDITY establishes a current baseline by default.
- Summary delivery and each attachment are checkpointed separately so a failed
  attachment retry does not duplicate the summary.
- The message parser preserves received date in KST, cleans sender quoting,
  prefers plain text, falls back to sanitized HTML text, and limits previews.

## Discord delivery

New target-folder mail is sent to the explicitly allowlisted
`MAIL_ARCHIVE_DISCORD_CHANNEL_ID` as a
Markdown summary followed by eligible attachments. Dynamic mail content is
escaped and Discord mentions are disabled. Naver remains the only mail source of
truth; Governor state contains UID checkpoints and delivery IDs, not mail bodies.
The compact summary renders Folder, From, and Date inline, promotes the subject
to a level-three heading, lists attachment names, and preserves the first 15
normalized preview lines as ordinary paragraphs.
Discord normalizes uploaded filenames to ASCII, so every attachment message
renders the original decoded filename as escaped text and uses a stable
ASCII-only multipart filename. Korean filenames therefore remain visible in all
Discord clients without changing the source attachment.

## Daily unread organizer

The organizer is a separate scheduled workflow over the same Naver account. It
discovers unread messages in `INBOX` and every incoming or user-created folder,
while excluding Sent, Drafts, Trash, Junk, and the configured trash folder.
Header scans and previews use `BODY.PEEK`; opening or importing a message does
not mark it read.

The organizer is sent to `MAIL_ORGANIZER_DISCORD_CHANNEL_ID`. It publishes one
compact subject message per unread mail with direct `Import`, `Mark Read`, and
`Delete` buttons. The header retains bulk `Menu` and `Close` actions. Actions
preserve the legacy behavior:

- `Mark Read` sets `\\Seen` in the source Naver folder.
- `Import` posts the full summary and eligible attachments to
  `MAIL_ARCHIVE_DISCORD_CHANNEL_ID` without changing Naver read state. Summary
  and attachment progress are checkpointed.
- `Delete` requires a fresh confirmation and moves the message to Naver Trash.
- bulk actions operate only on the saved digest snapshot.
- an empty digest closes itself, and stale digests expire after 14 days.
- no Discord message is sent when there is no unread mail.

All controls re-check the configured guild, channel, and user allowlists. Naver
remains authoritative; organizer state stores only UIDVALIDITY/UID references,
delivery progress, schedule slots, and the header/item Discord message IDs
needed to restore buttons after restart.

Use `/mail-organizer-now` for a manual run and `/mail-organizer-schedule` to
persist a once- or twice-daily KST schedule. Times use five-minute steps.

## Cutover procedure

1. Copy the current archive checkpoint into the Governor state directory.
2. Run one read-only scan with delivery disabled and verify no historical replay.
3. Enable Governor Discord delivery while leaving the legacy poller running long
   enough to compare folder counts and errors.
4. After live mail is observed in Discord, disable only the legacy mail workers.
5. Do not remove unrelated Telegram, fax, document, or Brain services as part of
   this cutover.

## Configuration

Production secrets use host files mounted read-only, never Git:

```text
MAIL_NAVER_ENABLED=true
MAIL_NAVER_HOST=imap.naver.com
MAIL_NAVER_PORT=993
MAIL_NAVER_USERNAME=
MAIL_NAVER_PASSWORD_FILE=/run/secrets/naver_mail_password
MAIL_NAVER_FOLDERS=INBOX,세무사,영덕군보건소
MAIL_NAVER_STATE_PATH=/data/mail/naver-discord.json
MAIL_NAVER_POLL_SECONDS=60
MAIL_NAVER_TIMEOUT_SECONDS=20
MAIL_NAVER_MAX_ATTACHMENT_MB=20
MAIL_NAVER_PREVIEW_CHARS=2200
MAIL_NAVER_MARK_EXISTING_ON_FIRST_RUN=true
MAIL_ARCHIVE_DISCORD_CHANNEL_ID=
MAIL_ORGANIZER_DISCORD_CHANNEL_ID=
MAIL_ORGANIZER_ENABLED=true
MAIL_ORGANIZER_STATE_PATH=/data/mail/discord-organizer.json
MAIL_ORGANIZER_MAX_ITEMS=30
MAIL_ORGANIZER_SCHEDULER_POLL_SECONDS=60
MAIL_ORGANIZER_TRASH_FOLDER=Deleted Messages
MAIL_ORGANIZER_RUNS_PER_DAY=1
MAIL_ORGANIZER_FIRST_TIME=09:00
MAIL_ORGANIZER_SECOND_TIME=17:00
MAIL_ORGANIZER_DIGEST_TTL_DAYS=14
```
