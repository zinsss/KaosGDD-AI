const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const portalRoot = path.join(__dirname, "../../apps/family-portal");
const indexSource = fs.readFileSync(path.join(portalRoot, "index.html"), "utf8");
const appSource = fs.readFileSync(path.join(portalRoot, "app.js"), "utf8");
const workerSource = fs.readFileSync(path.join(portalRoot, "sw.js"), "utf8");
const webPushSource = fs.readFileSync(path.join(portalRoot, "web-push.js"), "utf8");

function bootSource() {
  const match = indexSource.match(/<script id="portalBoot">([\s\S]*?)<\/script>/);
  assert.ok(match, "portal boot script must remain inline so it can recover from external asset failures");
  return match[1];
}

function loadBoot(href = "https://family.kaosgdd.net/#/today") {
  const elements = new Map([
    ["themeColor", { content: "#2E3440" }],
    ["appleStatusBarStyle", { content: "black-translucent" }],
    ["appleAppTitle", { content: "KaosGDD" }],
    ["appFavicon", { href: "/icons/main/favicon.ico?v=93" }],
    ["appFavicon32", { href: "/icons/main/favicon-32x32.png?v=93" }],
    ["appFavicon16", { href: "/icons/main/favicon-16x16.png?v=93" }],
    ["appAppleIcon", { href: "/icons/main/kaos-master-1024.png?v=97" }],
    ["appManifest", { href: "/manifest.webmanifest?v=101" }],
    ["routeTitle", { textContent: "Agenda" }],
    ["topNav", { setAttribute(name, value) { this[name] = value; } }],
    ["view", { textContent: "", innerHTML: "" }],
  ]);
  const app = { dataset: {} };
  const kicker = { textContent: "KaosGDD" };
  const replaced = [];
  const history = [];
  const listeners = new Map();
  const locationUrl = new URL(href);
  const window = {
    location: {
      hostname: locationUrl.hostname,
      href: locationUrl.href,
      replace(value) { replaced.push(value); },
    },
    history: { replaceState(_state, _title, value) { history.push(value); } },
    addEventListener(name, handler) { listeners.set(name, handler); },
    setTimeout() { return 7; },
    clearTimeout() {},
  };
  const document = {
    title: "KaosGDD",
    documentElement: { lang: "en" },
    getElementById: (id) => elements.get(id) || null,
    querySelector(selector) {
      if (selector === ".app") return app;
      if (selector === ".kicker") return kicker;
      return null;
    },
  };
  vm.runInNewContext(bootSource(), { window, document, URL, Date });
  return { window, document, elements, app, kicker, replaced, history, listeners };
}

test("Family shell is classified before external scripts can paint Main", () => {
  const boot = loadBoot();
  boot.window.KAOS_PORTAL_BOOT.prepare();

  assert.equal(boot.window.KAOS_PORTAL_BOOT.profile, "family");
  assert.equal(boot.app.dataset.profile, "family");
  assert.equal(boot.elements.get("routeTitle").textContent, "오늘");
  assert.equal(boot.kicker.textContent, "");
  assert.match(boot.elements.get("view").innerHTML, /Family 불러오는 중/);
  assert.equal(boot.elements.get("appManifest").href, "/manifest-family.webmanifest?v=102");
  assert.ok(indexSource.indexOf("window.KAOS_PORTAL_BOOT.prepare()") < indexSource.indexOf('src="/translations.js'));
});

test("Main keeps its existing initial shell", () => {
  const boot = loadBoot("https://kaosgdd.net/#/agenda");
  boot.window.KAOS_PORTAL_BOOT.prepare();

  assert.equal(boot.window.KAOS_PORTAL_BOOT.profile, "main");
  assert.equal(boot.app.dataset.profile, "main");
  assert.equal(boot.elements.get("routeTitle").textContent, "Agenda");
  assert.equal(boot.kicker.textContent, "KaosGDD");
  assert.equal(boot.elements.get("view").innerHTML, "");
  assert.equal(boot.elements.get("appManifest").href, "/manifest.webmanifest?v=101");
});

test("a failed startup performs one top-level auth recovery then shows a retry", () => {
  const first = loadBoot();
  first.window.KAOS_PORTAL_BOOT.prepare();
  first.listeners.get("error")({ target: { tagName: "SCRIPT" } });
  assert.equal(first.replaced.length, 1);
  assert.match(first.replaced[0], /kaos-boot-recovery=/);
  assert.match(first.replaced[0], /#\/today$/);

  const second = loadBoot(first.replaced[0]);
  second.window.KAOS_PORTAL_BOOT.prepare();
  second.window.KAOS_PORTAL_BOOT.fail();
  assert.equal(second.replaced.length, 0);
  assert.match(second.elements.get("view").innerHTML, /Family를 시작하지 못했습니다/);
  assert.match(second.elements.get("view").innerHTML, /다시 로그인/);
});

test("successful render cancels recovery and removes its transient query", () => {
  const boot = loadBoot("https://family.kaosgdd.net/?kaos-boot-recovery=123#/today");
  boot.window.KAOS_PORTAL_BOOT.markReady();

  assert.equal(boot.window.KAOS_PORTAL_BOOT.ready, true);
  assert.deepEqual(boot.history, ["/#/today"]);
  assert.match(appSource, /window\.KAOS_PORTAL_BOOT\?\.markReady\(\);/);
  assert.match(indexSource, /src="\/app\.js\?v=410"/);
});

test("Family cannot inherit the Main service worker cache", () => {
  assert.match(workerSource, /This worker intentionally caches nothing/);
  assert.doesNotMatch(workerSource, /caches\.(open|match)|cache\.add(All)?\(/);
  assert.match(webPushSource, /return window\.location\.hostname !== "family\.kaosgdd\.net";/);
  assert.match(webPushSource, /if \(isMain\(\) && "serviceWorker" in navigator\)/);
});
