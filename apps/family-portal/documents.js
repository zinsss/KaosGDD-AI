(function exposePortalDocuments(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_PORTAL_DOCUMENTS = api;
})(typeof globalThis === "object" ? globalThis : this, function createPortalDocuments() {
  function positiveInteger(value, fallback) {
    const number = Number(value);
    return Number.isInteger(number) && number > 0 ? number : fallback;
  }

  function normalizeItem(value) {
    const item = value && typeof value === "object" ? value : {};
    const id = positiveInteger(item.id, 0);
    return Object.freeze({
      id,
      title: String(item.title || (id ? `Document ${id}` : "Document")),
      created: String(item.created || ""),
      filename: String(item.filename || ""),
      correspondent: String(item.correspondent || ""),
      url: String(item.url || ""),
    });
  }

  function normalizePage(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    const page = positiveInteger(source.page, 1);
    const pageSize = positiveInteger(source.pageSize, 20);
    const query = String(source.query || "");
    const resultCount = Math.max(0, Number(source.resultCount) || 0);
    const totalCount = Math.max(0, Number(source.totalCount) || 0);
    const visibleCount = query ? resultCount : totalCount;
    return Object.freeze({
      query,
      items: Object.freeze((Array.isArray(source.items) ? source.items : []).map(normalizeItem).filter((item) => item.id)),
      resultCount,
      totalCount,
      page,
      pageSize,
      pageCount: Math.max(1, Math.ceil(visibleCount / pageSize)),
    });
  }

  function normalizeDocument(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    const item = normalizeItem(source);
    return Object.freeze({
      ...item,
      content: String(source.content || ""),
      tagIds: Object.freeze(Array.isArray(source.tagIds) ? source.tagIds.map(Number).filter(Number.isInteger) : []),
      tags: Object.freeze(Array.isArray(source.tags) ? source.tags.map((tag) => String(tag || "").trim()).filter(Boolean) : []),
    });
  }

  function normalizeInboxItem(value) {
    const item = value && typeof value === "object" ? value : {};
    const id = String(item.id || "");
    const title = String(item.title || item.filename || "Document").trim() || "Document";
    const status = String(item.status || "ocr_pending");
    const labels = {
      ocr_pending: "OCR PENDING",
      review: "REVIEW",
      archived: "ARCHIVED",
      failed: "FAILED",
    };
    return Object.freeze({
      id,
      title,
      submittedAt: String(item.submittedAt || ""),
      filename: String(item.filename || ""),
      sha256: String(item.sha256 || ""),
      sizeBytes: Math.max(0, Number(item.sizeBytes) || 0),
      taskId: String(item.taskId || ""),
      documentId: positiveInteger(item.documentId, 0),
      url: String(item.url || ""),
      source: String(item.source || "pwa"),
      status,
      statusLabel: labels[status] || status.toUpperCase(),
      updatedAt: String(item.updatedAt || ""),
      error: String(item.error || ""),
    });
  }

  function normalizeInbox(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    return Object.freeze({
      items: Object.freeze(
        (Array.isArray(source.items) ? source.items : [])
          .map(normalizeInboxItem)
          .filter((item) => item.id && item.status !== "applied"),
      ),
    });
  }

  return Object.freeze({ normalizeDocument, normalizeInbox, normalizeInboxItem, normalizeItem, normalizePage });
});
