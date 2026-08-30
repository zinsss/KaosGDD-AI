(function exposeKaosDeepLinks(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.KAOS_DEEP_LINKS = api;
})(typeof globalThis === "object" ? globalThis : this, function createKaosDeepLinks() {
  function hashParam(hash, name) {
    const query = String(hash || "").split("?", 2)[1] || "";
    return new URLSearchParams(query).get(String(name || "")) || "";
  }

  function validDate(value) {
    const normalized = String(value || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return "";
    const [year, month, day] = normalized.split("-").map(Number);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    if (
      parsed.getUTCFullYear() !== year
      || parsed.getUTCMonth() + 1 !== month
      || parsed.getUTCDate() !== day
    ) return "";
    return normalized;
  }

  function dateParam(hash, name) {
    return validDate(hashParam(hash, name));
  }

  return Object.freeze({ dateParam, hashParam, validDate });
});
