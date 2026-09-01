(function exposePortalNavigation(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_PORTAL_NAVIGATION = api;
})(typeof globalThis === "object" ? globalThis : this, function createPortalNavigation() {
  const personalMenu = Object.freeze([
    Object.freeze({ route: "today", label: "Agenda" }),
    Object.freeze({ route: "calendar", label: "Calendar" }),
    Object.freeze({ route: "tasks", label: "Tasks" }),
    Object.freeze({ route: "supplies", label: "Supplies" }),
    Object.freeze({ route: "memos", label: "Memos" }),
    Object.freeze({ route: "documents", label: "Documents" }),
    Object.freeze({ route: "fax", label: "Fax" }),
    Object.freeze({ route: "mail", label: "Mail" }),
    Object.freeze({ route: "services", label: "Utils" }),
    Object.freeze({ route: "settings", label: "Settings" }),
  ]);
  const personalRoutes = new Set(personalMenu.map((item) => item.route));
  const aliases = Object.freeze({
    add: "calendar",
    "add-event": "calendar",
    "edit-event": "calendar",
    "add-task": "tasks",
    "edit-task": "tasks",
    "add-memo": "memos",
    service: "services",
  });

  function selectedPersonalRoute(route) {
    const normalized = String(route || "");
    const selected = aliases[normalized] || normalized;
    return personalRoutes.has(selected) ? selected : "today";
  }

  return Object.freeze({ personalMenu, selectedPersonalRoute });
});
