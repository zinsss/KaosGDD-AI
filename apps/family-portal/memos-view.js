window.KAOS_MEMOS_VIEW = (() => {
  function renderAttachmentList(deps, attachments, options = {}) {
    const items = (Array.isArray(attachments) ? attachments : []).map((attachment) => {
      const url = deps.memoAttachmentUrl(attachment);
      if (!url) return "";
      const filename = attachment.filename || "attachment";
      const preview = deps.isMemoImageAttachment(attachment)
        ? `<img src="${deps.escapeHtml(deps.memoAttachmentUrl(attachment, { thumbnail: true }))}" alt="" loading="lazy" />`
        : `<span class="memoAttachmentIcon" aria-hidden="true">FILE</span>`;
      return `
        <li class="memoAttachmentItem">
          <a class="memoAttachmentLink" href="${deps.escapeHtml(url)}" target="_blank" rel="noopener" download="${deps.escapeHtml(filename)}">
            ${preview}
            <span class="memoAttachmentText">
              <strong>${deps.escapeHtml(filename)}</strong>
              <small>${deps.escapeHtml(attachment.type || "file")} · ${deps.escapeHtml(deps.formatBytes(attachment.size || 0))}</small>
            </span>
          </a>
          ${options.editing ? `<button class="archiveAction memoAttachmentRemove" type="button" data-memo-edit-attachment-remove="${deps.escapeHtml(attachment.name)}">REMOVE</button>` : ""}
        </li>
      `;
    }).join("");
    if (!items && !options.editing) return "";
    return `
      <section class="memoAttachments" aria-label="Attachments">
        <p>FILES${items ? ` · ${(attachments || []).length}` : ""}</p>
        ${items ? `<ul class="memoAttachmentList">${items}</ul>` : `<p class="archiveStatusMessage">No files attached.</p>`}
      </section>
    `;
  }

  function renderMemos(deps) {
    const memos = deps.state.memos;
    const rows = memos.items
      .map((item) => {
        const date = deps.archiveDateParts(item.updated || item.created);
        return `
          <li class="archiveRecord ${String(memos.selectedName) === String(item.name) ? "isSelected" : ""}">
            <button class="archiveRecordButton" type="button" data-memo-open="${deps.escapeHtml(item.name)}" aria-current="${String(memos.selectedName) === String(item.name) ? "true" : "false"}">
              <span class="archiveRecordId">#${deps.escapeHtml(deps.memoDisplayNumber(item))}</span>
              <time class="archiveRecordDate" datetime="${deps.escapeHtml(date.raw)}">${deps.escapeHtml(date.label)}</time>
              <strong class="archiveRecordTitle">${deps.escapeHtml(item.title)}</strong>
            </button>
          </li>
        `;
      })
      .join("");
    const selected = memos.selected;
    const hasDetail = memos.detailLoading || memos.detailError || selected;
    const summary = memos.appliedQuery
      ? `${memos.resultCount} MATCHES // MEMOS`
      : `${memos.totalCount} MEMOS`;
    const tagButtons = (Array.isArray(memos.tagOptions) ? memos.tagOptions : [])
      .map((tag) => `<button class="archiveTagChip ${memos.appliedQuery === `#${tag}` ? "isActive" : ""}" type="button" data-memo-tag="${deps.escapeHtml(tag)}">#${deps.escapeHtml(tag)}</button>`)
      .join("");
    const detail = memos.detailLoading
      ? `
        <section class="archiveDetail" data-memo-detail tabindex="-1" aria-busy="true">
          <header class="archiveDetailHeader">
            <div>
              <p>MEMO DETAIL</p>
              <h3 id="memoDetailTitle">Loading memo...</h3>
            </div>
            <button class="archiveAction" type="button" data-memo-close>BACK</button>
          </header>
          <p class="archiveStatusMessage">Reading Memos packet...</p>
        </section>
      `
      : memos.detailError
        ? `
          <section class="archiveDetail" data-memo-detail tabindex="-1" aria-labelledby="memoDetailTitle">
            <header class="archiveDetailHeader">
              <div>
                <p>MEMO DETAIL</p>
                <h3 id="memoDetailTitle">Memo unavailable</h3>
              </div>
              <button class="archiveAction" type="button" data-memo-close>BACK</button>
            </header>
            <div class="archiveError" role="alert"><p>${deps.escapeHtml(memos.detailError)}</p></div>
          </section>
        `
        : selected
          ? `
            <section class="archiveDetail" data-memo-detail tabindex="-1" aria-labelledby="memoDetailTitle">
              <header class="archiveDetailHeader">
                <div>
                  <p>MEMO #${deps.escapeHtml(deps.memoDisplayNumber(selected))}</p>
                  <h3 id="memoDetailTitle">${deps.escapeHtml(selected.title)}</h3>
                </div>
                <div class="archiveActions memoDetailActions">
                  ${memos.editing ? "" : `<button class="archiveAction isActive" type="button" data-memo-edit-start>EDIT</button>`}
                  <button class="archiveAction" type="button" data-memo-close ${memos.editSaving ? "disabled" : ""}>BACK</button>
                </div>
              </header>
              ${
                memos.editing
                  ? `
                    <form class="memoEditForm" data-memo-edit="${deps.escapeHtml(selected.name)}">
                      <label>
                        <span>MARKDOWN</span>
                        <textarea name="content" rows="16" data-memo-edit-content data-markdown-editor>${deps.escapeHtml(memos.editDraft)}</textarea>
                      </label>
                      ${renderAttachmentList(deps, memos.editAttachments, { editing: true })}
                      <label class="memoFilePicker">
                        <span>ADD FILES</span>
                        <input name="files" type="file" multiple data-memo-files />
                      </label>
                      ${memos.editError ? `<p class="formNote isError" role="alert">${deps.escapeHtml(memos.editError)}</p>` : ""}
                      <div class="archiveActions memoEditFormActions">
                        <button class="archiveAction" type="button" data-memo-edit-cancel ${memos.editSaving ? "disabled" : ""}>CANCEL</button>
                        <button class="archiveAction isActive" type="submit" ${memos.editSaving ? "disabled" : ""}>${memos.editSaving ? "SAVING" : "SAVE"}</button>
                      </div>
                    </form>
                  `
                  : `
                    <dl class="archiveMetadata">
                      ${deps.archiveMeta("Updated", selected.updated ? deps.formatDocumentDate(selected.updated) : "")}
                      ${deps.archiveMeta("Created", selected.created ? deps.formatDocumentDate(selected.created) : "")}
                    </dl>
                    ${renderAttachmentList(deps, selected.attachments)}
                    <div class="archiveOcrRegion" role="region" aria-label="Memo content" tabindex="0">
                      <p>MEMO TEXT</p>
                      <pre>${deps.escapeHtml(selected.content || "No memo content.")}</pre>
                    </div>
                  `
              }
            </section>
          `
          : "";
    return `
      <section class="archiveTerminal" data-archive-kind="memos" aria-label="Memo archive">
        <form class="archiveCommand memoArchiveToolbar" data-memo-search role="search">
          <div class="memoArchiveCommands">
            <a class="archiveAction archiveTopAction" href="#/add-memo">New</a>
            <button class="archiveAction archiveTopAction ${memos.toolbarPanel === "search" ? "isActive" : ""}" type="button" data-memos-toolbar="search" aria-expanded="${memos.toolbarPanel === "search"}">Search</button>
            <button class="archiveAction archiveTopAction ${memos.toolbarPanel === "tags" ? "isActive" : ""}" type="button" data-memos-toolbar="tags" aria-expanded="${memos.toolbarPanel === "tags"}">Tags</button>
            <button class="archiveAction archiveTopAction" type="button" data-memos-refresh aria-label="Reload memos" title="Reload memos" ${memos.loading ? "disabled" : ""}>Reload</button>
          </div>
          ${memos.toolbarPanel === "search" ? `
            <label class="archiveSearchBox memoToolbarPanel" for="memoQuery">
              <span class="archiveSearchIcon" aria-hidden="true">⌕</span>
              <input id="memoQuery" name="query" type="search" value="${deps.escapeHtml(memos.query)}" placeholder="Search memos" autocomplete="off" />
              ${memos.appliedQuery ? `<button class="archiveSearchClear" type="button" data-memos-clear aria-label="Clear memo search">×</button>` : ""}
            </label>
          ` : `<input type="hidden" name="query" value="${deps.escapeHtml(memos.query)}" />`}
          ${memos.toolbarPanel === "tags" ? `
            <div class="archiveTagFilters memoToolbarPanel" aria-label="Memo tags">
              ${tagButtons || `<p class="archiveTagStatus">No tags found.</p>`}
            </div>
          ` : ""}
          <button class="srOnly" type="submit">Search</button>
        </form>
        <div class="archiveWorkspace ${hasDetail ? "hasDetail" : ""}">
          <section class="archiveIndex" aria-labelledby="memosIndexTitle" aria-busy="${memos.loading}">
            <header class="archiveIndexHeader">
              <h3 id="memosIndexTitle">RECORD BOARD</h3>
              <p class="archiveStatusMessage" role="status" aria-live="polite">${memos.checked && !memos.error ? deps.escapeHtml(summary) : memos.loading ? "LOADING MEMO BOARD" : "MEMO BOARD STANDBY"}</p>
            </header>
            <div class="archiveColumnHeader" aria-hidden="true">
              <span>NO.</span><span>DATE</span><span>TITLE</span>
            </div>
            ${
              memos.error
                ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(memos.error)}</p><button class="archiveAction" type="button" data-memos-refresh>RETRY</button></div>`
                : memos.loading && !memos.checked
                  ? `<p class="archiveStatusMessage">Reading Memos archive...</p>`
                  : !memos.error && memos.checked && !rows
                    ? `<p class="archiveStatusMessage">No matching memos.</p>`
                    : rows
                      ? `<ol class="archiveRecordList">${rows}</ol>`
                      : ""
            }
          </section>
          ${detail}
        </div>
      </section>
    `;
  }

  return { renderMemos };
})();
