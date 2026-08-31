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
    });
  }

  return Object.freeze({ normalizeDocument, normalizeItem, normalizePage });
});
