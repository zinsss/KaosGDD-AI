const assert = require("node:assert/strict");
const test = require("node:test");

const { dateParam, hashParam, validDate } = require("../../apps/family-portal/deep-links.js");

test("accepts real ISO calendar dates", () => {
  assert.equal(validDate("2026-08-30"), "2026-08-30");
  assert.equal(validDate("2028-02-29"), "2028-02-29");
});

test("rejects invalid or normalized calendar dates", () => {
  assert.equal(validDate("2026-02-29"), "");
  assert.equal(validDate("2026-04-31"), "");
  assert.equal(validDate("2026-13-01"), "");
  assert.equal(validDate("2026-8-30"), "");
  assert.equal(validDate("anything"), "");
});

test("reads selected calendar and weather dates from hash routes", () => {
  const hash = "#/calendar?date=2026-08-30&weather=2026-08-31";
  assert.equal(hashParam(hash, "date"), "2026-08-30");
  assert.equal(dateParam(hash, "date"), "2026-08-30");
  assert.equal(dateParam(hash, "weather"), "2026-08-31");
});

test("returns empty for missing and invalid date parameters", () => {
  assert.equal(dateParam("#/calendar", "date"), "");
  assert.equal(dateParam("#/calendar?date=2026-02-30", "date"), "");
});
