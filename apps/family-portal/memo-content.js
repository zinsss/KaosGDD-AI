(function exposeMemoContent(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_MEMO_CONTENT = api;
})(typeof globalThis === "object" ? globalThis : this, function createMemoContent() {
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeLinkTarget(value) {
    const target = String(value || "").trim();
    if (/^(?:https?:|mailto:)/i.test(target) || /^(?:\/|#)/.test(target)) return target;
    return "";
  }

  function renderInlineMarkup(value) {
    const source = String(value || "");
    const pattern = /(`[^`\n]+`|<<[^<>\n]+>>|\*\*[^*\n]+\*\*|__[^_\n]+__|\[[^\]\n]+\]\([^\n)]+\))/g;
    let html = "";
    let cursor = 0;
    for (const match of source.matchAll(pattern)) {
      html += escapeHtml(source.slice(cursor, match.index));
      const token = match[0];
      if (token.startsWith("`")) {
        html += `<code>${escapeHtml(token.slice(1, -1))}</code>`;
      } else if (token.startsWith("<<")) {
        const copyText = token.slice(2, -2).trim();
        html += `<button class="memoCopyToken" type="button" data-memo-copy-token="${escapeHtml(copyText)}" aria-label="Copy ${escapeHtml(copyText)}" title="Copy to clipboard">${escapeHtml(copyText)}</button>`;
      } else if (token.startsWith("[")) {
        const parts = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        const target = safeLinkTarget(parts?.[2]);
        html += target
          ? `<a href="${escapeHtml(target)}"${/^https?:/i.test(target) ? ' target="_blank" rel="noopener noreferrer"' : ""}>${escapeHtml(parts[1])}</a>`
          : escapeHtml(parts?.[1] || token);
      } else {
        html += `<strong>${escapeHtml(token.slice(2, -2))}</strong>`;
      }
      cursor = Number(match.index) + token.length;
    }
    return html + escapeHtml(source.slice(cursor));
  }

  function render(value) {
    const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let paragraph = [];
    let listType = "";
    let listItems = [];
    let fenced = false;
    let codeLines = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      blocks.push(`<p>${paragraph.map(renderInlineMarkup).join("<br />")}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (!listItems.length) return;
      blocks.push(`<${listType}>${listItems.map((item) => `<li>${renderInlineMarkup(item)}</li>`).join("")}</${listType}>`);
      listType = "";
      listItems = [];
    };
    const flushText = () => {
      flushParagraph();
      flushList();
    };

    for (const line of lines) {
      if (/^\s*```/.test(line)) {
        if (fenced) {
          blocks.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
          codeLines = [];
        } else {
          flushText();
        }
        fenced = !fenced;
        continue;
      }
      if (fenced) {
        codeLines.push(line);
        continue;
      }
      if (!line.trim()) {
        flushText();
        continue;
      }
      const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/);
      if (heading) {
        flushText();
        const level = heading[1].length;
        blocks.push(`<h${level}>${renderInlineMarkup(heading[2])}</h${level}>`);
        continue;
      }
      if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
        flushText();
        blocks.push("<hr />");
        continue;
      }
      const quote = line.match(/^\s*>\s?(.*)$/);
      if (quote) {
        flushText();
        blocks.push(`<blockquote>${renderInlineMarkup(quote[1])}</blockquote>`);
        continue;
      }
      const list = line.match(/^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/);
      if (list) {
        flushParagraph();
        const nextType = list[1] ? "ul" : "ol";
        if (listType && listType !== nextType) flushList();
        listType = nextType;
        listItems.push(list[3]);
        continue;
      }
      flushList();
      paragraph.push(line);
    }
    if (fenced) blocks.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    flushText();
    return blocks.join("") || "<p>No memo content.</p>";
  }

  return Object.freeze({ render });
});
