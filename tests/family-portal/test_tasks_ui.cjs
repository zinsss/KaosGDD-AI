const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");

test("task due-today label compares against real today, not selected date", () => {
  assert.match(appSource, /const dueDate = task\.due === ymd\(new Date\(\)\)/);
  assert.doesNotMatch(appSource, /const dueDate = task\.due === state\.selectedDate/);
});
