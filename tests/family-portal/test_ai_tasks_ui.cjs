const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
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
  assert.match(appSource, /data-ai-task-unified/);
  assert.match(appSource, /Prompt-only searches official sources\. Add PDF or open Details for URL\/source text\./);
  assert.match(appSource, /질문만 입력하면 공식\/의학 자료를 찾아 요약해요/);
  assert.match(appSource, /<details class="aiTaskSourceDetails">/);
  assert.match(appSource, /details: "DETAILS"/);
  assert.match(appSource, /details: "자료 추가"/);
  assert.match(stylesSource, /\.aiTaskSourceDetails summary/);
  assert.match(stylesSource, /content: "\[ "/);
  assert.match(stylesSource, /content: " \]"/);
  assert.match(appSource, /async function startUnifiedAiTask\(form\)/);
  assert.match(appSource, /\/api\/ai-tasks\/run/);
  assert.match(appSource, /scheduleAiTasksPoll\(1200\)/);
  assert.match(appSource, /AI TASK RUNNING/);
  assert.match(appSource, /AI TASK FAILED/);
  assert.match(appSource, /AI 작업 중/);
  assert.match(appSource, /AI 작업 실패/);
  assert.match(appSource, /renderAiTaskPlan\(sourceInfo\.plan\)/);
  assert.match(appSource, /renderAiTaskSources\(webResult\.sources\)/);
  assert.match(appSource, /function renderAiTaskTextbookSources\(sources\)/);
  assert.match(appSource, /TEXTBOOK BACKGROUND/);
  assert.match(appSource, /renderAiTaskTextbookSources\(webResult\.textbookSources\)/);
  assert.match(appSource, /renderAiTaskTextbookSources\(textbookSources\)/);
  assert.match(appSource, /function aiTaskIsOfficialWebPreview\(preview\)/);
  assert.match(appSource, /String\(sourceInfo\.type \|\| ""\) === "official_web_search"/);
  assert.match(appSource, /data-ai-task-general-web/);
  assert.match(appSource, /async function searchGeneralWebForAiTask\(\)/);
  assert.match(appSource, /\/api\/ai-tasks\/general-web\/preview/);
  assert.match(appSource, /GENERAL WEB CONTEXT/);
  assert.match(appSource, /Supplemental web context\. Verify important decisions against official sources\./);
  assert.match(appSource, /추가 웹 참고자료입니다\. 중요한 판단은 공식 자료로 다시 확인하세요\./);
  assert.match(appSource, /async function previewUnifiedAiTask\(form\)/);
  assert.match(appSource, /await startUnifiedAiTask\(form\)/);
  assert.match(appSource, /\/api\/ai-tasks\/web\/preview/);
  assert.match(appSource, /result: "RESULT"/);
  assert.match(appSource, /result: "결과"/);
  assert.match(appSource, /data-ai-task-open/);
  assert.match(appSource, /function openAiTaskArchive\(id\)/);
  assert.match(appSource, /aiTaskPreviewFromRecord\(selected\)/);
  assert.match(appSource, /data-ai-task-close/);
  assert.match(appSource, /function closeAiTaskArchive\(\)/);
  assert.match(appSource, /AI TASK ARCHIVE/);
  assert.match(appSource, /AI 기록/);
  assert.match(appSource, /SAVED/);
  assert.match(appSource, /data-ai-task-copy/);
  assert.match(appSource, /\/api\/ai-tasks\/official-doc-memo\/preview/);
  assert.match(appSource, /name="sourcePdf" type="file" accept="application\/pdf,\.pdf"/);
  assert.match(appSource, /const hasSourcePdf = sourcePdf instanceof File && sourcePdf\.size > 0;/);
  assert.match(appSource, /body: formData/);
  assert.match(appSource, /Save this AI draft to Memos/);
  assert.match(appSource, /이 AI 초안을 메모에 저장할까요/);
  assert.match(appSource, /await createMemo\(content\)/);
  assert.match(appSource, /\/api\/ai-tasks\/\$\{encodeURIComponent\(taskId\)\}\/complete/);
});

test("Family AI Tasks keeps its own light theme surface", () => {
  assert.match(stylesSource, /\.app\[data-profile="family"\]\[data-route="ai-tasks"\] \.archiveTerminal/);
  assert.match(stylesSource, /--archive-bg: #fffaff;/);
  assert.match(stylesSource, /font-family: inherit;/);
  assert.match(stylesSource, /grid-template-columns: repeat\(9, auto\);/);
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

test("AI Tasks API proxy allows long-running official-source searches", () => {
  assert.match(nginxSource, /location \^~ \/api\/ai-tasks\/ \{[\s\S]*proxy_read_timeout 180s;/);
  assert.match(nginxSource, /location \^~ \/api\/ai-tasks\/ \{[\s\S]*proxy_send_timeout 180s;/);
  assert.match(nginxSource, /location = \/api\/ai-tasks \{[\s\S]*proxy_read_timeout 180s;/);
});
