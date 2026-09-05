const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");

const composeServices = fs.readFileSync("deploy/h3-backend/compose.services.yaml", "utf8");
const envExample = fs.readFileSync("deploy/h3-backend/.env.example", "utf8");

test("governor-api receives the Paperless default owner setting", () => {
  const governorBlock = composeServices.match(/  governor-api:\n[\s\S]*?    secrets:\n/);

  assert.ok(governorBlock, "governor-api block should exist in compose.services.yaml");
  assert.match(
    governorBlock[0],
    /PAPERLESS_DEFAULT_OWNER_ID:\s*"\$\{PAPERLESS_DEFAULT_OWNER_ID:-\}"/,
  );
});

test("H3 env template documents the Paperless default owner setting", () => {
  assert.match(envExample, /^PAPERLESS_DEFAULT_OWNER_ID=$/m);
});

test("governor-api can read local medical textbook indexes for AI Tasks", () => {
  const governorBlock = composeServices.match(/  governor-api:\n[\s\S]*?    entrypoint:/);

  assert.ok(governorBlock, "governor-api block should exist in compose.services.yaml");
  assert.match(governorBlock[0], /AI_TASK_TEXTBOOK_SEARCH_ENABLED:\s*"\$\{AI_TASK_TEXTBOOK_SEARCH_ENABLED:-true\}"/);
  assert.match(governorBlock[0], /AI_TASK_TEXTBOOK_INDEX_PATH:\s*"\$\{AI_TASK_TEXTBOOK_INDEX_PATH:-\/data\/textbooks\/harrison\/index\/harrison22\.index\.sqlite\}"/);
  assert.match(governorBlock[0], /\$\{KAOS_ROOT:-\/srv\/kaos\}\/reference\/textbooks:\/data\/textbooks:ro/);
});

test("H3 env template documents the AI Task textbook override knobs", () => {
  assert.match(envExample, /^AI_TASK_TEXTBOOK_SEARCH_ENABLED=true$/m);
  assert.match(envExample, /^AI_TASK_TEXTBOOK_INDEX_PATH=\/data\/textbooks\/harrison\/index\/harrison22\.index\.sqlite$/m);
});
