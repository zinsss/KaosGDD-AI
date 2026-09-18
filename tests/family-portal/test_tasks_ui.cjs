const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");
const adapterSource = fs.readFileSync(path.join(__dirname, "../../apps/calendar-adapter/server.py"), "utf8");

test("task due-today label compares against real today, not selected date", () => {
  assert.match(appSource, /const dueDate = task\.due === ymd\(new Date\(\)\)/);
  assert.doesNotMatch(appSource, /const dueDate = task\.due === state\.selectedDate/);
});

test("agenda calendar and tasks share Family GDDZiN Brain source pills", () => {
  assert.match(appSource, /function renderItemPills\(item\) \{/);
  assert.match(appSource, /const brainManaged = isBrainManagedItem\(item\);/);
  assert.match(appSource, /const collectionPill = brainManaged && collectionPillForItem\(item\)\.owner === "zin" \? "" : renderCollectionPill\(item\);/);
  assert.match(appSource, /brainManaged \? renderAutomationPill\("brain"\) : ""/);
  assert.match(appSource, /function isBrainManagedItem\(item\) \{/);
  assert.match(appSource, /if \(isGeneratedCalendarEvent\(item\)\) return true;/);
  assert.match(appSource, /return isRecurringTask\(item\);/);
  assert.match(appSource, /labels = \{\n    brain: uiText\("badge\.brain", "Brain"\),\n  \}/);
  assert.doesNotMatch(appSource, /renderAutomationPill\("repeating"\)/);
});

test("task timestamps are created and displayed in Korea time", () => {
  assert.match(appSource, /function dateTimePartsInTimeZone\(date, timeZone = "Asia\/Seoul"\) \{/);
  assert.match(appSource, /function localDateTimeStamp\(date = new Date\(\)\) \{/);
  assert.match(appSource, /function timestampHasExplicitTimezone\(raw\) \{/);
  assert.match(appSource, /return dateTimePartsInTimeZone\(parsed\);/);
  assert.match(appSource, /nextTask\.completed = override\.completed \|\| localDateTimeStamp\(\);/);
  assert.match(appSource, /rawTask\.completed = localDateTimeStamp\(\);/);
  assert.doesNotMatch(appSource, /completed = new Date\(\)\.toISOString\(\)\.slice\(0, 19\)/);
  assert.doesNotMatch(appSource, /lastModified = new Date\(\)\.toISOString\(\)\.slice\(0, 19\)/);
});

test("task creation is server-backed and never presented as local", () => {
  assert.match(appSource, /uiText\("task\.create", "Create task"\)/);
  assert.doesNotMatch(appSource, /Create local task/);
  assert.doesNotMatch(appSource, /mockAdapter\.createTask\(formData\)/);
  assert.match(appSource, /uiText\("task\.serverRequired", "Task server unavailable\. Reconnect and try again\."\)/);
});

test("task add and edit forms can select and safely move between Family and GDDZiN", () => {
  assert.match(appSource, /function renderTaskOwnerSelect\(selectedOwner\)/);
  assert.match(appSource, /<select name="taskOwner" data-task-owner/);
  assert.match(appSource, /editing\s*\? collectionOwnerForItem\(task\)/);
  assert.match(appSource, /targetCollectionId: writableCollectionIdFromForm\(formData, "VTODO"\)/);
  assert.match(translations, /"task\.list": "할 일 목록"/);
  assert.match(adapterSource, /target_collection_id = str\(payload\.get\("targetCollectionId"\)/);
  assert.match(adapterSource, /select_collection\(collections, target_collection_id, "VTODO"\)/);
  assert.match(adapterSource, /return \{"ok": True, "uid": uid, "collection": target_collection\["id"\], "moved": True\}/);
});
