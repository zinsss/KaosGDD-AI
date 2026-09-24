const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "../..");
const app = fs.readFileSync(path.join(root, "apps/family-portal/app.js"), "utf8");
const index = fs.readFileSync(path.join(root, "apps/family-portal/index.html"), "utf8");
const navigation = fs.readFileSync(path.join(root, "apps/family-portal/navigation.js"), "utf8");
const view = fs.readFileSync(path.join(root, "apps/family-portal/scribble-view.js"), "utf8");
const deployHelper = fs.readFileSync(path.join(root, "deploy/h3-backend/kaos-h3"), "utf8");
const { expiryTitleColor, expiryUrgency, normalizeList } = require("../../apps/family-portal/scribble.js");

test("Scribble normalizes text and file captures", () => {
  const result = normalizeList({ items: [
    { id: "one", title: "Note", text: "Body" },
    { id: "two", title: "Scan", filename: "scan.pdf", hasFile: true, sizeBytes: 12 },
  ] });
  assert.equal(result.items[0].kind, "text");
  assert.equal(result.items[1].kind, "file");
  assert.equal(result.items[1].filename, "scan.pdf");
});

test("Scribble titles progressively turn red from day 25 until expiry", () => {
  const now = Date.parse("2026-09-30T00:00:00Z");
  assert.equal(expiryUrgency({ createdAt: "2026-09-06T00:00:00Z" }, now), 0);
  assert.equal(expiryUrgency({ createdAt: "2026-09-02T12:00:00Z" }, now), 0.5);
  assert.equal(expiryUrgency({ createdAt: "2026-08-31T00:00:00Z" }, now), 1);
  assert.equal(expiryTitleColor({ createdAt: "2026-09-06T00:00:00Z" }, now), "");
  assert.equal(expiryTitleColor({ createdAt: "2026-08-31T00:00:00Z" }, now), "rgb(191, 97, 106)");
});

test("Scribble is a small staging inbox with both handoff actions", () => {
  assert.match(app, /fetch\("\/api\/scribble"/);
  assert.match(app, /async function saveScribbleToMemos/);
  assert.match(app, /async function saveScribbleToPaperless/);
  assert.match(view, /data-scribble-create/);
  assert.match(view, /data-scribble-to-memo/);
  assert.match(view, /data-scribble-to-paperless/);
  assert.match(navigation, /route: "scribble", label: "Scribble"/);
  assert.match(index, /src="\/navigation\.js\?v=11"/);
  assert.match(index, /src="\/scribble\.js\?v=1"/);
  assert.match(index, /href="\/styles\.css\?v=416"/);
  assert.match(index, /src="\/scribble-view\.js\?v=5"/);
  assert.ok(index.indexOf('src="/scribble-view.js?v=5"') < index.indexOf('src="/app.js?v=387"'));
  assert.match(view, /class="archiveTerminal scribbleBoard"/);
  assert.doesNotMatch(view, /QUICK CAPTURE|Scribble Inbox/);
  assert.match(view, /STAGING QUEUE/);
  assert.match(view, /name="file" type="file" data-app-file/);
  assert.match(view, /class="appFileControl"/);
  assert.doesNotMatch(view, /input::file-selector-button/);
});

test("family portal deployment makes every static asset nginx-readable", () => {
  assert.match(deployHelper, /rsync -a --chmod=D755,F644 --delete/);
});
