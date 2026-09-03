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
  assert.match(appSource, /function familySmartEventProposals\(dateValue = state\.selectedDate\)/);
  assert.match(appSource, /adjustFamilySmartEventEnd\(item, Number\(state\.smartEventEndOffsets\[index\] \|\| 0\)\)/);
  assert.match(appSource, /function adjustFamilySmartEventEnd\(item, minutes\)/);
  assert.match(appSource, /endMs <= startMs\) return item;/);
  assert.match(appSource, /function familySmartEventDurationMinutes\(item\)/);
  assert.match(appSource, /function formatFamilySmartEventDuration\(item\)/);
  assert.match(appSource, /Math\.round\(\(endMs - startMs\) \/ 60_000\)/);
});

test("family smart event UI previews first and then saves with confirmation", () => {
  assert.match(appSource, /function renderFamilySmartEventPanel\(\)/);
  assert.match(appSource, /data-family-smart-event-input/);
  assert.doesNotMatch(appSource, /event\.smartTextboxLabel/);
  assert.doesNotMatch(translations, /"event\.smartTextboxLabel"/);
  assert.match(appSource, /data-family-smart-event-preview/);
  assert.match(appSource, /renderFamilySmartEventPreview\(proposals\)/);
  assert.match(appSource, /data-family-smart-event-save/);
  assert.match(appSource, /saveFamilySmartEvents\(\)/);
  assert.match(appSource, /window\.confirm\(familySmartEventSaveConfirmMessage\(proposals\)\)/);
  assert.match(appSource, /postCalendarEvent\(payload\)/);
  assert.match(appSource, /window\.location\.hash = "#\/calendar";/);
  assert.match(appSource, /data-add-event-mode="smart"/);
  assert.match(appSource, /familySmartEventPreviewBody/);
  assert.match(appSource, /data-family-smart-event-end-step="-60"/);
  assert.match(appSource, /data-family-smart-event-end-step="60"/);
  assert.match(appSource, /data-family-smart-event-index="\$\{index\}"/);
  assert.match(appSource, /&lt;&lt;/);
  assert.match(appSource, /formatFamilySmartEventDuration\(item\)/);
  assert.match(appSource, /&gt;&gt;/);
  assert.match(appSource, /item\.allDay \? uiText\("event\.allDayPill", "All Day"\) : `\$\{item\.startTime\}–\$\{item\.endTime\}`/);
});

test("family smart event input updates preview on input without rerendering the page", () => {
  const inputListener = appSource.match(/document\.addEventListener\("input", \(event\) => \{[\s\S]*?\n\}\);/);
  assert.ok(inputListener);
  assert.match(inputListener[0], /data-family-smart-event-input/);
  assert.match(inputListener[0], /state\.smartEventEndOffsets = \{\};/);
  assert.match(inputListener[0], /updateFamilySmartEventPreview\(\);/);
  assert.ok(appSource.includes('const saveButton = document.querySelector("[data-family-smart-event-save]");'));
  assert.match(appSource, /saveButton\.disabled = !proposals\.length \|\| state\.smartEventSaving;/);

  const changeListener = appSource.match(/document\.addEventListener\("change", async \(event\) => \{[\s\S]*?\n\}\);/);
  assert.ok(changeListener);
  assert.doesNotMatch(changeListener[0], /data-family-smart-event-input/);
});

test("family smart event assets include styling, translations, and cache busters", () => {
  assert.match(styles, /\.familySmartEventPanel \.panelBody \{/);
  assert.match(styles, /\.app\[data-profile="family"\] \.familySmartEventPanel textarea \{/);
  assert.match(styles, /width: 100%;/);
  assert.match(styles, /box-sizing: border-box;/);
  assert.match(styles, /resize: vertical;/);
  assert.match(styles, /font-family: inherit;/);
  assert.match(styles, /border-radius: 14px;/);
  assert.match(styles, /linear-gradient\(180deg, rgba\(255, 250, 255, 0\.86\), rgba\(244, 237, 248, 0\.92\)\)/);
  assert.match(styles, /\.familySmartEventPreview \{/);
  assert.match(styles, /\.familySmartEventControls \{/);
  assert.match(styles, /\.familySmartEventStep \{/);
  assert.match(styles, /\.familySmartEventDuration \{/);
  assert.match(styles, /\.familySmartEventPreviewBody \{/);
  assert.match(styles, /grid-column: 2;/);
  assert.match(translations, /"event\.smart": "스마트 입력"/);
  assert.match(translations, /"event\.smartPlaceholder": "연차\/10:30 3교시 참관수업 \/ 2:30 스파예가"/);
  assert.match(translations, /"event\.smartSave": "확인 후 저장"/);
  assert.match(translations, /"event\.smartSaving": "저장 중\.\.\."/);
  assert.match(translations, /"dialog\.familySmartEventSaveConfirm": "미리보기 일정 \{count\}개를 캘린더에 저장할까요\?"/);
  assert.match(translations, /"event\.smartShorter": "1시간 줄이기"/);
  assert.match(translations, /"event\.smartLonger": "1시간 늘리기"/);
  assert.match(translations, /"event\.smartHoursSuffix": "시간"/);
  assert.match(translations, /"event\.smartMinutesSuffix": "분"/);
  assert.match(styles, /grid-template-columns: 96px minmax\(0, 1fr\);/);
  assert.match(indexSource, /href="\/styles\.css\?v=297"/);
  assert.match(indexSource, /src="\/translations\.js\?v=180"/);
  assert.match(indexSource, /src="\/app\.js\?v=284"/);
});
