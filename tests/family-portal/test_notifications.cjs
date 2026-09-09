const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const viewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/notifications-view.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

test("personal PWA exposes the Governor notification inbox", () => {
  assert.match(appSource, /fetch\("\/api\/notifications\?limit=100"/);
  assert.match(appSource, /KAOS_NOTIFICATIONS_VIEW\.renderNotifications/);
  assert.match(viewSource, /type="checkbox"/);
  assert.match(viewSource, /data-notification-ack=/);
  assert.doesNotMatch(viewSource, />ACK<\/button>/);
  assert.match(viewSource, /No pending notifications\./);
  assert.match(indexSource, /src="\/notifications-view\.js\?v=2"/);
  assert.ok(indexSource.indexOf('src="/notifications-view.js?v=2"') < indexSource.indexOf('src="/app.js?v=333"'));
});

test("notification acknowledgement uses the protected same-origin API", () => {
  assert.match(appSource, /fetch\(`\/api\/notifications\/\$\{encodeURIComponent\(id\)\}\/acknowledge`/);
  assert.match(appSource, /method: "POST"/);
  assert.match(appSource, /if \(!notificationCheck\.checked\) return/);
  assert.match(appSource, /notificationCheck\.disabled = true/);
  assert.match(nginxSource, /location \^~ \/api\/notifications/);
});
