const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const portalRoot = path.join(__dirname, "../../apps/family-portal");
const translationsSource = fs.readFileSync(path.join(portalRoot, "translations.js"), "utf8");
const appSource = fs.readFileSync(path.join(portalRoot, "app.js"), "utf8");
const memosViewSource = fs.readFileSync(path.join(portalRoot, "memos-view.js"), "utf8");
const aiTasksViewSource = fs.readFileSync(path.join(portalRoot, "ai-tasks-view.js"), "utf8");
const indexSource = fs.readFileSync(path.join(portalRoot, "index.html"), "utf8");

function loadWindowAsset(source) {
  const sandbox = { window: {} };
  vm.runInNewContext(source, sandbox);
  return sandbox.window;
}

const translations = loadWindowAsset(translationsSource).KAOS_TRANSLATIONS.ko;

function koreanText(key, english, params = {}) {
  return String(translations[key] ?? english).replace(/\{(\w+)\}/g, (match, name) => (
    params[name] === undefined ? match : String(params[name])
  ));
}

test("every statically referenced Family translation key exists", () => {
  const sources = fs.readdirSync(portalRoot)
    .filter((name) => name.endsWith(".js"))
    .map((name) => fs.readFileSync(path.join(portalRoot, name), "utf8"));
  const referenced = new Set();
  for (const source of sources) {
    for (const match of source.matchAll(/uiText\(\s*["']([^"']+)["']/g)) referenced.add(match[1]);
    for (const match of source.matchAll(/text\(deps,\s*["']([^"']+)["']/g)) referenced.add(match[1]);
  }
  const missing = [...referenced].filter((key) => !Object.hasOwn(translations, key)).sort();
  assert.deepEqual(missing, []);
});

test("Family routes and refreshed assets cannot fall back to stale English labels", () => {
  assert.match(appSource, /"ai-tasks": uiText\("route\.aiTasks", "AI Tasks"\)/);
  assert.equal(translations["route.settings"], "설정");
  assert.equal(translations["route.aiTasks"], "AI 작업");
  assert.match(indexSource, /src="\/translations\.js\?v=198"/);
  assert.match(indexSource, /src="\/ai-tasks-view\.js\?v=6"/);
  assert.match(indexSource, /src="\/memos-view\.js\?v=15"/);
  assert.match(indexSource, /src="\/app\.js\?v=407"/);
});

test("Family memo board renders Korean controls and headings", () => {
  const memosView = loadWindowAsset(memosViewSource).KAOS_MEMOS_VIEW;
  const html = memosView.renderMemos({
    state: {
      memos: {
        items: [],
        selected: null,
        selectedName: "",
        detailLoading: false,
        detailError: "",
        appliedQuery: "",
        query: "",
        resultCount: 0,
        totalCount: 0,
        tagOptions: [],
        toolbarPanel: "",
        checked: true,
        loading: false,
        error: "",
      },
    },
    uiText: koreanText,
    escapeHtml: (value) => String(value),
    archiveDateParts: () => ({ raw: "", label: "" }),
    memoDisplayNumber: () => "",
    archiveMeta: () => "",
    formatDocumentDate: () => "",
    memoAttachmentUrl: () => "",
    isMemoImageAttachment: () => false,
    formatBytes: () => "",
    renderMemoContent: () => "",
  });

  for (const label of ["검색", "태그", "새로고침", "메모 목록", "메모 0개", "번호", "날짜", "제목", "일치하는 메모가 없습니다."]) {
    assert.match(html, new RegExp(label));
  }
  for (const label of ["RECORD BOARD", "MEMO BOARD STANDBY", ">Search<", ">Tags<", ">Reload<"]) {
    assert.doesNotMatch(html, new RegExp(label));
  }
});

test("Family AI task labels are Korean", () => {
  const aiTasksView = loadWindowAsset(aiTasksViewSource).KAOS_AI_TASKS_VIEW;
  const labels = aiTasksView.labelsForProfile({ portalProfile: () => "family" });
  assert.equal(labels.archive, "AI 기록");
  assert.equal(labels.query, "검색어");
  assert.equal(labels.sources, "출처");
  assert.equal(labels.number, "번호");
  assert.equal(labels.date, "날짜");
  assert.equal(labels.columnTitle, "제목");
});
