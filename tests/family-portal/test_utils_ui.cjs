const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("main Utils renders as the shared archive terminal board", () => {
  assert.match(appSource, /function renderServices\(\) \{/);
  assert.match(appSource, /<section class="archiveTerminal" data-archive-kind="services" aria-label="Utils board">/);
  assert.match(appSource, /<div class="archiveColumnHeader" aria-hidden="true">[\s\S]*<span>NO\.<\/span><span>TYPE<\/span><span>TITLE<\/span>/);
  assert.match(appSource, /class="archiveRecordList"/);
  assert.match(appSource, /class="archiveSourceLink"[\s\S]*>OPEN<\/a>/);
});

test("embedded desktop service actions use bracket command styling", () => {
  assert.match(appSource, /class="archiveTerminal desktopServiceWorkspace"/);
  assert.match(appSource, /<button class="archiveAction" type="button" data-reload-service-frame>RELOAD<\/button>/);
  assert.match(appSource, /const openAction = `<a class="archiveAction"/);
});

test("main form action rows use compact bracket command styling", () => {
  assert.match(styles, /\.app\[data-profile="main"\] \.formActions \.primaryButton::before,[\s\S]*content: "\[";/);
  assert.match(styles, /\.app\[data-profile="main"\] \.formActions \.primaryButton::after,[\s\S]*content: "\]";/);
  assert.match(styles, /\.app\[data-profile="main"\] \.formActions \.dangerButton,[\s\S]*\.app\[data-profile="main"\] \.eventReadOnly \.dangerButton \{[\s\S]*color: var\(--archive-error\);/);
  assert.match(styles, /\.app\[data-profile="main"\] \.settingsActionRow \.openButton \{[\s\S]*background: transparent;/);
});
