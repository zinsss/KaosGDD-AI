window.KAOS_NOTIFICATIONS_VIEW = (() => {
  function renderNotifications(deps) {
    const briefing = deps.state.todayBriefing;
    const payload = briefing.data || {};
    const summary = briefing.loading && !briefing.checked
      ? "LOADING TODAY"
      : payload.generatedAt
        ? `UPDATED ${deps.escapeHtml(deps.formatNotificationDate(payload.generatedAt))}`
        : "TODAY";
    return `
      <section class="archiveTerminal notificationInbox kaosToday" aria-label="KaosToday">
        <div class="archiveCommand">
          <div>
            <strong>KAOS TODAY</strong>
            <p class="archiveStatusMessage" role="status" aria-live="polite">${summary}</p>
          </div>
          <button class="archiveAction archiveRefreshAction" type="button" data-notifications-refresh aria-label="Refresh KaosToday" title="Refresh KaosToday" ${briefing.loading ? "disabled" : ""}>↻</button>
        </div>
        ${
          briefing.error
            ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(briefing.error)}</p><button class="archiveAction" type="button" data-notifications-refresh>RETRY</button></div>`
            : briefing.loading && !briefing.checked
              ? `<p class="archiveStatusMessage">Building today's briefing...</p>`
              : payload.plainText
                ? `<pre class="kaosTodayText">${deps.escapeHtml(payload.plainText)}</pre>`
                : `<p class="archiveStatusMessage notificationEmpty">No briefing available.</p>`
        }
      </section>
    `;
  }

  return { renderNotifications };
})();
