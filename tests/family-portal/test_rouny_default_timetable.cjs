const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");

test("Rouny stores a shared default timetable independently from the editor selection", () => {
  assert.match(appSource, /ROUNY_DEFAULT_STORAGE_KEY = "kaosgdd\.v2\.rouny\.defaultTemplateId\.v1"/);
  assert.match(appSource, /defaultTemplateId: ""/);
  assert.match(appSource, /function normalizeRounyDefaultTemplateId\(/);
  assert.match(appSource, /JSON\.stringify\(\{ baseRevision: state\.rouny\.revision, defaultTemplateId, templates \}\)/);
  assert.match(
    appSource,
    /templates\.find\(\(item\) => item\.id === state\.rouny\.defaultTemplateId\)[\s\S]*templates\.find\(\(item\) => item\.id === state\.rouny\.selectedTemplateId\)/,
  );
});

test("Rouny detail offers Make default and identifies the current default", () => {
  assert.match(appSource, /data-rouny-set-default=/);
  assert.match(appSource, /function setDefaultRounyTemplate\(templateId\)/);
  assert.match(appSource, /rounySetDefault\.dataset\.rounySetDefault/);
  assert.match(translations, /"rouny\.makeDefault": "기본으로 만들기"/);
  assert.match(translations, /"rouny\.defaultTemplate": "기본 시간표"/);
  assert.match(indexSource, /src="\/translations\.js\?v=183"/);
  assert.match(indexSource, /src="\/app\.js\?v=327"/);
});

test("Rouny timeline uses slightly taller hourly cells", () => {
  assert.match(appSource, /ROUNY_TIMELINE_HOUR_HEIGHT = 72/);
  assert.match(styles, /\.rounyTimelineHour \{[\s\S]*?height: 72px;/);
  assert.match(indexSource, /href="\/styles\.css\?v=318"/);
});
