const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const moduleSource = fs.readFileSync(path.join(root, "apps/family-portal/gratitude-journal.js"), "utf8");
const appSource = fs.readFileSync(path.join(root, "apps/family-portal/app.js"), "utf8");
const indexSource = fs.readFileSync(path.join(root, "apps/family-portal/index.html"), "utf8");
const styleSource = fs.readFileSync(path.join(root, "apps/family-portal/styles.css"), "utf8");

function loadModule(fetchImpl = async () => ({ ok: true, json: async () => ({ ok: true }) })) {
  const window = {};
  vm.runInNewContext(moduleSource, { window, fetch: fetchImpl, encodeURIComponent, JSON });
  return window.KAOS_GRATITUDE_JOURNAL;
}

test("gratitude journal module loads before the portal app", () => {
  assert.ok(indexSource.indexOf('src="/gratitude-journal.js?v=2"') < indexSource.indexOf('src="/app.js?v=343"'));
  assert.match(appSource, /gratitude: window\.KAOS_GRATITUDE_JOURNAL\.initialState\(\)/);
  assert.match(appSource, /renderGratitudeJournal\(today\)/);
  assert.match(styleSource, /\.gratitudePanel\s*\{[^}]*grid-column: 1 \/ -1/s);
});

test("renders five text fields for both profiles", () => {
  const journalModule = loadModule();
  for (const profile of ["main", "family"]) {
    const html = journalModule.render({
      journal: journalModule.initialState(),
      profile,
      date: "2026-09-15",
      escapeHtml: (value) => String(value),
    });
    assert.equal((html.match(/data-gratitude-item=/g) || []).length, 5);
    assert.match(html, /<details class="panel gratitudePanel" data-gratitude-disclosure >/);
    assert.doesNotMatch(html, /data-gratitude-disclosure open/);
  }
});

test("save sends the five slots and current etag", async () => {
  let request;
  const responsePayload = {
    ok: true,
    date: "2026-09-15",
    exists: true,
    items: ["one", "two", "", "", ""],
    etag: '"new"',
    lastModified: "2026-09-15T10:00:00",
  };
  const journalModule = loadModule(async (url, options) => {
    request = { url, options };
    return { ok: true, status: 200, json: async () => responsePayload };
  });
  const journal = journalModule.initialState();
  Object.assign(journal, { date: "2026-09-15", items: ["one", "two", "", "", ""], etag: '"old"' });

  await journalModule.save({ journal, profile: "main", date: "2026-09-15", rerender() {} });

  assert.equal(request.url, "/api/calendar/gratitude");
  assert.equal(request.options.method, "PUT");
  assert.deepEqual(JSON.parse(request.options.body), {
    date: "2026-09-15",
    items: ["one", "two", "", "", ""],
    etag: '"old"',
  });
  assert.equal(journal.etag, '"new"');
  assert.equal(journal.dirty, false);
});
