const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const navSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/navigation.js"), "utf8");

test("main PWA exposes AI Tasks as a first-class read/confirm workflow", () => {
  assert.match(navSource, /route: "ai-tasks", label: "AI Tasks"/);
  assert.match(appSource, /"ai-tasks": "AI Tasks"/);
  assert.match(appSource, /else if \(route === "ai-tasks"\) view\.innerHTML = renderAiTasks\(\);/);
  assert.match(appSource, /if \(route === "ai-tasks"\) loadAiTasks\(\);/);
});

test("AI Tasks official document memo flow previews before saving to Memos", () => {
  assert.match(appSource, /data-ai-task-official-memo/);
  assert.match(appSource, /\/api\/ai-tasks\/official-doc-memo\/preview/);
  assert.match(appSource, /Save this AI draft to Memos/);
  assert.match(appSource, /await createMemo\(content\)/);
  assert.match(appSource, /\/api\/ai-tasks\/\$\{encodeURIComponent\(taskId\)\}\/complete/);
});

test("AI Tasks preview errors use actionable messages", () => {
  assert.match(appSource, /function aiTaskErrorMessage\(code\)/);
  assert.match(appSource, /ai_task_archive_write_failed: "AI draft was made, but Governor could not write the AI Task archive\."/);
  assert.match(appSource, /ai_task_source_fetch_failed: "Could not fetch the source URL\. Try a specific article page or paste the source text\."/);
  assert.match(appSource, /ai_task_source_not_found: "The source page says it does not exist\. Try a specific article page or paste the text\."/);
  assert.match(appSource, /error: aiTaskErrorMessage\(error\.message \|\| "ai_task_preview_failed"\)/);
});
