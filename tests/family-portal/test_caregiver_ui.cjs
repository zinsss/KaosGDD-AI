const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const caregiverViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/caregiver-view.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");

test("caregiver page rendering is delegated to the view module", () => {
  assert.match(appSource, /KAOS_CAREGIVER_VIEW\.renderCaregiver\(caregiverViewContext\(\)\)/);
  assert.match(caregiverViewSource, /class="caregiverPage"/);
  assert.match(caregiverViewSource, /data-caregiver-settings-form/);
  assert.match(caregiverViewSource, /data-caregiver-retry/);
  assert.match(caregiverViewSource, /data-caregiver-copy-month/);
  assert.match(caregiverViewSource, /class="caregiverMonthGrid"/);
  assert.match(indexSource, /src="\/caregiver-view\.js\?v=1"/);
  assert.ok(indexSource.indexOf('src="/caregiver-view.js?v=1"') < indexSource.indexOf('src="/app.js?v=327"'));
});
