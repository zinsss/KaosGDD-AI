const assert = require("node:assert/strict");
const test = require("node:test");

const { normalizeMessage, normalizePage } = require("../../apps/family-portal/mail.js");

test("normalizes Naver mail headers for the portal", () => {
  const message = normalizeMessage({
    mailbox: "INBOX",
    uid: 49980,
    sender: "Naver <notice@example.com>",
    subject: "공지",
    preview: "본문 미리보기",
    receivedAt: "2026-09-01T07:00:00+09:00",
    attachmentCount: 2,
  });

  assert.equal(message.id, "INBOX:49980");
  assert.equal(message.subject, "공지");
  assert.equal(message.attachmentCount, 2);
});

test("drops malformed mail rows and preserves mailbox metadata", () => {
  const page = normalizePage({
    folders: ["INBOX", "세무사"],
    mailboxCount: 2,
    limit: 10,
    messages: [
      { mailbox: "INBOX", uid: 1, subject: "" },
      { mailbox: "INBOX", uid: 0, subject: "bad" },
    ],
  });

  assert.equal(page.items.length, 1);
  assert.equal(page.items[0].subject, "(No subject)");
  assert.deepEqual(page.folders, ["INBOX", "세무사"]);
  assert.equal(page.mailboxCount, 2);
});
