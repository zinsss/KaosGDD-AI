const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const aiTasksViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/ai-tasks-view.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const navSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/navigation.js"), "utf8");
const stylesSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");
const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

test("main PWA exposes AI Tasks as a first-class read/confirm workflow", () => {
  assert.match(navSource, /route: "ai-tasks", label: "AI Tasks"/);
  assert.match(appSource, /"ai-tasks": "AI Tasks"/);
  assert.match(appSource, /else if \(route === "ai-tasks"\) view\.innerHTML = renderAiTasks\(\);/);
  assert.match(appSource, /if \(route === "ai-tasks"\) loadAiTasks\(\);/);
});

test("AI Tasks official document memo flow previews before saving to Memos", () => {
  assert.match(appSource, /function aiTaskViewContext\(\)/);
  assert.match(appSource, /KAOS_AI_TASKS_VIEW\.renderAiTasks\(aiTaskViewContext\(\)\)/);
  assert.match(aiTasksViewSource, /data-ai-task-unified/);
  assert.doesNotMatch(aiTasksViewSource, /Prompt-only searches official sources\. Add PDF or open Details for URL\/source text\./);
  assert.doesNotMatch(aiTasksViewSource, /질문만 입력하면 공식\/의학 자료를 찾아 요약해요/);
  const composer = aiTasksViewSource.match(/<form class="archiveIndex aiTaskComposer"[\s\S]*?<\/form>/)?.[0] || "";
  assert.doesNotMatch(composer, /archiveIndexHeader|data-ai-tasks-refresh/);
  assert.match(composer, /type="submit"[\s\S]*data-ai-task-clear/);
  assert.match(aiTasksViewSource, /<details class="aiTaskSourceDetails">/);
  assert.match(aiTasksViewSource, /details: "DETAILS"/);
  assert.match(aiTasksViewSource, /details: "자료 추가"/);
  assert.match(stylesSource, /\.aiTaskSourceDetails summary/);
  assert.match(stylesSource, /content: "\["/);
  assert.match(stylesSource, /content: "\]"/);
  assert.match(appSource, /async function startUnifiedAiTask\(form\)/);
  assert.match(appSource, /\/api\/ai-tasks\/run/);
  assert.match(appSource, /scheduleAiTasksPoll\(1200\)/);
  assert.match(aiTasksViewSource, /AI TASK RUNNING/);
  assert.match(aiTasksViewSource, /AI TASK FAILED/);
  assert.match(aiTasksViewSource, /AI 작업 중/);
  assert.match(aiTasksViewSource, /AI 작업 실패/);
  assert.match(aiTasksViewSource, /renderAiTaskPlan\(deps, sourceInfo\.plan\)/);
  assert.match(aiTasksViewSource, /renderAiTaskSources\(deps, webResult\.sources\)/);
  assert.match(appSource, /function renderAiTaskTextbookSources\(sources\)/);
  assert.match(aiTasksViewSource, /TEXTBOOK BACKGROUND/);
  assert.match(aiTasksViewSource, /renderAiTaskTextbookSources\(deps, webResult\.textbookSources\)/);
  assert.match(aiTasksViewSource, /renderAiTaskTextbookSources\(deps, textbookSources\)/);
  assert.match(appSource, /function aiTaskIsOfficialWebPreview\(preview\)/);
  assert.match(appSource, /String\(sourceInfo\.type \|\| ""\) === "official_web_search"/);
  assert.match(appSource, /data-ai-task-general-web/);
  assert.match(appSource, /async function searchGeneralWebForAiTask\(\)/);
  assert.match(appSource, /\/api\/ai-tasks\/general-web\/preview/);
  assert.match(aiTasksViewSource, /GENERAL WEB CONTEXT/);
  assert.match(aiTasksViewSource, /Supplemental web context\. Verify important decisions against official sources\./);
  assert.match(aiTasksViewSource, /추가 웹 참고자료입니다\. 중요한 판단은 공식 자료로 다시 확인하세요\./);
  assert.match(appSource, /async function previewUnifiedAiTask\(form\)/);
  assert.match(appSource, /await startUnifiedAiTask\(form\)/);
  assert.match(appSource, /\/api\/ai-tasks\/web\/preview/);
  assert.match(aiTasksViewSource, /result: "RESULT"/);
  assert.match(aiTasksViewSource, /result: "결과"/);
  assert.match(aiTasksViewSource, /data-ai-task-open/);
  assert.match(appSource, /function openAiTaskArchive\(id\)/);
  assert.match(appSource, /aiTaskPreviewFromRecord\(selected\)/);
  assert.match(aiTasksViewSource, /data-ai-task-close/);
  assert.match(appSource, /function closeAiTaskArchive\(\)/);
  assert.match(aiTasksViewSource, /AI TASK ARCHIVE/);
  assert.match(aiTasksViewSource, /AI 기록/);
  assert.match(aiTasksViewSource, /SAVED/);
  assert.match(aiTasksViewSource, /data-ai-task-copy/);
  assert.match(appSource, /\/api\/ai-tasks\/official-doc-memo\/preview/);
  assert.match(aiTasksViewSource, /name="sourcePdf" type="file" accept="application\/pdf,\.pdf"/);
  assert.match(aiTasksViewSource, /name="sourcePdf"[^>]*data-app-file/);
  assert.match(aiTasksViewSource, /class="appFileControl"/);
  assert.match(appSource, /const hasSourcePdf = sourcePdf instanceof File && sourcePdf\.size > 0;/);
  assert.match(appSource, /body: formData/);
  assert.match(appSource, /Save this AI draft to Memos/);
  assert.match(appSource, /이 AI 초안을 메모에 저장할까요/);
  assert.match(appSource, /await createMemo\(content\)/);
  assert.match(appSource, /\/api\/ai-tasks\/\$\{encodeURIComponent\(taskId\)\}\/complete/);
  assert.match(aiTasksViewSource, /data-ai-task-delete/);
  assert.match(appSource, /async function deleteAiTaskArchive\(\)/);
  assert.match(appSource, /method: "DELETE"/);
  assert.match(appSource, /\/api\/ai-tasks\/\$\{encodeURIComponent\(taskId\)\}/);
  assert.match(appSource, /이 AI 기록을 삭제할까요\?/);
  assert.match(indexSource, /src="\/ai-tasks-view\.js\?v=5"/);
  assert.ok(indexSource.indexOf('src="/ai-tasks-view.js?v=5"') < indexSource.indexOf('src="/app.js?v=378"'));
});

test("Family AI Tasks keeps its own light theme surface", () => {
  assert.match(stylesSource, /\.app\[data-profile="family"\]:is\(\[data-route="ai-tasks"\], \[data-route="memos"\]\) \.archiveTerminal/);
  assert.match(stylesSource, /--archive-bg: #fffaff;/);
  assert.match(stylesSource, /font-family: inherit;/);
  assert.match(stylesSource, /grid-template-columns: repeat\(9, auto\);/);
});

test("AI Task detail keeps its title and actions on separate single rows", () => {
  assert.match(stylesSource, /\.aiTaskPreview > \.archiveDetailHeader \{[\s\S]*grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(stylesSource, /\.aiTaskPreview > \.archiveDetailHeader h3 \{[\s\S]*text-overflow: ellipsis;[\s\S]*white-space: nowrap;/);
  assert.match(stylesSource, /\.aiTaskPreview > \.archiveDetailHeader > \.archiveActions \{[\s\S]*flex-wrap: nowrap;[\s\S]*overflow-x: auto;/);
});

test("AI Task archive dates reach the right edge", () => {
  assert.match(stylesSource, /\[data-archive-kind="ai-tasks"\] \.archiveRecord \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\);/);
  assert.ok(
    stylesSource.lastIndexOf('[data-archive-kind="ai-tasks"] .archiveRecord')
      > stylesSource.lastIndexOf("grid-template-columns: minmax(0, 1fr) 48px"),
  );
});

test("AI Tasks preview errors use actionable messages", () => {
  assert.match(appSource, /function aiTaskErrorMessage\(code\)/);
  assert.match(appSource, /kaosbrain_web_search_not_configured: "KaosBrain web search is not configured\."/);
  assert.match(appSource, /kaosbrain_web_search_unavailable: "KaosBrain OpenClaw web search is unavailable\."/);
  assert.match(appSource, /web_task_openai_rate_limited: "OpenAI web search is rate-limited right now\."/);
  assert.match(appSource, /ai_task_archive_write_failed: "AI draft was made, but Governor could not write the AI Task archive\."/);
  assert.match(appSource, /ai_task_source_fetch_failed: "Could not fetch the source URL\. Try a specific article page or paste the source text\."/);
  assert.match(appSource, /ai_task_source_not_found: "The source page says it does not exist\. Try a specific article page or paste the text\."/);
  assert.match(appSource, /ai_task_pdf_text_empty: "Could not read text from that PDF\. If it is scanned, use Paperless OCR first or paste the text\."/);
  assert.match(appSource, /error: aiTaskErrorMessage\(aiTaskErrorCode\(error, "ai_task_preview_failed"\)\)/);
});

test("personal AI Tasks offers in-memory OpenClaw device authorization recovery", () => {
  assert.match(appSource, /String\(preview\?\.error \|\| ""\) === "kaosbrain_openai_auth_required"/);
  assert.match(aiTasksViewSource, /deps\.portalProfile\(\) === "main"/);
  assert.match(aiTasksViewSource, /data-openclaw-auth-start/);
  assert.match(aiTasksViewSource, /data-openclaw-auth-retry/);
  assert.match(aiTasksViewSource, /OPEN DEVICE PAGE/);
  assert.match(appSource, /\/api\/ai-tasks\/openclaw-auth\/\$\{action\}/);
  assert.match(appSource, /scheduleOpenClawAuthPoll/);
  assert.match(appSource, /if \(getRoute\(\) !== "ai-tasks"\) cancelOpenClawAuthFlow\(\{ clearState: true \}\)/);
  assert.match(appSource, /openclawAuthFlowGeneration/);
  assert.equal(
    (appSource.match(/const auth = await requestOpenClawAuth\("(?:start|status)"\);\s*if \(!openclawAuthFlowIsCurrent\(generation\)\) return;/g) || []).length,
    2,
  );
  assert.match(appSource, /new Set\(\["web", "general_web"\]\)\.has\(kind\)/);
  assert.match(appSource, /OPENCLAW_AUTH_PENDING_STATUSES/);
  assert.match(appSource, /candidate\.hostname === "auth\.openai\.com"/);
  assert.match(appSource, /!candidate\.username/);
  assert.match(appSource, /!candidate\.password/);
  assert.match(appSource, /candidate\.port === "443"/);
  assert.match(appSource, /!candidate\.hash/);
  assert.match(appSource, /\["\/codex\/device", "\/oauth\/authorize"\]/);
  assert.doesNotMatch(appSource, /localStorage[^\n]*openclaw/i);
  assert.doesNotMatch(appSource, /console\.[a-z]+\([^\n]*userCode/i);
  assert.match(stylesSource, /\.app\[data-profile="main"\]\[data-route="ai-tasks"\] \.openclawAuthCard/);
});

test("OpenClaw recovery card renders only for the exact personal auth-required error", () => {
  const context = { window: {}, URL };
  vm.runInNewContext(aiTasksViewSource, context);
  const view = context.window.KAOS_AI_TASKS_VIEW;
  const deps = {
    state: { aiTasks: { deleting: false, openclawAuth: { status: "idle" } } },
    portalProfile: () => "main",
    escapeHtml: (value) => String(value ?? ""),
    archiveMeta: () => "",
    aiTaskIsOfficialWebPreview: () => false,
    aiTaskErrorMessage: (value) => String(value || ""),
  };
  const exact = view.renderAiTaskStatePanel(deps, {
    kind: "web",
    status: "failed",
    error: "kaosbrain_openai_auth_required",
    source: {},
    result: {},
  });
  assert.match(exact, /class="openclawAuthCard"/);

  const other = view.renderAiTaskStatePanel(deps, {
    kind: "web",
    status: "failed",
    error: "kaosbrain_ai_task_unauthorized",
    source: {},
    result: {},
  });
  assert.doesNotMatch(other, /class="openclawAuthCard"/);

  const family = view.renderAiTaskStatePanel({ ...deps, portalProfile: () => "family" }, {
    kind: "web",
    status: "failed",
    error: "kaosbrain_openai_auth_required",
    source: {},
    result: {},
  });
  assert.doesNotMatch(family, /class="openclawAuthCard"/);

  deps.state.aiTasks.openclawAuth = { status: "succeeded" };
  const sourceTask = view.renderAiTaskStatePanel(deps, {
    kind: "official_doc_memo",
    status: "failed",
    error: "kaosbrain_openai_auth_required",
    source: { type: "pdf", filename: "source.pdf" },
    result: {},
  });
  assert.match(sourceTask, /attach or paste its source/);
  assert.doesNotMatch(sourceTask, /data-openclaw-auth-retry/);
});

test("AI Tasks API proxy allows long-running official-source searches", () => {
  assert.match(nginxSource, /location \^~ \/api\/ai-tasks\/ \{[\s\S]*proxy_read_timeout 180s;/);
  assert.match(nginxSource, /location \^~ \/api\/ai-tasks\/ \{[\s\S]*proxy_send_timeout 180s;/);
  assert.match(nginxSource, /location = \/api\/ai-tasks \{[\s\S]*proxy_read_timeout 180s;/);
});
