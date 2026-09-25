const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/typography.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

function loadTypography(hostname = "kaosgdd.net") {
  const values = new Map();
  const styleValues = new Map();
  const app = {
    dataset: {},
    style: {
      setProperty: (name, value) => styleValues.set(name, value),
    },
  };
  const documentElement = {
    style: {
      fontSize: "",
      removeProperty(name) {
        if (name === "font-size") this.fontSize = "";
      },
    },
  };
  const window = {
    location: { hostname },
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
    },
    document: {
      documentElement,
      querySelector: (selector) => selector === ".app" ? app : null,
    },
  };
  vm.runInNewContext(source, { window });
  return { typography: window.KAOS_PORTAL_TYPOGRAPHY, app, documentElement, values, styleValues };
}

test("typography preferences remain profile-scoped with safe defaults", () => {
  const main = loadTypography();
  assert.equal(main.typography.mainFontPreference(), "sarasa");
  assert.equal(main.typography.familyFontPreference(), "nanum");

  main.typography.setMainFontPreference("orbit");
  main.typography.setFamilyFontPreference("invalid");
  assert.equal(main.app.dataset.mainFont, "orbit");
  assert.equal(main.app.dataset.familyFont, undefined);
  assert.equal(main.values.get("kaosgdd.v2.main.font.v1"), "orbit");
  assert.equal(main.values.get("kaosgdd.v2.family.font.v1"), "nanum");
});

test("typography scale stepping is bounded and applies only to the active profile", () => {
  const family = loadTypography("family.kaosgdd.net");
  family.typography.stepFamilyFontScale(1);
  assert.equal(family.typography.familyFontScalePreference(), 105);
  assert.equal(family.app.dataset.familyFontScale, "105");
  assert.equal(family.documentElement.style.fontSize, "105%");

  for (let index = 0; index < 20; index += 1) family.typography.stepFamilyFontScale(1);
  assert.equal(family.typography.familyFontScalePreference(), 120);

  family.typography.applyMainFontScalePreference(80);
  assert.equal(family.app.dataset.mainFontScale, undefined);
});

test("Family can opt into a separate title-only font", () => {
  const family = loadTypography("family.kaosgdd.net");

  assert.equal(family.typography.familyTitleFontEnabled(), false);
  assert.equal(family.typography.familyTitleFontPreference(), "subakhwa");
  assert.equal(family.typography.familyTitleFontFamily(), '"116Subakhwa", sans-serif');
  family.typography.setFamilyTitleFontEnabled(true);
  family.typography.setFamilyTitleFontPreference("gultokki");

  assert.equal(family.app.dataset.familyTitleFontEnabled, "true");
  assert.equal(family.app.dataset.familyTitleFont, "gultokki");
  assert.equal(family.styleValues.get("--family-title-font"), '"HsGultokki", sans-serif');
  assert.equal(family.values.get("kaosgdd.v2.family.titleFontEnabled.v1"), "true");
  assert.equal(family.values.get("kaosgdd.v2.family.titleFont.v1"), "gultokki");
});

test("Family title font choices stay selectable before separate-title mode is enabled", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");

  assert.match(appSource, /<select data-family-title-font-setting aria-label="제목 폰트">/);
  assert.doesNotMatch(appSource, /data-family-title-font-setting[^>]*disabled/);
  assert.match(appSource, /setFamilyTitleFontEnabled\(familyTitleFontEnabledControl\.checked\);\s*applyFamilyTitleFontElements\(\);\s*return;/);
  assert.doesNotMatch(appSource, /setFamilyTitleFontEnabled\(familyTitleFontEnabledControl\.checked\);\s*render\(\);/);
  assert.match(appSource, /setFamilyTitleFontPreference\(familyTitleFont\.value\);\s*applyFamilyTitleFontElements\(\);\s*return;/);
  assert.doesNotMatch(appSource, /setFamilyTitleFontPreference\(familyTitleFont\.value\);\s*render\(\);/);
  assert.match(appSource, /function applyFamilyTitleFontElements\(\)[\s\S]*element\.style\.setProperty\("font-family", family, "important"\)/);
  assert.match(appSource, /view\.innerHTML = portalProfile\(\) === "family" \? renderFamilyAgenda\(\) : renderMainAgenda\(\);\s*applyFamilyTitleFontElements\(\);/);
});

test("typography asset loads before the portal application", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
  assert.ok(index.indexOf('src="/typography.js?v=5"') < index.indexOf('src="/app.js?v=395"'));
});

test("every textual UI element follows the profile global font", () => {
  assert.match(styles, /\.app\[data-profile="main"\]\[data-main-font\] :where\(\*\),/);
  assert.match(styles, /\.app\[data-profile="family"\]\[data-family-font\] :where\(\*\) \{[\s\S]*?font-family: inherit !important;/);
  assert.match(styles, /Glyph-only elements retain the icon fonts/);
  assert.match(styles, /font-family: "Kaos Weather Icons", var\(--weather-icon-font\) !important;/);
  assert.match(styles, /data-family-title-font-enabled="true"\][\s\S]*font-family: var\(--family-title-font\) !important;/);
  assert.match(source, /subakhwa: '\"116Subakhwa\", sans-serif'/);
  assert.match(source, /gultokki: '\"HsGultokki\", sans-serif'/);
  assert.match(source, /"jibtokki-round": '\"HsJibtokiRound\", sans-serif'/);
  assert.match(source, /lotteria: '\"Lotteria\", sans-serif'/);
});
