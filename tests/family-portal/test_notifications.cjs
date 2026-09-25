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
  assert.match(viewSource, /aria-label="KaosGDD Today"/);
  assert.match(viewSource, /class="archiveCommand kaosTodayToolbar"/);
  assert.match(viewSource, /data-notifications-refresh[^>]*>Reload<\/button>/);
  assert.match(indexSource, /href="\/styles\.css\?v=422"/);
  assert.match(fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8"), /\.notificationInbox\.kaosToday \{\s*gap: 4px;/);
  assert.match(viewSource, /payload\.plainText/);
  assert.match(viewSource, /class="kaosTodayText"/);
  assert.match(viewSource, /class="kaosTodayCounters"/);
  assert.match(viewSource, /Tasks <strong>\$\{taskCount\}<\/strong> \(GDDZiN/);
  assert.match(viewSource, /Supplies <strong>\$\{supplyCount\}<\/strong>/);
  assert.doesNotMatch(viewSource, /data-notification-ack=/);
  assert.match(indexSource, /src="\/notifications-view\.js\?v=8"/);
  assert.ok(indexSource.indexOf('src="/notifications-view.js?v=8"') < indexSource.indexOf('src="/app.js?v=391"'));
  assert.ok(viewSource.indexOf('class="kaosTodayText"') < viewSource.indexOf('class="archiveCommand kaosTodayToolbar"'));
});

test("main Today is a selectable briefing route while Agenda remains the default page", () => {
  assert.match(appSource, /today: "Today",\s*agenda: "Agenda"/);
  assert.match(appSource, /label: "KaosGDD",\s*defaultRoute: "agenda"/);
  assert.match(appSource, /route === "notifications"\) return "today"/);
  assert.match(appSource, /route === "today"\) view\.innerHTML = portalProfile\(\) === "main" \? renderNotifications\(\) : renderFamilyAgenda\(\)/);
  assert.match(appSource, /route === "agenda"\) view\.innerHTML = renderMainAgenda\(\)/);
  assert.match(appSource, /window\.location\.hash = "#\/today"/);
  assert.match(appSource, /function todayCounters\(\)/);
  assert.match(appSource, /taskMatchesMode\(task, "active"\)/);
  assert.match(appSource, /byOwner\.zin \|\| 0/);
  assert.match(appSource, /byOwner\.family \|\| 0/);
  assert.match(appSource, /month: "short",\s*day: "numeric",\s*year: "numeric",\s*hour: "2-digit",\s*minute: "2-digit",\s*hourCycle: "h23"/);
});

test("viewing KaosToday acknowledges only notification rows included in its briefing", () => {
  assert.match(appSource, /fetch\(`\/api\/notifications\/\$\{encodeURIComponent\(id\)\}\/acknowledge`/);
  assert.match(appSource, /method: "POST"/);
  assert.match(appSource, /item\?\.source === "notification"/);
  assert.match(appSource, /!item\.acknowledged/);
  assert.match(nginxSource, /location \^~ \/api\/notifications/);
  assert.match(nginxSource, /location = \/api\/today/);
});
