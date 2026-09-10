const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "../..");
const app = fs.readFileSync(path.join(root, "apps/family-portal/app.js"), "utf8");
const styles = fs.readFileSync(path.join(root, "apps/family-portal/styles.css"), "utf8");

test("Agenda gives only today's date group a subtle highlight", () => {
  assert.match(app, /familyAgendaDateGroup \$\{date === today \? "isToday" : ""\}/);
  assert.match(styles, /\.familyAgendaDateGroup\.isToday\s*\{/);
  assert.match(styles, /background:\s*color-mix\(in srgb, var\(--nord8\) 6%, transparent\)/);
});
