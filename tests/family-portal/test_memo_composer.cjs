const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const memosViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/memos-view.js"), "utf8");
const stylesSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("top add opens the native one-box memo composer", () => {
  assert.match(appSource, /if \(action === "memo"\) \{\s*window\.location\.hash = "#\/add-memo";/s);
  assert.match(appSource, /<form class="panel memoComposerPanel" data-create-memo>/);
  assert.match(appSource, /<textarea[\s\S]*name="content"[\s\S]*data-memo-content/);
  assert.doesNotMatch(appSource, /action: "memo", label: "Memo", note: "Later"/);
});

test("memo composer uploads arbitrary files and links them to a private memo", () => {
  assert.match(appSource, /fetch\("\/api\/memos\/api\/v1\/memos"/);
  assert.match(appSource, /fetch\("\/api\/memos\/attachments\/upload"/);
  assert.match(appSource, /JSON\.stringify\(\{ content: normalized, visibility: "PRIVATE", attachments: attachmentReferences \}\)/);
  assert.match(appSource, /name="files" type="file" multiple data-app-file data-memo-files/);
  assert.match(appSource, /class="appFileChoose">파일 선택<\/span>/);
  assert.match(appSource, /data-app-file-selection>선택한 파일 없음<\/span>/);
  assert.match(appSource, /files\.length === 1[\s\S]*files\[0\]\.name[\s\S]*개 파일 선택됨/);
  assert.match(stylesSource, /\.appFileControl \{[\s\S]*font-family: inherit !important;/);
  assert.match(stylesSource, /\.appFileControl input\[type="file"\] \{[\s\S]*opacity: 0;/);
  assert.match(appSource, /memo_content_or_attachment_required/);
  assert.match(appSource, /cleanupMemoAttachments/);
});

test("memo details preview, download, add, and remove attachments", () => {
  assert.match(appSource, /function normalizeMemoAttachment/);
  assert.match(appSource, /function memoAttachmentUrl/);
  assert.match(appSource, /updateMask=content,attachments/);
  assert.match(memosViewSource, /class="memoAttachments"/);
  assert.match(memosViewSource, /data-memo-edit-attachment-remove/);
  assert.match(memosViewSource, /download="\$\{deps\.escapeHtml\(filename\)\}"/);
  assert.match(stylesSource, /\.memoAttachmentList \{/);
});

test("main and family memos routes render native archive board controls", () => {
  assert.match(memosViewSource, /data-archive-kind="memos"/);
  assert.match(memosViewSource, /data-memo-search/);
  assert.match(memosViewSource, /data-memos-refresh/);
  assert.match(memosViewSource, /data-memos-refresh[^>]*>Reload<\/button>/);
  assert.doesNotMatch(memosViewSource, /data-memos-refresh[^>]*>↻<\/button>/);
  assert.match(memosViewSource, /href="#\/add-memo">New<\/a>/);
  assert.match(memosViewSource, /data-memos-toolbar="search"[^>]*>Search<\/button>/);
  assert.match(memosViewSource, /data-memos-toolbar="tags"[^>]*>Tags<\/button>/);
  assert.match(memosViewSource, /class="archiveSearchBox memoToolbarPanel"/);
  assert.match(memosViewSource, /class="archiveTagFilters memoToolbarPanel"/);
  assert.match(memosViewSource, /data-memo-tag=/);
  assert.match(appSource, /class="openButton memoHeaderCancel" href="#\/memos">Cancel<\/a>/);
  assert.match(stylesSource, /\.memoHeaderCancel \{[\s\S]*font-size: 0\.78rem;[\s\S]*font-weight: 500;[\s\S]*line-height: 1;/);
  assert.match(stylesSource, /\.memoHeaderCancel::before \{\s*content: "\[";/);
  assert.match(stylesSource, /\.memoHeaderCancel::after \{\s*content: "\]";/);
  assert.doesNotMatch(stylesSource, /\.archiveTopAction \{[^}]*font-family:/);
  assert.match(appSource, /memoToolbarToggle\.dataset\.memosToolbar/);
  assert.match(appSource, /state\.memos\.appliedQuery === tagQuery \? "" : tagQuery/);
  assert.match(stylesSource, /\.memoArchiveCommands \{[\s\S]*display: flex;[\s\S]*gap: 0;/);
  assert.match(stylesSource, /\[data-archive-kind="memos"\] \.memoArchiveCommands \{[\s\S]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\);/);
  assert.match(stylesSource, /\[data-archive-kind="memos"\] \.memoArchiveToolbar \{[\s\S]*border: 0;[\s\S]*background: transparent;[\s\S]*box-shadow: none;/);
  assert.match(stylesSource, /\.memoArchiveCommands \.archiveTopAction\.isActive \{[\s\S]*background: var\(--main-tab-active-bg\);/);
  assert.match(stylesSource, /\.archiveTopAction\.isActive:hover,[\s\S]*\.archiveTopAction\.isActive:focus-visible \{[\s\S]*color: var\(--main-tab-active-text\);/);
  assert.match(stylesSource, /\.memoArchiveCommands \.archiveTopAction::before,[\s\S]*\.memoArchiveCommands \.archiveTopAction::after \{\s*content: none;/);
  assert.match(stylesSource, /\.memoArchiveToolbar > \.archiveTagFilters,[\s\S]*\.documentToolbarPanel > \.archiveTagFilters \{[\s\S]*gap: 10px;[\s\S]*padding: 6px 2px 10px;/);
  assert.doesNotMatch(stylesSource, /\[data-archive-kind="memos"\] \.memoToolbarPanel \.archiveTagChip \{/);
  assert.match(stylesSource, /\.archiveTagChip \{[\s\S]*background: rgba\(67, 76, 94, 0\.34\);/);
  assert.match(memosViewSource, /data-memo-open/);
  assert.match(appSource, /if \(route === "memos"\) loadMemos\(\);/);
  assert.doesNotMatch(appSource, /portalProfile\(\) === "family"[\s\S]*memosFrame/);
});

test("family memos receive the shared archive layout and light family theme", () => {
  assert.match(
    stylesSource,
    /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveTerminal/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]:is\(\[data-route="ai-tasks"\], \[data-route="memos"\]\) \.archiveTerminal/,
  );
  assert.match(stylesSource, /--archive-bg: #fffaff;/);
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="memos"\] \[data-archive-kind="memos"\] \.archiveSearchBar \{\n  border-color: transparent;\n  border-radius: 0;\n  background: transparent;/,
  );
});

test("family portal proxies native memos api to governor", () => {
  const nginxSource = fs.readFileSync(path.join(__dirname, "../../deploy/h3-backend/family-portal/nginx.conf"), "utf8");

  assert.match(nginxSource, /location \^~ \/api\/memos\/ \{/);
  assert.match(nginxSource, /location \^~ \/api\/memos\/ \{[\s\S]*client_max_body_size 21m;/);
  assert.match(nginxSource, /set \$governor_api http:\/\/governor-api:8096;/);
  assert.match(nginxSource, /location \^~ \/api\/memos\/ \{[\s\S]*proxy_pass \$governor_api;/);
});
