const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("settings loads the read-only system status endpoint", () => {
  assert.match(appSource, /fetch\("\/api\/system\/status"/);
  assert.match(appSource, /function renderSystemStatusPanel\(\)/);
  assert.match(appSource, /data-system-status/);
  assert.match(appSource, /Observation only\. No restart, deploy, reboot, shell, package-update, or system write controls are exposed in PWA\./);
});

test("settings top add button is hidden because system writes are not exposed in PWA", () => {
  assert.match(appSource, /if \(selectedRoute === "settings"\) return "";/);
  assert.match(appSource, /topAction[\s\S]*data-top-add/);
});

test("system status has a navigation-only brain channel link", () => {
  assert.match(appSource, /data-brain-channel-link/);
  assert.match(appSource, /#brain link not configured/);
  assert.doesNotMatch(appSource, /data-system-(restart|reboot|deploy|shell|update)/);
});

test("nginx proxies only the read-only system api namespace to governor api", () => {
  assert.match(nginxSource, /location \^~ \/api\/system\//);
  assert.match(nginxSource, /proxy_pass http:\/\/governor-api:8096;/);
});

test("main settings renders a compact KaosGDD settings terminal", () => {
  assert.match(appSource, /function renderMainSettings\(\)/);
  assert.match(appSource, /class="archiveTerminal settingsTerminal"/);
  assert.match(appSource, /SETTINGS/);
  assert.match(appSource, /KAOSGDD \/\/ GOVERNED/);
  assert.match(appSource, /renderGovernorSettingsStatus\(\{ showRecurringDetails: false \}\)/);
  assert.match(appSource, /if \(portalProfile\(\) === "main"\) return renderMainSettings\(\);/);
  assert.match(styles, /\.app\[data-profile="main"\] \.settingsTerminal \{/);
  assert.match(styles, /\.app\[data-profile="main"\] \.settingsListCompact \{/);
});
