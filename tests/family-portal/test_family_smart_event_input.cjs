const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");

test("family calendar add defaults to smart preview while main stays manual", () => {
  assert.match(appSource, /addEventMode: portalProfile\(\) === "family" \? "smart" : "normal"/);
  assert.match(appSource, /function prepareAddEventRoute\(\)/);
  assert.match(appSource, /if \(portalProfile\(\) === "family"\) \{\s*state\.addEventMode = "smart";/);
  assert.match(appSource, /else if \(state\.addEventMode === "smart"\) \{\s*state\.addEventMode = "normal";/);
  assert.match(appSource, /if \(portalProfile\(\) !== "family" && state\.addEventMode === "smart"\) state\.addEventMode = "normal";/);
  assert.match(appSource, /runTopAddAction\(action\)[\s\S]*if \(action === "event"\) \{\s*prepareAddEventRoute\(\);/);
  assert.match(appSource, /enteringRoute && route === "add-event"\) prepareAddEventRoute\(\);/);
});

test("family smart event parser splits wife-style day text without saving", () => {
  assert.match(appSource, /function normalizeFamilySmartEventTime\(hourValue, minuteValue, meridiem = ""\)/);
  assert.match(appSource, /if \(!marker && hour >= 1 && hour <= 7\) hour \+= 12;/);
  assert.match(appSource, /function parseFamilySmartEventInput\(value, dateValue = state\.selectedDate\)/);
  assert.match(appSource, /\.split\(/);
  assert.match(appSource, /\\n/);
  assert.match(appSource, /timeExpression = String\.raw/);
  assert.match(appSource, /part\.match\(new RegExp/);
  assert.match(appSource, /allDay: true/);
  assert.ok(appSource.includes("(?:\\\\s*[-~–—]\\\\s*${timeExpression})?"));
  assert.match(appSource, /const explicitEndTime = match\[6\]/);
  assert.match(appSource, /const title = String\(match\[9\] \|\| ""\)\.trim\(\) \|\| part;/);
  assert.match(appSource, /explicitEndMinutes === null[\s\S]*addLocalMinutes\(dateValue, startTime, 60\)/);
  assert.match(appSource, /explicitEndMinutes <= startMinutes[\s\S]*addLocalMinutes\(dateValue, explicitEndTime, 24 \* 60\)/);
  assert.doesNotMatch(appSource, /data-family-smart-event-save/);
});

test("family smart event UI is a preview-only contextual input", () => {
  assert.match(appSource, /function renderFamilySmartEventPanel\(\)/);
  assert.match(appSource, /data-family-smart-event-input/);
  assert.match(appSource, /data-family-smart-event-preview/);
  assert.match(appSource, /renderFamilySmartEventPreview\(parseFamilySmartEventInput\(state\.smartEventInput, state\.selectedDate\)\)/);
  assert.match(appSource, /<button class="primaryButton" type="button" disabled>\$\{uiText\("event\.smartSavePending"/);
  assert.match(appSource, /data-add-event-mode="smart"/);
});

test("family smart event input updates preview on input without rerendering the page", () => {
  const inputListener = appSource.match(/document\.addEventListener\("input", \(event\) => \{[\s\S]*?\n\}\);/);
  assert.ok(inputListener);
  assert.match(inputListener[0], /data-family-smart-event-input/);
  assert.match(inputListener[0], /preview\.innerHTML = `/);
  assert.match(inputListener[0], /renderFamilySmartEventPreview\(parseFamilySmartEventInput\(state\.smartEventInput, state\.selectedDate\)\)/);

  const changeListener = appSource.match(/document\.addEventListener\("change", async \(event\) => \{[\s\S]*?\n\}\);/);
  assert.ok(changeListener);
  assert.doesNotMatch(changeListener[0], /data-family-smart-event-input/);
});

test("family smart event assets include styling, translations, and cache busters", () => {
  assert.match(styles, /\.familySmartEventPanel \.panelBody \{/);
  assert.match(styles, /\.familySmartEventPreview \{/);
  assert.match(translations, /"event\.smart": "스마트 입력"/);
  assert.match(translations, /"event\.smartPlaceholder": "연차\/10:30 3교시 참관수업 \/ 2:30 스파예가"/);
  assert.match(translations, /"event\.smartSavePending": "저장은 다음 단계"/);
  assert.match(indexSource, /href="\/styles\.css\?v=289"/);
  assert.match(indexSource, /src="\/translations\.js\?v=175"/);
  assert.match(indexSource, /src="\/app\.js\?v=277"/);
});
