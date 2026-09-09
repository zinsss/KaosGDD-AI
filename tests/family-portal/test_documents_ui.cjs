const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const documentsViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/documents-view.js"), "utf8");
const memosViewSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/memos-view.js"), "utf8");
const indexSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/index.html"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("documents inbox rows open a local detail panel with status-only actions", () => {
  assert.match(documentsViewSource, /data-document-inbox-open/);
  assert.match(documentsViewSource, /data-document-inbox-detail/);
  assert.match(documentsViewSource, /data-document-inbox-refresh-status/);
  assert.match(documentsViewSource, /data-document-inbox-paperless/);
});

test("document upload selects the new inbox record after returning to inbox", () => {
  assert.match(appSource, /state\.documents\.selectedInboxId = String\(payload\.item\?\.id \|\| ""\);/);
});

test("documents metadata review previews before confirmed apply", () => {
  assert.match(appSource, /data-document-metadata-review/);
  assert.match(appSource, /function renderDocumentMetadataReview/);
  assert.match(documentsViewSource, /archiveMeta\("Tags", selected\.tags\?\.length/);
  assert.match(documentsViewSource, /renderDocumentMetadataReview\(\{ documentId: selected\.id, recordId: selectedReviewRecord\?\.id \|\| "", title: selected\.title, tags: selected\.tags \}\)/);
  assert.match(appSource, /metadata\/proposal/);
  assert.match(appSource, /data-document-ai-tags/);
  assert.match(appSource, /metadata\/tag-suggestions/);
  assert.match(appSource, /resetDocumentMetadataReview\("", state\.documents\.selected\.id, state\.documents\.selected\.title, state\.documents\.selected\.tags\);/);
  assert.match(documentsViewSource, /archiveMeta\("File", selected\.filename \|\| "unknown"\)/);
  assert.match(documentsViewSource, /archiveMeta\("Tags", selected\.tags\?\.length/);
  assert.match(documentsViewSource, /: "none"\)/);
  assert.match(appSource, /AI TAGS/);
  assert.match(appSource, /CONFIRM BEFORE APPLYING/);
  assert.match(appSource, /window\.confirm\(`Apply Paperless metadata/);
  assert.match(appSource, /metadata\/apply/);
  assert.match(appSource, /data-document-metadata-record/);
  assert.match(appSource, /JSON\.stringify\(\{ recordId, title, tags, confirmed: true \}\)/);
  assert.match(appSource, /state\.documents\.inboxItems = state\.documents\.inboxItems\.filter\(\(item\) => String\(item\.id\) !== recordId\);/);
  assert.match(appSource, /state\.documents\.inboxChecked = false;/);
  assert.match(appSource, /state\.documents\.mode = "archive";/);
  assert.match(appSource, /state\.documents\.selectedInboxId = "";/);
});

test("documents archive keeps inbox documents visible with review markers", () => {
  assert.match(documentsViewSource, /const inboxRecordByDocumentId = documents\.inboxItems\.reduce/);
  assert.match(documentsViewSource, /const reviewRecord = inboxRecordByDocumentId\.get\(String\(item\.id\)\);/);
  assert.match(documentsViewSource, /class="archiveReviewMarker"/);
  assert.match(documentsViewSource, /const selectedReviewRecord = selected \? inboxRecordByDocumentId\.get\(String\(selected\.id\)\) \|\| null : null;/);
  assert.match(documentsViewSource, /archiveMeta\("Inbox", selectedReviewRecord\.statusLabel \|\| "REVIEW"\)/);
  assert.match(documentsViewSource, /renderDocumentMetadataReview\(\{ documentId: selected\.id, recordId: selectedReviewRecord\?\.id \|\| "", title: selected\.title, tags: selected\.tags \}\)/);
  assert.match(styles, /\.archiveReviewMarker \{/);
});

test("documents archive loads inbox markers alongside the Paperless archive", () => {
  assert.match(appSource, /if \(route === "documents" && state\.documents\.mode !== "inbox"\) loadDocuments\(\);/);
  assert.match(appSource, /if \(route === "documents" && portalProfile\(\) === "main"\) \{[\s\S]*loadDocumentTags\(\);[\s\S]*loadDocumentInbox\(\);[\s\S]*\}/);
  assert.match(appSource, /if \(portalProfile\(\) === "main"\) void loadMainAttention\(\);/);
});

test("documents archive supports multiple selected tag filters", () => {
  assert.match(appSource, /async function loadDocumentTags/);
  assert.match(appSource, /fetch\("\/api\/paperless\/tags"/);
  assert.match(appSource, /\(state\.documents\.selectedTags \|\| \[\]\)\.forEach\(\(tag\) => params\.append\("tag", tag\)\);/);
  assert.match(documentsViewSource, /data-document-tag/);
  assert.match(appSource, /async function toggleDocumentTagFilter/);
  assert.match(documentsViewSource, /data-documents-clear-tags/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveTagFilters \{/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveTagChip \{/);
});

test("documents upload and metadata editor use aligned label columns", () => {
  assert.match(appSource, /<label class="archiveCommandLine">[\s\S]*<span>FILE<\/span>[\s\S]*<span>TITLE<\/span>/);
  assert.match(appSource, /<div class="archiveCommandLine">[\s\S]*<span>TITLE<\/span>[\s\S]*<span>TAGS<\/span>/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveCommandLine \{\n  display: grid;\n  grid-template-columns: 5\.25ch minmax\(0, 1fr\);/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveMetadataReview \{\n  display: grid;\n  gap: 8px;/);
});

test("archive command actions render as bracketed text while mode tabs stay boxed", () => {
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveAction::before,[\s\S]*content: "\[";/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveAction::after,[\s\S]*content: "\]";/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveAction,[\s\S]*border: 0;[\s\S]*background: transparent;/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveCommandActions \.archiveAction \{[\s\S]*border: 1px solid var\(--archive-line\);[\s\S]*background: rgba\(67, 76, 94, 0\.34\);/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveCommandActions \.archiveAction::before,[\s\S]*content: none;/);
});

test("desktop archive rows keep no date and title in separate lanes", () => {
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveRecordId \{[\s\S]*overflow: hidden;[\s\S]*text-overflow: ellipsis;[\s\S]*white-space: nowrap;/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveRecordDate \{[\s\S]*overflow: hidden;[\s\S]*text-overflow: ellipsis;[\s\S]*white-space: nowrap;/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveColumnHeader \{[\s\S]*grid-template-columns: 12ch 18ch minmax\(0, 1fr\) 48px;/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveColumnHeader span \{[\s\S]*font-size: 0\.68rem;/);
  assert.match(styles, /\.app\[data-profile="main"\] \[data-archive-kind="memos"\] \.archiveColumnHeader \{[\s\S]*grid-template-columns: 12ch 18ch minmax\(0, 1fr\);/);
  assert.match(styles, /\.app:is\(\[data-profile="main"\], \[data-profile="family"\]\[data-route="ai-tasks"\], \[data-profile="family"\]\[data-route="memos"\]\) \.archiveRecordButton \{[\s\S]*grid-template-columns: 12ch 18ch minmax\(0, 1fr\);/);
});

test("memos archive rendering is delegated to the view module", () => {
  assert.match(appSource, /KAOS_MEMOS_VIEW\.renderMemos\(memosViewContext\(\)\)/);
  assert.match(memosViewSource, /data-archive-kind="memos"/);
  assert.match(memosViewSource, /id="memosIndexTitle">RECORD BOARD/);
  assert.match(memosViewSource, /data-memo-open/);
  assert.match(memosViewSource, /data-memos-refresh/);
  assert.match(memosViewSource, /data-memos-clear/);
  assert.match(memosViewSource, /data-memo-detail/);
  assert.match(indexSource, /src="\/memos-view\.js\?v=2"/);
  assert.ok(indexSource.indexOf('src="/memos-view.js?v=2"') < indexSource.indexOf('src="/app.js?v=334"'));
});

test("documents archive rendering is delegated to the view module", () => {
  assert.match(appSource, /KAOS_DOCUMENTS_VIEW\.renderDocuments\(documentsViewContext\(\)\)/);
  assert.match(documentsViewSource, /data-archive-kind="documents"/);
  assert.match(documentsViewSource, /id="documentsIndexTitle">RECORD BOARD/);
  assert.match(documentsViewSource, /id="documentsInboxTitle">INBOX BOARD/);
  assert.match(documentsViewSource, /data-document-search/);
  assert.match(documentsViewSource, /data-paperless-open/);
  assert.match(documentsViewSource, /data-paperless-detail/);
  assert.match(indexSource, /src="\/documents-view\.js\?v=1"/);
  assert.ok(indexSource.indexOf('src="/documents-view.js?v=1"') < indexSource.indexOf('src="/app.js?v=334"'));
});
