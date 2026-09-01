const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");

test("top add opens the native one-box memo composer", () => {
  assert.match(appSource, /if \(action === "memo"\) \{\s*window\.location\.hash = "#\/add-memo";/s);
  assert.match(appSource, /<form class="panel memoComposerPanel" data-create-memo>/);
  assert.match(appSource, /<textarea[\s\S]*name="content"[\s\S]*data-memo-content/);
  assert.doesNotMatch(appSource, /action: "memo", label: "Memo", note: "Later"/);
});

test("memo composer posts one private content payload through the Governor relay", () => {
  assert.match(appSource, /fetch\("\/api\/memos\/api\/v1\/memos"/);
  assert.match(appSource, /JSON\.stringify\(\{ content: normalized, visibility: "PRIVATE" \}\)/);
});
