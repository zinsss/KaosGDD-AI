const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const memosViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/memos-view.js"), "utf8");
const stylesSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

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
  assert.match(memosViewSource, /data-archive-kind="memos"/);
  assert.match(memosViewSource, /data-memo-search/);
  assert.match(memosViewSource, /data-memos-refresh/);
  assert.match(memosViewSource, /href="#\/add-memo">NEW<\/a>/);
  assert.ok(memosViewSource.indexOf('href="#/add-memo">NEW</a>') < memosViewSource.indexOf('class="archiveSearchBox"'));
  assert.ok(memosViewSource.indexOf('class="archiveSearchBox"') < memosViewSource.indexOf('data-memos-refresh'));
  assert.match(stylesSource, /\[data-archive-kind="memos"\] \.archiveSearchBar \{\n  grid-template-columns: auto minmax\(0, 1fr\) 44px;/);
  assert.match(memosViewSource, /data-memo-open/);
  assert.match(appSource, /if \(route === "memos"\) loadMemos\(\);/);
  assert.doesNotMatch(appSource, /portalProfile\(\) === "family"[\s\S]*memosFrame/);
});

test("family memos receive the shared archive layout and light family theme", () => {
  assert.match(
    stylesSource,
    /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveTerminal/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]:is\(\[data-route="ai-tasks"\], \[data-route="memos"\]\) \.archiveTerminal/,
  );
  assert.match(stylesSource, /--archive-bg: #fffaff;/);
});

test("family portal proxies native memos api to governor", () => {
  const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

  assert.match(nginxSource, /location \^~ \/api\/memos\/ \{/);
  assert.match(nginxSource, /set \$governor_api http:\/\/governor-api:8096;/);
  assert.match(nginxSource, /location \^~ \/api\/memos\/ \{[\s\S]*proxy_pass \$governor_api;/);
});
