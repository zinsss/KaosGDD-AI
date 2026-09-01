(function exposePortalMail(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_PORTAL_MAIL = api;
})(typeof globalThis === "object" ? globalThis : this, function createPortalMail() {
  const modes = Object.freeze(["all", "yeongdeok", "tax", "attachments"]);
  const modeLabels = Object.freeze({
    all: "ALL",
    yeongdeok: "영덕군보건소",
    tax: "세무사",
    attachments: "ATT",
  });

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
      attachments: Object.freeze(
        (Array.isArray(source.attachments) ? source.attachments : []).map(normalizeAttachment).filter(Boolean),
      ),
    });
  }

  function normalizeAttachment(value) {
    const source = value && typeof value === "object" ? value : {};
    const filename = clean(source.filename, 240) || "attachment";
    return Object.freeze({
      index: Math.max(0, Number(source.index) || 0),
      filename,
      contentType: clean(source.contentType, 120) || "application/octet-stream",
      sizeBytes: Math.max(0, Number(source.sizeBytes) || 0),
    });
  }

  function normalizeDetail(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    return normalizeMessage(source.message || source);
  }

  function normalizeMode(value) {
    const mode = clean(value, 40).toLowerCase();
    return modes.includes(mode) ? mode : "all";
  }

  function filterItems(items, modeValue) {
    const mode = normalizeMode(modeValue);
    const source = Array.isArray(items) ? items : [];
    if (mode === "attachments") return Object.freeze(source.filter((item) => item.attachmentCount > 0));
    if (mode === "yeongdeok") return Object.freeze(source.filter((item) => item.mailbox === "영덕군보건소"));
    if (mode === "tax") return Object.freeze(source.filter((item) => item.mailbox === "세무사"));
    return Object.freeze(source.slice());
  }

  function counts(items) {
    const source = Array.isArray(items) ? items : [];
    return Object.freeze({
      all: source.length,
      yeongdeok: source.filter((item) => item.mailbox === "영덕군보건소").length,
      tax: source.filter((item) => item.mailbox === "세무사").length,
      attachments: source.filter((item) => item.attachmentCount > 0).length,
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

  return Object.freeze({
    counts,
    filterItems,
    modeLabels,
    modes,
    normalizeAttachment,
    normalizeDetail,
    normalizeMessage,
    normalizeMode,
    normalizePage,
  });
});
