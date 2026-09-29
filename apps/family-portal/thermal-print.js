window.KAOS_THERMAL_PRINT = (() => {
  const state = {
    document: null,
    destinations: [],
    selectedId: "",
    loading: false,
    submitting: false,
    message: "",
    error: "",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function root() {
    return document.getElementById("overlayRoot");
  }

  function destinationStatus(item) {
    if (item.available) return "Ready";
    if (item.status === "awaiting_connection") return "Printer not connected yet";
    if (item.status === "awaiting_printer" || item.status === "printer_not_ready") return "Waiting for printer";
    if (item.status === "printer_unreachable") return "Connector offline";
    if (item.status === "missing_token") return "Connector token missing";
    return "Unavailable";
  }

  function render() {
    const overlay = root();
    if (!overlay || !state.document) return;
    const selected = state.destinations.find((item) => item.id === state.selectedId) || null;
    const destinations = state.loading
      ? `<p class="thermalPrintStatus">Checking print destinations…</p>`
      : state.destinations.length
        ? `
          <div class="thermalPrintDestinations" role="radiogroup" aria-label="Print destination">
            ${state.destinations.map((item) => `
              <button
                class="thermalPrintDestination ${item.id === state.selectedId ? "isSelected" : ""}"
                type="button"
                role="radio"
                aria-checked="${item.id === state.selectedId}"
                data-thermal-destination="${escapeHtml(item.id)}"
              >
                <strong>${escapeHtml(item.label)}</strong>
                <small>${escapeHtml(destinationStatus(item))}</small>
              </button>
            `).join("")}
          </div>
        `
        : `<p class="thermalPrintStatus">No print destination is configured.</p>`;
    overlay.innerHTML = `
      <div class="thermalPrintBackdrop" data-thermal-print-close></div>
      <section class="thermalPrintDialog" role="dialog" aria-modal="true" aria-labelledby="thermalPrintTitle">
        <header class="thermalPrintHeader">
          <div>
            <p>80 MM RECEIPT</p>
            <h2 id="thermalPrintTitle">${escapeHtml(state.document.title || "Print")}</h2>
          </div>
          <button class="thermalPrintClose" type="button" data-thermal-print-close aria-label="Close">Close</button>
        </header>
        <div class="thermalPrintBody">
          ${destinations}
          <p class="thermalPrintHint">Preview uses the exact 80 mm server renderer. A job is sent only when its destination reports a ready printer.</p>
          ${state.message ? `<p class="thermalPrintMessage" role="status">${escapeHtml(state.message)}</p>` : ""}
          ${state.error ? `<p class="thermalPrintMessage isError" role="alert">${escapeHtml(state.error)}</p>` : ""}
        </div>
        <footer class="thermalPrintActions">
          <button class="thermalPrintCommand" type="button" data-thermal-print-preview>Preview</button>
          <button class="thermalPrintCommand isActive" type="button" data-thermal-print-submit ${!selected?.available || state.submitting ? "disabled" : ""}>
            ${state.submitting ? "Sending…" : selected?.available ? `Print at ${escapeHtml(selected.label)}` : "Printer unavailable"}
          </button>
        </footer>
      </section>
    `;
    document.documentElement.classList.add("hasThermalPrintDialog");
    overlay.querySelector("[data-thermal-print-preview]")?.focus();
  }

  function close() {
    const overlay = root();
    if (overlay) overlay.innerHTML = "";
    document.documentElement.classList.remove("hasThermalPrintDialog");
    state.document = null;
    state.destinations = [];
    state.selectedId = "";
    state.loading = false;
    state.submitting = false;
    state.message = "";
    state.error = "";
  }

  function notifyPrinterNotReady() {
    window.alert("Printer not ready.");
  }

  async function loadDestinations({ notifyUnavailable = false } = {}) {
    state.loading = true;
    if (!notifyUnavailable) render();
    try {
      const response = await fetch("/api/thermal-print/destinations", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      state.destinations = Array.isArray(payload.destinations) ? payload.destinations : [];
      state.selectedId = state.destinations.find((item) => item.available)?.id || state.destinations[0]?.id || "";
      if (notifyUnavailable && !state.destinations.some((item) => item.available)) {
        close();
        notifyPrinterNotReady();
        return false;
      }
    } catch (error) {
      state.destinations = [];
      if (notifyUnavailable) {
        close();
        notifyPrinterNotReady();
        return false;
      }
      state.error = `Could not check printers: ${error.message || "unknown error"}`;
    } finally {
      state.loading = false;
      if (state.document) render();
    }
    return true;
  }

  async function open(printDocument) {
    if (!printDocument || typeof printDocument !== "object") return;
    state.document = printDocument;
    state.destinations = [];
    state.selectedId = "";
    state.message = "";
    state.error = "";
    await loadDestinations({ notifyUnavailable: true });
  }

  async function responseError(response) {
    const payload = await response.json().catch(() => ({}));
    return payload.error || `HTTP ${response.status}`;
  }

  async function preview() {
    if (!state.document) return;
    state.error = "";
    state.message = "Rendering 80 mm preview…";
    render();
    const previewWindow = window.open("about:blank", "_blank");
    try {
      const response = await fetch("/api/thermal-print/preview", {
        method: "POST",
        headers: { Accept: "application/pdf", "Content-Type": "application/json" },
        body: JSON.stringify({ document: state.document }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      if (previewWindow) previewWindow.location.replace(url);
      else {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener";
        link.click();
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      state.message = "Preview opened. No paper was used.";
    } catch (error) {
      if (previewWindow) previewWindow.close();
      state.message = "";
      state.error = `Could not render preview: ${error.message || "unknown error"}`;
    }
    render();
  }

  async function submit() {
    const destination = state.destinations.find((item) => item.id === state.selectedId);
    if (!state.document || !destination?.available || state.submitting) return;
    state.submitting = true;
    state.message = "";
    state.error = "";
    render();
    try {
      const response = await fetch("/api/thermal-print/jobs", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ destinationId: destination.id, document: state.document }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      state.message = `Sent to ${destination.label}${payload.printerJobId ? ` · ${payload.printerJobId}` : ""}.`;
    } catch (error) {
      state.error = `Print failed: ${error.message || "unknown error"}`;
      await loadDestinations();
    } finally {
      state.submitting = false;
      render();
    }
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-thermal-print-close]")) {
      close();
      return;
    }
    const destination = event.target.closest("[data-thermal-destination]");
    if (destination) {
      state.selectedId = destination.dataset.thermalDestination || "";
      state.message = "";
      state.error = "";
      render();
      return;
    }
    if (event.target.closest("[data-thermal-print-preview]")) {
      void preview();
      return;
    }
    if (event.target.closest("[data-thermal-print-submit]")) void submit();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.document) close();
  });

  return { open, close };
})();
