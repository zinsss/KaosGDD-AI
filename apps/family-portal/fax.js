(function exposePortalFax(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_PORTAL_FAX = api;
})(typeof globalThis === "object" ? globalThis : this, function createPortalFax() {
  const faxIdPattern = /^[0-9a-f]{32}$/;
  const jobIdPattern = /^[A-Za-z0-9_.:-]{1,80}$/;
  const modes = Object.freeze(["all", "received", "sent", "failed"]);

  function clean(value, maximum = 160) {
    return String(value || "").trim().slice(0, maximum);
  }

  function normalizeItem(value) {
    const source = value && typeof value === "object" ? value : {};
    const direction = clean(source.direction, 16).toLowerCase();
    if (!["incoming", "outgoing"].includes(direction)) return null;
    const incomingId = clean(source.id || source.faxId, 32).toLowerCase();
    const outgoingId = clean(source.id || source.jobId || source.faxId, 80);
    const id = direction === "incoming" ? incomingId : outgoingId;
    if (direction === "incoming" && !faxIdPattern.test(id)) return null;
    if (direction === "outgoing" && !jobIdPattern.test(id)) return null;
    const status = clean(source.status || (direction === "incoming" ? "archived" : "unknown"), 24).toLowerCase();
    const documentAvailable = direction === "incoming" && Boolean(source.documentAvailable ?? source.hasDocument ?? source.documentUrl);
    const documentUrl = documentAvailable
      ? clean(source.documentUrl || `/api/fax/items/${id}/document`, 240)
      : "";
    return Object.freeze({
      id,
      key: `${direction}:${id}`,
      direction,
      status,
      title: clean(source.title || source.filename || "Fax", 160),
      filename: clean(source.filename || source.title || "fax.pdf", 160),
      remote: clean(source.remote, 40),
      destination: clean(source.destination, 40),
      pages: clean(source.pages, 16),
      receivedAt: clean(source.receivedAt, 64),
      archivedAt: clean(source.archivedAt, 64),
      createdAt: clean(source.createdAt, 64),
      completedAt: clean(source.completedAt, 64),
      error: clean(source.error, 240),
      hylafaxJobId: clean(source.hylafaxJobId, 40),
      documentAvailable,
      documentUrl,
      attentionAcknowledged: Boolean(source.attentionAcknowledged),
    });
  }

  function counts(items) {
    const rows = Array.isArray(items) ? items : [];
    return Object.freeze({
      all: rows.length,
      received: rows.filter((item) => item.direction === "incoming").length,
      sent: rows.filter((item) => item.status === "sent").length,
      failed: rows.filter((item) => item.status === "failed").length,
    });
  }

  function normalizeArchive(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    const items = Object.freeze(
      (Array.isArray(source.items) ? source.items : []).map(normalizeItem).filter(Boolean),
    );
    const sourceAttention = source.attention && typeof source.attention === "object" ? source.attention : {};
    const attention = Object.freeze({
      failed: Number.isFinite(Number(sourceAttention.failed))
        ? Math.max(0, Number(sourceAttention.failed))
        : items.filter((item) => item.status === "failed" && !item.attentionAcknowledged).length,
    });
    return Object.freeze({ items, counts: counts(items), attention });
  }

  function normalizeMode(value) {
    const mode = clean(value, 16).toLowerCase();
    return modes.includes(mode) ? mode : "all";
  }

  function filterItems(items, mode) {
    const selected = normalizeMode(mode);
    const rows = Array.isArray(items) ? items : [];
    if (selected === "received") return rows.filter((item) => item.direction === "incoming");
    if (selected === "sent") return rows.filter((item) => item.status === "sent");
    if (selected === "failed") return rows.filter((item) => item.status === "failed");
    return rows;
  }

  return Object.freeze({ counts, filterItems, modes, normalizeArchive, normalizeItem, normalizeMode });
});
