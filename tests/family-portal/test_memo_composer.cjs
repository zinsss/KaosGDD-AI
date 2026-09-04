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

test("main and family memos routes render native archive board controls", () => {
  assert.match(appSource, /data-archive-kind="memos"/);
  assert.match(appSource, /data-memo-search/);
  assert.match(appSource, /data-memos-refresh/);
  assert.match(appSource, /href="#\/add-memo">NEW<\/a>/);
  assert.match(appSource, /data-memo-open/);
  assert.match(appSource, /if \(route === "memos"\) loadMemos\(\);/);
  assert.doesNotMatch(appSource, /portalProfile\(\) === "family"[\s\S]*memosFrame/);
});

test("family portal proxies native memos api to governor", () => {
  const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

  assert.match(nginxSource, /location \^~ \/api\/memos\/ \{/);
  assert.match(nginxSource, /location \^~ \/api\/memos\/ \{[\s\S]*proxy_pass http:\/\/governor-api:8096;/);
});
