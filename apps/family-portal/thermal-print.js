window.KAOS_THERMAL_PRINT = (() => {
  const state = {
    document: null,
    destinations: [],
    selectedId: "",
    loading: false,
    previewLoading: false,
    previewUrl: "",
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
          <div class="thermalPrintPreviewPane">
            ${
              state.previewLoading
                ? `<div class="thermalPrintPreviewLoading"><p class="thermalPrintStatus">Rendering 80 mm preview…</p></div>`
                : state.previewUrl
                  ? `<iframe class="thermalPrintPreviewFrame" src="${escapeHtml(state.previewUrl)}" title="80 mm receipt preview"></iframe>`
                  : `<div class="thermalPrintPreviewLoading"><p class="thermalPrintStatus">Preview unavailable.</p></div>`
            }
          </div>
          <div class="thermalPrintLocation">
            <p class="thermalPrintSectionLabel">Print location</p>
            ${destinations}
          </div>
          ${state.message ? `<p class="thermalPrintMessage" role="status">${escapeHtml(state.message)}</p>` : ""}
          ${state.error ? `<p class="thermalPrintMessage isError" role="alert">${escapeHtml(state.error)}</p>` : ""}
        </div>
        <footer class="thermalPrintActions">
          <button class="thermalPrintCommand isActive" type="button" data-thermal-print-submit ${!selected?.available || !state.previewUrl || state.previewLoading || state.submitting ? "disabled" : ""}>
            ${state.submitting ? "Printing…" : "Print"}
          </button>
        </footer>
      </section>
    `;
    document.documentElement.classList.add("hasThermalPrintDialog");
  }

  function releasePreviewUrl() {
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = "";
  }

  function close() {
    const overlay = root();
    if (overlay) overlay.innerHTML = "";
    document.documentElement.classList.remove("hasThermalPrintDialog");
    releasePreviewUrl();
    state.document = null;
    state.destinations = [];
    state.selectedId = "";
    state.loading = false;
    state.previewLoading = false;
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
    releasePreviewUrl();
    state.document = printDocument;
    state.destinations = [];
    state.selectedId = "";
    state.previewLoading = true;
    state.message = "";
    state.error = "";
    const destinationsReady = await loadDestinations({ notifyUnavailable: true });
    if (!destinationsReady || state.document !== printDocument) return;
    await loadPreview();
  }

  async function responseError(response) {
    const payload = await response.json().catch(() => ({}));
    return payload.error || `HTTP ${response.status}`;
  }

  async function loadPreview() {
    if (!state.document) return;
    const requestedDocument = state.document;
    state.error = "";
    state.previewLoading = true;
    render();
    try {
      const response = await fetch("/api/thermal-print/preview", {
        method: "POST",
        headers: { Accept: "application/pdf", "Content-Type": "application/json" },
        body: JSON.stringify({ document: state.document }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      if (state.document !== requestedDocument) {
        URL.revokeObjectURL(url);
        return;
      }
      releasePreviewUrl();
      state.previewUrl = url;
    } catch (error) {
      state.error = `Could not render preview: ${error.message || "unknown error"}`;
    } finally {
      if (state.document === requestedDocument) {
        state.previewLoading = false;
        render();
      }
    }
  }

  async function submit() {
    const destination = state.destinations.find((item) => item.id === state.selectedId);
    if (!state.document || !destination?.available || !state.previewUrl || state.submitting) return;
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
    if (event.target.closest("[data-thermal-print-submit]")) void submit();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.document) close();
  });

  return { open, close };
})();
