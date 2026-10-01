const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const portalRoot = path.join(__dirname, "../../apps/family-portal");
const appSource = fs.readFileSync(path.join(portalRoot, "app.js"), "utf8");
const indexSource = fs.readFileSync(path.join(portalRoot, "index.html"), "utf8");
const stylesSource = fs.readFileSync(path.join(portalRoot, "styles.css"), "utf8");
const translationsSource = fs.readFileSync(path.join(portalRoot, "translations.js"), "utf8");

test("family ledger offers separate Excel and printable PDF downloads", () => {
  assert.match(appSource, /href="\/api\/ledger\/export\.xlsx"[^>]+data-ledger-export="xlsx"/);
  assert.match(appSource, /href="\/api\/ledger\/export\.pdf"[^>]+data-ledger-export="pdf"/);
  assert.match(appSource, /dialog\.ledgerPdfExportConfirm/);
  assert.match(translationsSource, /"ledger\.exportPdf": "PDF"/);
  assert.match(translationsSource, /"dialog\.ledgerPdfExportConfirm": "인쇄용 PDF 파일을 이 기기에 저장할까요\?"/);
});

test("ledger export actions stay usable as a four-button mobile row", () => {
  assert.match(stylesSource, /\.ledgerToolbarActions\s*\{[\s\S]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
  assert.match(indexSource, /href="\/styles\.css\?v=435"/);
  assert.match(indexSource, /src="\/translations\.js\?v=197"/);
  assert.match(indexSource, /src="\/app\.js\?v=406"/);
});
