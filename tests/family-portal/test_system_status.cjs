const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const settingsViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/settings-view.js"), "utf8");
const systemStatusViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/system-status-view.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("settings loads the read-only system status endpoint", () => {
  assert.match(appSource, /fetch\("\/api\/system\/status"/);
  assert.match(appSource, /function renderSystemStatusPanel\(\)/);
  assert.match(appSource, /KAOS_SYSTEM_STATUS_VIEW\.renderSystemStatusPanel\(systemStatusViewContext\(\)\)/);
  assert.match(systemStatusViewSource, /data-system-status/);
  assert.match(appSource, /function recurringWorkerSummary\(worker\) \{/);
  assert.match(appSource, /function recurringWorkerStatusLine\(worker\) \{/);
  assert.match(systemStatusViewSource, /Recurring sync/);
  assert.match(systemStatusViewSource, /const worker = runtime\.worker \|\| \{\};/);
  assert.match(systemStatusViewSource, /Observation only\. No restart, deploy, reboot, shell, package-update, or system write controls are exposed in PWA\./);
  assert.match(indexSource, /src="\/system-status-view\.js\?v=1"/);
  assert.ok(indexSource.indexOf('src="/system-status-view.js?v=1"') < indexSource.indexOf('src="/app.js?v=325"'));
});

test("settings top add button is hidden because system writes are not exposed in PWA", () => {
  assert.match(appSource, /if \(selectedRoute === "settings"\) return "";/);
  assert.match(appSource, /topAction[\s\S]*data-top-add/);
});

test("system status has a navigation-only brain channel link", () => {
  assert.match(systemStatusViewSource, /data-brain-channel-link/);
  assert.match(systemStatusViewSource, /#brain link not configured/);
  assert.doesNotMatch(systemStatusViewSource, /data-system-(restart|reboot|deploy|shell|update)/);
});

test("nginx proxies only the read-only system api namespace to governor api", () => {
  assert.match(nginxSource, /location \^~ \/api\/system\//);
  assert.match(nginxSource, /location = \/api\/settings\/status/);
  assert.match(nginxSource, /set \$governor_api http:\/\/governor-api:8096;/);
  assert.match(nginxSource, /proxy_pass \$governor_api;/);
});

test("main settings renders a compact KaosGDD settings terminal", () => {
  assert.match(appSource, /function renderMainSettings\(\)/);
  assert.match(appSource, /class="archiveTerminal settingsTerminal"/);
  assert.match(appSource, /CONTROL ROOM/);
  assert.match(appSource, /KAOSGDD \/\/ READ ONLY/);
  assert.match(appSource, /renderGovernorSettingsStatus\(\{ showRecurringDetails: false \}\)/);
  assert.match(appSource, /if \(portalProfile\(\) === "main"\) return renderMainSettings\(\);/);
  assert.match(styles, /\.app\[data-profile="main"\] \.settingsTerminal \{/);
  assert.match(styles, /\.app\[data-profile="main"\] \.settingsListCompact \{/);
});

test("main settings avoids legacy editor stacks and keeps system writes out of PWA", () => {
  const mainSettingsStart = appSource.indexOf("function renderMainSettings()");
  const settingsStart = appSource.indexOf("function renderSettings()", mainSettingsStart);
  const mainSettingsSource = appSource.slice(mainSettingsStart, settingsStart);
  assert.match(appSource, /function renderMainSettingsMap\(\)/);
  assert.match(appSource, /function renderMainSettingsLinks\(\)/);
  assert.match(appSource, /System writes", "KaosSystemOperator \/ Codex, not PWA"/);
  assert.doesNotMatch(mainSettingsSource, /renderMailOrganizerSettings\(\)/);
  assert.doesNotMatch(mainSettingsSource, /renderCustomEventSettings\(\)/);
  assert.match(appSource, /if \(route === "settings"\) \{[\s\S]*loadSystemStatus\(\);[\s\S]*loadGovernorSettingsStatus\(\);[\s\S]*if \(portalProfile\(\) !== "main"\) \{[\s\S]*loadWeatherSettings\(\);[\s\S]*loadRecurringTasks\(\);[\s\S]*\}/);
  assert.match(styles, /\.app\[data-profile="main"\] \.settingsLinkGrid \{/);
});

test("custom event settings rendering is delegated to the settings view module", () => {
  assert.match(appSource, /KAOS_SETTINGS_VIEW\.renderCustomEventSettings\(settingsViewContext\(\)\)/);
  assert.match(settingsViewSource, /data-custom-events/);
  assert.match(settingsViewSource, /data-custom-event-setting="marketDaysEnabled"/);
  assert.match(settingsViewSource, /data-custom-event-setting="claimDayEnabled"/);
  assert.match(settingsViewSource, /data-custom-events-sync/);
  assert.match(settingsViewSource, /Generated calendar events/);
  assert.match(indexSource, /src="\/settings-view\.js\?v=1"/);
  assert.ok(indexSource.indexOf('src="/settings-view.js?v=1"') < indexSource.indexOf('src="/app.js?v=325"'));
});
