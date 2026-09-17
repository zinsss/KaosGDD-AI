const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const viewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/notifications-view.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

test("personal PWA renders the shared KaosToday briefing instead of an ACK list", () => {
  assert.match(appSource, /fetch\("\/api\/notifications\?limit=100"/);
  assert.match(appSource, /fetch\("\/api\/today"/);
  assert.match(appSource, /KAOS_NOTIFICATIONS_VIEW\.renderNotifications/);
  assert.match(viewSource, /KAOS TODAY/);
  assert.match(viewSource, /payload\.plainText/);
  assert.match(viewSource, /class="kaosTodayText"/);
  assert.doesNotMatch(viewSource, /data-notification-ack=/);
  assert.match(indexSource, /src="\/notifications-view\.js\?v=5"/);
  assert.ok(indexSource.indexOf('src="/notifications-view.js?v=5"') < indexSource.indexOf('src="/app.js?v=351"'));
});

test("viewing KaosToday acknowledges only notification rows included in its briefing", () => {
  assert.match(appSource, /fetch\(`\/api\/notifications\/\$\{encodeURIComponent\(id\)\}\/acknowledge`/);
  assert.match(appSource, /method: "POST"/);
  assert.match(appSource, /item\?\.source === "notification"/);
  assert.match(appSource, /!item\.acknowledged/);
  assert.match(nginxSource, /location \^~ \/api\/notifications/);
  assert.match(nginxSource, /location = \/api\/today/);
});
