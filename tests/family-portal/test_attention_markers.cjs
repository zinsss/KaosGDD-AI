const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("main shell derives quiet attention markers from existing read-only state", () => {
  assert.match(appSource, /attention: \{\n    checked: false,\n    loading: false,/);
  assert.match(appSource, /function mainAttentionMarkers\(\) \{/);
  assert.match(appSource, /state\.mail\.unreadItems\.length > 0/);
  assert.match(appSource, /state\.documents\.inboxItems\.some\(\(item\) => item\.status === "failed"\)/);
  assert.match(appSource, /Number\(state\.fax\.attention\?\.failed \|\| 0\) > 0/);
  assert.match(appSource, /function systemStatusIsCritical\(\) \{/);
});

test("main shell shows markers in mobile dropdown and desktop open list", () => {
  assert.match(appSource, /function mainMenuLabelWithAttention\(item\) \{/);
  assert.match(appSource, /return `\$\{item\.label\}\$\{marker \? " •" : ""\}`;/);
  assert.match(appSource, /<span>\$\{escapeHtml\(item\.label\)\}<\/span>\n              \$\{renderMainMenuAttentionDot\(item\.route\)\}/);
});

test("main shell refreshes attention once from existing protected endpoints", () => {
  assert.match(appSource, /async function loadMainAttention\(\{ force = false \} = \{\}\) \{/);
  assert.match(appSource, /loadUnreadMail\(\{ force \}\)/);
  assert.match(appSource, /loadDocumentInbox\(\{ force \}\)/);
  assert.match(appSource, /loadFax\(\{ force \}\)/);
  assert.match(appSource, /loadSystemStatus\(\{ force \}\)/);
  assert.match(appSource, /if \(portalProfile\(\) === "main"\) void loadMainAttention\(\);/);
});

test("main logo and menu dots use amber attention and red critical colors", () => {
  assert.match(styles, /\.app\[data-profile="main"\]\[data-attention="attention"\] \.appIdentity \.kicker \{[\s\S]*color: var\(--nord13\);/);
  assert.match(styles, /\.app\[data-profile="main"\]\[data-attention="critical"\] \.appIdentity \.kicker \{[\s\S]*color: var\(--nord11\);/);
  assert.match(styles, /\.mainMenuAttentionDot \{[\s\S]*color: var\(--nord13\);/);
  assert.match(styles, /\.mainMenuAttentionDot\.is-critical \{[\s\S]*color: var\(--nord11\);/);
});
