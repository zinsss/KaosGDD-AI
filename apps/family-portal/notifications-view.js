window.KAOS_NOTIFICATIONS_VIEW = (() => {
  function renderNotifications(deps) {
    const briefing = deps.state.todayBriefing;
    const payload = briefing.data || {};
    const counters = deps.counters || {};
    const taskCount = counters.tasksReady ? counters.tasks : "—";
    const gddzinCount = counters.tasksReady ? counters.gddzin : "—";
    const familyCount = counters.tasksReady ? counters.family : "—";
    const supplyCount = counters.suppliesReady ? counters.supplies : "—";
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
        <p class="kaosTodayCounters" aria-label="Today totals">
          <span>Tasks <strong>${taskCount}</strong> (GDDZiN <strong>${gddzinCount}</strong>, Family <strong>${familyCount}</strong>)</span>
          <span aria-hidden="true">/</span>
          <span>Supplies <strong>${supplyCount}</strong></span>
        </p>
        <div class="archiveCommand kaosTodayToolbar">
          <p class="archiveStatusMessage" role="status" aria-live="polite">${summary}</p>
          <button class="archiveAction" type="button" data-notifications-refresh aria-label="Reload KaosGDD Today" title="Reload KaosGDD Today" ${briefing.loading ? "disabled" : ""}>Reload</button>
        </div>
      </section>
    `;
  }

  return { renderNotifications };
})();
