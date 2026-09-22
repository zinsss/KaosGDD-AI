(function exposeMarkdownEditor(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KAOS_MARKDOWN_EDITOR = api;
})(typeof globalThis === "object" ? globalThis : this, function createMarkdownEditor() {
  const INDENT = "  ";

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function inlineMarkup(value) {
    const source = String(value || "");
    const pattern = /(`[^`\n]+`|<<[^<>\n]+>>|\*\*[^*\n]+\*\*|__[^_\n]+__|\[[^\]\n]+\]\([^\n)]+\))/g;
    let html = "";
    let cursor = 0;
    for (const match of source.matchAll(pattern)) {
      html += escapeHtml(source.slice(cursor, match.index));
      const token = match[0];
      const className = token.startsWith("`")
        ? "mdInlineCode"
        : token.startsWith("[")
          ? "mdLink"
          : "mdStrong";
      html += `<span class="${className}">${escapeHtml(token)}</span>`;
      cursor = Number(match.index) + token.length;
    }
    return html + escapeHtml(source.slice(cursor));
  }

  function highlightMarkdown(value) {
    let fenced = false;
    const lines = String(value || "").split("\n");
    const html = lines.map((line) => {
      if (/^\s*```/.test(line)) {
        fenced = !fenced;
        return `<span class="mdCodeFence">${escapeHtml(line)}</span>`;
      }
      if (fenced) return `<span class="mdCodeBlock">${escapeHtml(line)}</span>`;
      const heading = line.match(/^\s{0,3}(#{1,6})(?:\s|$)/);
      if (heading) {
        return `<span class="mdHeading mdH${heading[1].length}">${inlineMarkup(line)}</span>`;
      }
      if (/^\s*>/.test(line)) return `<span class="mdQuote">${inlineMarkup(line)}</span>`;
      const list = line.match(/^(\s*)([-*+]|\d+\.)(\s+)/);
      if (list) {
        const start = list[0].length;
        return `${escapeHtml(list[1])}<span class="mdListMarker">${escapeHtml(list[2])}</span>${escapeHtml(list[3])}${inlineMarkup(line.slice(start))}`;
      }
      if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
        return `<span class="mdRule">${escapeHtml(line)}</span>`;
      }
      return inlineMarkup(line);
    }).join("\n");
    return `${html}\n `;
  }

  function safeLinkTarget(value) {
    const target = String(value || "").trim();
    if (/^(?:https?:|mailto:)/i.test(target) || /^(?:\/|#)/.test(target)) return target;
    return "";
  }

  function renderInlineMarkdown(value) {
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

  function renderMarkdown(value) {
    const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let paragraph = [];
    let listType = "";
    let listItems = [];
    let fenced = false;
    let codeLines = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      blocks.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br />")}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (!listItems.length) return;
      blocks.push(`<${listType}>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${listType}>`);
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
        blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
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
        blocks.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
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

  function lineIndexAt(value, offset) {
    return String(value).slice(0, Math.max(0, offset)).split("\n").length - 1;
  }

  function lineOffset(lines, lineIndex) {
    let offset = 0;
    for (let index = 0; index < lineIndex; index += 1) offset += lines[index].length + 1;
    return offset;
  }

  function selectedLineRange(value, start, end) {
    const lines = String(value).split("\n");
    const startLine = lineIndexAt(value, start);
    const adjustedEnd = end > start && String(value)[end - 1] === "\n" ? end - 1 : end;
    const endLine = lineIndexAt(value, adjustedEnd);
    return { lines, startLine, endLine };
  }

  function editText(value, selectionStart, selectionEnd, command) {
    const source = String(value || "");
    const start = Math.max(0, Number(selectionStart) || 0);
    const end = Math.max(start, Number(selectionEnd) || start);
    const { lines, startLine, endLine } = selectedLineRange(source, start, end);
    const originalBlockStart = lineOffset(lines, startLine);
    const startColumn = start - originalBlockStart;
    const originalEndStart = lineOffset(lines, endLine);
    const endColumn = end - originalEndStart;

    if (command === "indent" || command === "outdent") {
      const removed = [];
      for (let index = startLine; index <= endLine; index += 1) {
        if (command === "indent") {
          lines[index] = INDENT + lines[index];
          removed.push(-INDENT.length);
        } else {
          const match = lines[index].match(/^(?: {1,2}|\t)/);
          const count = match ? match[0].length : 0;
          lines[index] = lines[index].slice(count);
          removed.push(count);
        }
      }
      const nextStartColumn = command === "indent"
        ? startColumn + INDENT.length
        : Math.max(0, startColumn - removed[0]);
      const lastRemoved = removed[removed.length - 1];
      const nextEndColumn = command === "indent"
        ? endColumn + INDENT.length
        : Math.max(0, endColumn - lastRemoved);
      return {
        value: lines.join("\n"),
        start: lineOffset(lines, startLine) + nextStartColumn,
        end: lineOffset(lines, endLine) + nextEndColumn,
      };
    }

    if (command === "up" && startLine > 0) {
      const block = lines.splice(startLine, endLine - startLine + 1);
      lines.splice(startLine - 1, 0, ...block);
      return {
        value: lines.join("\n"),
        start: lineOffset(lines, startLine - 1) + startColumn,
        end: lineOffset(lines, endLine - 1) + endColumn,
      };
    }

    if (command === "down" && endLine < lines.length - 1) {
      const block = lines.splice(startLine, endLine - startLine + 1);
      lines.splice(startLine + 1, 0, ...block);
      return {
        value: lines.join("\n"),
        start: lineOffset(lines, startLine + 1) + startColumn,
        end: lineOffset(lines, endLine + 1) + endColumn,
      };
    }

    return { value: source, start, end };
  }

  function commandButton(command, label, title) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.markdownCommand = command;
    button.textContent = label;
    button.title = title;
    button.setAttribute("aria-label", title);
    return button;
  }

  function enhance(textarea) {
    if (!textarea || textarea.dataset.markdownEnhanced === "true") return;
    textarea.dataset.markdownEnhanced = "true";
    textarea.classList.add("markdownEditorInput");

    const editor = document.createElement("div");
    editor.className = "markdownEditor";
    const toolbar = document.createElement("div");
    toolbar.className = "markdownEditorToolbar";
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", "Markdown editing controls");
    toolbar.append(
      commandButton("outdent", "←", "Outdent selected lines"),
      commandButton("indent", "→", "Indent selected lines"),
      commandButton("up", "↑", "Move selected lines up"),
      commandButton("down", "↓", "Move selected lines down"),
    );

    const surface = document.createElement("div");
    surface.className = "markdownEditorSurface";
    const highlight = document.createElement("pre");
    highlight.className = "markdownEditorHighlight";
    highlight.setAttribute("aria-hidden", "true");

    textarea.parentNode.insertBefore(editor, textarea);
    editor.append(toolbar, surface);
    surface.append(highlight, textarea);

    const refresh = () => {
      highlight.innerHTML = highlightMarkdown(textarea.value);
      highlight.scrollTop = textarea.scrollTop;
      highlight.scrollLeft = textarea.scrollLeft;
    };
    const run = (command) => {
      const result = editText(textarea.value, textarea.selectionStart, textarea.selectionEnd, command);
      textarea.value = result.value;
      textarea.focus({ preventScroll: true });
      textarea.setSelectionRange(result.start, result.end);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      refresh();
    };

    toolbar.addEventListener("pointerdown", (event) => event.preventDefault());
    toolbar.addEventListener("click", (event) => {
      const button = event.target.closest("[data-markdown-command]");
      if (button) run(button.dataset.markdownCommand || "");
    });
    textarea.addEventListener("input", refresh);
    textarea.addEventListener("scroll", refresh, { passive: true });
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Tab") {
        event.preventDefault();
        run(event.shiftKey ? "outdent" : "indent");
      } else if (event.altKey && event.key === "ArrowUp") {
        event.preventDefault();
        run("up");
      } else if (event.altKey && event.key === "ArrowDown") {
        event.preventDefault();
        run("down");
      }
    });
    refresh();
  }

  function enhanceAll(scope) {
    const root = scope && typeof scope.querySelectorAll === "function" ? scope : document;
    root.querySelectorAll("textarea[data-markdown-editor]").forEach(enhance);
  }

  return Object.freeze({ editText, enhanceAll, highlightMarkdown, renderMarkdown });
});
