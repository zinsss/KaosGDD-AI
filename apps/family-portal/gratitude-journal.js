(() => {
  const ITEM_COUNT = 5;

  function emptyItems() {
    return Array.from({ length: ITEM_COUNT }, () => "");
  }

  function initialState() {
    return {
      date: "",
      checked: false,
      loading: false,
      saving: false,
      exists: false,
      etag: "",
      lastModified: "",
      items: emptyItems(),
      dirty: false,
      open: false,
      error: "",
    };
  }

  function normalizeItems(value) {
    const items = Array.isArray(value) ? value.slice(0, ITEM_COUNT).map((item) => String(item || "")) : [];
    return items.concat(emptyItems()).slice(0, ITEM_COUNT);
  }

  function resetForDate(journal, date) {
    Object.assign(journal, initialState(), { date });
  }

  function labels(profile) {
    if (profile === "family") {
      return {
        kicker: "감사일기",
        title: "오늘 감사한 일 5가지",
        placeholder: (index) => `${index + 1}번째 감사한 일`,
        loading: "불러오는 중…",
        saved: "저장됨",
        save: "저장",
        saving: "저장 중…",
        required: "감사한 일을 하나 이상 적어주세요.",
        conflict: "다른 기기에서 먼저 수정되었습니다. 지금 입력한 내용으로 덮어쓰려면 다시 저장하세요.",
        unavailable: "감사일기를 불러올 수 없습니다.",
        calendarTitle: "감사한 일",
        calendarNone: "기록 없음",
      };
    }
    return {
      kicker: "Journal",
      title: "5 Thankful Things",
      placeholder: (index) => `Thankful thing ${index + 1}`,
      loading: "Loading…",
      saved: "Saved",
      save: "Save",
      saving: "Saving…",
      required: "Write at least one thankful thing.",
      conflict: "This entry changed on another device. Save again to overwrite it with your current text.",
      unavailable: "Could not load the gratitude journal.",
      calendarTitle: "Thankful Things",
      calendarNone: "No gratitude entry.",
    };
  }

  function render(context) {
    const { journal, profile, date, escapeHtml } = context;
    const copy = labels(profile);
    if (journal.date !== date && !journal.dirty) resetForDate(journal, date);
    const items = normalizeItems(journal.items);
    const status = journal.error
      ? `<p class="gratitudeStatus isError" role="alert">${escapeHtml(journal.error)}</p>`
      : journal.loading
        ? `<p class="gratitudeStatus">${escapeHtml(copy.loading)}</p>`
        : journal.exists && !journal.dirty
          ? `<p class="gratitudeStatus isSaved">${escapeHtml(copy.saved)}</p>`
          : `<p class="gratitudeStatus" aria-hidden="true">&nbsp;</p>`;
    return `
      <details class="panel gratitudePanel" data-gratitude-disclosure ${journal.open ? "open" : ""}>
        <summary class="panelHeader gratitudeHeader">
          <div>
            <p class="label">${escapeHtml(copy.kicker)}</p>
            <h2>${escapeHtml(copy.title)}</h2>
          </div>
          ${status}
          <span class="gratitudeToggle" aria-hidden="true">⌄</span>
        </summary>
        <form class="panelBody gratitudeForm" data-gratitude-form>
          <div class="gratitudeFields">
            ${items.map((item, index) => `
              <label class="gratitudeField">
                <span>${index + 1}</span>
                <input
                  type="text"
                  maxlength="500"
                  value="${escapeHtml(item)}"
                  placeholder="${escapeHtml(copy.placeholder(index))}"
                  aria-label="${escapeHtml(copy.placeholder(index))}"
                  data-gratitude-item="${index}"
                  ${journal.loading || journal.saving ? "disabled" : ""}
                />
              </label>
            `).join("")}
          </div>
          <div class="gratitudeActions">
            <button class="primary" type="submit" ${journal.loading || journal.saving ? "disabled" : ""}>
              ${escapeHtml(journal.saving ? copy.saving : copy.save)}
            </button>
          </div>
        </form>
      </details>
    `;
  }

  function renderReadOnly(context) {
    const { journal, profile, date, escapeHtml, hasPrevious = false } = context;
    const copy = labels(profile);
    if (journal.date !== date) resetForDate(journal, date);
    const items = normalizeItems(journal.items).map((item) => item.trim()).filter(Boolean);
    const message = journal.error
      ? `<p class="calendarGratitudeMessage isError" role="alert">${escapeHtml(journal.error)}</p>`
      : journal.loading || !journal.checked
        ? `<p class="calendarGratitudeMessage">${escapeHtml(copy.loading)}</p>`
        : items.length
          ? `<ol class="calendarGratitudeList">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`
          : `<p class="calendarGratitudeMessage">${escapeHtml(copy.calendarNone)}</p>`;
    return `
      <div class="panelBody calendarGratitude ${hasPrevious ? "withDivider" : ""}">
        <p class="label sectionLabel">${escapeHtml(copy.calendarTitle)}</p>
        ${message}
      </div>
    `;
  }

  function applyPayload(journal, payload) {
    journal.date = String(payload.date || journal.date);
    journal.exists = Boolean(payload.exists);
    journal.etag = String(payload.etag || "");
    journal.lastModified = String(payload.lastModified || "");
    journal.items = normalizeItems(payload.items);
    journal.dirty = false;
    journal.error = "";
  }

  async function load(context, { force = false } = {}) {
    const { journal, profile, date, rerender } = context;
    const copy = labels(profile);
    if (journal.date !== date) resetForDate(journal, date);
    if (!force && (journal.checked || journal.loading)) return;
    journal.loading = true;
    journal.error = "";
    try {
      const response = await fetch(`/api/calendar/gratitude?date=${encodeURIComponent(date)}`, {
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      if (!journal.dirty) applyPayload(journal, payload);
    } catch (error) {
      journal.error = copy.unavailable;
    } finally {
      journal.loading = false;
      journal.checked = true;
      rerender();
    }
  }

  async function save(context) {
    const { journal, profile, date, rerender } = context;
    const copy = labels(profile);
    const items = normalizeItems(journal.items).map((item) => item.trim());
    if (!items.some(Boolean)) {
      journal.error = copy.required;
      rerender();
      return;
    }
    journal.saving = true;
    journal.error = "";
    rerender();
    try {
      const response = await fetch("/api/calendar/gratitude", {
        method: "PUT",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ date, items, etag: journal.etag }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 409) {
        journal.etag = String(payload.current?.etag || "");
        journal.error = copy.conflict;
        journal.dirty = true;
        return;
      }
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      applyPayload(journal, payload);
    } catch (error) {
      journal.error = copy.unavailable;
    } finally {
      journal.saving = false;
      journal.checked = true;
      rerender();
    }
  }

  function handleInput(journal, event) {
    const input = event.target.closest("[data-gratitude-item]");
    if (!input) return false;
    const index = Number(input.dataset.gratitudeItem);
    if (!Number.isInteger(index) || index < 0 || index >= ITEM_COUNT) return false;
    journal.items[index] = input.value;
    journal.dirty = true;
    journal.error = "";
    return true;
  }

  window.KAOS_GRATITUDE_JOURNAL = {
    initialState,
    render,
    renderReadOnly,
    load,
    save,
    handleInput,
  };
})();
