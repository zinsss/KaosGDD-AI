const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/typography.js"), "utf8");

function loadTypography(hostname = "kaosgdd.net") {
  const values = new Map();
  const app = { dataset: {} };
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
  return { typography: window.KAOS_PORTAL_TYPOGRAPHY, app, documentElement, values };
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

test("typography asset loads before the portal application", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
  assert.ok(index.indexOf('src="/typography.js?v=1"') < index.indexOf('src="/app.js?v=374"'));
});
