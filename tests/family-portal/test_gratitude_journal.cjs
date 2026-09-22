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
  assert.ok(indexSource.indexOf('src="/gratitude-journal.js?v=4"') < indexSource.indexOf('src="/app.js?v=374"'));
  assert.match(appSource, /gratitude: window\.KAOS_GRATITUDE_JOURNAL\.initialState\(\)/);
  assert.match(appSource, /calendarGratitude: window\.KAOS_GRATITUDE_JOURNAL\.initialState\(\)/);
  assert.match(appSource, /renderGratitudeJournal\(today\)/);
  assert.match(appSource, /renderCalendarGratitude\(\s*state\.selectedDate,/);
  assert.match(appSource, /route === "calendar"\) window\.KAOS_GRATITUDE_JOURNAL\.load\(calendarGratitudeContext\(\)\)/);
  assert.match(styleSource, /\.gratitudePanel\s*\{[^}]*grid-column: 1 \/ -1/s);
  assert.match(styleSource, /\.gratitudeField input::placeholder\s*\{[^}]*rgba\(216, 222, 233, 0\.26\)[^}]*opacity: 1;/s);
  assert.match(styleSource, /\.app\[data-profile="main"\] \.gratitudeField input\s*\{[^}]*border-radius: 0;/s);
  assert.match(styleSource, /\.gratitudeField input:focus\s*\{[^}]*outline: none;[^}]*inset 2px 0 0/s);
  assert.match(styleSource, /\.app\[data-profile="family"\] \.gratitudeField input,[\s\S]*\.calendarGratitudeList\s*\{[^}]*color: #594964;/s);
});

test("renders a selected day's gratitude as a read-only list", () => {
  const journalModule = loadModule();
  const journal = journalModule.initialState();
  Object.assign(journal, {
    date: "2026-09-15",
    checked: true,
    exists: true,
    items: ["따뜻한 차", "무사한 하루", "", "", ""],
  });

  const html = journalModule.renderReadOnly({
    journal,
    profile: "family",
    date: "2026-09-15",
    escapeHtml: (value) => String(value),
    hasPrevious: true,
  });

  assert.match(html, /calendarGratitude withDivider/);
  assert.match(html, /감사한 일/);
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.doesNotMatch(html, /data-gratitude-item/);
});

test("renders a quiet empty state for a day without an entry", () => {
  const journalModule = loadModule();
  const journal = journalModule.initialState();
  Object.assign(journal, { date: "2026-09-15", checked: true });

  const html = journalModule.renderReadOnly({
    journal,
    profile: "main",
    date: "2026-09-15",
    escapeHtml: (value) => String(value),
  });

  assert.match(html, /No gratitude entry\./);
  assert.doesNotMatch(html, /withDivider/);
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
    assert.match(html, /<details class="panel gratitudePanel" data-gratitude-disclosure data-gratitude-scope="agenda" >/);
    assert.doesNotMatch(html, /data-gratitude-disclosure open/);
  }
});

test("calendar gratitude editor scopes past-date fields and saves separately", () => {
  const journalModule = loadModule();
  const html = journalModule.render({
    journal: journalModule.initialState(),
    profile: "main",
    date: "2026-09-15",
    scope: "calendar",
    embedded: true,
    escapeHtml: (value) => String(value),
  });

  assert.match(html, /class="calendarGratitudeEditor"/);
  assert.match(html, /data-gratitude-form data-gratitude-scope="calendar"/);
  assert.equal((html.match(/data-gratitude-scope="calendar"/g) || []).length, 7);
  assert.match(appSource, /if \(date <= ymd\(new Date\(\)\)\)/);
  assert.match(appSource, /gratitudeForm\.dataset\.gratitudeScope === "calendar"/);
  assert.match(appSource, /gratitudeInput\.dataset\.gratitudeScope === "calendar"/);
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
