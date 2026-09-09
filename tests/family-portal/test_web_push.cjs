const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "../..");
const app = fs.readFileSync(path.join(root, "apps/family-portal/app.js"), "utf8");
const client = fs.readFileSync(path.join(root, "apps/family-portal/web-push.js"), "utf8");
const worker = fs.readFileSync(path.join(root, "apps/family-portal/sw.js"), "utf8");
const index = fs.readFileSync(path.join(root, "apps/family-portal/index.html"), "utf8");
const nginx = fs.readFileSync(path.join(root, "deploy/h3-backend/family-portal/nginx.conf"), "utf8");

test("personal PWA registers Web Push without adding a navigation item", () => {
  assert.match(index, /src="\/web-push\.js\?v=1"/);
  assert.ok(index.indexOf('src="/web-push.js?v=1"') < index.indexOf('src="/app.js?v=335"'));
  assert.match(client, /family\.kaosgdd\.net/);
  assert.match(client, /navigator\.serviceWorker\.register\("\/sw\.js"/);
  assert.doesNotMatch(app.slice(0, app.indexOf("const familyRoutes")), /web-push/);
});

test("settings exposes enable, disable, and test controls", () => {
  assert.match(app, /function renderWebPushSettings\(\)/);
  assert.match(app, /data-web-push-enable/);
  assert.match(app, /data-web-push-disable/);
  assert.match(app, /data-web-push-test/);
  assert.match(app, /Sensitive notification text stays inside KaosGDD/);
});

test("service worker displays generic payload and opens the existing notifications route", () => {
  assert.match(worker, /addEventListener\("push"/);
  assert.match(worker, /showNotification/);
  assert.match(worker, /\/#\/notifications/);
  assert.match(worker, /clients\.matchAll/);
  assert.doesNotMatch(worker, /cache\.add|caches\.open/);
});

test("nginx exposes service worker scope and Web Push API", () => {
  assert.match(nginx, /location = \/sw\.js/);
  assert.match(nginx, /Service-Worker-Allowed "\/"/);
  assert.match(nginx, /location \^~ \/api\/web-push/);
});
