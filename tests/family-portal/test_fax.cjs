const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { counts, filterItems, normalizeArchive, normalizeItem, normalizeMode } = require("../../apps/family-portal/fax.js");
const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");

const incomingId = "0123456789abcdef0123456789abcdef";
const outgoingId = "sent-1";

test("normalizes safe incoming fax archive records", () => {
  const item = normalizeItem({
    faxId: incomingId,
    direction: "incoming",
    filename: "received.pdf",
    remote: "07079664986",
    pages: "2",
    status: "archived",
    documentAvailable: true,
  });

  assert.equal(item.key, `incoming:${incomingId}`);
  assert.equal(item.documentUrl, `/api/fax/items/${incomingId}/document`);
  assert.equal(item.remote, "07079664986");
});

test("rejects malformed identifiers and directions", () => {
  assert.equal(normalizeItem({ id: "../state.json", direction: "incoming" }), null);
  assert.equal(normalizeItem({ jobId: "../state.json", direction: "outgoing" }), null);
  assert.equal(normalizeItem({ id: incomingId, direction: "sideways" }), null);
});

test("derives board counts and filters from normalized records", () => {
  const archive = normalizeArchive({
    items: [
      { id: incomingId, direction: "incoming", status: "archived", documentAvailable: true },
      { jobId: outgoingId, direction: "outgoing", status: "sent" },
      { jobId: "failed-1", direction: "outgoing", status: "failed" },
    ],
  });

  assert.deepEqual(counts(archive.items), { all: 3, received: 1, sent: 1, failed: 1 });
  assert.equal(filterItems(archive.items, "received")[0].direction, "incoming");
  assert.equal(filterItems(archive.items, "failed")[0].status, "failed");
});

test("unknown board modes safely select all", () => {
  assert.equal(normalizeMode("not-a-mode"), "all");
});

test("fax archive board uses the common no date title header", () => {
  assert.match(appSource, /id="faxIndexTitle">RECORD BOARD[\s\S]*<span>NO\.<\/span><span>DATE<\/span><span>TITLE<\/span>/);
  assert.doesNotMatch(appSource, /<span>ID<\/span><span>DATE<\/span><span>REMOTE<\/span><span>TITLE<\/span>/);
});
