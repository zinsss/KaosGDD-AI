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
      <section class="archiveTerminal notificationInbox kaosToday" aria-label="KaosGDD Today">
        ${
          briefing.error
            ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(briefing.error)}</p><button class="archiveAction" type="button" data-notifications-refresh>RETRY</button></div>`
            : briefing.loading && !briefing.checked
              ? `<p class="archiveStatusMessage">Building today's briefing...</p>`
              : payload.plainText
                ? `<pre class="kaosTodayText">${deps.escapeHtml(payload.plainText)}</pre>`
                : `<p class="archiveStatusMessage notificationEmpty">No briefing available.</p>`
        }
        <div class="archiveCommand kaosTodayToolbar">
          <p class="archiveStatusMessage" role="status" aria-live="polite">${summary}</p>
          <button class="archiveAction" type="button" data-notifications-refresh aria-label="Reload KaosGDD Today" title="Reload KaosGDD Today" ${briefing.loading ? "disabled" : ""}>Reload</button>
        </div>
      </section>
    `;
  }

  return { renderNotifications };
})();
