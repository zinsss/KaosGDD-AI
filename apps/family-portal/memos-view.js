window.KAOS_MEMOS_VIEW = (() => {
  function text(deps, key, english, params = {}) {
    if (typeof deps.uiText === "function") return deps.uiText(key, english, params);
    return String(english).replace(/\{(\w+)\}/g, (match, name) => (params[name] === undefined ? match : String(params[name])));
  }

  function renderAttachmentList(deps, attachments, options = {}) {
    const items = (Array.isArray(attachments) ? attachments : []).map((attachment) => {
      const url = deps.memoAttachmentUrl(attachment);
      if (!url) return "";
      const filename = attachment.filename || text(deps, "memos.attachment", "attachment");
      const preview = deps.isMemoImageAttachment(attachment)
        ? `<img src="${deps.escapeHtml(deps.memoAttachmentUrl(attachment, { thumbnail: true }))}" alt="" loading="lazy" />`
        : `<span class="memoAttachmentIcon" aria-hidden="true">${deps.escapeHtml(text(deps, "common.files", "FILE"))}</span>`;
      return `
        <li class="memoAttachmentItem">
          <a class="memoAttachmentLink" href="${deps.escapeHtml(url)}" target="_blank" rel="noopener" download="${deps.escapeHtml(filename)}">
            ${preview}
            <span class="memoAttachmentText">
              <strong>${deps.escapeHtml(filename)}</strong>
              <small>${deps.escapeHtml(attachment.type || text(deps, "memos.attachment", "file"))} · ${deps.escapeHtml(deps.formatBytes(attachment.size || 0))}</small>
            </span>
          </a>
          ${options.editing ? `<button class="archiveAction memoAttachmentRemove" type="button" data-memo-edit-attachment-remove="${deps.escapeHtml(attachment.name)}">${deps.escapeHtml(text(deps, "memos.removeFile", "REMOVE"))}</button>` : ""}
        </li>
      `;
    }).join("");
    if (!items && !options.editing) return "";
    return `
      <section class="memoAttachments" aria-label="${deps.escapeHtml(text(deps, "memos.attachmentsAria", "Attachments"))}">
        <p>${deps.escapeHtml(text(deps, "common.files", "FILES"))}${items ? ` · ${(attachments || []).length}` : ""}</p>
        ${items ? `<ul class="memoAttachmentList">${items}</ul>` : `<p class="archiveStatusMessage">${deps.escapeHtml(text(deps, "memos.noFiles", "No files attached."))}</p>`}
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
      ? text(deps, "memos.matches", `${memos.resultCount} MATCHES // MEMOS`, { count: memos.resultCount })
      : text(deps, "memos.count", `${memos.totalCount} MEMOS`, { count: memos.totalCount });
    const tagButtons = (Array.isArray(memos.tagOptions) ? memos.tagOptions : [])
      .map((tag) => `<button class="archiveTagChip ${memos.appliedQuery === `#${tag}` ? "isActive" : ""}" type="button" data-memo-tag="${deps.escapeHtml(tag)}">#${deps.escapeHtml(tag)}</button>`)
      .join("");
    const detail = memos.detailLoading
      ? `
        <section class="archiveDetail" data-memo-detail tabindex="-1" aria-busy="true">
          <header class="archiveDetailHeader">
            <div>
              <p>${deps.escapeHtml(text(deps, "memos.detail", "MEMO DETAIL"))}</p>
              <h3 id="memoDetailTitle">${deps.escapeHtml(text(deps, "memos.loadingDetail", "Loading memo..."))}</h3>
            </div>
            <button class="archiveAction" type="button" data-memo-close>${deps.escapeHtml(text(deps, "common.back", "BACK"))}</button>
          </header>
          <p class="archiveStatusMessage">${deps.escapeHtml(text(deps, "memos.readingDetail", "Reading Memos packet..."))}</p>
        </section>
      `
      : memos.detailError
        ? `
          <section class="archiveDetail" data-memo-detail tabindex="-1" aria-labelledby="memoDetailTitle">
            <header class="archiveDetailHeader">
              <div>
                <p>${deps.escapeHtml(text(deps, "memos.detail", "MEMO DETAIL"))}</p>
                <h3 id="memoDetailTitle">${deps.escapeHtml(text(deps, "memos.unavailable", "Memo unavailable"))}</h3>
              </div>
              <button class="archiveAction" type="button" data-memo-close>${deps.escapeHtml(text(deps, "common.back", "BACK"))}</button>
            </header>
            <div class="archiveError" role="alert"><p>${deps.escapeHtml(memos.detailError)}</p></div>
          </section>
        `
        : selected
          ? `
            <section class="archiveDetail" data-memo-detail tabindex="-1" aria-labelledby="memoDetailTitle">
              <header class="archiveDetailHeader">
                <div>
                  <p>${deps.escapeHtml(text(deps, "memos.label", "MEMO"))} #${deps.escapeHtml(deps.memoDisplayNumber(selected))}</p>
                  <h3 id="memoDetailTitle">${deps.escapeHtml(selected.title)}</h3>
                </div>
                <div class="archiveActions memoDetailActions">
                  ${deps.portalProfile() === "main" && !memos.editing ? `<button class="archiveAction" type="button" data-thermal-print="memo" ${memos.deleting ? "disabled" : ""}>${deps.escapeHtml(text(deps, "common.print", "PRINT"))}</button>` : ""}
                  ${memos.editing ? "" : `<button class="archiveAction isActive" type="button" data-memo-edit-start ${memos.deleting ? "disabled" : ""}>${deps.escapeHtml(text(deps, "common.edit", "EDIT"))}</button>`}
                  ${memos.editing ? "" : `<button class="archiveAction memoDeleteAction" type="button" data-memo-delete ${memos.deleting ? "disabled" : ""}>${deps.escapeHtml(text(deps, "common.delete", "DELETE"))}</button>`}
                  <button class="archiveAction" type="button" data-memo-close ${memos.editSaving || memos.deleting ? "disabled" : ""}>${deps.escapeHtml(text(deps, "common.back", "BACK"))}</button>
                </div>
              </header>
              ${
                memos.editing
                  ? `
                    <form class="memoEditForm" data-memo-edit="${deps.escapeHtml(selected.name)}">
                      <label>
                        <span>${deps.escapeHtml(text(deps, "memos.memoText", "MEMO TEXT"))}</span>
                        <textarea name="content" rows="16" data-memo-edit-content>${deps.escapeHtml(memos.editDraft)}</textarea>
                      </label>
                      ${renderAttachmentList(deps, memos.editAttachments, { editing: true })}
                      <div class="memoFilePicker">
                        <span>${deps.escapeHtml(text(deps, "memos.addFiles", "ADD FILES"))}</span>
                        <label class="appFileControl">
                          <input name="files" type="file" multiple data-app-file data-memo-files />
                          <span class="appFileChoose">${deps.escapeHtml(text(deps, "memos.chooseFile", "파일 선택"))}</span>
                          <span class="appFileSelection" data-app-file-selection>${deps.escapeHtml(text(deps, "memos.noFileSelected", "선택한 파일 없음"))}</span>
                        </label>
                      </div>
                      ${memos.editError ? `<p class="formNote isError" role="alert">${deps.escapeHtml(memos.editError)}</p>` : ""}
                      <div class="archiveActions memoEditFormActions">
                        <button class="archiveAction" type="button" data-memo-edit-cancel ${memos.editSaving ? "disabled" : ""}>${deps.escapeHtml(text(deps, "common.cancel", "CANCEL"))}</button>
                        <button class="archiveAction isActive" type="submit" ${memos.editSaving ? "disabled" : ""}>${deps.escapeHtml(memos.editSaving ? text(deps, "common.saving", "SAVING") : text(deps, "common.save", "SAVE"))}</button>
                      </div>
                    </form>
                  `
                  : `
                    <dl class="archiveMetadata">
                      ${deps.archiveMeta(text(deps, "common.updated", "Updated"), selected.updated ? deps.formatDocumentDate(selected.updated) : "")}
                      ${deps.archiveMeta(text(deps, "common.created", "Created"), selected.created ? deps.formatDocumentDate(selected.created) : "")}
                    </dl>
                    ${renderAttachmentList(deps, selected.attachments)}
                    <div class="archiveOcrRegion" role="region" aria-label="${deps.escapeHtml(text(deps, "memos.contentAria", "Memo content"))}" tabindex="0">
                      <p>${deps.escapeHtml(text(deps, "memos.memoText", "MEMO TEXT"))}</p>
                      <article class="memoContent">${deps.renderMemoContent(selected.content)}</article>
                    </div>
                  `
              }
            </section>
          `
          : "";
    return `
      <section class="archiveTerminal" data-archive-kind="memos" aria-label="${deps.escapeHtml(text(deps, "memos.archiveAria", "Memo archive"))}">
        <form class="archiveCommand memoArchiveToolbar" data-memo-search role="search">
          <div class="memoArchiveCommands">
            <button class="archiveAction archiveTopAction ${memos.toolbarPanel === "search" ? "isActive" : ""}" type="button" data-memos-toolbar="search" aria-expanded="${memos.toolbarPanel === "search"}">${deps.escapeHtml(text(deps, "memos.search", "Search"))}</button>
            <button class="archiveAction archiveTopAction ${memos.toolbarPanel === "tags" ? "isActive" : ""}" type="button" data-memos-toolbar="tags" aria-expanded="${memos.toolbarPanel === "tags"}">${deps.escapeHtml(text(deps, "memos.tags", "Tags"))}</button>
            <button class="archiveAction archiveTopAction" type="button" data-memos-refresh aria-label="${deps.escapeHtml(text(deps, "memos.reloadAria", "Reload memos"))}" title="${deps.escapeHtml(text(deps, "memos.reloadAria", "Reload memos"))}" ${memos.loading ? "disabled" : ""}>${deps.escapeHtml(text(deps, "memos.reload", "Reload"))}</button>
          </div>
          ${memos.toolbarPanel === "search" ? `
            <label class="archiveSearchBox memoToolbarPanel" for="memoQuery">
              <span class="archiveSearchIcon" aria-hidden="true">⌕</span>
              <input id="memoQuery" name="query" type="search" value="${deps.escapeHtml(memos.query)}" placeholder="${deps.escapeHtml(text(deps, "memos.searchPlaceholder", "Search memos"))}" autocomplete="off" />
              ${memos.appliedQuery ? `<button class="archiveSearchClear" type="button" data-memos-clear aria-label="${deps.escapeHtml(text(deps, "memos.clearSearch", "Clear memo search"))}">×</button>` : ""}
            </label>
          ` : `<input type="hidden" name="query" value="${deps.escapeHtml(memos.query)}" />`}
          ${memos.toolbarPanel === "tags" ? `
            <div class="archiveTagFilters memoToolbarPanel" aria-label="${deps.escapeHtml(text(deps, "memos.tagsAria", "Memo tags"))}">
              ${tagButtons || `<p class="archiveTagStatus">${deps.escapeHtml(text(deps, "memos.noTags", "No tags found."))}</p>`}
            </div>
          ` : ""}
          <button class="srOnly" type="submit">${deps.escapeHtml(text(deps, "memos.search", "Search"))}</button>
        </form>
        <div class="archiveWorkspace ${hasDetail ? "hasDetail" : ""}">
          <section class="archiveIndex" aria-labelledby="memosIndexTitle" aria-busy="${memos.loading}">
            <header class="archiveIndexHeader">
              <h3 id="memosIndexTitle">${deps.escapeHtml(text(deps, "memos.board", "RECORD BOARD"))}</h3>
              <p class="archiveStatusMessage" role="status" aria-live="polite">${memos.checked && !memos.error ? deps.escapeHtml(summary) : deps.escapeHtml(memos.loading ? text(deps, "memos.loadingBoard", "LOADING MEMO BOARD") : text(deps, "memos.boardStandby", "MEMO BOARD STANDBY"))}</p>
            </header>
            <div class="archiveColumnHeader" aria-hidden="true">
              <span>${deps.escapeHtml(text(deps, "memos.columnNumber", "NO."))}</span><span>${deps.escapeHtml(text(deps, "memos.columnDate", "DATE"))}</span><span>${deps.escapeHtml(text(deps, "memos.columnTitle", "TITLE"))}</span>
            </div>
            ${
              memos.error
                ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(memos.error)}</p><button class="archiveAction" type="button" data-memos-refresh>${deps.escapeHtml(text(deps, "common.retry", "RETRY"))}</button></div>`
                : memos.loading && !memos.checked
                  ? `<p class="archiveStatusMessage">${deps.escapeHtml(text(deps, "memos.readingArchive", "Reading Memos archive..."))}</p>`
                  : !memos.error && memos.checked && !rows
                    ? `<p class="archiveStatusMessage">${deps.escapeHtml(text(deps, "memos.noMatches", "No matching memos."))}</p>`
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
