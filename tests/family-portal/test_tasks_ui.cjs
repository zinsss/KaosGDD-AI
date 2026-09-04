const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");

test("task due-today label compares against real today, not selected date", () => {
  assert.match(appSource, /const dueDate = task\.due === ymd\(new Date\(\)\)/);
  assert.doesNotMatch(appSource, /const dueDate = task\.due === state\.selectedDate/);
});

test("agenda calendar and tasks share Family GDDZiN Brain source pills", () => {
  assert.match(appSource, /function renderItemPills\(item\) \{/);
  assert.match(appSource, /renderCollectionPill\(item\)/);
  assert.match(appSource, /isBrainManagedItem\(item\) \? renderAutomationPill\("brain"\) : ""/);
  assert.match(appSource, /function isBrainManagedItem\(item\) \{/);
  assert.match(appSource, /if \(isGeneratedCalendarEvent\(item\)\) return true;/);
  assert.match(appSource, /return isRecurringTask\(item\);/);
  assert.match(appSource, /labels = \{\n    brain: uiText\("badge\.brain", "Brain"\),\n  \}/);
  assert.doesNotMatch(appSource, /renderAutomationPill\("repeating"\)/);
});
