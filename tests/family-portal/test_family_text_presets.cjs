const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");
const familyPortalNginx = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");
const deployHelper = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/kaos-h3"), "utf8");

test("family preset text is a standalone server-backed route with cached categories", () => {
  assert.match(appSource, /FAMILY_TEXT_PRESETS_STORAGE_KEY = "kaosgdd\.v2\.family\.textPresets\.v1"/);
  assert.match(appSource, /DEFAULT_FAMILY_TEXT_PRESET_CATEGORIES = Object\.freeze/);
  assert.match(appSource, /function normalizeFamilyTextPresets\(value\)/);
  assert.match(appSource, /function loadFamilyTextPresetDocument\(\)/);
  assert.match(appSource, /function saveFamilyTextPresetDocument\(presetDocument\)/);
  assert.match(appSource, /async function loadFamilyTextPresets\(\{ force = false \} = \{\}\)/);
  assert.match(appSource, new RegExp('fetch\\("/api/text-presets"'));
  assert.match(appSource, /async function persistFamilyTextPresetDocument\(presetDocument/);
  assert.match(appSource, /JSON\.stringify\(\{ baseRevision, categories: normalized\.categories \}\)/);
  assert.match(appSource, /maybeMigrateLocalTextPresetsToServer/);
  assert.match(appSource, /function renderTextPresets\(\)/);
  assert.match(appSource, /"text-presets": uiText\("route\.textPresets"/);
  assert.match(appSource, /route === "text-presets"\) view\.innerHTML = renderTextPresets\(\);/);
  assert.match(appSource, /if \(route === "text-presets"\) loadFamilyTextPresets\(\);/);
  assert.match(appSource, /portalProfile\(\) === "main"[\s\S]*route === "text-presets"/);
});

test("family preset text API is proxied to calendar-adapter", () => {
  assert.match(familyPortalNginx, /location = \/api\/text-presets/);
  assert.match(familyPortalNginx, /location = \/api\/text-presets[\s\S]*proxy_pass http:\/\/calendar-adapter:8091;/);
  assert.match(deployHelper, /location = \/api\/text-presets/);
  assert.match(deployHelper, /family portal \/api\/text-presets must route to calendar-adapter/);
});

test("category buttons copy one random saved text with the shared clipboard helper", () => {
  assert.match(appSource, /data-family-text-category-copy/);
  assert.match(appSource, /function randomFamilyTextPreset\(category\)/);
  assert.match(appSource, /Math\.floor\(Math\.random\(\) \* normalized\.length\)/);
  assert.match(appSource, /const preset = randomFamilyTextPreset\(category\);/);
  assert.match(appSource, /await writeTextToClipboard\(preset\);/);
  assert.match(appSource, /textPresets\.copied/);
  assert.match(appSource, /textPresets\.copyError/);
});

test("preset text manager supports category and text-tab editing", () => {
  assert.match(appSource, /data-family-text-presets-manage/);
  assert.match(appSource, /data-family-text-presets-done/);
  assert.match(appSource, /data-family-text-category-add/);
  assert.match(appSource, /data-family-text-category-rename/);
  assert.match(appSource, /data-family-text-category-delete/);
  assert.match(appSource, /data-family-text-tab-add/);
  assert.match(appSource, /data-family-text-tab-delete/);
  assert.match(appSource, /data-family-text-current-text/);
  assert.match(appSource, /saveFamilyTextPresetEditorDraft\(\)/);
});

test("family preset text assets include styles, translations, and cache-busted bundles", () => {
  assert.match(styles, /\.familyTextPresetCategoryGrid \{/);
  assert.match(styles, /\.familyTextPresetTabs \{/);
  assert.match(styles, /\.familyTextPresetEditor \{/);
  assert.match(styles, /\.familyTextPresetEditor textarea \{/);
  assert.match(translations, /"route\.textPresets": "문구"/);
  assert.match(translations, /"textPresets\.manageTitle": "문구 관리"/);
  assert.match(translations, /"textPresets\.shared":/);
  assert.match(translations, /"textPresets\.localFallback":/);
  assert.match(translations, /"textPresets\.copyRandom": "랜덤 복사"/);
  assert.match(indexSource, /href="\/styles\.css\?v=297"/);
  assert.match(indexSource, /src="\/translations\.js\?v=180"/);
  assert.match(indexSource, /src="\/app\.js\?v=285"/);
});
