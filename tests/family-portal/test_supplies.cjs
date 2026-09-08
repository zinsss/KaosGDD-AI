const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const suppliesViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/supplies-view.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

test("top add opens the native supply composer route", () => {
  assert.match(appSource, /"add-supply": "Add Supply"/);
  assert.match(appSource, /if \(action === "supply"\) \{\s*window\.location\.hash = "#\/add-supply";/s);
  assert.match(appSource, /else if \(route === "add-supply"\) view\.innerHTML = renderAddSupply\(\);/);
  assert.match(appSource, /KAOS_SUPPLIES_VIEW\.renderAddSupply\(suppliesViewContext\(\)\)/);
  assert.match(suppliesViewSource, /data-create-supply/);
  assert.match(styles, /\.supplyAddPanel \.archiveFormRow input \{[\s\S]*?min-height: 52px;/);
  assert.match(styles, /\.supplyAddPanel \.archiveFormRow input \{[\s\S]*?border: 1px solid var\(--archive-line\);/);
  assert.match(styles, /\.supplyAddPanel \.archiveFormRow input \{[\s\S]*?background: var\(--archive-surface\);/);
  assert.match(indexSource, /href="\/styles\.css\?v=318"/);
});

test("main supplies route renders as an archive board instead of an inline composer", () => {
  assert.match(appSource, /KAOS_SUPPLIES_VIEW\.renderSupplies\(suppliesViewContext\(\), options\)/);
  assert.match(suppliesViewSource, /data-archive-kind="supplies"/);
  assert.match(suppliesViewSource, /id="suppliesIndexTitle">RECORD BOARD/);
  assert.match(suppliesViewSource, /id="suppliesIndexTitle">RECORD BOARD[\s\S]*<span>NO\.<\/span><span>DATE<\/span><span>TITLE<\/span>/);
  assert.match(suppliesViewSource, /data-supplies-mode="active"/);
  assert.match(suppliesViewSource, /data-supplies-mode="done"/);
  assert.match(suppliesViewSource, /data-supplies-retry/);
  assert.match(indexSource, /src="\/supplies-view\.js\?v=1"/);
  assert.ok(indexSource.indexOf('src="/supplies-view.js?v=1"') < indexSource.indexOf('src="/app.js?v=327"'));
});

test("family portal routes supplies api only to governor", () => {
  const suppliesBlock = nginxSource.match(/location \^~ \/api\/supplies \{[\s\S]*?\n    \}/)?.[0] || "";
  assert.match(suppliesBlock, /proxy_pass \$governor_api;/);
  assert.doesNotMatch(suppliesBlock, /return 404;/);
  assert.doesNotMatch(nginxSource, /kaosgovernor-legacy-api/);
});
