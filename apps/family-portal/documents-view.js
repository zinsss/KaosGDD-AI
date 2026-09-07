window.KAOS_DOCUMENTS_VIEW = (() => {
  function renderDocuments(deps) {
    const documents = deps.state.documents;
    const archiveActive = documents.mode !== "inbox";
    const inboxActive = documents.mode === "inbox";
    const selectedInbox = inboxActive
      ? documents.inboxItems.find((item) => item.id === documents.selectedInboxId) || null
      : null;
    const inboxRecordByDocumentId = documents.inboxItems.reduce((records, item) => {
      if (item.documentId) records.set(String(item.documentId), item);
      return records;
    }, new Map());
    const inboxRows = documents.inboxItems
      .map((item) => {
        const date = deps.archiveDateParts(item.submittedAt);
        const statusClass = item.status === "failed" ? "isError" : item.status === "archived" ? "isOk" : "";
        const sourceLink = item.url
          ? `<a class="archiveSourceLink" href="${deps.escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${deps.escapeHtml(item.title)} in Paperless" title="Open in Paperless">SRC</a>`
          : `<span class="archiveSourceLink isDisabled">${deps.escapeHtml(item.taskId ? "OCR" : "--")}</span>`;
        return `
          <li class="archiveRecord ${String(documents.selectedInboxId) === String(item.id) ? "isSelected" : ""}">
            <button class="archiveRecordButton" type="button" data-document-inbox-open="${deps.escapeHtml(item.id)}" aria-current="${String(documents.selectedInboxId) === String(item.id) ? "true" : "false"}">
              <span class="archiveRecordId">#${deps.escapeHtml(item.id)}</span>
              <time class="archiveRecordDate" datetime="${deps.escapeHtml(date.raw)}">${deps.escapeHtml(date.label)}</time>
              <strong class="archiveRecordTitle">${deps.escapeHtml(item.title || "Document")}</strong>
              <span class="archiveRecordStatus ${statusClass}">${deps.escapeHtml(item.statusLabel)}</span>
            </button>
            ${sourceLink}
          </li>
        `;
      })
      .join("");
    const rows = documents.items
      .map((item) => {
        const title = item.title || `Document ${item.id}`;
        const date = deps.archiveDateParts(item.created);
        const reviewRecord = inboxRecordByDocumentId.get(String(item.id));
        const reviewLabel = reviewRecord?.status === "failed" ? "FAILED" : reviewRecord ? "REVIEW" : "";
        return `
          <li class="archiveRecord ${String(documents.selectedId) === String(item.id) ? "isSelected" : ""}">
            <button class="archiveRecordButton" type="button" data-paperless-open="${deps.escapeHtml(item.id)}" aria-current="${String(documents.selectedId) === String(item.id) ? "true" : "false"}">
              <span class="archiveRecordId">#${deps.escapeHtml(item.id)}</span>
              <time class="archiveRecordDate" datetime="${deps.escapeHtml(date.raw)}">${deps.escapeHtml(date.label)}</time>
              <strong class="archiveRecordTitle">${deps.escapeHtml(title)}${reviewLabel ? `<span class="archiveReviewMarker">${deps.escapeHtml(reviewLabel)}</span>` : ""}</strong>
            </button>
            ${item.url ? `<a class="archiveSourceLink" href="${deps.escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${deps.escapeHtml(title)} in Paperless" title="Open in Paperless">SRC</a>` : `<span class="archiveSourceLink isDisabled">--</span>`}
          </li>
        `;
      })
      .join("");
    const activeTags = documents.selectedTags || [];
    const hasFilters = Boolean(documents.appliedQuery || activeTags.length);
    const filterLabel = [
      documents.appliedQuery ? `${documents.resultCount} MATCHES` : "",
      activeTags.length ? `TAGS ${activeTags.map((tag) => `#${tag}`).join(" ")}` : "",
    ].filter(Boolean).join(" // ");
    const summary = hasFilters
      ? `${filterLabel} // ${documents.totalCount} DOCUMENTS`
      : `${documents.totalCount} DOCUMENTS`;
    const tagFilters = documents.tagsLoading
      ? `<p class="archiveStatusMessage archiveTagStatus">LOADING TAGS</p>`
      : documents.tagsError
        ? `<p class="archiveStatusMessage archiveTagStatus">${deps.escapeHtml(documents.tagsError)}</p>`
        : documents.tagOptions.length
          ? `
            <div class="archiveTagFilters" aria-label="Document tag filters">
              ${documents.tagOptions.map((tag) => {
                const active = activeTags.some((name) => name.toLowerCase() === tag.name.toLowerCase());
                return `<button class="archiveTagChip ${active ? "isActive" : ""}" type="button" data-document-tag="${deps.escapeHtml(tag.name)}" aria-pressed="${active}">#${deps.escapeHtml(tag.name)}</button>`;
              }).join("")}
              ${activeTags.length ? `<button class="archiveAction archiveClearTags" type="button" data-documents-clear-tags>CLEAR TAGS</button>` : ""}
            </div>
          `
          : "";
    const selected = documents.selected;
    const selectedReviewRecord = selected ? inboxRecordByDocumentId.get(String(selected.id)) || null : null;
    const hasDetail = documents.detailLoading || documents.detailError || selected;
    const detail = documents.detailLoading
      ? `
        <section class="archiveDetail" data-paperless-detail tabindex="-1" aria-busy="true">
          <header class="archiveDetailHeader">
            <div>
              <p>DOCUMENT DETAIL</p>
              <h3 id="archiveDetailTitle">Loading document...</h3>
            </div>
            <button class="archiveAction" type="button" data-paperless-close>BACK</button>
          </header>
          <p class="archiveStatusMessage">Reading OCR packet...</p>
        </section>
      `
      : documents.detailError
        ? `
          <section class="archiveDetail" data-paperless-detail tabindex="-1" aria-labelledby="archiveDetailTitle">
            <header class="archiveDetailHeader">
              <div>
                <p>DOCUMENT DETAIL</p>
                <h3 id="archiveDetailTitle">Document unavailable</h3>
              </div>
              <button class="archiveAction" type="button" data-paperless-close>BACK</button>
            </header>
            <div class="archiveError" role="alert"><p>${deps.escapeHtml(documents.detailError)}</p></div>
          </section>
        `
        : selected
          ? `
            <section class="archiveDetail" data-paperless-detail tabindex="-1" aria-labelledby="archiveDetailTitle">
              <header class="archiveDetailHeader">
                <div>
                  <p>PAPERLESS #${deps.escapeHtml(selected.id)}</p>
                  <h3 id="archiveDetailTitle">${deps.escapeHtml(selected.title || `Document ${selected.id}`)}</h3>
                </div>
                <button class="archiveAction" type="button" data-paperless-close>BACK</button>
              </header>
              <dl class="archiveMetadata">
                ${deps.archiveMeta("Correspondent", selected.correspondent || "unknown")}
                ${deps.archiveMeta("Created", selected.created ? deps.formatDocumentDate(selected.created) : "")}
                ${deps.archiveMeta("File", selected.filename || "unknown")}
                ${deps.archiveMeta("Tags", selected.tags?.length ? selected.tags.map((tag) => `#${tag}`).join(" ") : "none")}
                ${selectedReviewRecord ? deps.archiveMeta("Inbox", selectedReviewRecord.statusLabel || "REVIEW") : ""}
              </dl>
              <div class="archiveActions">
                ${selected.url ? `<a class="archiveAction" href="${deps.escapeHtml(selected.url)}" target="_blank" rel="noopener noreferrer">OPEN PAPERLESS</a>` : ""}
              </div>
              ${deps.renderDocumentMetadataReview({ documentId: selected.id, recordId: selectedReviewRecord?.id || "", title: selected.title, tags: selected.tags })}
              <div class="archiveOcrRegion" role="region" aria-label="OCR text" tabindex="0">
                <p>OCR TEXT</p>
                <pre>${deps.escapeHtml(selected.content || "No recognized text.")}</pre>
              </div>
            </section>
          `
          : "";
    const inboxDetail = selectedInbox
      ? (() => {
        const metadataReview = deps.renderDocumentMetadataReview({
          documentId: selectedInbox.documentId,
          recordId: selectedInbox.id,
          title: selectedInbox.title,
        });
        return `
        <section class="archiveDetail" data-document-inbox-detail tabindex="-1" aria-labelledby="documentInboxDetailTitle">
          <header class="archiveDetailHeader">
            <div>
              <p>INBOX #${deps.escapeHtml(selectedInbox.id)}</p>
              <h3 id="documentInboxDetailTitle">${deps.escapeHtml(selectedInbox.title || "Document")}</h3>
            </div>
            <button class="archiveAction" type="button" data-document-inbox-close>BACK</button>
          </header>
          <dl class="archiveMetadata">
            ${deps.archiveMeta("Status", selectedInbox.statusLabel)}
            ${deps.archiveMeta("Submitted", selectedInbox.submittedAt ? deps.formatDocumentDate(selectedInbox.submittedAt) : "")}
            ${deps.archiveMeta("Updated", selectedInbox.updatedAt ? deps.formatDocumentDate(selectedInbox.updatedAt) : "")}
            ${deps.archiveMeta("File", selectedInbox.filename)}
            ${deps.archiveMeta("Size", deps.formatBytes(selectedInbox.sizeBytes))}
            ${deps.archiveMeta("Task", selectedInbox.taskId)}
            ${deps.archiveMeta("SHA", selectedInbox.sha256 ? selectedInbox.sha256.slice(0, 16) : "")}
            ${selectedInbox.error ? deps.archiveMeta("Error", selectedInbox.error) : ""}
          </dl>
          <div class="archiveActions">
            <button class="archiveAction" type="button" data-document-inbox-refresh-status ${documents.inboxLoading ? "disabled" : ""}>↻ STATUS</button>
            ${
              selectedInbox.documentId
                ? `<button class="archiveAction isActive" type="button" data-document-inbox-paperless="${deps.escapeHtml(selectedInbox.documentId)}">OPEN DETAIL</button>`
                : ""
            }
            ${
              selectedInbox.url
                ? `<a class="archiveAction" href="${deps.escapeHtml(selectedInbox.url)}" target="_blank" rel="noopener noreferrer">SRC</a>`
                : ""
            }
          </div>
          ${metadataReview}
        </section>
      `;
      })()
      : "";
    const modeTabs = `
      <div class="segmentedTabs archiveModeTabs" role="tablist" aria-label="Document board mode">
        <button type="button" role="tab" data-document-mode="archive" aria-selected="${archiveActive}" class="${archiveActive ? "isActive" : ""}">Archive</button>
        <button type="button" role="tab" data-document-mode="inbox" aria-selected="${inboxActive}" class="${inboxActive ? "isActive" : ""}">Inbox</button>
      </div>
    `;
    const archiveBoard = `
      <form class="archiveCommand archiveSearchBar" data-document-search role="search">
        <label class="archiveSearchBox" for="paperlessQuery">
          <span class="archiveSearchIcon" aria-hidden="true">⌕</span>
          <input id="paperlessQuery" name="query" type="search" value="${deps.escapeHtml(documents.query)}" placeholder="Search documents" autocomplete="off" />
          ${documents.appliedQuery ? `<button class="archiveSearchClear" type="button" data-documents-clear aria-label="Clear document search">×</button>` : ""}
        </label>
        <button class="archiveAction archiveTopAction" type="button" data-documents-refresh aria-label="Refresh documents" title="Refresh documents" ${documents.loading ? "disabled" : ""}>↻</button>
        <button class="srOnly" type="submit">Search</button>
      </form>
      ${tagFilters}
      <div class="archiveWorkspace ${hasDetail ? "hasDetail" : ""}">
        <section class="archiveIndex" aria-labelledby="documentsIndexTitle" aria-busy="${documents.loading}">
          <header class="archiveIndexHeader">
            <h3 id="documentsIndexTitle">RECORD BOARD</h3>
            <p class="archiveStatusMessage" role="status" aria-live="polite">${documents.checked && !documents.error ? deps.escapeHtml(summary) : documents.loading ? "LOADING DOCUMENT BOARD" : "DOCUMENT BOARD STANDBY"}</p>
          </header>
          <div class="archiveColumnHeader" aria-hidden="true">
            <span>NO.</span><span>DATE</span><span>TITLE</span>
          </div>
          ${
            documents.error
              ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(documents.error)}</p><button class="archiveAction" type="button" data-documents-refresh>RETRY</button></div>`
              : documents.loading && !documents.checked
                ? `<p class="archiveStatusMessage">Searching Paperless archive...</p>`
                : !documents.error && documents.checked && !rows
                  ? `<p class="archiveStatusMessage">No matching documents.</p>`
                  : rows
                    ? `<ol class="archiveRecordList">${rows}</ol>`
                    : ""
          }
          ${
            !documents.error && documents.checked && documents.pageCount > 1
              ? `
                <nav class="archivePager" aria-label="Document pages">
                  <button class="archiveAction" type="button" aria-label="Previous document page" data-documents-page="${documents.page - 1}" ${documents.page <= 1 ? "disabled" : ""}>&lt;</button>
                  <span>PAGE ${documents.page}/${documents.pageCount}</span>
                  <button class="archiveAction" type="button" aria-label="Next document page" data-documents-page="${documents.page + 1}" ${documents.page >= documents.pageCount ? "disabled" : ""}>&gt;</button>
                </nav>
              `
              : ""
          }
        </section>
        ${detail}
      </div>
    `;
    const inboxBoard = `
      <div class="archiveWorkspace ${selectedInbox ? "hasDetail" : ""}">
        <section class="archiveIndex" aria-labelledby="documentsInboxTitle" aria-busy="${documents.inboxLoading}">
          <header class="archiveIndexHeader">
            <h3 id="documentsInboxTitle">INBOX BOARD</h3>
            <p class="archiveStatusMessage" role="status">${
              documents.inboxChecked && !documents.inboxError
                ? `${documents.inboxItems.length} RECORDS // OCR QUEUE`
                : documents.inboxLoading
                  ? "LOADING DOCUMENT INBOX"
                  : "DOCUMENT INBOX STANDBY"
            }</p>
          </header>
          <div class="archiveColumnHeader" aria-hidden="true">
            <span>NO.</span><span>DATE</span><span>TITLE</span>
          </div>
          ${
            documents.inboxError
              ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(documents.inboxError)}</p><button class="archiveAction" type="button" data-documents-refresh>RETRY</button></div>`
              : documents.inboxLoading && !documents.inboxChecked
                ? `<p class="archiveStatusMessage">Reading document intake board...</p>`
                : documents.inboxChecked && !inboxRows
                  ? `<p class="archiveStatusMessage">No pending document intake records.</p>`
                  : inboxRows
                    ? `<ol class="archiveRecordList">${inboxRows}</ol>`
                    : ""
          }
        </section>
        ${inboxDetail}
      </div>
    `;
    return `
      <section class="archiveTerminal" data-archive-kind="documents" aria-label="Document archive">
        ${modeTabs}
        ${archiveActive ? archiveBoard : inboxBoard}
      </section>
    `;
  }

  return { renderDocuments };
})();
