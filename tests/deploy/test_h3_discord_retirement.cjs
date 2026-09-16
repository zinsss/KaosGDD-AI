const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");

const compose = fs.readFileSync("deploy/h3-backend/compose.yaml", "utf8");
const servicesCompose = fs.readFileSync(
  "deploy/h3-backend/compose.services.yaml",
  "utf8",
);
const helper = fs.readFileSync("deploy/h3-backend/kaos-h3", "utf8");
const collector = fs.readFileSync(
  "apps/governor/src/kaos_governor/maintenance_collector.py",
  "utf8",
);
const worker = fs.readFileSync(
  "apps/governor/src/kaos_governor/worker.py",
  "utf8",
);
const serviceUnit = fs.readFileSync(
  "deploy/h3-backend/kaos-h3-maintenance-report.service",
  "utf8",
);
const timerUnit = fs.readFileSync(
  "deploy/h3-backend/kaos-h3-maintenance-report.timer",
  "utf8",
);
const workflow = fs.readFileSync(".github/workflows/test.yaml", "utf8");

test("H3 runtime defines only transport-neutral Governor services", () => {
  assert.doesNotMatch(compose, /governor-discord:/);
  assert.doesNotMatch(compose, /discord_bot_token/);
  assert.doesNotMatch(compose, /integrations\/discoord\/Dockerfile/);
  assert.match(compose, /governor-worker:/);
  assert.match(compose, /governor-tools:/);
  assert.match(compose, /\/data\/notifications\/maintenance-report\.json/);
  assert.match(compose, /secrets\/governor-runtime\.env/);
});

test("H3 up stops the retired bot and cannot build or start it", () => {
  assert.match(helper, /docker update --restart=no kaos-governor-discord/);
  assert.match(helper, /docker stop --time 30 kaos-governor-discord/);
  assert.doesNotMatch(helper, /build governor-discord/);
  assert.doesNotMatch(helper, /up --detach[^\n]*governor-discord/);
  assert.match(helper, /build governor-worker governor-tools/);
  assert.match(helper, /up --detach[^\n]*governor-worker/);
  assert.match(helper, /up --detach[^\n]*governor-tools/);
  assert.ok(
    helper.indexOf('build governor-worker governor-tools') <
      helper.indexOf('retire_discord_runtime', helper.indexOf('up_runtime()')),
    "successor images must build before the existing bot is stopped",
  );
});

test("retired token is quarantined without being read or overwritten", () => {
  assert.match(helper, /retired-secrets\/h3-governor-discord/);
  assert.match(helper, /retired Discord token collision/);
  assert.match(helper, /install -d -m 0700/);
  assert.match(helper, /mv -- "\$\{source\}" "\$\{target\}"/);
  assert.doesNotMatch(helper, /cat[^\n]*discord_bot_token/);
});

test("maintenance collection is host scheduled and Discord independent", () => {
  assert.doesNotMatch(collector, /kaosdiscoord|discord\.py/);
  assert.match(helper, /maintenance_collector\.py/);
  assert.match(helper, /sudo systemctl enable --now kaos-h3-maintenance-report\.timer/);
  assert.doesNotMatch(helper, /systemctl --user/);
  assert.match(serviceUnit, /User=__KAOS_DEPLOY_USER__/);
  assert.match(serviceUnit, /ExecStart=\/srv\/projects\/KaosGDD-AI\/deploy\/h3-backend\/kaos-h3 maintenance-report/);
  assert.match(timerUnit, /OnBootSec=2min/);
  assert.match(timerUnit, /OnCalendar=\*-\*-\* 05:00:00 Asia\/Seoul/);
  assert.match(timerUnit, /Persistent=true/);
});

test("neutral API and CI images no longer build the Discord adapter", () => {
  assert.match(servicesCompose, /governor-api:[\s\S]*dockerfile: apps\/governor\/Dockerfile/);
  assert.doesNotMatch(servicesCompose, /integrations\/discoord\/Dockerfile/);
  assert.doesNotMatch(workflow, /discord_bot_token|governor-discord:test|integrations\/discoord\/Dockerfile/);
  assert.match(workflow, /apps\/governor\/Dockerfile/);
  assert.match(workflow, /\.\/deploy\/h3-backend\/kaos-h3 config >\/dev\/null/);
});

test("worker records a digest as sent instead of queuing Discord publication", () => {
  assert.match(worker, /service\.record_sent\(current\.date\(\)\)/);
  assert.doesNotMatch(worker, /service\.record_scheduled\(current\.date\(\), content\)/);
  assert.match(worker, /retire_pending_publications/);
});
