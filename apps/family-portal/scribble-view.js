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
      <form class="archiveDetail scribbleEditor" data-scribble-edit="${deps.escapeHtml(selected.id)}">
        <header class="archiveDetailHeader scribbleEditorHeader">
          <div>
            <p>${selected.hasFile ? "FILE CAPTURE" : "TEXT CAPTURE"}</p>
            <h3>${deps.escapeHtml(selected.title)}</h3>
          </div>
          <button type="button" class="archiveAction" data-scribble-close>BACK</button>
        </header>
        <label class="archiveCommandLine">
          <span>TITLE</span>
          <input name="title" value="${deps.escapeHtml(selected.title)}" maxlength="200" autocomplete="off" />
        </label>
        <label class="archiveCommandLine scribbleTextLine">
          <span>TEXT</span>
          <textarea name="text" rows="10" placeholder="Add a note or edit the captured text" data-markdown-editor>${deps.escapeHtml(selected.text)}</textarea>
        </label>
        ${selected.hasFile ? `
          <div class="scribbleFile">
            <span class="scribbleFileType">FILE</span>
            <strong>${deps.escapeHtml(selected.filename)}</strong>
            <small>${deps.escapeHtml(deps.formatBytes(selected.sizeBytes))}</small>
            <a class="archiveAction" href="/api/scribble/${encodeURIComponent(selected.id)}/file" target="_blank" rel="noopener">OPEN</a>
          </div>
        ` : ""}
        <div class="archiveActions scribbleActions">
          <button class="archiveAction isActive" type="submit" ${board.saving ? "disabled" : ""}>SAVE</button>
          ${selected.text ? `<button class="archiveAction isActive" type="button" data-scribble-to-memo>TO MEMOS</button>` : ""}
          ${selected.hasFile ? `<button class="archiveAction ${selected.contentType === "application/pdf" || selected.filename.toLowerCase().endsWith(".pdf") ? "isActive" : ""}" type="button" data-scribble-to-paperless ${selected.contentType === "application/pdf" || selected.filename.toLowerCase().endsWith(".pdf") ? "" : "disabled title=\"Convert to PDF first\""}>TO PAPERLESS</button>` : ""}
          <button class="archiveAction scribbleDeleteAction" type="button" data-scribble-delete>DELETE</button>
        </div>
      </form>
    ` : "";
    return `
      <section class="archiveTerminal scribbleBoard" data-archive-kind="scribble" aria-label="Scribble staging inbox">
        <form class="archiveCommand scribbleCapture" data-scribble-create>
          <label class="archiveCommandLine">
            <span>TITLE</span>
            <input name="title" maxlength="200" placeholder="Optional title" autocomplete="off" />
          </label>
          <label class="archiveCommandLine scribbleTextLine">
            <span>TEXT</span>
            <textarea name="text" rows="4" placeholder="Write something to sort out later…" data-scribble-capture-text data-markdown-editor></textarea>
          </label>
          <label class="archiveCommandLine scribbleFilePicker">
            <span>FILE</span>
            <input name="file" type="file" />
          </label>
          <div class="scribbleCaptureFooter">
            <p class="archiveStatusMessage">30-DAY BUFFER // TEXT → MEMOS // PDF → PAPERLESS</p>
            <div class="archiveCommandActions">
              <button class="archiveAction isActive" type="submit" ${board.saving ? "disabled" : ""}>${board.saving ? "SAVING" : "CAPTURE"}</button>
            </div>
          </div>
        </form>
        ${board.error ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(board.error)}</p><button class="archiveAction" type="button" data-scribble-refresh>RETRY</button></div>` : ""}
        <div class="archiveWorkspace scribbleWorkspace ${selected ? "hasDetail" : ""}">
          <section class="archiveIndex scribbleList" aria-busy="${board.loading}">
            <header class="archiveIndexHeader">
              <div>
                <p class="archiveNodeLabel">STAGING QUEUE</p>
                <h3>INBOX</h3>
              </div>
              <div class="scribbleListStatus">
                <span>${board.loading ? "LOADING" : `${board.items.length} ITEMS`}</span>
                <button class="archiveAction archiveRefreshAction" type="button" data-scribble-refresh aria-label="Refresh Scribble inbox" title="Refresh Scribble inbox">↻</button>
              </div>
            </header>
            ${!board.loading && !rows ? `<p class="archiveStatusMessage">Nothing waiting.</p>` : `<ol>${rows}</ol>`}
          </section>
          ${detail}
        </div>
      </section>
    `;
  }

  return { renderScribble };
})();
