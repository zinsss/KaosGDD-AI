const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { personalMenu, selectedPersonalRoute } = require("../../apps/family-portal/navigation.js");

test("personal menu has the accepted labels and order", () => {
  assert.deepEqual(
    personalMenu.map((item) => [item.route, item.label]),
    [
      ["today", "Agenda"],
      ["calendar", "Calendar"],
      ["tasks", "Tasks"],
      ["supplies", "Supplies"],
      ["memos", "Memos"],
      ["documents", "Documents"],
      ["fax", "Fax"],
      ["mail", "Mail"],
      ["ai-tasks", "AI Tasks"],
      ["services", "Utils"],
      ["settings", "Settings"],
    ],
  );
  assert.equal(new Set(personalMenu.map((item) => item.route)).size, personalMenu.length);
});

test("personal subroutes select their owning main menu", () => {
  assert.equal(selectedPersonalRoute("add-event"), "calendar");
  assert.equal(selectedPersonalRoute("edit-task"), "tasks");
  assert.equal(selectedPersonalRoute("add-supply"), "supplies");
  assert.equal(selectedPersonalRoute("add-memo"), "memos");
  assert.equal(selectedPersonalRoute("add-document"), "documents");
  assert.equal(selectedPersonalRoute("service"), "services");
  assert.equal(selectedPersonalRoute("supplies"), "supplies");
  assert.equal(selectedPersonalRoute("documents"), "documents");
  assert.equal(selectedPersonalRoute("fax"), "fax");
  assert.equal(selectedPersonalRoute("ai-tasks"), "ai-tasks");
  assert.equal(selectedPersonalRoute("add-ai-task"), "ai-tasks");
});

test("unknown personal routes safely select Agenda", () => {
  assert.equal(selectedPersonalRoute(""), "today");
  assert.equal(selectedPersonalRoute("not-a-route"), "today");
});

test("the navigation contract loads before the portal application", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
  const styleIndex = index.indexOf('href="/styles.css?v=306"');
  const navigationIndex = index.indexOf('src="/navigation.js?v=5"');
  const documentsIndex = index.indexOf('src="/documents.js?v=7"');
  const faxIndex = index.indexOf('src="/fax.js?v=2"');
  const mailIndex = index.indexOf('src="/mail.js?v=7"');
  const applicationIndex = index.indexOf('src="/app.js?v=311"');
  assert.ok(styleIndex >= 0);
  assert.ok(navigationIndex >= 0);
  assert.ok(documentsIndex > navigationIndex);
  assert.ok(faxIndex > documentsIndex);
  assert.ok(mailIndex > faxIndex);
  assert.ok(applicationIndex > mailIndex);
});

test("weather icon font is lazy-loaded after emoji fallback render", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.doesNotMatch(index, /preload" href="\/fonts\/KaosWeatherIcons\.woff2/);
  assert.match(appSource, /function loadKaosWeatherIcons\(\) \{/);
  assert.match(appSource, /document\.fonts\s*\.\s*load\('16px "Kaos Weather Icons"', String\.fromCodePoint\(0xe30d\)\)/);
  assert.match(appSource, /root\.classList\.add\("kaosWeatherIconsReady"\);/);
  assert.match(appSource, /return weatherIconGlyph\(0xe30d, "☀️"\);/);
  assert.match(styles, /--weather-icon-font:/);
  assert.match(styles, /html\.kaosWeatherIconsReady \.dayWeatherGlyph/);
  assert.doesNotMatch(styles, /Symbols Nerd Font|Nerd Font Symbols/);
});

test("weather detail rows keep icon font away from temperature text", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(appSource, /class="weatherPartGlyph"/);
  assert.match(appSource, /class="weatherPartTemperature"/);
  assert.match(styles, /\.weatherPartGlyph \{[\s\S]*font-family: var\(--weather-icon-font\);/);
  assert.match(styles, /\.weatherPartTemperature \{[\s\S]*font-family: "Sarasa Gothic Mono"/);
  const valueBlock = styles.match(/\.weatherPartValue \{[^}]*\}/)?.[0] || "";
  assert.doesNotMatch(valueBlock, /font-family: var\(--weather-icon-font\);/);
});

test("current location weather control is symbol-only", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(styles, /\.currentLocationWeatherButton \{[\s\S]*border: 0;[\s\S]*background: transparent;/);
  assert.match(styles, /\.currentLocationWeatherButton:hover \{[\s\S]*color: var\(--nord13\);/);
});

test("kaosgdd.net defaults to KaosGDD branding before family host override", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");

  assert.match(index, /<meta name="apple-mobile-web-app-title" id="appleAppTitle" content="KaosGDD" \/>/);
  assert.match(index, /<title>KaosGDD<\/title>/);
  assert.match(index, /document\.title = "Kaos Family";/);
  assert.match(index, /<p class="kicker">KaosGDD<\/p>/);
  assert.match(index, /<h1 id="routeTitle">Agenda<\/h1>/);
});

test("main desktop navigation renders an open list while preserving the mobile picker", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(appSource, /<select data-main-menu aria-label="Main menu">/);
  assert.match(appSource, /class="desktopMainMenuList"/);
  assert.match(appSource, /data-desktop-main-menu/);
  assert.match(styles, /\.desktopMainMenuList \{\n  display: none;/);
  assert.match(styles, /@media \(min-width: 1180px\)/);
  assert.match(styles, /\.app\[data-profile="main"\] \.mainMenuPicker \{\n    display: block;\n    position: static;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.mainMenuPicker select \{\n    display: none;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.desktopMainMenuList \{\n    display: grid;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.appTop \{\n    border-radius: 0;/);
  assert.match(styles, /\.topAddButton \{[\s\S]*width: 36px;[\s\S]*height: 36px;[\s\S]*min-height: 36px;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.appIdentity \{\n    padding-right: 50px;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.topNav \{\n    margin-top: 28px;/);
  assert.match(styles, /@media \(min-width: 1180px\) \{[\s\S]*\.app\[data-profile="main"\] \.view \{[\s\S]*padding-top: 0;[\s\S]*padding-bottom: 40px;/);
  assert.match(styles, /@media \(min-width: 1180px\) \{[\s\S]*\.app\[data-profile="main"\]\[data-route="memos"\] \.view \{[\s\S]*padding-top: 0;[\s\S]*padding-bottom: 40px;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.topAddWrap \{\n    position: absolute;\n    top: 16px;\n    right: 16px;/);
});

test("family mobile navigation stays on one horizontal row", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(styles, /@media \(max-width: 1179px\) \{[\s\S]*\.app\[data-profile="family"\] \.topNav \{[\s\S]*display: flex;[\s\S]*flex-wrap: nowrap;[\s\S]*overflow-x: auto;/);
  assert.match(styles, /\.app\[data-profile="family"\] \.topNav a \{[\s\S]*flex: 0 0 auto;/);
});
