const assert = require("node:assert/strict");
const test = require("node:test");

const { counts, filterItems, normalizeDetail, normalizeMessage, normalizeMode, normalizePage } = require("../../apps/family-portal/mail.js");

test("normalizes Naver mail headers for the portal", () => {
  const message = normalizeMessage({
    mailbox: "INBOX",
    uid: 49980,
    uidValidity: "80",
    unread: true,
    sender: "Naver <notice@example.com>",
    subject: "공지",
    preview: "본문 미리보기",
    receivedAt: "2026-09-01T07:00:00+09:00",
    attachmentCount: 2,
    attachments: [{ index: 1, filename: "notice.pdf", contentType: "application/pdf", sizeBytes: 8 }],
  });

  assert.equal(message.id, "INBOX:49980");
  assert.equal(message.subject, "공지");
  assert.equal(message.uidValidity, "80");
  assert.equal(message.unread, true);
  assert.equal(message.attachmentCount, 2);
  assert.equal(message.attachments[0].index, 1);
  assert.equal(message.attachments[0].filename, "notice.pdf");
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

test("normalizes full mail detail payloads", () => {
  const message = normalizeDetail({
    message: {
      mailbox: "세무사",
      uid: 7,
      subject: "세무사 본문",
      preview: "본문",
      attachments: [{ filename: "", contentType: "", sizeBytes: -1 }],
    },
  });

  assert.equal(message.id, "세무사:7");
  assert.equal(message.preview, "본문");
  assert.equal(message.attachments[0].filename, "attachment");
  assert.equal(message.attachments[0].contentType, "application/octet-stream");
  assert.equal(message.attachments[0].sizeBytes, 0);
});

test("filters scoped mail rows by board tab", () => {
  const page = normalizePage({
    messages: [
      { mailbox: "영덕군보건소", uid: 1, subject: "보건소", attachmentCount: 1 },
      { mailbox: "세무사", uid: 2, subject: "세무사", unread: true },
    ],
  });

  assert.equal(normalizeMode("bad"), "unread");
  assert.deepEqual(counts(page.items), { all: 2, yeongdeok: 1, tax: 1, attachments: 1, unread: 1 });
  assert.equal(filterItems(page.items, "yeongdeok")[0].subject, "보건소");
  assert.equal(filterItems(page.items, "tax")[0].subject, "세무사");
  assert.equal(filterItems(page.items, "unread")[0].mailbox, "세무사");
});
