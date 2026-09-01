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
  assert.match(appSource, /Inbox actions are status\/detail only/);
});

test("document upload selects the new inbox record after returning to inbox", () => {
  assert.match(appSource, /state\.documents\.selectedInboxId = String\(payload\.item\?\.id \|\| ""\);/);
});
