const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { personalMenu, selectedPersonalRoute } = require("../../apps/family-portal/navigation.js");

test("personal menu has the accepted labels and order", () => {
  assert.deepEqual(
    personalMenu.map((item) => [item.route, item.label]),
    [
      ["today", "Agenda"],
      ["calendar", "Calendar"],
      ["tasks", "Tasks"],
      ["memos", "Memos"],
      ["documents", "Documents"],
      ["fax", "Fax"],
      ["mail", "Mail"],
      ["services", "Utils"],
      ["settings", "Settings"],
    ],
  );
  assert.equal(new Set(personalMenu.map((item) => item.route)).size, personalMenu.length);
});

test("personal subroutes select their owning main menu", () => {
  assert.equal(selectedPersonalRoute("add-event"), "calendar");
  assert.equal(selectedPersonalRoute("edit-task"), "tasks");
  assert.equal(selectedPersonalRoute("service"), "services");
  assert.equal(selectedPersonalRoute("supplies"), "services");
  assert.equal(selectedPersonalRoute("documents"), "documents");
  assert.equal(selectedPersonalRoute("fax"), "fax");
});

test("unknown personal routes safely select Agenda", () => {
  assert.equal(selectedPersonalRoute(""), "today");
  assert.equal(selectedPersonalRoute("not-a-route"), "today");
});

test("the navigation contract loads before the portal application", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
  const navigationIndex = index.indexOf('src="/navigation.js?v=1"');
  const documentsIndex = index.indexOf('src="/documents.js?v=1"');
  const faxIndex = index.indexOf('src="/fax.js?v=1"');
  const applicationIndex = index.indexOf('src="/app.js?v=225"');
  assert.ok(navigationIndex >= 0);
  assert.ok(documentsIndex > navigationIndex);
  assert.ok(faxIndex > documentsIndex);
  assert.ok(applicationIndex > faxIndex);
});
