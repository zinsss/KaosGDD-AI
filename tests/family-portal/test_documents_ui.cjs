const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/app.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../apps/family-portal/styles.css"), "utf8");

test("documents inbox rows open a local detail panel with status-only actions", () => {
  assert.match(appSource, /data-document-inbox-open/);
  assert.match(appSource, /data-document-inbox-detail/);
  assert.match(appSource, /data-document-inbox-refresh-status/);
  assert.match(appSource, /data-document-inbox-paperless/);
});

test("document upload selects the new inbox record after returning to inbox", () => {
  assert.match(appSource, /state\.documents\.selectedInboxId = String\(payload\.item\?\.id \|\| ""\);/);
});

test("documents metadata review previews before confirmed apply", () => {
  assert.match(appSource, /data-document-metadata-review/);
  assert.match(appSource, /function renderDocumentMetadataReview/);
  assert.match(appSource, /archiveMeta\("Tags", selected\.tags\?\.length/);
  assert.match(appSource, /renderDocumentMetadataReview\(\{ documentId: selected\.id, title: selected\.title, tags: selected\.tags \}\)/);
  assert.match(appSource, /metadata\/proposal/);
  assert.match(appSource, /CONFIRM BEFORE APPLYING/);
  assert.match(appSource, /window\.confirm\(`Apply Paperless metadata/);
  assert.match(appSource, /metadata\/apply/);
  assert.match(appSource, /data-document-metadata-record/);
  assert.match(appSource, /JSON\.stringify\(\{ recordId, title, tags, confirmed: true \}\)/);
  assert.match(appSource, /state\.documents\.mode = "archive";/);
  assert.match(appSource, /state\.documents\.selectedInboxId = "";/);
});

test("documents upload and metadata editor use aligned label columns", () => {
  assert.match(appSource, /<label class="archiveCommandLine">[\s\S]*<span>FILE<\/span>[\s\S]*<span>TITLE<\/span>/);
  assert.match(appSource, /<div class="archiveCommandLine">[\s\S]*<span>TITLE<\/span>[\s\S]*<span>TAGS<\/span>/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveCommandLine \{\n  display: grid;\n  grid-template-columns: 5\.25ch minmax\(0, 1fr\);/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveMetadataReview \{\n  display: grid;\n  gap: 8px;/);
});

test("archive command actions render as bracketed text while mode tabs stay boxed", () => {
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveAction::before,[\s\S]*content: "\[";/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveAction::after,[\s\S]*content: "\]";/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveAction,[\s\S]*border: 0;[\s\S]*background: transparent;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveCommandActions \.archiveAction \{[\s\S]*border: 1px solid var\(--archive-line\);[\s\S]*background: rgba\(67, 76, 94, 0\.34\);/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveCommandActions \.archiveAction::before,[\s\S]*content: none;/);
});

test("desktop archive rows keep no date and title in separate lanes", () => {
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveRecordId \{[\s\S]*overflow: hidden;[\s\S]*text-overflow: ellipsis;[\s\S]*white-space: nowrap;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveRecordDate \{[\s\S]*overflow: hidden;[\s\S]*text-overflow: ellipsis;[\s\S]*white-space: nowrap;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveColumnHeader \{[\s\S]*grid-template-columns: 12ch 18ch minmax\(0, 1fr\) 48px;/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveColumnHeader span \{[\s\S]*font-size: 0\.68rem;/);
  assert.match(styles, /\.app\[data-profile="main"\] \[data-archive-kind="memos"\] \.archiveColumnHeader \{[\s\S]*grid-template-columns: 12ch 18ch minmax\(0, 1fr\);/);
  assert.match(styles, /\.app\[data-profile="main"\] \.archiveRecordButton \{[\s\S]*grid-template-columns: 12ch 18ch minmax\(0, 1fr\);/);
});
