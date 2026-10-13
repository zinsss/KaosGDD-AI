const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const portalRoot = path.join(__dirname, "../../apps/family-portal");
const appSource = fs.readFileSync(path.join(portalRoot, "app.js"), "utf8");
const indexSource = fs.readFileSync(path.join(portalRoot, "index.html"), "utf8");
const stylesSource = fs.readFileSync(path.join(portalRoot, "styles.css"), "utf8");
const translationsSource = fs.readFileSync(path.join(portalRoot, "translations.js"), "utf8");

test("editable ledger entries expose a clear Korean edit action on mobile and desktop", () => {
  assert.match(appSource, /entry\.locked[\s\S]*ledgerLockedAction[\s\S]*: `<button type="button" class="ledgerEditButton" data-ledger-edit=/);
  assert.match(appSource, /class="ledgerEditButton" data-ledger-edit="\$\{escapeHtml\(entry\.id\)\}">\$\{escapeHtml\(uiText\("common\.edit", "Edit"\)\)\}<\/button>/);
  assert.match(appSource, /aria-label="\$\{escapeHtml\(`\$\{uiText\("common\.edit", "Edit"\)\}: \$\{entry\.date\} \$\{entry\.category\}`\)\}"/);
  assert.match(translationsSource, /"common\.edit": "수정"/);
  assert.match(stylesSource, /\.ledgerEditButton,[\s\S]*min-height: 32px;/);
});

test("ledger edit reuses the validated revision-aware PUT form with cancel and error recovery", () => {
  assert.match(appSource, /entryId \? `\/api\/ledger\/entries\/\$\{encodeURIComponent\(entryId\)\}` : "\/api\/ledger\/entries"/);
  assert.match(appSource, /method: entryId \? "PUT" : "POST"/);
  assert.match(appSource, /baseRevision: Number\(container\.dataset\.ledgerRevision \|\| 0\)/);
  assert.match(appSource, /name="amount" type="text" inputmode="numeric" pattern="\[0-9\]\+\(,\[0-9\]\{3\}\)\*"[\s\S]*required/);
  assert.match(appSource, /data-ledger-cancel>\$\{escapeHtml\(uiText\("common\.cancel", "Cancel"\)\)\}/);
  assert.match(appSource, /setLedgerEditorBusy\(container, true\)[\s\S]*setLedgerEditorBusy\(container, false\)/);
  assert.match(appSource, /if \(error\.message === "ledger_revision_conflict"\) await loadLedger\(\{ force: true \}\)/);
  assert.match(appSource, /window\.alert\(uiText\("dialog\.ledgerSaveError"/);
});

test("ledger JavaScript and CSS cache versions are bumped together", () => {
  assert.match(indexSource, /href="\/styles\.css\?v=441"/);
  assert.match(indexSource, /src="\/app\.js\?v=411"/);
});
