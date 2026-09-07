window.KAOS_MAIL_VIEW = (() => {
  function renderMail(deps) {
    const mail = deps.state.mail;
    const mailApi = window.KAOS_PORTAL_MAIL;
    const mode = mailApi.normalizeMode(mail.mode);
    const items = mode === "unread" ? mail.unreadItems : mailApi.filterItems(mail.items, mode);
    const activeLoading = mode === "unread" ? mail.unreadLoading || mail.unreadApplying : mail.loading;
    const activeChecked = mode === "unread" ? mail.unreadChecked : mail.checked;
    const activeError = mode === "unread" ? mail.unreadError : mail.error;
    const activeErrorActions = activeError
      ? `
        <div class="archiveActions">
          ${deps.isMailAccessError(activeError) ? `<a class="archiveAction isActive" href="${deps.escapeHtml(deps.mailReloginUrl())}" target="_blank" rel="noopener">RELOGIN</a>` : ""}
          <button class="archiveAction" type="button" data-mail-refresh>RETRY</button>
        </div>
      `
      : "";
    const selectedListItem = items.find((item) => item.id === mail.selectedKey) || null;
    const selected = mail.selected || selectedListItem;
    const hasDetail = mail.detailLoading || mail.detailError || Boolean(selected);
    const unreadReadCount = mode === "unread" ? items.filter((item) => deps.unreadMailAction(item) === "read").length : 0;
    const unreadDeleteCount = mode === "unread" ? items.filter((item) => deps.unreadMailAction(item) === "delete").length : 0;
    const modeButtons = mailApi.modes
      .map((itemMode) => {
        const active = itemMode === mode;
        const label = mailApi.modeLabels[itemMode] || itemMode.toUpperCase();
        return `<button class="archiveAction ${active ? "isActive" : ""}" type="button" data-mail-mode="${deps.escapeHtml(itemMode)}" aria-pressed="${active}">${deps.escapeHtml(label)}</button>`;
      })
      .join("");
    const modeLabel = mailApi.modeLabels[mode] || mode.toUpperCase();
    const rows = items
      .map((item) => {
        const date = deps.archiveDateParts(item.receivedAt);
        const selectedAction = deps.unreadMailAction(item);
        const unreadActions = mode === "unread"
          ? `
            <fieldset class="archiveUnreadActions" aria-label="Unread mail action for ${deps.escapeHtml(item.subject)}">
              <label class="${selectedAction === "read" ? "isSelected" : ""}">
                <input type="checkbox" data-mail-unread-action="read" data-mail-unread-key="${deps.escapeHtml(item.id)}" ${selectedAction === "read" ? "checked" : ""} />
                <span>READ</span>
              </label>
              <label class="${selectedAction === "delete" ? "isSelected" : ""}">
                <input type="checkbox" data-mail-unread-action="delete" data-mail-unread-key="${deps.escapeHtml(item.id)}" ${selectedAction === "delete" ? "checked" : ""} />
                <span>DEL</span>
              </label>
            </fieldset>
          `
          : `<span class="archiveSourceLink isDisabled">${deps.escapeHtml(item.attachmentCount ? `ATT ${item.attachmentCount}` : "MAIL")}</span>`;
        return `
          <li class="archiveRecord ${mode === "unread" ? "hasUnreadActions" : ""} ${selectedListItem?.id === item.id ? "isSelected" : ""}">
            <button class="archiveRecordButton" type="button" data-mail-open="${deps.escapeHtml(item.id)}" aria-current="${selectedListItem?.id === item.id ? "true" : "false"}">
              <span class="archiveRecordId">#${deps.escapeHtml(item.uid)}</span>
              <time class="archiveRecordDate" datetime="${deps.escapeHtml(date.raw)}">${deps.escapeHtml(date.label)}</time>
              <strong class="archiveRecordTitle">${deps.escapeHtml(item.subject)}</strong>
            </button>
            ${unreadActions}
          </li>
        `;
      })
      .join("");
    const summary = mail.unreadApplying
      ? "APPLYING UNREAD MAIL ACTIONS"
      : activeChecked && !activeError
        ? mode === "unread"
          ? `${items.length} UNREAD // ${unreadReadCount} READ // ${unreadDeleteCount} DEL`
          : `${items.length} MESSAGES // ${modeLabel} BOARD`
        : activeLoading
          ? "LOADING MAIL BOARD"
          : "MAIL BOARD STANDBY";
    const attachmentRows = selected?.attachments?.length
      ? selected.attachments
        .map(
          (attachment, index) => {
            const attachmentIndex = attachment.index || index + 1;
            return `
            <div>
              <dt>ATT ${deps.escapeHtml(attachmentIndex)}</dt>
              <dd>
                <a class="archiveInlineLink" href="${deps.escapeHtml(deps.mailAttachmentUrl(selected, attachmentIndex))}" target="_blank" rel="noopener">
                  ${deps.escapeHtml(attachment.filename)}
                </a>
                · ${deps.escapeHtml(attachment.contentType)} · ${deps.escapeHtml(deps.formatBytes(attachment.sizeBytes))}
              </dd>
            </div>
          `;
          },
        )
        .join("")
      : "";
    const detail = mail.detailLoading
      ? `
        <section class="archiveDetail" data-mail-detail tabindex="-1" aria-busy="true">
          <header class="archiveDetailHeader">
            <div>
              <p>MAIL DETAIL</p>
              <h3 id="mailDetailTitle">Loading mail...</h3>
            </div>
            <button class="archiveAction" type="button" data-mail-close>BACK</button>
          </header>
          <p class="archiveStatusMessage">Reading Naver Mail body with PEEK...</p>
        </section>
      `
      : mail.detailError
        ? `
          <section class="archiveDetail" data-mail-detail tabindex="-1" aria-labelledby="mailDetailTitle">
            <header class="archiveDetailHeader">
              <div>
                <p>MAIL DETAIL</p>
                <h3 id="mailDetailTitle">Mail unavailable</h3>
            </div>
            <button class="archiveAction" type="button" data-mail-close>BACK</button>
          </header>
            <div class="archiveError" role="alert">
              <p>${deps.escapeHtml(mail.detailError)}</p>
              ${
                deps.isMailAccessError(mail.detailError)
                  ? `<a class="archiveAction isActive" href="${deps.escapeHtml(deps.mailReloginUrl())}" target="_blank" rel="noopener">RELOGIN</a>`
                  : ""
              }
            </div>
          </section>
        `
        : selected
          ? `
        <section class="archiveDetail" data-mail-detail tabindex="-1" aria-labelledby="mailDetailTitle">
          <header class="archiveDetailHeader">
            <div>
              <p>MAIL #${deps.escapeHtml(selected.uid)}</p>
              <h3 id="mailDetailTitle">${deps.escapeHtml(selected.subject)}</h3>
            </div>
            <button class="archiveAction" type="button" data-mail-close>BACK</button>
          </header>
          <dl class="archiveMetadata">
            ${deps.archiveMeta("Mailbox", selected.mailbox)}
            ${deps.archiveMeta("From", selected.sender || "unknown")}
            ${deps.archiveMeta("Received", selected.receivedAt ? deps.formatDocumentDate(selected.receivedAt) : "")}
            ${deps.archiveMeta("Attachments", selected.attachmentCount ? String(selected.attachmentCount) : "")}
            ${attachmentRows}
          </dl>
          <div class="archiveOcrRegion" role="region" aria-label="Mail preview" tabindex="0">
            <p>BODY</p>
            <pre>${deps.escapeHtml(selected.preview || "No readable text body.")}</pre>
          </div>
        </section>
      `
          : "";
    return `
      <section class="archiveTerminal" data-archive-kind="mail" aria-label="Mail board">
        <div class="archiveCommand" aria-label="Mail board actions">
          <div class="archiveCommandActions">${modeButtons}</div>
          <button class="archiveAction archiveRefreshAction" type="button" data-mail-refresh aria-label="Refresh mail board" title="Refresh mail board" ${activeLoading ? "disabled" : ""}>↻</button>
        </div>
        <div class="archiveWorkspace ${hasDetail ? "hasDetail" : ""}">
          <section class="archiveIndex" aria-labelledby="mailIndexTitle" aria-busy="${activeLoading}">
            <header class="archiveIndexHeader">
              <h3 id="mailIndexTitle">RECORD BOARD</h3>
              <p class="archiveStatusMessage" role="status" aria-live="polite">${deps.escapeHtml(summary)}</p>
            </header>
            <div class="archiveColumnHeader" aria-hidden="true">
              <span>NO.</span><span>DATE</span><span>TITLE</span>
            </div>
            ${
              activeError
                ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(activeError)}</p>${activeErrorActions}</div>`
                : activeLoading && !activeChecked
                  ? `<p class="archiveStatusMessage">${mode === "unread" ? "Reading unread Naver Mail..." : "Reading Naver Mail headers..."}</p>`
                  : activeChecked && !rows
                    ? `<p class="archiveStatusMessage">No messages on this board.</p>`
                    : rows
                      ? `<ol class="archiveRecordList">${rows}</ol>${
                          mode === "unread"
                            ? `<div class="archiveUnreadApplyBar">
                                <p>${deps.escapeHtml(unreadReadCount)} READ // ${deps.escapeHtml(unreadDeleteCount)} DEL</p>
                                <button class="archiveAction isActive" type="button" data-mail-unread-apply ${mail.unreadApplying || !items.length ? "disabled" : ""}>${mail.unreadApplying ? "APPLYING" : "APPLY"}</button>
                              </div>`
                            : ""
                        }`
                      : ""
            }
          </section>
          ${detail}
        </div>
      </section>
    `;
  }

  return { renderMail };
})();
