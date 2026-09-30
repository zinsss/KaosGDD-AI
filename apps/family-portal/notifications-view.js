window.KAOS_NOTIFICATIONS_VIEW = (() => {
  function insertCountersAfterHeading(value, countsLine) {
    const lines = String(value || "").split("\n");
    if (!lines[0]) return countsLine;
    lines.splice(1, 0, countsLine);
    return lines.join("\n");
  }

  function briefingTextWithCounters(value, counters = {}) {
    if (!String(value || "")) return "";
    const taskCount = counters.tasksReady ? counters.tasks : "—";
    const gddzinCount = counters.tasksReady ? counters.gddzin : "—";
    const familyCount = counters.tasksReady ? counters.family : "—";
    const supplyCount = counters.suppliesReady ? counters.supplies : "—";
    const countsLine = `Tasks ${taskCount} (GDDZiN ${gddzinCount}, Family ${familyCount}) / Supplies ${supplyCount}`;
    return insertCountersAfterHeading(value, countsLine);
  }

  function renderNotifications(deps) {
    const briefing = deps.state.todayBriefing;
    const payload = briefing.data || {};
    const counters = deps.counters || {};
    const todayText = briefingTextWithCounters(payload.plainText, counters);
    const summary = briefing.loading && !briefing.checked
      ? "LOADING TODAY"
      : payload.generatedAt
        ? `UPDATED ${deps.escapeHtml(deps.formatNotificationDate(payload.generatedAt))}`
        : "TODAY";
    return `
      <section class="archiveTerminal notificationInbox kaosToday" aria-label="KaosGDD Today">
        <div class="kaosTodayContent">
          ${
            briefing.error
              ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(briefing.error)}</p><button class="archiveAction" type="button" data-notifications-refresh>RETRY</button></div>`
              : briefing.loading && !briefing.checked
                ? `<p class="archiveStatusMessage kaosTodayLoading">Building today's briefing...</p>`
                : todayText
                  ? `<pre class="kaosTodayText">${deps.escapeHtml(todayText)}</pre>`
                  : `<p class="archiveStatusMessage notificationEmpty">No briefing available.</p>`
          }
        </div>
        <div class="archiveCommand kaosTodayToolbar">
          <p class="archiveStatusMessage" role="status" aria-live="polite">${summary}</p>
          <span class="kaosTodayActions">
            ${todayText ? `<button class="archiveAction" type="button" data-thermal-print="today">Print</button>` : ""}
            <button class="archiveAction" type="button" data-notifications-refresh aria-label="Reload KaosGDD Today" title="Reload KaosGDD Today" ${briefing.loading ? "disabled" : ""}>Reload</button>
          </span>
        </div>
      </section>
    `;
  }

  return { briefingTextWithCounters, insertCountersAfterHeading, renderNotifications };
})();
