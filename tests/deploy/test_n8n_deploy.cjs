const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");

const compose = fs.readFileSync("deploy/h3-backend/compose.n8n.yaml", "utf8");
const helper = fs.readFileSync("deploy/h3-backend/kaos-h3", "utf8");
const migrationPlan = fs.readFileSync(
  "docs/migration/n8n-workflow-migration-plan.md",
  "utf8",
);
const literaturePilot = JSON.parse(
  fs.readFileSync("deploy/h3-backend/n8n/workflows/medical-literature-pilot.json", "utf8"),
);

test("n8n and its supported PostgreSQL release are digest-pinned", () => {
  assert.match(compose, /image: postgres:17-alpine@sha256:[a-f0-9]{64}/);
  assert.match(compose, /image: n8nio\/n8n@sha256:[a-f0-9]{64}/);
  assert.doesNotMatch(compose, /image: (?:postgres|n8nio\/n8n):latest/);
});

test("n8n editor is private and its persistent paths are narrow", () => {
  assert.match(compose, /N8N_BIND_ADDRESS:-127\.0\.0\.1}:5678:5678/);
  assert.match(compose, /data\/n8n:\/home\/node\/\.n8n/);
  assert.match(compose, /data\/n8n-postgres:\/var\/lib\/postgresql\/data/);
  assert.doesNotMatch(compose, /docker\.sock/);
  assert.doesNotMatch(compose, /- \/srv:\/|\$\{KAOS_ROOT[^\n]*:\/srv/);
});

test("dangerous local execution nodes and unreviewed packages stay disabled", () => {
  assert.match(compose, /N8N_PUBLIC_API_DISABLED: "true"/);
  assert.match(compose, /N8N_COMMUNITY_PACKAGES_ENABLED: "false"/);
  assert.match(compose, /N8N_UNVERIFIED_PACKAGES_ENABLED: "false"/);
  assert.match(compose, /n8n-nodes-base\.executeCommand/);
  assert.match(compose, /n8n-nodes-base\.readWriteFile/);
  assert.match(compose, /n8n-nodes-base\.localFileTrigger/);
});

test("H3 helper owns a separate n8n lifecycle", () => {
  for (const command of [
    "n8n-setup",
    "n8n-preflight",
    "n8n-up",
    "n8n-down",
    "n8n-status",
    "n8n-logs",
  ]) {
    assert.match(helper, new RegExp(`${command.replace("-", "\\-")}\\)`));
  }
});

test("migration plan preserves Governor authority and one workflow owner", () => {
  assert.match(migrationPlan, /KaosGovernor remains the authority/);
  assert.match(migrationPlan, /first active n8n schedule/);
  assert.match(migrationPlan, /owns no KaosGDD domain\s+> state and sends no notifications/);
  assert.match(migrationPlan, /no duplicate scheduler or poller should be enabled/);
  assert.match(migrationPlan, /Stop the native owner before activating the n8n owner/);
  assert.match(migrationPlan, /System updates, reboot, shell scripts \| Do not migrate/);
});

test("first n8n pilot is manual, inactive, credential-free, and read-only", () => {
  assert.equal(literaturePilot.id, "KaosMedLitPilotV1");
  assert.equal(literaturePilot.active, false);
  assert.deepEqual(literaturePilot.tags, []);
  assert.ok(literaturePilot.nodes.some((node) => node.type === "n8n-nodes-base.manualTrigger"));
  assert.ok(literaturePilot.nodes.some((node) => node.type === "n8n-nodes-base.httpRequest"));
  assert.ok(literaturePilot.nodes.every((node) => !node.credentials));
  assert.ok(literaturePilot.nodes.every((node) => node.type !== "n8n-nodes-base.webhook"));
  assert.ok(literaturePilot.nodes.every((node) => node.type !== "n8n-nodes-base.scheduleTrigger"));
  assert.ok(literaturePilot.nodes.every((node) => node.type !== "n8n-nodes-base.executeCommand"));
  const request = literaturePilot.nodes.find((node) => node.name === "Search Europe PMC");
  assert.equal(request.parameters.url, "https://www.ebi.ac.uk/europepmc/webservices/rest/search");
  assert.equal(request.parameters.options.timeout, 15000);
  const code = literaturePilot.nodes
    .filter((node) => node.type === "n8n-nodes-base.code")
    .map((node) => node.parameters.jsCode)
    .join("\n");
  assert.doesNotMatch(code, /process\.env|\$env|\$vars|fetch\s*\(/);
  assert.match(code, /const pageSize = 5/);
  assert.match(code, /query\.length > 500/);
  assert.match(code, /records\.slice\(0, request\.pageSize\)/);
  assert.match(code, /cleanText\(record\.abstractText, 4000\)/);
  assert.match(migrationPlan, /first inactive, manual,\s*> read-only literature-search pilot/);
});
