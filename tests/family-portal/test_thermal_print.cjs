const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.join(__dirname, "../../apps/family-portal");
const appSource = fs.readFileSync(path.join(root, "app.js"), "utf8");
const indexSource = fs.readFileSync(path.join(root, "index.html"), "utf8");
const memosSource = fs.readFileSync(path.join(root, "memos-view.js"), "utf8");
const moduleSource = fs.readFileSync(path.join(root, "thermal-print.js"), "utf8");
const stylesSource = fs.readFileSync(path.join(root, "styles.css"), "utf8");

test("loads the thermal print controller before the application", () => {
  assert.match(indexSource, /src="\/thermal-print\.js\?v=3"/);
  assert.ok(indexSource.indexOf('src="/thermal-print.js?v=3"') < indexSource.indexOf('src="/app.js?v=403"'));
});

test("limits print actions to the requested personal surfaces", () => {
  assert.match(appSource, /thermalPrintAction\("agenda"\)/);
  assert.match(appSource, /thermalPrintAction\("event"\)/);
  assert.match(appSource, /thermalPrintAction\("tasks"\)/);
  assert.match(appSource, /thermalPrintAction\("task"\)/);
  assert.match(appSource, /data-thermal-print-task-id=/);
  assert.match(appSource, /thermalPrintTaskDocument\(taskPrintButton\.dataset\.thermalPrintTaskId/);
  assert.match(memosSource, /data-thermal-print="memo"/);
  assert.match(appSource, /if \(portalProfile\(\) !== "main"\) return "";/);
  assert.match(memosSource, /deps\.portalProfile\(\) === "main"/);
});

test("builds structured documents instead of sending page html", () => {
  for (const kind of ["agenda", "event", "tasks", "task", "memo"]) {
    assert.match(appSource, new RegExp(`kind: "${kind}"`));
  }
  assert.doesNotMatch(moduleSource, /innerHTML:\s*state\.document/);
  assert.match(moduleSource, /JSON\.stringify\(\{ document: state\.document \}\)/);
});

test("single-event receipts use Korean weekdays and the compact event layout", () => {
  const helperStart = appSource.indexOf("const THERMAL_PRINT_KOREAN_WEEKDAYS");
  const documentStart = appSource.indexOf("function thermalPrintEventDocument", helperStart);
  const documentEnd = appSource.indexOf("function thermalPrintTaskDocument", documentStart);
  assert.ok(helperStart >= 0 && documentStart > helperStart && documentEnd > documentStart);

  const context = {};
  vm.runInNewContext(`${appSource.slice(helperStart, documentStart)}\nresult = thermalPrintDateLabel("2026-10-03");`, context);
  assert.equal(context.result, "2026-10-03 토");

  const eventDocumentSource = appSource.slice(documentStart, documentEnd);
  assert.match(eventDocumentSource, /KST/);
  assert.match(eventDocumentSource, /meta: \[\]/);
  assert.match(eventDocumentSource, /sections: \[\]/);
  assert.match(eventDocumentSource, /body: event\.description \|\| ""/);
  assert.doesNotMatch(eventDocumentSource, /Calendar|Location|Repeat|Alarm/);
});

test("agenda, tasks, task details, and memos keep only printable content", () => {
  const agendaStart = appSource.indexOf("function thermalPrintAgendaDocument");
  const tasksStart = appSource.indexOf("function thermalPrintTasksDocument", agendaStart);
  const eventStart = appSource.indexOf("function thermalPrintEventDocument", tasksStart);
  const taskStart = appSource.indexOf("function thermalPrintTaskDocument", eventStart);
  const memoStart = appSource.indexOf("function thermalPrintMemoDocument", taskStart);
  const dispatcherStart = appSource.indexOf("function thermalPrintDocument", memoStart);
  const agendaSource = appSource.slice(agendaStart, tasksStart);
  const tasksSource = appSource.slice(tasksStart, eventStart);
  const taskSource = appSource.slice(taskStart, memoStart);
  const memoSource = appSource.slice(memoStart, dispatcherStart);

  for (const source of [agendaSource, tasksSource, taskSource, memoSource]) {
    assert.match(source, /meta: \[\]/);
  }
  assert.match(agendaSource, /thermalPrintDateLabel\(today\)/);
  assert.doesNotMatch(agendaSource, /"Events"|"Task"|priorityMark|subtasks/);
  assert.match(tasksSource, /thermalPrintDateLabel\(due\)/);
  assert.doesNotMatch(tasksSource, /"Total"|All collections|priorityMark|subtasks|thermalPrintCollectionLabel/);
  assert.match(taskSource, /KST/);
  assert.doesNotMatch(taskSource, /"Due"|"List"|"Priority"|"Active"|"Completed"/);
  assert.match(memoSource, /sections: \[\]/);
  assert.doesNotMatch(memoSource, /Memo #|Updated|Created|Tags|Attachments/);
});

test("supports preview and destination-aware submission", () => {
  assert.match(moduleSource, /\/api\/thermal-print\/destinations/);
  assert.match(moduleSource, /\/api\/thermal-print\/preview/);
  assert.match(moduleSource, /\/api\/thermal-print\/jobs/);
  assert.match(moduleSource, /destinationId: destination\.id/);
  assert.match(moduleSource, /!selected\?\.available/);
  assert.match(moduleSource, /No paper was used/);
});

test("shows a not-ready popup instead of the selector when no printer is available", () => {
  assert.match(moduleSource, /window\.alert\("Printer not ready\."\)/);
  assert.match(moduleSource, /!state\.destinations\.some\(\(item\) => item\.available\)/);
  assert.match(moduleSource, /loadDestinations\(\{ notifyUnavailable: true \}\)/);
});

test("pressing Print alerts and leaves the selector closed while the printer is unavailable", async () => {
  let alertMessage = "";
  const overlay = { innerHTML: "", querySelector: () => null };
  const context = {
    document: {
      documentElement: { classList: { add() {}, remove() {} } },
      addEventListener() {},
      getElementById: () => overlay,
    },
    fetch: async () => ({
      ok: true,
      json: async () => ({
        ok: true,
        destinations: [{ id: "home", label: "Home", available: false, status: "awaiting_printer" }],
      }),
    }),
    URL,
    window: {
      alert(message) { alertMessage = message; },
      setTimeout,
    },
  };
  vm.runInNewContext(moduleSource, context);

  await context.window.KAOS_THERMAL_PRINT.open({ version: 1, kind: "task", title: "Test task" });

  assert.equal(alertMessage, "Printer not ready.");
  assert.equal(overlay.innerHTML, "");
});

test("renders the selector as a modal using the current PWA design tokens", () => {
  assert.match(stylesSource, /\.thermalPrintDialog/);
  assert.match(stylesSource, /\.thermalPrintDestination\.isSelected \{[\s\S]*?background: transparent;[\s\S]*?color: var\(--main-tab-active-text\);/);
  assert.match(stylesSource, /\.thermalPrintCommand::before[\s\S]*?content: "\[";/);
  assert.match(stylesSource, /\.thermalPrintCommand\.isActive \{[\s\S]*?background: transparent;[\s\S]*?color: var\(--main-tab-active-text\);/);
  assert.doesNotMatch(moduleSource, /class="archiveAction[^\"]*"[^>]*data-thermal-print-(?:preview|submit)/);
  assert.match(stylesSource, /html\.hasThermalPrintDialog/);
});
