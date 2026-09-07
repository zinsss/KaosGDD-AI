window.KAOS_MEMOS_VIEW = (() => {
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
                <button class="archiveAction" type="button" data-memo-close>BACK</button>
              </header>
              <dl class="archiveMetadata">
                ${deps.archiveMeta("Updated", selected.updated ? deps.formatDocumentDate(selected.updated) : "")}
                ${deps.archiveMeta("Created", selected.created ? deps.formatDocumentDate(selected.created) : "")}
              </dl>
              <div class="archiveOcrRegion" role="region" aria-label="Memo content" tabindex="0">
                <p>MEMO TEXT</p>
                <pre>${deps.escapeHtml(selected.content || "No memo content.")}</pre>
              </div>
            </section>
          `
          : "";
    return `
      <section class="archiveTerminal" data-archive-kind="memos" aria-label="Memo archive">
        <form class="archiveCommand archiveSearchBar" data-memo-search role="search">
          <label class="archiveSearchBox" for="memoQuery">
            <span class="archiveSearchIcon" aria-hidden="true">⌕</span>
            <input id="memoQuery" name="query" type="search" value="${deps.escapeHtml(memos.query)}" placeholder="Search memos" autocomplete="off" />
            ${memos.appliedQuery ? `<button class="archiveSearchClear" type="button" data-memos-clear aria-label="Clear memo search">×</button>` : ""}
          </label>
          <button class="archiveAction archiveTopAction" type="button" data-memos-refresh aria-label="Refresh memos" title="Refresh memos" ${memos.loading ? "disabled" : ""}>↻</button>
          <a class="archiveAction archiveTopAction" href="#/add-memo">NEW</a>
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
