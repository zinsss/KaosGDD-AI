const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

test("top add opens the native supply composer route", () => {
  assert.match(appSource, /"add-supply": "Add Supply"/);
  assert.match(appSource, /if \(action === "supply"\) \{\s*window\.location\.hash = "#\/add-supply";/s);
  assert.match(appSource, /else if \(route === "add-supply"\) view\.innerHTML = renderAddSupply\(\);/);
  assert.match(appSource, /data-create-supply/);
});

test("main supplies route renders as an archive board instead of an inline composer", () => {
  assert.match(appSource, /data-archive-kind="supplies"/);
  assert.match(appSource, /id="suppliesIndexTitle">RECORD BOARD/);
  assert.match(appSource, /data-supplies-mode="active"/);
  assert.match(appSource, /data-supplies-mode="done"/);
  assert.match(appSource, /data-supplies-retry/);
});

test("family portal routes supplies api only to governor", () => {
  const suppliesBlock = nginxSource.match(/location \^~ \/api\/supplies \{[\s\S]*?\n    \}/)?.[0] || "";
  assert.match(suppliesBlock, /proxy_pass http:\/\/governor-api:8096;/);
  assert.doesNotMatch(suppliesBlock, /return 404;/);
  assert.doesNotMatch(nginxSource, /kaosgovernor-legacy-api/);
});
