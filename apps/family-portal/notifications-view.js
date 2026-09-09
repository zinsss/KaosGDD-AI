window.KAOS_NOTIFICATIONS_VIEW = (() => {
  function renderNotifications(deps) {
    const inbox = deps.state.notifications;
    const rows = inbox.items
      .map((item) => {
        const critical = Number(item.priority || 0) === 1;
        return `
          <li class="notificationRecord ${critical ? "isCritical" : ""}">
            <header>
              <span class="notificationCategory">${deps.escapeHtml(String(item.category || "notification").toUpperCase())}</span>
              <time datetime="${deps.escapeHtml(item.createdAt || "")}">${deps.escapeHtml(deps.formatNotificationDate(item.createdAt))}</time>
            </header>
            ${item.title ? `<strong>${deps.escapeHtml(item.title)}</strong>` : ""}
            <p>${deps.escapeHtml(item.message || "")}</p>
            <label class="notificationAck">
              <input
                type="checkbox"
                data-notification-ack="${deps.escapeHtml(item.id || "")}"
                aria-label="Mark notification checked"
              />
              <span>CHECKED</span>
            </label>
          </li>
        `;
      })
      .join("");
    const summary = inbox.loading && !inbox.checked
      ? "LOADING NOTIFICATIONS"
      : `${inbox.pendingCount} PENDING${inbox.criticalCount ? ` // ${inbox.criticalCount} CRITICAL` : ""}`;
    return `
      <section class="archiveTerminal notificationInbox" aria-label="Notification inbox">
        <div class="archiveCommand">
          <div>
            <strong>GOVERNOR INBOX</strong>
            <p class="archiveStatusMessage" role="status" aria-live="polite">${deps.escapeHtml(summary)}</p>
          </div>
          <button class="archiveAction archiveRefreshAction" type="button" data-notifications-refresh aria-label="Refresh notifications" title="Refresh notifications" ${inbox.loading ? "disabled" : ""}>↻</button>
        </div>
        ${
          inbox.error
            ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(inbox.error)}</p><button class="archiveAction" type="button" data-notifications-refresh>RETRY</button></div>`
            : inbox.loading && !inbox.checked
              ? `<p class="archiveStatusMessage">Reading Governor inbox...</p>`
              : rows
                ? `<ol class="notificationRecordList">${rows}</ol>`
                : `<p class="archiveStatusMessage notificationEmpty">No pending notifications.</p>`
        }
      </section>
    `;
  }

  return { renderNotifications };
})();
