const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const textPresetsSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/text-presets.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");
const familyPortalNginx = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");
const deployHelper = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/kaos-h3"), "utf8");

test("family preset text is a standalone server-backed route with cached categories", () => {
  assert.match(textPresetsSource, /STORAGE_KEY = "kaosgdd\.v2\.family\.textPresets\.v1"/);
  assert.match(textPresetsSource, /DEFAULT_CATEGORIES = Object\.freeze/);
  assert.match(appSource, /function textPresetContext\(\)/);
  assert.match(appSource, /async function loadFamilyTextPresets\(options = \{\}\)/);
  assert.match(textPresetsSource, /function loadDocument\(deps\)/);
  assert.match(textPresetsSource, /function saveDocument\(deps, presetDocument\)/);
  assert.match(textPresetsSource, /async function load\(deps, \{ force = false \} = \{\}\)/);
  assert.match(textPresetsSource, new RegExp('fetch\\("/api/text-presets"'));
  assert.match(textPresetsSource, /async function persist\(deps, presetDocument/);
  assert.match(textPresetsSource, /JSON\.stringify\(\{ baseRevision, categories: normalized\.categories \}\)/);
  assert.match(textPresetsSource, /maybeMigrateLocalToServer/);
  assert.match(appSource, /function renderTextPresets\(\)/);
  assert.match(appSource, /KAOS_TEXT_PRESETS\.render\(textPresetContext\(\)\)/);
  assert.match(appSource, /"text-presets": uiText\("route\.textPresets"/);
  assert.match(appSource, /route === "text-presets"\) view\.innerHTML = renderTextPresets\(\);/);
  assert.match(appSource, /if \(route === "text-presets"\) loadFamilyTextPresets\(\);/);
  assert.match(appSource, /portalProfile\(\) === "main"[\s\S]*route === "text-presets"/);
});

test("family preset text API is proxied to calendar-adapter", () => {
  assert.match(familyPortalNginx, /location = \/api\/text-presets/);
  assert.match(familyPortalNginx, /set \$calendar_adapter http:\/\/calendar-adapter:8091;/);
  assert.match(familyPortalNginx, /location = \/api\/text-presets[\s\S]*proxy_pass \$calendar_adapter;/);
  assert.match(deployHelper, /location = \/api\/text-presets/);
  assert.match(deployHelper, /family portal \/api\/text-presets must route to calendar-adapter/);
});

test("category buttons copy one random saved text with the shared clipboard helper", () => {
  assert.match(textPresetsSource, /data-family-text-category-copy/);
  assert.match(textPresetsSource, /function randomPreset\(deps, category\)/);
  assert.match(textPresetsSource, /RANDOM_STATE_KEY = "kaosgdd\.v2\.family\.textPresets\.randomState\.v1"/);
  assert.match(textPresetsSource, /function shuffledIndexes\(count\)/);
  assert.match(textPresetsSource, /Math\.floor\(Math\.random\(\) \* \(index \+ 1\)\)/);
  assert.match(textPresetsSource, /remaining\.shift\(\)/);
  assert.match(textPresetsSource, /categoryState\.signature !== presetSignature \|\| !remaining\.length/);
  assert.match(textPresetsSource, /const preset = randomPreset\(deps, category\);/);
  assert.match(textPresetsSource, /await deps\.writeTextToClipboard\(preset\);/);
  assert.match(textPresetsSource, /textPresets\.copied/);
  assert.match(textPresetsSource, /textPresets\.copyError/);
});

test("preset text manager supports category and text-tab editing", () => {
  assert.match(textPresetsSource, /data-family-text-presets-manage/);
  assert.match(textPresetsSource, /data-family-text-presets-done/);
  assert.match(textPresetsSource, /data-family-text-category-add/);
  assert.match(textPresetsSource, /data-family-text-category-rename/);
  assert.match(textPresetsSource, /data-family-text-category-delete/);
  assert.match(textPresetsSource, /data-family-text-tab-add/);
  assert.match(textPresetsSource, /data-family-text-tab-delete/);
  assert.match(textPresetsSource, /data-family-text-current-text/);
  assert.match(textPresetsSource, /saveEditorDraft\(deps\)/);
  assert.match(appSource, /KAOS_TEXT_PRESETS\.handleClick\(textPresetContext\(\), event\)/);
  assert.match(appSource, /KAOS_TEXT_PRESETS\.handleSubmit\(textPresetContext\(\), event\)/);
});

test("family preset text assets include styles, translations, and cache-busted bundles", () => {
  assert.match(styles, /\.familyTextPresetCategoryGrid \{/);
  assert.match(styles, /\.familyTextPresetTabs \{/);
  assert.match(styles, /\.familyTextPresetTabs\.isTextTabs \{[\s\S]*gap: 10px;[\s\S]*padding-inline: 2px 10px;/);
  assert.match(styles, /\.familyTextPresetEditor \{/);
  assert.match(styles, /\.familyTextPresetEditor \{[\s\S]*border-top: 1px solid var\(--line\);/);
  assert.match(styles, /\.familyTextPresetEditor textarea \{/);
  assert.match(translations, /"route\.textPresets": "차팅"/);
  assert.match(translations, /"textPresets\.manageTitle": "차팅 관리"/);
  assert.match(translations, /"textPresets\.shared":/);
  assert.match(translations, /"textPresets\.localFallback":/);
  assert.match(translations, /"textPresets\.copyRandom": "랜덤 복사"/);
  assert.match(indexSource, /href="\/styles\.css\?v=321"/);
  assert.match(indexSource, /src="\/translations\.js\?v=184"/);
  assert.match(indexSource, /src="\/text-presets\.js\?v=1"/);
  assert.match(indexSource, /src="\/app\.js\?v=329"/);
  assert.ok(indexSource.indexOf('src="/text-presets.js?v=1"') < indexSource.indexOf('src="/app.js?v=329"'));
});
