(function exposePortalMail(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_PORTAL_MAIL = api;
})(typeof globalThis === "object" ? globalThis : this, function createPortalMail() {
  function clean(value, maximum = 240) {
    return String(value || "").trim().slice(0, maximum);
  }

  function normalizeMessage(value) {
    const source = value && typeof value === "object" ? value : {};
    const mailbox = clean(source.mailbox, 160) || "INBOX";
    const uid = Math.max(0, Number(source.uid) || 0);
    if (!uid) return null;
    const receivedAt = clean(source.receivedAt, 80);
    return Object.freeze({
      id: `${mailbox}:${uid}`,
      mailbox,
      uid,
      sender: clean(source.sender, 240),
      subject: clean(source.subject, 240) || "(No subject)",
      preview: clean(source.preview, 3000),
      receivedAt,
      attachmentCount: Math.max(0, Number(source.attachmentCount) || 0),
    });
  }

  function normalizePage(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    const items = Object.freeze(
      (Array.isArray(source.messages) ? source.messages : Array.isArray(source.items) ? source.items : [])
        .map(normalizeMessage)
        .filter(Boolean),
    );
    return Object.freeze({
      items,
      folders: Object.freeze((Array.isArray(source.folders) ? source.folders : []).map((item) => clean(item, 160)).filter(Boolean)),
      mailboxCount: Math.max(0, Number(source.mailboxCount) || 0),
      limit: Math.max(1, Number(source.limit) || items.length || 50),
    });
  }

  return Object.freeze({ normalizeMessage, normalizePage });
});
