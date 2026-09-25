const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { personalMenu, selectedPersonalRoute, notificationRoute } = require("../../apps/family-portal/navigation.js");

test("personal menu has the accepted labels and order", () => {
  assert.deepEqual(
    personalMenu.map((item) => [item.route, item.label]),
    [
      ["today", "Today"],
      ["agenda", "Agenda"],
      ["scribble", "Scribble"],
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
  assert.equal(selectedPersonalRoute("scribble"), "scribble");
  assert.equal(selectedPersonalRoute("agenda"), "agenda");
  assert.equal(selectedPersonalRoute("today"), "today");
  assert.equal(selectedPersonalRoute("notifications"), "today");
  assert.equal(selectedPersonalRoute("documents"), "documents");
  assert.equal(selectedPersonalRoute("fax"), "fax");
  assert.equal(selectedPersonalRoute("ai-tasks"), "ai-tasks");
  assert.equal(selectedPersonalRoute("add-ai-task"), "ai-tasks");
});

test("unknown personal routes safely select Agenda", () => {
  assert.equal(selectedPersonalRoute(""), "agenda");
  assert.equal(selectedPersonalRoute("not-a-route"), "agenda");
});

test("Today is independently selectable in the main menu", () => {
  assert.equal(personalMenu.some((item) => item.route === "today"), true);
  assert.equal(personalMenu.some((item) => item.route === "notifications"), false);
  assert.equal(selectedPersonalRoute("today"), "today");
  assert.equal(selectedPersonalRoute("notifications"), "today");
});

test("notification categories point at the selector destination that can acknowledge them", () => {
  assert.equal(notificationRoute("mail"), "mail");
  assert.equal(notificationRoute("fax"), "fax");
  assert.equal(notificationRoute("maintenance"), "settings");
  assert.equal(notificationRoute("system"), "settings");
  assert.equal(notificationRoute("daily"), "today");
});

test("the navigation contract loads before the portal application", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
  const styleIndex = index.indexOf('href="/styles.css?v=425"');
  const navigationIndex = index.indexOf('src="/navigation.js?v=11"');
  const calendarViewIndex = index.indexOf('src="/calendar-view.js?v=2"');
  const documentsIndex = index.indexOf('src="/documents.js?v=7"');
  const faxIndex = index.indexOf('src="/fax.js?v=3"');
  const mailIndex = index.indexOf('src="/mail.js?v=7"');
  const applicationIndex = index.indexOf('src="/app.js?v=394"');
  assert.ok(styleIndex >= 0);
  assert.ok(navigationIndex >= 0);
  assert.ok(calendarViewIndex > navigationIndex);
  assert.ok(documentsIndex > calendarViewIndex);
  assert.ok(faxIndex > documentsIndex);
  assert.ok(mailIndex > faxIndex);
  assert.ok(applicationIndex > mailIndex);
});

test("family mobile header keeps the page title and right-aligned navigation on one line", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(appSource, /family:\s*\{\s*label: ""/);
  assert.match(styles, /\.app\[data-profile="family"\] \.appIdentity \.kicker \{\s*display: none;/);
  assert.match(styles, /\.app\[data-profile="family"\] \.topNav a:first-child \{\s*margin-left: auto;/);
  assert.doesNotMatch(styles, /\.app\[data-profile="family"\] \.appTop \{[\s\S]*?grid-template-rows: auto auto;/);
});

test("all PWA pages end with scrollable flow space independent of the iOS safe area", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  assert.match(styles, /--page-bottom-reserve: clamp\(96px, 14dvh, 144px\);/);
  assert.doesNotMatch(styles, /--page-bottom-reserve: max\([^;]*safe-bottom/);
  assert.doesNotMatch(styles, /\.app\[data-profile="main"\] \{\s*--page-bottom-reserve: 0px;/);
  assert.match(styles, /\.view \{[\s\S]*?padding: 14px 0 var\(--page-bottom-reserve\);[\s\S]*?overflow-y: auto;/);
  assert.match(styles, /@media \(display-mode: standalone\) \{[\s\S]*html:has\(\.app\[data-profile="main"\]\),[\s\S]*height: 100vh;[\s\S]*\.app\[data-profile="main"\] \{\s*position: relative;\s*inset: auto;\s*height: 100vh;\s*min-height: 100vh;/);
});

test("mobile layout scrolls without a visible desktop scrollbar", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  assert.match(styles, /@media \(max-width: 1179px\) \{\s*\.view \{\s*scrollbar-width: none;/);
  assert.match(styles, /\.view::\-webkit-scrollbar \{\s*display: none;\s*width: 0;\s*height: 0;/);
});

test("main and family settings share the complete font list", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const typographySource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/typography.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");

  assert.match(typographySource, /fontOptions = Object\.freeze\(\[[\s\S]*id: "sarasa"[\s\S]*id: "elice"[\s\S]*id: "nanum"[\s\S]*id: "watermelon"[\s\S]*id: "milky-way"[\s\S]*id: "kita"[\s\S]*id: "free-time"/);
  assert.match(appSource, /fontIdSet: FAMILY_FONT_OPTIONS/);
  assert.match(appSource, /const MAIN_FONT_OPTIONS = FAMILY_FONT_OPTIONS/);
  assert.match(appSource, /renderSharedFontOptions\(selectedFont, \{ translate: true \}\)/);
  assert.match(appSource, /renderSharedFontOptions\(selectedFont\)/);
  assert.match(styles, /font-family: "Watermelon";[\s\S]*EF-watermelonSalad\.woff2/);
  assert.match(styles, /font-family: "SchoolSafeBoardMarker";[\s\S]*HakgyoansimBoadmarkerR\.woff2/);
  assert.match(styles, /font-family: "SchoolSafetyMilkyWay";[\s\S]*TTHakgyoansimEunhasuR\.woff2/);
  assert.match(styles, /font-family: "Kita";[\s\S]*KITA-Regular\.woff/);
  assert.match(styles, /font-family: "SchoolSafetyFreeTime";[\s\S]*HakgyoansimJayusiganR\.woff2/);
  assert.match(styles, /data-family-font="watermelon"[\s\S]*"Watermelon"/);
  assert.match(styles, /data-family-font="board-marker"[\s\S]*"SchoolSafeBoardMarker"/);
  assert.match(styles, /data-family-font="milky-way"[\s\S]*"SchoolSafetyMilkyWay"/);
  assert.match(styles, /data-family-font="kita"[\s\S]*"Kita"/);
  assert.match(styles, /data-family-font="free-time"[\s\S]*"SchoolSafetyFreeTime"/);
  assert.match(styles, /data-family-font="sarasa"[\s\S]*"Sarasa Gothic Mono"/);
  assert.match(styles, /data-family-font="elice"[\s\S]*"EllisDigitalCoding"/);
  assert.match(styles, /data-family-font="orbit"[\s\S]*"Orbit"/);
  assert.match(styles, /data-main-font="watermelon"[\s\S]*"Watermelon"/);
  assert.match(styles, /data-main-font="milky-way"[\s\S]*"SchoolSafetyMilkyWay"/);
  assert.match(styles, /data-main-font="kita"[\s\S]*"Kita"/);
  assert.match(styles, /data-main-font="free-time"[\s\S]*"SchoolSafetyFreeTime"/);
  assert.match(translations, /"settings\.fontSarasa": "Sarasa Gothic Mono"/);
  assert.match(translations, /"settings\.fontElice": "Elice Digital Baeum"/);
  assert.match(translations, /"settings\.fontOrbit": "Orbit"/);
  assert.match(translations, /"settings\.fontWatermelon": "Watermelon"/);
  assert.match(translations, /"settings\.fontBoardMarker": "학교안심 보드마커"/);
  assert.match(translations, /"settings\.fontMilkyWay": "학교안심 은하수"/);
  assert.match(translations, /"settings\.fontKita": "KITA"/);
  assert.match(translations, /"settings\.fontFreeTime": "학교안심 자유시간"/);
  assert.doesNotMatch(styles, /@font-face\s*\{[\s\S]*?src:\s*url\("https?:\/\//);
  assert.match(typographySource, /fontScaleOptions = Object\.freeze\(\[80, 85, 90, 95, 100, 105, 110, 115, 120\]\)/);
  assert.match(appSource, /data-family-font-step="-1"/);
  assert.match(appSource, /data-family-font-reset/);
  assert.match(appSource, /data-family-font-step="1"/);
  assert.match(typographySource, /global\.localStorage\.setItem\(profiles\[profile\]\.scaleKey, String\(normalized\)\)/);
  assert.match(styles, /\.familyFontScaleActions button \{/);
  assert.match(translations, /"settings\.fontSize": "글자 크기"/);
});

test("main typography avoids heavy synthesized bold while keeping light hierarchy", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(styles, /\.app\[data-profile="main"\] \{\s*-webkit-font-smoothing: antialiased;\s*-moz-osx-font-smoothing: grayscale;/);
  assert.match(styles, /\.app\[data-profile="main"\],\s*\.app\[data-profile="main"\] \* \{\s*font-synthesis-weight: none;/);
  assert.match(styles, /\.app\[data-profile="main"\] \* \{\s*font-weight: 400 !important;/);
  assert.match(styles, /\.app\[data-profile="main"\] :where\([\s\S]*strong,[\s\S]*button,[\s\S]*summary,[\s\S]*\) \{\s*font-weight: 500 !important;/);
});

test("main controls follow the selected global font and bracketed commands have no inner spaces", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  assert.match(styles, /\.app\[data-profile="main"\]\[data-main-font\] :where\(\*\),[\s\S]*font-family: inherit !important;/);
  assert.match(styles, /input::file-selector-button,[\s\S]*input::-webkit-file-upload-button[\s\S]*font-family: inherit !important;/);
  assert.doesNotMatch(styles, /Controls keep the terminal UI typeface/);
  assert.doesNotMatch(appSource, />\[[ ]+[^<]+[ ]+\]<\/button>/);
  assert.doesNotMatch(styles, /content: "\[[ ]+"|content: "[ ]+\]"/);
});

test("main weather uses the compact Day label for afternoon forecasts", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  assert.match(appSource, /Afternoon: uiText\("weather\.afternoon", "Day"\)/);
  assert.doesNotMatch(appSource, /Afternoon: uiText\("weather\.afternoon", "Afternoon"\)/);
});

test("calendar daypart weather glyphs share a fixed aligned column", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  assert.match(styles, /\.weatherPart \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\) 6\.25rem;/);
  assert.match(styles, /\.weatherPartValue \{[\s\S]*?grid-template-columns: 1\.25rem minmax\(0, 1fr\);[\s\S]*?width: 100%;/);
  assert.match(styles, /\.weatherPartGlyph \{[\s\S]*?font-size: 1\.08rem;[\s\S]*?text-align: center;/);
  assert.match(styles, /\.weatherPartTemperature \{[\s\S]*?font-size: 0\.84rem;[\s\S]*?text-align: right;/);
});

test("calendar month panel rendering is delegated to the view module", () => {
  const index = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const calendarViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/calendar-view.js"), "utf8");

  assert.match(appSource, /KAOS_CALENDAR_VIEW\.renderCalendarMonthPanel\(calendarMonthPanelContext\(\), options\)/);
  assert.match(calendarViewSource, /class="panel calendarMonthPanel/);
  assert.match(calendarViewSource, /class="calendarGrid"/);
  assert.match(calendarViewSource, /data-month-shift="-1"/);
  assert.match(calendarViewSource, /data-date="\$\{cell\.value\}"/);
  assert.match(calendarViewSource, /data-calendar-add-event/);
  assert.match(index, /src="\/calendar-view\.js\?v=2"/);
  assert.ok(index.indexOf('src="/calendar-view.js?v=2"') < index.indexOf('src="/app.js?v=394"'));
  assert.match(calendarViewSource, /dayCaregiverMark" role="img"/);
  assert.match(calendarViewSource, /hasMarket \|\| eventCount \|\| taskCount/);
});

test("family calendar event counters use a quiet theme color", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  assert.match(styles, /\.app\[data-profile="family"\] \.dayEventCount\s*\{[^}]*color: #8c5f83;/s);
});

test("family mobile calendar header keeps its controls on one row", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  assert.match(styles, /@media \(max-width: 640px\)[\s\S]*data-profile="family"\]\[data-route="calendar"\][\s\S]*\.calendarMonthPanel \.panelHeader\s*\{[^}]*flex-wrap: nowrap;/);
  assert.match(styles, /data-route="calendar"\][^\n]*\.calendarMonthTitle\s*\{[^}]*flex-wrap: nowrap;/s);
  assert.match(styles, /data-route="calendar"\][^\n]*\.calendarHeaderActions\s*\{[^}]*flex-wrap: nowrap;/s);
});

test("calendar title uses native month and year dropdowns", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(appSource, /data-calendar-year-select/);
  assert.match(appSource, /data-calendar-month-select/);
  assert.match(appSource, /applySelectedCalendarYearMonth\(nextYear, currentMonth\)/);
  assert.match(appSource, /applySelectedCalendarYearMonth\(currentYear, nextMonth\)/);
  assert.match(styles, /\.calendarTitleSelect \{/);
  assert.match(styles, /appearance: auto;/);
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

test("weather time-of-day panel opens the selected date detail metrics", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  const translations = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/translations.js"), "utf8");

  assert.match(appSource, /class="selectedWeatherParts weatherDetailTrigger"/);
  assert.match(appSource, /data-open-weather-detail=/);
  assert.match(appSource, /async function openWeatherDetailPopup\(dateValue, cityValue\)/);
  assert.match(appSource, /fetch\(`\/api\/weather\/month\?\$\{params\.toString\(\)\}`/);
  assert.match(appSource, /precipitationProbability: part\?\.precipitationProbability \?\? ""/);
  assert.match(appSource, /humidityPercent: part\?\.humidityPercent \?\? ""/);
  assert.match(appSource, /windSpeedKmh: part\?\.windSpeedKmh \?\? ""/);
  assert.match(appSource, /class="weatherDetailPeriods"/);
  assert.match(styles, /\.weatherDetailPeriod dl \{/);
  assert.match(translations, /"weather\.precipitationProbability": "강수 확률"/);
  assert.match(translations, /"weather\.humidity": "습도"/);
});

test("calendar month grid supports guarded horizontal touch swipes", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
  assert.match(styles, /\.calendarGrid \{[\s\S]*?touch-action: pan-y;/);
  assert.match(appSource, /Math\.abs\(deltaX\) >= 48/);
  assert.match(appSource, /Math\.abs\(deltaX\) > Math\.abs\(deltaY\) \* 1\.25/);
  assert.match(appSource, /moveSelectedMonth\(deltaX < 0 \? 1 : -1, \{ revealCollectionTabs: true \}\)/);
  assert.match(appSource, /options\.revealCollectionTabs[\s\S]*?view\.scrollTop = 0/);
  assert.match(appSource, /suppressCalendarGridClick && event\.target\.closest\("\.calendarGrid"\)/);
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
  assert.match(appSource, /data-compact-main-menu-toggle/);
  assert.match(appSource, /data-compact-main-menu-popup/);
  assert.match(appSource, /class="desktopMainMenuList"/);
  assert.match(appSource, /data-desktop-main-menu/);
  assert.match(styles, /\.desktopMainMenuList \{\n  display: none;/);
  assert.match(styles, /@media \(min-width: 1180px\)/);
  assert.match(styles, /\.app\[data-profile="main"\] \.mainMenuPicker \{\n    display: block;\n    position: static;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.mainMenuPicker select \{\n    display: none;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.desktopMainMenuList \{\n    display: grid;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.appTop \{\n    border-radius: 0;/);
  assert.match(styles, /\.topAddButton \{[\s\S]*display: inline-flex;[\s\S]*width: auto;[\s\S]*height: 36px;[\s\S]*border-radius: 0;/);
  assert.match(styles, /\.topHeaderActions \{[\s\S]*grid-row: 1;[\s\S]*align-self: end;/);
  assert.match(styles, /:is\(\[data-route="calendar"\], \[data-route="tasks"\]\) \.collectionRail button,[\s\S]*?justify-content: center;[\s\S]*?text-align: center;/);
  assert.match(appSource, /function revealCalendarCollectionTabs\(\) \{[\s\S]*?view\.scrollTop = 0;[\s\S]*?requestAnimationFrame/);
  assert.match(appSource, /if \(enteringRoute\) view\.scrollTop = 0;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.appIdentity \{\n    padding-right: 140px;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.topNav \{\n    margin-top: 28px;/);
  assert.match(styles, /@media \(min-width: 1180px\) \{[\s\S]*\.app\[data-profile="main"\] \.view \{[\s\S]*padding-top: 0;[\s\S]*padding-bottom: 40px;/);
  assert.match(styles, /@media \(min-width: 1180px\) \{[\s\S]*\.app\[data-profile="main"\]\[data-route="memos"\] \.view \{[\s\S]*padding-top: 0;[\s\S]*padding-bottom: 40px;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.topHeaderActions \{\n    position: absolute;\n    top: 16px;\n    right: 16px;/);
});

test("narrow browser layout uses the themed compact menu", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(styles, /@media \(max-width: 1179px\) and \(display-mode: browser\)/);
  assert.match(styles, /\.app\[data-profile="main"\] \.mainMenuPicker select \{\s*display: none;/);
  assert.match(styles, /\.compactMainMenuPopup \{[\s\S]*background: rgba\(37, 43, 54, 0\.98\);/);
  assert.match(styles, /\.compactMainMenuPopup a\.isActive \{[\s\S]*color: var\(--nord13\);/);
  assert.match(appSource, /function toggleCompactMainMenu\(\)/);
  assert.match(appSource, /closeCompactMainMenu\(\{ restoreFocus: true \}\)/);
});

test("global reload synchronizes recurring tasks before reloading while family reloads from its title", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(appSource, /class="topReloadButton"[^>]*data-app-reload/);
  assert.match(appSource, /reloadLabel = state\.appReloadStatus === "syncing" \? "\[Syncing…\]" : state\.appReloadStatus === "synced" \? "\[Synced\]" : "\[Reload\]"/);
  assert.match(appSource, />\[Add\]<\/button>/);
  assert.match(appSource, /identity\.dataset\.appReload = "";/);
  assert.match(appSource, /identity\.setAttribute\("aria-label", "새로고침"\);/);
  assert.match(appSource, /async function syncAndReloadApplication\(\) \{[\s\S]*await syncRecurringTasksNow\(\);[\s\S]*window\.location\.reload\(\);/);
  assert.match(appSource, /event\.target\.closest\("\[data-app-reload\]"\)[\s\S]*await syncAndReloadApplication\(\);/);
  assert.match(appSource, /Sync recurring tasks and reload KaosGDD/);
  assert.match(appSource, /state\.appReloadStatus = "syncing";[\s\S]*state\.appReloadStatus = "synced";/);
  assert.match(styles, /\.topReloadButton \{[\s\S]*display: inline-flex;[\s\S]*width: auto;[\s\S]*height: 36px;[\s\S]*border-radius: 0;/);
  assert.doesNotMatch(styles, /data-main-font[^}]*:where\([\s\S]*?\.topReloadButton/);
  assert.match(styles, /\.app\[data-profile="family"\] \.appIdentity\[data-app-reload\] \{/);
});

test("family mobile navigation stays on one horizontal row", () => {
  const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

  assert.match(styles, /@media \(max-width: 1179px\) \{[\s\S]*\.app\[data-profile="family"\] \.topNav \{[\s\S]*display: flex;[\s\S]*flex-wrap: nowrap;[\s\S]*overflow-x: auto;/);
  assert.match(styles, /\.app\[data-profile="family"\] \.topNav a \{[\s\S]*touch-action: manipulation;/);
  assert.match(styles, /\.app\[data-profile="family"\] \.topNav a \{[\s\S]*flex: 0 0 auto;/);
  assert.match(appSource, /const familyNavLink = event\.target\.closest\("\[data-nav\]"\);[\s\S]*?if \(window\.location\.hash === nextHash\) render\(\);[\s\S]*?window\.location\.hash = nextHash;[\s\S]*?render\(\);/);
  assert.match(appSource, /nav\.querySelector\("\[data-nav\]\.isActive"\)\?\.scrollIntoView\(\{ block: "nearest", inline: "nearest" \}\);/);
  assert.match(appSource, /function renderFamilySettingsSection\(name, renderer\) \{[\s\S]*?try \{[\s\S]*?return renderer\(\);[\s\S]*?catch \(error\)/);
});
