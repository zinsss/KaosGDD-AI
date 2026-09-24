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
        return `<button class="archiveAction archiveTopAction ${active ? "isActive" : ""}" type="button" data-fax-mode="${deps.escapeHtml(itemMode)}" aria-pressed="${active}">${deps.escapeHtml(itemMode.toUpperCase())}</button>`;
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
    const proposal = fax.compose?.proposal;
    const composer = fax.compose?.open
      ? `
        <section class="archiveDetail faxSendComposer" aria-labelledby="faxSendTitle">
          <header class="archiveDetailHeader">
            <div><p>OUTGOING FAX</p><h3 id="faxSendTitle">Send fax</h3></div>
            <button class="archiveAction" type="button" data-fax-send-cancel ${fax.compose.saving ? "disabled" : ""}>Cancel</button>
          </header>
          ${proposal ? `
            <dl class="archiveMetadata">
              ${deps.archiveMeta("Destination", proposal.fax?.destination || "")}
              ${deps.archiveMeta("File", proposal.fax?.filename || "")}
              ${deps.archiveMeta("Pages", String(proposal.fax?.pageCount || ""))}
            </dl>
            <p class="archiveStatusMessage">Check the destination and document before transmitting.</p>
            <div class="archiveActions">
              <button class="archiveAction isActive" type="button" data-fax-send-approve ${fax.compose.saving ? "disabled" : ""}>${fax.compose.saving ? "Sending…" : "Send"}</button>
              <button class="archiveAction" type="button" data-fax-send-cancel ${fax.compose.saving ? "disabled" : ""}>Cancel</button>
            </div>
          ` : `
            <form class="faxSendForm" data-fax-send-form>
              <label><span>FAX NUMBER</span><input name="destination" type="tel" inputmode="tel" autocomplete="tel" placeholder="02-1234-5678" required></label>
              <label><span>PDF OR IMAGE</span><input name="document" type="file" accept="application/pdf,image/jpeg,image/png,image/webp,image/tiff,image/bmp" required></label>
              ${fax.compose?.error ? `<p class="archiveError" role="alert">${deps.escapeHtml(fax.compose.error)}</p>` : ""}
              <button class="archiveAction isActive" type="submit" ${fax.compose?.saving ? "disabled" : ""}>${fax.compose?.saving ? "Preparing…" : "Review"}</button>
            </form>
          `}
          ${proposal && fax.compose?.error ? `<p class="archiveError" role="alert">${deps.escapeHtml(fax.compose.error)}</p>` : ""}
        </section>
      `
      : "";
    return `
      <section class="archiveTerminal" data-archive-kind="fax" aria-label="Fax board">
        ${composer}
        <div class="archiveCommand faxArchiveToolbar" aria-label="Fax board actions">
          <div class="faxArchiveCommands">
            ${modeButtons}
            <button class="archiveAction archiveTopAction" type="button" data-fax-refresh aria-label="Reload fax board" title="Reload fax board" ${fax.loading ? "disabled" : ""}>Reload</button>
          </div>
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
