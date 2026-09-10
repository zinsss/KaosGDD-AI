(function exposePortalScribble(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_PORTAL_SCRIBBLE = api;
})(typeof globalThis === "object" ? globalThis : this, function createPortalScribble() {
  function normalizeItem(value) {
    const item = value && typeof value === "object" ? value : {};
    return Object.freeze({
      id: String(item.id || ""),
      createdAt: String(item.createdAt || ""),
      updatedAt: String(item.updatedAt || ""),
      expiresAt: String(item.expiresAt || ""),
      source: String(item.source || "pwa"),
      kind: item.hasFile || item.kind === "file" ? "file" : "text",
      title: String(item.title || "Untitled"),
      text: String(item.text || ""),
      filename: String(item.filename || ""),
      contentType: String(item.contentType || ""),
      sizeBytes: Math.max(0, Number(item.sizeBytes) || 0),
      hasFile: Boolean(item.hasFile || item.filename),
    });
  }

  function normalizeList(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    return Object.freeze({
      items: Object.freeze((Array.isArray(source.items) ? source.items : []).map(normalizeItem).filter((item) => item.id)),
    });
  }

  function expiryUrgency(item, now = Date.now()) {
    const createdAt = Date.parse(String(item?.createdAt || ""));
    if (!Number.isFinite(createdAt)) return 0;
    const ageDays = (Number(now) - createdAt) / 86_400_000;
    return Math.max(0, Math.min(1, (ageDays - 25) / 5));
  }

  function expiryTitleColor(item, now = Date.now()) {
    const urgency = expiryUrgency(item, now);
    if (urgency <= 0) return "";
    const normal = [236, 239, 244];
    const expiring = [191, 97, 106];
    const values = normal.map((value, index) => Math.round(value + ((expiring[index] - value) * urgency)));
    return `rgb(${values.join(", ")})`;
  }

  return Object.freeze({ expiryTitleColor, expiryUrgency, normalizeItem, normalizeList });
});
