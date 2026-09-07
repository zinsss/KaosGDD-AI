window.KAOS_FAX_VIEW = (() => {
  function renderFax(deps) {
    const fax = deps.state.fax;
    const faxApi = window.KAOS_PORTAL_FAX;
    const mode = faxApi.normalizeMode(fax.mode);
    const items = faxApi.filterItems(fax.items, mode);
    const selected = fax.items.find((item) => item.key === fax.selectedKey) || null;
    const hasDetail = Boolean(selected);
    const modeButtons = faxApi.modes
      .map((itemMode) => {
        const active = itemMode === mode;
        return `<button class="archiveAction ${active ? "isActive" : ""}" type="button" data-fax-mode="${deps.escapeHtml(itemMode)}" aria-pressed="${active}">${deps.escapeHtml(itemMode.toUpperCase())}</button>`;
      })
      .join("");
    const rows = items
      .map((item) => {
        const date = deps.formatFaxDate(item);
        const title = item.title || item.filename || "Fax";
        return `
          <li class="archiveRecord ${selected?.key === item.key ? "isSelected" : ""}">
            <button class="archiveRecordButton" type="button" data-fax-open="${deps.escapeHtml(item.key)}" aria-current="${selected?.key === item.key ? "true" : "false"}">
              <span class="archiveRecordId">${deps.escapeHtml(item.direction === "incoming" ? "IN" : "OUT")} ${deps.escapeHtml(item.id.slice(0, 6).toUpperCase())}</span>
              <time class="archiveRecordDate" datetime="${deps.escapeHtml(date.raw)}">${deps.escapeHtml(date.label)}</time>
              <strong class="archiveRecordTitle">${deps.escapeHtml(title)}</strong>
            </button>
            ${
              item.documentAvailable && item.documentUrl
                ? `<a class="archiveSourceLink" href="${deps.escapeHtml(item.documentUrl)}" target="_blank" rel="noopener noreferrer" aria-label="Open fax PDF" title="Open fax PDF">PDF</a>`
                : `<span class="archiveSourceLink isDisabled" aria-label="No retained PDF">--</span>`
            }
          </li>
        `;
      })
      .join("");
    const detail = selected
      ? `
        <section class="archiveDetail" data-fax-detail tabindex="-1" aria-labelledby="faxDetailTitle">
          <header class="archiveDetailHeader">
            <div>
              <p>${deps.escapeHtml(selected.direction === "incoming" ? "RECEIVED FAX" : "SENT FAX")} #${deps.escapeHtml(selected.id.slice(0, 8).toUpperCase())}</p>
              <h3 id="faxDetailTitle">${deps.escapeHtml(selected.title || selected.filename || "Fax")}</h3>
            </div>
            <button class="archiveAction" type="button" data-fax-close>BACK</button>
          </header>
          <dl class="archiveMetadata">
            ${deps.archiveMeta("Direction", selected.direction === "incoming" ? "Incoming" : "Outgoing")}
            ${deps.archiveMeta("Status", selected.status || "unknown")}
            ${deps.archiveMeta("Remote", selected.remote || selected.destination || "unknown")}
            ${deps.archiveMeta("Pages", selected.pages || "unknown")}
            ${deps.archiveMeta("Received", selected.receivedAt || selected.completedAt || selected.createdAt || "")}
            ${deps.archiveMeta("Archived", selected.archivedAt || "")}
            ${deps.archiveMeta("HylaFAX Job", selected.hylafaxJobId || "")}
            ${selected.error ? deps.archiveMeta("Error", selected.error) : ""}
          </dl>
          <div class="archiveActions">
            ${
              selected.direction === "outgoing" && selected.status === "failed"
                ? selected.attentionAcknowledged
                  ? `<span class="archiveAction isDisabled">ACKNOWLEDGED</span>`
                  : `<button class="archiveAction isActive" type="button" data-fax-ack="${deps.escapeHtml(selected.id)}">ACK</button>`
                : ""
            }
            ${
              selected.documentAvailable && selected.documentUrl
                ? `<a class="archiveAction" href="${deps.escapeHtml(selected.documentUrl)}" target="_blank" rel="noopener noreferrer">OPEN PDF</a>`
                : `<span class="archiveAction isDisabled">PDF NOT RETAINED</span>`
            }
          </div>
        </section>
      `
      : "";
    const summary = fax.checked && !fax.error
      ? `${items.length} RECORDS // ${mode.toUpperCase()} BOARD`
      : fax.loading
        ? "LOADING FAX BOARD"
        : "FAX BOARD STANDBY";
    return `
      <section class="archiveTerminal" data-archive-kind="fax" aria-label="Fax board">
        <div class="archiveCommand" aria-label="Fax board modes">
          <div class="archiveCommandActions">${modeButtons}</div>
          <button class="archiveAction archiveRefreshAction" type="button" data-fax-refresh aria-label="Refresh fax board" title="Refresh fax board" ${fax.loading ? "disabled" : ""}>↻</button>
        </div>
        <div class="archiveWorkspace ${hasDetail ? "hasDetail" : ""}">
          <section class="archiveIndex" aria-labelledby="faxIndexTitle" aria-busy="${fax.loading}">
            <header class="archiveIndexHeader">
              <h3 id="faxIndexTitle">RECORD BOARD</h3>
              <p class="archiveStatusMessage" role="status" aria-live="polite">${deps.escapeHtml(summary)}</p>
            </header>
            <div class="archiveColumnHeader" aria-hidden="true">
              <span>NO.</span><span>DATE</span><span>TITLE</span>
            </div>
            ${
              fax.error
                ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(fax.error)}</p><button class="archiveAction" type="button" data-fax-refresh>RETRY</button></div>`
                : fax.loading && !fax.checked
                  ? `<p class="archiveStatusMessage">Reading HylaFAX archive...</p>`
                  : rows
                    ? `<ol class="archiveRecordList">${rows}</ol>`
                    : `<p class="archiveStatusMessage">No fax records on this board.</p>`
            }
          </section>
          ${detail}
        </div>
      </section>
    `;
  }

  return { renderFax };
})();
