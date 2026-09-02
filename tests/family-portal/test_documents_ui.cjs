const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");

test("documents inbox rows open a local detail panel with status-only actions", () => {
  assert.match(appSource, /data-document-inbox-open/);
  assert.match(appSource, /data-document-inbox-detail/);
  assert.match(appSource, /data-document-inbox-refresh-status/);
  assert.match(appSource, /data-document-inbox-paperless/);
});

test("document upload selects the new inbox record after returning to inbox", () => {
  assert.match(appSource, /state\.documents\.selectedInboxId = String\(payload\.item\?\.id \|\| ""\);/);
});

test("documents metadata review previews before confirmed apply", () => {
  assert.match(appSource, /data-document-metadata-review/);
  assert.match(appSource, /metadata\/proposal/);
  assert.match(appSource, /CONFIRM BEFORE APPLYING/);
  assert.match(appSource, /window\.confirm\(`Apply Paperless metadata/);
  assert.match(appSource, /metadata\/apply/);
  assert.match(appSource, /JSON\.stringify\(\{ title, tags, confirmed: true \}\)/);
});
