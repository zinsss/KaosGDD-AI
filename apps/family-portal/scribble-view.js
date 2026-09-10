window.KAOS_SCRIBBLE_VIEW = (() => {
  function renderScribble(deps) {
    const board = deps.state.scribble;
    const selected = board.items.find((item) => item.id === board.selectedId) || null;
    const rows = board.items.map((item) => {
      const expiryColor = deps.scribbleExpiryTitleColor(item);
      return `
      <li class="scribbleRow ${item.id === board.selectedId ? "isSelected" : ""}">
        <button type="button" data-scribble-open="${deps.escapeHtml(item.id)}">
          <span class="scribbleKind" aria-hidden="true">${item.hasFile ? "▣" : "✎"}</span>
          <span class="scribbleRowText">
            <strong${expiryColor ? ` style="color: ${expiryColor}"` : ""}>${deps.escapeHtml(item.title)}</strong>
            <small>${deps.escapeHtml(deps.scribbleMeta(item))}</small>
          </span>
        </button>
      </li>
    `;
    }).join("");
    const detail = selected ? `
      <form class="scribbleEditor" data-scribble-edit="${deps.escapeHtml(selected.id)}">
        <div class="scribbleEditorHeader">
          <span>${selected.hasFile ? "FILE" : "TEXT"}</span>
          <button type="button" class="archiveAction" data-scribble-close>BACK</button>
        </div>
        <label>
          <span>Title</span>
          <input name="title" value="${deps.escapeHtml(selected.title)}" maxlength="200" autocomplete="off" />
        </label>
        <label>
          <span>Text</span>
          <textarea name="text" rows="10" placeholder="Add a note or edit the captured text">${deps.escapeHtml(selected.text)}</textarea>
        </label>
        ${selected.hasFile ? `
          <div class="scribbleFile">
            <span>${deps.escapeHtml(selected.filename)}</span>
            <small>${deps.escapeHtml(deps.formatBytes(selected.sizeBytes))}</small>
            <a class="archiveAction" href="/api/scribble/${encodeURIComponent(selected.id)}/file" target="_blank" rel="noopener">OPEN</a>
          </div>
        ` : ""}
        <div class="scribbleActions">
          <button class="primaryButton" type="submit" ${board.saving ? "disabled" : ""}>SAVE CHANGES</button>
          ${selected.text ? `<button class="archiveAction isActive" type="button" data-scribble-to-memo>TO MEMOS</button>` : ""}
          ${selected.hasFile ? `<button class="archiveAction ${selected.contentType === "application/pdf" || selected.filename.toLowerCase().endsWith(".pdf") ? "isActive" : ""}" type="button" data-scribble-to-paperless ${selected.contentType === "application/pdf" || selected.filename.toLowerCase().endsWith(".pdf") ? "" : "disabled title=\"Convert to PDF first\""}>TO PAPERLESS</button>` : ""}
          <button class="dangerButton" type="button" data-scribble-delete>DELETE</button>
        </div>
      </form>
    ` : "";
    return `
      <section class="scribbleBoard">
        <form class="scribbleCapture" data-scribble-create>
          <div class="scribbleCaptureLine">
            <input name="title" maxlength="200" placeholder="Title (optional)" autocomplete="off" />
            <button class="primaryButton" type="submit" ${board.saving ? "disabled" : ""}>CAPTURE</button>
          </div>
          <textarea name="text" rows="4" placeholder="Quick text…" data-scribble-capture-text></textarea>
          <label class="scribbleFilePicker">
            <span>+ FILE</span>
            <input name="file" type="file" />
          </label>
          <p>Temporary inbox · kept for 30 days. Send text to Memos or PDF files to Paperless after review.</p>
        </form>
        ${board.error ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(board.error)}</p><button class="archiveAction" type="button" data-scribble-refresh>RETRY</button></div>` : ""}
        <div class="scribbleWorkspace ${selected ? "hasDetail" : ""}">
          <section class="scribbleList" aria-busy="${board.loading}">
            <header><strong>INBOX</strong><span>${board.loading ? "LOADING" : `${board.items.length} ITEMS`}</span><button class="archiveAction" type="button" data-scribble-refresh>↻</button></header>
            ${!board.loading && !rows ? `<p class="archiveStatusMessage">Nothing waiting.</p>` : `<ol>${rows}</ol>`}
          </section>
          ${detail}
        </div>
      </section>
    `;
  }

  return { renderScribble };
})();
