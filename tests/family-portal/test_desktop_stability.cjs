const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("desktop shell starts only when its sidebar leaves at least the narrow content width", () => {
  assert.match(appSource, /const DESKTOP_MEDIA_QUERY = "\(min-width: 1280px\)";/);
  assert.match(styles, /@media \(min-width: 1280px\) \{[\s\S]*?grid-template-columns: 220px minmax\(0, 1fr\);/);
  assert.match(styles, /@media \(max-width: 1279px\)/);
  assert.doesNotMatch(styles, /(?:min|max)-width: 11(?:79|80)px/);

  const narrowContentWidth = Math.min(1279, 1040) - 40;
  const desktopContentWidth = (width) => Math.min(width, 1420) - 32 - 220 - 16;
  assert.equal(narrowContentWidth, 1000);
  assert.deepEqual([1180, 1280, 1440, 1920].map((width) => width < 1280 ? Math.min(width, 1040) - 40 : desktopContentWidth(width)), [1000, 1012, 1152, 1152]);
  assert.ok(desktopContentWidth(1280) >= narrowContentWidth);
});

test("desktop scroll ownership stays stable at short viewport heights", () => {
  assert.match(styles, /\.appTop \{[\s\S]*?min-height: 0;[\s\S]*?scrollbar-gutter: stable;[\s\S]*?overflow-x: hidden;[\s\S]*?overflow-y: auto;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.appTop \{\s*border-radius: 8px;\s*\}/);
  assert.match(styles, /\.view \{[\s\S]*?overflow-y: auto;[\s\S]*?overflow-x: hidden;[\s\S]*?scrollbar-gutter: stable;/);
  assert.match(styles, /\.desktopContextPane \{[\s\S]*?max-height: none;[\s\S]*?overflow: visible;/);
  assert.match(styles, /\.archiveDetail \{[\s\S]*?max-height: none;[\s\S]*?overflow: visible;/);
});

test("ledger desktop table owns horizontal overflow without clipping detail cells", () => {
  assert.match(styles, /\.ledgerDesktopTableWrap \{\s*display: block;\s*overflow-x: auto;\s*overflow-y: visible;/);
  assert.match(styles, /\.ledgerTable \{\s*width: 100%;\s*min-width: 1120px;/);
  assert.match(styles, /\.ledgerTable th:nth-child\(4\) \{ width: auto; \}/);
});

test("desktop archive toolbars keep every action while using compact wrapped controls", () => {
  assert.match(styles, /@media \(min-width: 1280px\) \{[\s\S]*?\.memoArchiveCommands,[\s\S]*?\.mailArchiveCommands,[\s\S]*?\.faxArchiveCommands,[\s\S]*?\.documentArchiveCommands \{[\s\S]*?display: flex;[\s\S]*?flex-wrap: wrap;/);
  assert.match(styles, /\.documentArchiveCommands \.archiveTopAction \{\s*width: auto;\s*min-height: 36px;\s*padding: 6px 10px;/);
});
