const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");
const adapterSource = fs.readFileSync(path.join(__dirname, "../../apps/calendar-adapter/server.py"), "utf8");

test("event add and edit forms expose an owner-backed calendar selector", () => {
  assert.match(appSource, /function renderEventOwnerSelect\(selectedOwner\)/);
  assert.match(appSource, /<select name="eventOwner" data-event-owner/);
  assert.match(appSource, /renderEventOwnerSelect\(draft\.owner/);
  assert.match(appSource, /owner: collectionOwnerForItem\(calendarEvent\)/);
  assert.match(appSource, /zin: "GDDZiN"/);
  assert.match(appSource, /family: uiText\("collection\.family", "Family"\)/);
  assert.match(translations, /"event\.calendar": "캘린더"/);
});

test("event writes resolve the selected owner and edits request a safe move", () => {
  assert.match(appSource, /formData\.get\("eventOwner"\)/);
  assert.match(appSource, /targetCollectionId: writableCollectionIdFromForm\(formData, "VEVENT"\)/);
  assert.match(adapterSource, /target_collection_id = str\(payload\.get\("targetCollectionId"\)/);
  assert.match(adapterSource, /"If-None-Match": "\*"/);
  assert.match(adapterSource, /radicale_request\(item_account, "DELETE", existing\["href"\]/);
  assert.match(adapterSource, /radicale_request\(target_account, "DELETE", target_href/);
});
