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
