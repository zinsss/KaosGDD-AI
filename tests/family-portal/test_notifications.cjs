const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

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
  assert.match(indexSource, /href="\/styles\.css\?v=433"/);
  assert.match(fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8"), /\.notificationInbox\.kaosToday \{\s*gap: 4px;/);
  assert.match(viewSource, /payload\.plainText/);
  assert.match(viewSource, /class="kaosTodayText"/);
  assert.match(viewSource, /class="kaosTodayContent"/);
  assert.match(viewSource, /const countsLine = `Tasks \$\{taskCount\} \(GDDZiN \$\{gddzinCount\}, Family \$\{familyCount\}\) \/ Supplies \$\{supplyCount\}`/);
  assert.match(viewSource, /lines\.splice\(1, 0, countsLine\)/);
  assert.match(viewSource, /briefingTextWithCounters\(payload\.plainText, counters\)/);
  assert.match(viewSource, /data-thermal-print="today"[^>]*>Print<\/button>/);
  assert.doesNotMatch(viewSource, /class="kaosTodayCounters"/);
  assert.doesNotMatch(viewSource, /data-notification-ack=/);
  assert.match(indexSource, /src="\/notifications-view\.js\?v=10"/);
  assert.ok(indexSource.indexOf('src="/notifications-view.js?v=10"') < indexSource.indexOf('src="/app.js?v=406"'));
  assert.ok(viewSource.indexOf('class="kaosTodayContent"') < viewSource.indexOf('class="kaosTodayText"'));
  assert.ok(viewSource.indexOf('class="kaosTodayText"') < viewSource.indexOf('class="archiveCommand kaosTodayToolbar"'));
});

test("Today totals become the second line of the briefing text", () => {
  const context = { window: {} };
  vm.runInNewContext(viewSource, context);

  const rendered = context.window.KAOS_NOTIFICATIONS_VIEW.briefingTextWithCounters(
    "### 2026년 9월 30일 (수) 🌤️\n• 📅 장날\n\n<시간표>",
    { tasksReady: true, tasks: 3, gddzin: 2, family: 1, suppliesReady: true, supplies: 3 },
  );

  assert.equal(
    rendered,
    "### 2026년 9월 30일 (수) 🌤️\n"
      + "Tasks 3 (GDDZiN 2, Family 1) / Supplies 3\n"
      + "• 📅 장날\n\n<시간표>",
  );
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

test("Today retry refreshes the notification inbox as well as the briefing", () => {
  assert.match(
    appSource,
    /data-notifications-refresh[\s\S]*?Promise\.all\(\[\s*loadNotifications\(\{ force: true \}\),\s*loadTodayBriefing\(\{ force: true \}\)/,
  );
});
