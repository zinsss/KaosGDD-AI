const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const portalRoot = path.join(__dirname, "../../apps/family-portal");
const appSource = fs.readFileSync(path.join(portalRoot, "app.js"), "utf8");
const stylesSource = fs.readFileSync(path.join(portalRoot, "styles.css"), "utf8");

function luminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi).map((value) => Number.parseInt(value, 16) / 255);
  const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2]);
}

function contrastRatio(foreground, background) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

test("ledger keeps the four reported list fields in the existing semantic table", () => {
  for (const key of ["date", "category", "amount", "details"]) {
    assert.match(appSource, new RegExp(`<th>\\$\\{escapeHtml\\(uiText\\("ledger\\.${key}"`));
  }
});

test("family ledger data uses a readable UI face without changing shared profile typography", () => {
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] :is\(\.ledgerEditor, \.ledgerSheet\) \{[\s\S]*?"Pretendard"/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] :is\([\s\S]*?\.ledgerEditorFields label,[\s\S]*?\.ledgerMobileMain small[\s\S]*?\) \{[\s\S]*?font-size: 0\.875rem;/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] \.ledgerTable th \{[\s\S]*?font-size: 0\.875rem;[\s\S]*?font-weight: 700;[\s\S]*?white-space: nowrap;/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] :is\(\.ledgerRowValue, \.ledgerMoney\) \{[\s\S]*?font-size: 0\.9rem;[\s\S]*?line-height: 1\.4;/,
  );
});

test("family ledger labels and values explicitly use AA dark colors on light panels", () => {
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] :is\(\.ledgerEditor, \.ledgerSheet\) \{\s*color: #34283b;/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] :is\([\s\S]*?\.ledgerMobileMain small[\s\S]*?\) \{\s*color: #594964;/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] :is\([\s\S]*?\.ledgerTable th,[\s\S]*?\.ledgerRowValue,[\s\S]*?\.ledgerMoney[\s\S]*?\) \{\s*color: #34283b;/,
  );
  assert.ok(contrastRatio("34283b", "fffaff") >= 4.5);
  assert.ok(contrastRatio("594964", "fffaff") >= 4.5);
});

test("narrow ledger rows give category and details their own readable second line", () => {
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] \.ledgerMobileRow \{[\s\S]*?grid-template-areas:\s*"date amount action"\s*"main main action";/,
  );
  assert.match(stylesSource, /\.app\[data-profile="family"\]\[data-route="ledger"\] \.ledgerMobileMain \{[\s\S]*?grid-area: main;[\s\S]*?gap: 2px;/);
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] \.ledgerMobileMain small \{[\s\S]*?white-space: normal;[\s\S]*?-webkit-line-clamp: 2;/,
  );
  assert.match(
    stylesSource,
    /\.app\[data-profile="family"\]\[data-route="ledger"\] \.ledgerMobileRow > :is\([\s\S]*?\.ledgerEditButton,[\s\S]*?\.ledgerLockedAction[\s\S]*?\) \{\s*grid-area: action;/,
  );
});
