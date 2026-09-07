window.KAOS_SYSTEM_STATUS_VIEW = (() => {
  function renderSystemStatusPanel(deps) {
    if (deps.portalProfile() !== "main") return "";
    const status = deps.state.systemStatus;
    if (!status.checked || (status.loading && !status.checked)) {
      return `<section class="settingsStatusPanel systemStatusPanel"><div class="settingsPolicyNote"><strong>System</strong><span>Loading read-only system status...</span></div></section>`;
    }
    if (status.error) {
      return `
        <section class="settingsStatusPanel systemStatusPanel">
          <div class="caregiverError">
            <span>${deps.escapeHtml(status.error)}</span>
            <button class="openButton" type="button" data-system-status-retry>${deps.uiText("common.retry", "다시 시도")}</button>
          </div>
        </section>
      `;
    }
    const data = status.data || {};
    const runtime = data.status || {};
    const brainTools = runtime.brainTools || {};
    const serviceStatus = runtime.serviceStatus || {};
    const worker = runtime.worker || {};
    const brainUrl = String(data.brainChannelUrl || "").trim();
    return `
      <section class="settingsStatusPanel systemStatusPanel" data-system-status>
        <div class="settingsStatusHeader">
          <strong>System Status</strong>
          <small>READ ONLY // ${deps.escapeHtml(deps.statusTimestampLabel(data.updatedAt))}</small>
        </div>
        <div class="settingsActionRow">
          <button class="openButton" type="button" data-system-status-retry>${status.loading ? "..." : "↻"}</button>
          ${
            brainUrl
              ? `<a class="openButton" href="${deps.escapeHtml(brainUrl)}" target="_blank" rel="noopener noreferrer" data-brain-channel-link>#brain</a>`
              : `<span class="settingsInlineLink isDisabled" data-brain-channel-missing>#brain link not configured</span>`
          }
        </div>
        <div class="settingsStatusGrid">
          <div>
            <span>KaosDiscoord</span>
            <strong>${deps.escapeHtml(String(runtime.version || "unknown"))}</strong>
          </div>
          <div>
            <span>Discord</span>
            <strong>${deps.escapeHtml(deps.statusReadyLabel(runtime.discordReady))}</strong>
          </div>
          <div>
            <span>Startup</span>
            <strong>${deps.escapeHtml(deps.statusReadyLabel(runtime.startupComplete))}</strong>
          </div>
          <div>
            <span>Brain tools</span>
            <strong>${deps.escapeHtml(deps.statusEnabledLabel(brainTools.enabled))}</strong>
          </div>
          <div>
            <span>Services</span>
            <strong>${deps.escapeHtml(deps.serviceStatusSummary(serviceStatus))}</strong>
          </div>
          <div>
            <span>Recurring sync</span>
            <strong>${deps.escapeHtml(deps.recurringWorkerSummary(worker))}</strong>
          </div>
        </div>
        ${deps.renderSystemServiceRows(serviceStatus)}
        <div class="systemRuntimeList">
          ${[
            deps.recurringWorkerStatusLine(worker),
            deps.runtimeStatusLine("Mail", runtime.naverMail),
            deps.runtimeStatusLine("Mail organizer", runtime.naverMailOrganizer),
            deps.runtimeStatusLine("Fax", runtime.fax),
            deps.runtimeStatusLine("Pushover", runtime.textNotifications),
            deps.runtimeStatusLine("Daily digest", runtime.dailyDigest),
          ].filter(Boolean).join("")}
        </div>
        <p class="formNote">Observation only. No restart, deploy, reboot, shell, package-update, or system write controls are exposed in PWA.</p>
      </section>
    `;
  }

  return { renderSystemStatusPanel };
})();
