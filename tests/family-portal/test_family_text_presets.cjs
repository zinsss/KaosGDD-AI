const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");

test("family settings has browser-local preset text saved as one line per item", () => {
  assert.match(appSource, /FAMILY_TEXT_PRESETS_STORAGE_KEY = "kaosgdd\.v2\.family\.textPresets\.v1"/);
  assert.match(appSource, /DEFAULT_FAMILY_TEXT_PRESETS = Object\.freeze/);
  assert.match(appSource, /function normalizeFamilyTextPresets\(value\)/);
  assert.match(appSource, /function loadFamilyTextPresets\(\)/);
  assert.match(appSource, /function saveFamilyTextPresets\(presets\)/);
  assert.match(appSource, /data-family-text-presets/);
  assert.match(appSource, /data-family-text-presets-save/);
});

test("copy random preset saves the visible textarea and uses the shared clipboard helper", () => {
  assert.match(appSource, /function randomFamilyTextPreset\(presets = loadFamilyTextPresets\(\)\)/);
  assert.match(appSource, /Math\.floor\(Math\.random\(\) \* normalized\.length\)/);
  assert.match(appSource, /const preset = randomFamilyTextPreset\(collectFamilyTextPresets\(\)\);/);
  assert.match(appSource, /await writeTextToClipboard\(preset\);/);
  assert.match(appSource, /settings\.textPresetsCopied/);
  assert.match(appSource, /settings\.textPresetsCopyError/);
});

test("family preset text assets include styles, translations, and cache-busted bundles", () => {
  assert.match(styles, /\.familyTextPresetEditor \{/);
  assert.match(styles, /\.familyTextPresetEditor textarea \{/);
  assert.match(translations, /"settings\.textPresets": "문구 프리셋"/);
  assert.match(translations, /"settings\.textPresetsCopyRandom": "랜덤 복사"/);
  assert.match(indexSource, /href="\/styles\.css\?v=286"/);
  assert.match(indexSource, /src="\/translations\.js\?v=172"/);
  assert.match(indexSource, /src="\/app\.js\?v=273"/);
});
