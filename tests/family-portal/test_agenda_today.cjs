const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "../..");
const app = fs.readFileSync(path.join(root, "apps/family-portal/app.js"), "utf8");
const styles = fs.readFileSync(path.join(root, "apps/family-portal/styles.css"), "utf8");

test("Agenda highlights today with date, marker, and time colors only", () => {
  assert.match(app, /familyAgendaDateGroup \$\{date === today \? "isToday" : ""\}/);
  assert.match(styles, /\.familyAgendaDateGroup\.isToday h3\s*\{[^}]*color:\s*var\(--nord8\)/s);
  assert.match(styles, /\.familyAgendaDateGroup\.isToday \.familyAgendaEventMarker\s*\{/);
  assert.match(styles, /\.familyAgendaDateGroup\.isToday \.familyAgendaMixedTime\s*\{/);
  assert.doesNotMatch(styles, /\.familyAgendaDateGroup\.isToday\s*\{[^}]*(?:box-shadow|color-mix)/s);
});
