const assert = require("node:assert/strict");
const test = require("node:test");

const { normalizeDocument, normalizeInbox, normalizePage } = require("../../apps/family-portal/documents.js");

test("normalizes Paperless browse pages for the portal", () => {
  const page = normalizePage({
    query: "",
    items: [{ id: 7, title: "Fax report", original_file_name: "ignored.pdf", filename: "fax.pdf" }],
    resultCount: 1,
    totalCount: 26,
    page: 2,
    pageSize: 10,
  });

  assert.equal(page.query, "");
  assert.equal(page.items[0].id, 7);
  assert.equal(page.items[0].filename, "fax.pdf");
  assert.equal(page.pageCount, 3);
});

test("uses matching result count for search pagination", () => {
  const page = normalizePage({ query: "fax", resultCount: 4, totalCount: 26, pageSize: 10 });
  assert.equal(page.pageCount, 1);
});

test("normalizes Paperless document OCR without creating another state store", () => {
  const document = normalizeDocument({
    id: 42,
    title: "Clinic form",
    content: "Recognized text",
    tagIds: [3, "4", "bad"],
  });

  assert.equal(document.content, "Recognized text");
  assert.deepEqual(document.tagIds, [3, 4]);
});

test("normalizes document intake inbox records", () => {
  const inbox = normalizeInbox({
    items: [
      {
        id: "doc-1",
        title: "Clinic PDF",
        submittedAt: "2026-09-01T00:00:00Z",
        sizeBytes: 123,
        taskId: "paperless-task",
        status: "ocr_pending",
      },
    ],
  });

  assert.equal(inbox.items[0].id, "doc-1");
  assert.equal(inbox.items[0].statusLabel, "OCR PENDING");
});
