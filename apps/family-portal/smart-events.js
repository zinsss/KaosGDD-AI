window.KAOS_FAMILY_SMART_EVENTS = (() => {
  function normalizeFamilySmartEventTime(hourValue, minuteValue, meridiem = "") {
    let hour = Number(hourValue);
    const minute = Number(minuteValue || "0");
    const marker = String(meridiem || "").trim();
    if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) return "";
    if (marker === "오전" && hour === 12) hour = 0;
    if (marker === "오후" && hour < 12) hour += 12;
    if (!marker && hour >= 1 && hour <= 7) hour += 12;
    return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  }

  function cleanFamilySmartEventTitle(value, fallback = "") {
    return String(value || "")
      .replace(/\s+/g, " ")
      .replace(/\s*,\s*/g, ",")
      .trim() || String(fallback || "").trim();
  }

  function splitFamilySmartEventInput(value) {
    const strongParts = String(value || "")
      .replace(/\r\n?/g, "\n")
      .replace(/[，、]/g, ",")
      .split(/(?:[\/\n+&]+|\s+(?:그리고|그다음|그 다음|다음|또|및)\s+)/)
      .map((part) => part.trim())
      .filter(Boolean);
    return strongParts.flatMap(splitFamilySmartEventWeakComma);
  }

  function splitFamilySmartEventWeakComma(value) {
    const parts = String(value || "").split(",").map((part) => part.trim()).filter(Boolean);
    if (parts.length <= 1) return parts;
    const results = [];
    let current = parts[0];
    for (const part of parts.slice(1)) {
      if (familySmartEventCommaStartsNewEvent(part)) {
        results.push(current.trim());
        current = part;
      } else {
        current = `${current},${part}`;
      }
    }
    results.push(current.trim());
    return results.filter(Boolean);
  }

  function familySmartEventCommaStartsNewEvent(value) {
    return /(?:^|\s)(?:오전|오후)?\s*\d{1,2}(?::\d{1,2}|시(?:\s*\d{1,2}분?)?)(?=\s|$)/.test(String(value || "").trim());
  }

  function parseFamilySmartEventInput(deps, value, dateValue = deps.state.selectedDate) {
    const timeExpression = String.raw`(?:(오전|오후)\s*)?(\d{1,2})(?::(\d{1,2})|시(?:\s*(\d{1,2})분?)?)`;
    const embeddedTimePattern = new RegExp(`(^|\\s)${timeExpression}(?:\\s*[-~–—]\\s*${timeExpression})?(?=\\s|$)`);
    return splitFamilySmartEventInput(value)
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const match = part.match(new RegExp(`^${timeExpression}(?:\\s*[-~–—]\\s*${timeExpression})?\\s*(.*)$`));
        let startTime = "";
        let explicitEndTime = "";
        let title = "";
        if (!match) {
          const embeddedMatch = part.match(embeddedTimePattern);
          if (!embeddedMatch) {
            return {
              title: part,
              allDay: true,
              startDate: dateValue,
              startTime: "",
              endDate: dateValue,
              endTime: "",
            };
          }
          const startMarker = embeddedMatch[2] || "";
          startTime = normalizeFamilySmartEventTime(embeddedMatch[3], embeddedMatch[4] || embeddedMatch[5] || "0", startMarker);
          explicitEndTime = embeddedMatch[7]
            ? normalizeFamilySmartEventTime(embeddedMatch[7], embeddedMatch[8] || embeddedMatch[9] || "0", embeddedMatch[6] || startMarker)
            : "";
          title = cleanFamilySmartEventTitle(`${part.slice(0, embeddedMatch.index)} ${part.slice(embeddedMatch.index + embeddedMatch[0].length)}`, part);
        } else {
          const startMarker = match[1] || "";
          startTime = normalizeFamilySmartEventTime(match[2], match[3] || match[4] || "0", startMarker);
          explicitEndTime = match[6]
            ? normalizeFamilySmartEventTime(match[6], match[7] || match[8] || "0", match[5] || startMarker)
            : "";
          title = cleanFamilySmartEventTitle(match[9] || "", part);
        }
        if (!startTime) {
          return {
            title: part,
            allDay: true,
            startDate: dateValue,
            startTime: "",
            endDate: dateValue,
            endTime: "",
          };
        }
        const startMinutes = deps.parseRounyMinutes(startTime);
        const explicitEndMinutes = deps.parseRounyMinutes(explicitEndTime);
        const end = explicitEndMinutes === null
          ? deps.addLocalMinutes(dateValue, startTime, 60)
          : explicitEndMinutes <= startMinutes
            ? deps.addLocalMinutes(dateValue, explicitEndTime, 24 * 60)
            : { date: dateValue, time: explicitEndTime };
        return {
          title,
          allDay: false,
          startDate: dateValue,
          startTime,
          endDate: end.date,
          endTime: end.time,
        };
      });
  }

  function normalizeFamilySmartEventProposal(deps, item, dateValue = deps.state.selectedDate) {
    if (!item || typeof item !== "object") return null;
    const title = String(item.title || item.summary || "").trim();
    const startDate = /^\d{4}-\d{2}-\d{2}$/.test(String(item.startDate || item.date || ""))
      ? String(item.startDate || item.date)
      : dateValue;
    if (!title) return null;
    if (item.allDay) {
      return {
        title,
        allDay: true,
        startDate,
        startTime: "",
        endDate: /^\d{4}-\d{2}-\d{2}$/.test(String(item.endDate || "")) ? String(item.endDate) : startDate,
        endTime: "",
        source: item.source || deps.state.smartEventPreviewSource || "grammar",
      };
    }
    const startTime = /^\d{2}:\d{2}$/.test(String(item.startTime || "")) ? String(item.startTime) : "";
    const endDate = /^\d{4}-\d{2}-\d{2}$/.test(String(item.endDate || "")) ? String(item.endDate) : startDate;
    const endTime = /^\d{2}:\d{2}$/.test(String(item.endTime || "")) ? String(item.endTime) : "";
    const startMs = startTime ? new Date(`${startDate}T${startTime}:00`).getTime() : NaN;
    const endMs = endTime ? new Date(`${endDate}T${endTime}:00`).getTime() : NaN;
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return null;
    return {
      title,
      allDay: false,
      startDate,
      startTime,
      endDate,
      endTime,
      source: item.source || deps.state.smartEventPreviewSource || "grammar",
    };
  }

  function familySmartEventBaseProposals(deps, dateValue = deps.state.selectedDate) {
    if (Array.isArray(deps.state.smartEventAiProposals)) {
      return deps.state.smartEventAiProposals
        .map((item) => normalizeFamilySmartEventProposal(deps, item, dateValue))
        .filter(Boolean);
    }
    return parseFamilySmartEventInput(deps, deps.state.smartEventInput, dateValue)
      .map((item) => normalizeFamilySmartEventProposal(deps, item, dateValue))
      .filter(Boolean);
  }

  function adjustFamilySmartEventEnd(deps, item, minutes) {
    if (item.allDay || !minutes) return item;
    const end = deps.addLocalMinutes(item.endDate, item.endTime, minutes);
    const startMs = new Date(`${item.startDate}T${item.startTime}:00`).getTime();
    const endMs = new Date(`${end.date}T${end.time}:00`).getTime();
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return item;
    return {
      ...item,
      endDate: end.date,
      endTime: end.time,
    };
  }

  function nextFamilySmartEventEndOffset(deps, item, currentOffset, step) {
    if (item.allDay || !step) return currentOffset;
    const current = adjustFamilySmartEventEnd(deps, item, currentOffset);
    const currentEndMinutes = deps.parseRounyMinutes(current.endTime);
    let stepMinutes = step;
    if (step > 0 && currentEndMinutes !== null && currentEndMinutes % 60 !== 0) {
      stepMinutes = 60 - (currentEndMinutes % 60);
    }
    let nextOffset = currentOffset + stepMinutes;
    if (step < 0 && currentOffset > 0 && nextOffset < 0) nextOffset = 0;
    const next = adjustFamilySmartEventEnd(deps, item, nextOffset);
    if (next.endDate === current.endDate && next.endTime === current.endTime) return currentOffset;
    return nextOffset;
  }

  function familySmartEventDurationMinutes(item) {
    if (item.allDay || !item.startDate || !item.startTime || !item.endDate || !item.endTime) return 0;
    const startMs = new Date(`${item.startDate}T${item.startTime}:00`).getTime();
    const endMs = new Date(`${item.endDate}T${item.endTime}:00`).getTime();
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return 0;
    return Math.round((endMs - startMs) / 60_000);
  }

  function formatFamilySmartEventDuration(deps, item) {
    const minutes = familySmartEventDurationMinutes(item);
    if (!minutes) return "";
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    const parts = [];
    if (hours) parts.push(`${hours}${deps.uiText("event.smartHoursSuffix", "h")}`);
    if (remainder) parts.push(`${remainder}${deps.uiText("event.smartMinutesSuffix", "m")}`);
    return parts.join(" ");
  }

  function familySmartEventProposals(deps, dateValue = deps.state.selectedDate) {
    return familySmartEventBaseProposals(deps, dateValue)
      .map((item, index) => adjustFamilySmartEventEnd(deps, item, Number(deps.state.smartEventEndOffsets[index] || 0)));
  }

  function familySmartEventRangeLabel(deps, item) {
    if (item.allDay) return deps.uiText("event.smartAllDayPreview", "All-day event");
    return `${item.startDate} ${item.startTime}–${item.endDate === item.startDate ? item.endTime : `${item.endDate} ${item.endTime}`}`;
  }

  function familySmartEventPayload(deps, item) {
    return {
      collectionId: deps.writableCollectionIdForOwner("family", "VEVENT"),
      title: String(item.title || "").trim(),
      allDay: Boolean(item.allDay),
      startDate: item.startDate || deps.state.selectedDate,
      startTime: item.startTime || deps.DEFAULT_EVENT_START_TIME,
      endDate: item.endDate || item.startDate || deps.state.selectedDate,
      endTime: item.endTime || deps.DEFAULT_EVENT_END_TIME,
      repeat: "",
      alarmTime: "",
      memo: "",
    };
  }

  function familySmartEventSaveConfirmMessage(deps, proposals) {
    const lines = proposals.slice(0, 8).map((item) => `- ${familySmartEventRangeLabel(deps, item)} ${item.title}`);
    if (proposals.length > lines.length) lines.push(`- … +${proposals.length - lines.length}`);
    return `${deps.uiText("dialog.familySmartEventSaveConfirm", "Save {count} previewed event(s) to the calendar?", { count: proposals.length })}\n\n${lines.join("\n")}`;
  }

  async function requestFamilySmartEventAiPreview(deps) {
    if (deps.portalProfile() !== "family" || deps.state.smartEventAiLoading) return;
    const text = String(deps.state.smartEventInput || "").trim();
    if (!text) {
      window.alert(deps.uiText("dialog.familySmartEventEmpty", "Add at least one event before saving."));
      return;
    }
    deps.state.smartEventAiLoading = true;
    deps.state.smartEventAiError = "";
    deps.render();
    try {
      const response = await fetch("/api/calendar/smart-events/preview", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text,
          date: deps.state.selectedDate,
          useAi: true,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
      deps.state.smartEventPreviewSource = payload.source === "ai" ? "ai" : "grammar";
      deps.state.smartEventAiError = payload.ai?.error || "";
      deps.state.smartEventAiProposals = Array.isArray(payload.events)
        ? payload.events.map((item) => normalizeFamilySmartEventProposal(deps, item, deps.state.selectedDate)).filter(Boolean)
        : [];
      deps.state.smartEventEndOffsets = {};
    } catch (error) {
      deps.state.smartEventAiError = error.message || deps.uiText("dialog.unknownError", "unknown error");
      window.alert(deps.uiText("dialog.familySmartEventAiError", "Could not load AI preview: {error}", {
        error: deps.state.smartEventAiError,
      }));
    } finally {
      deps.state.smartEventAiLoading = false;
      deps.render();
    }
  }

  async function saveFamilySmartEvents(deps) {
    if (deps.portalProfile() !== "family" || deps.state.smartEventSaving) return;
    const proposals = familySmartEventProposals(deps, deps.state.selectedDate).filter((item) => String(item.title || "").trim());
    if (!proposals.length) {
      window.alert(deps.uiText("dialog.familySmartEventEmpty", "Add at least one event before saving."));
      return;
    }
    if (!window.confirm(familySmartEventSaveConfirmMessage(deps, proposals))) return;
    if (!deps.state.remoteCalendar.live) {
      if (!deps.state.remoteCalendar.checked) await deps.loadRemoteCalendar();
      if (!deps.state.remoteCalendar.live) {
        window.alert(deps.uiText("dialog.radicaleSaveError", "Could not save to Radicale: {error}", {
          error: deps.state.remoteCalendar.error || deps.uiText("calendar.adapterUnavailable", "Calendar server unavailable"),
        }));
        return;
      }
    }
    const payloads = proposals.map((item) => familySmartEventPayload(deps, item));
    deps.state.smartEventSaving = true;
    deps.render();
    let savedCount = 0;
    try {
      for (const payload of payloads) {
        await deps.postCalendarEvent(payload);
        savedCount += 1;
      }
      deps.state.selectedDate = payloads[0]?.startDate || deps.state.selectedDate;
      clearDraft(deps);
      deps.state.addEventDraft = null;
      deps.state.eventPresetDraft = null;
      window.alert(deps.uiText("event.savedCount", "{count} saved", { count: payloads.length }));
      window.location.hash = "#/calendar";
      await deps.loadRemoteCalendar();
    } catch (error) {
      if (savedCount > 0) {
        deps.state.selectedDate = payloads[0]?.startDate || deps.state.selectedDate;
        clearDraft(deps);
        window.alert(deps.uiText("dialog.radicalePartialSaveError", "{saved}/{total} saved. Please check the calendar: {error}", {
          saved: savedCount,
          total: payloads.length,
          error: error.message || deps.uiText("dialog.unknownError", "unknown error"),
        }));
        window.location.hash = "#/calendar";
        await deps.loadRemoteCalendar();
        return;
      }
      window.alert(deps.uiText("dialog.radicaleSaveError", "Could not save to Radicale: {error}", {
        error: error.message || deps.uiText("dialog.unknownError", "unknown error"),
      }));
    } finally {
      deps.state.smartEventSaving = false;
      if (deps.getRoute() === "add-event") deps.render();
    }
  }

  function clearDraft(deps) {
    deps.state.smartEventInput = "";
    deps.state.smartEventAiProposals = null;
    deps.state.smartEventAiError = "";
    deps.state.smartEventPreviewSource = "grammar";
    deps.state.smartEventEndOffsets = {};
  }

  function updateFamilySmartEventPreview(deps) {
    const proposals = familySmartEventProposals(deps, deps.state.selectedDate);
    const preview = document.querySelector("[data-family-smart-event-preview]");
    if (preview) {
      preview.innerHTML = `
        <p class="label">${deps.uiText("event.smartPreview", "Preview")}</p>
        ${renderFamilySmartEventSourceNote(deps)}
        ${renderFamilySmartEventPreview(deps, proposals)}
      `;
    }
    const aiButton = document.querySelector("[data-family-smart-event-ai-preview]");
    if (aiButton) {
      aiButton.disabled = !String(deps.state.smartEventInput || "").trim() || deps.state.smartEventAiLoading;
      aiButton.textContent = deps.state.smartEventAiLoading ? deps.uiText("event.smartAiLoading", "Cleaning...") : deps.uiText("event.smartAiPreview", "AI clean");
    }
    const saveButton = document.querySelector("[data-family-smart-event-save]");
    if (saveButton) {
      saveButton.disabled = !proposals.length || deps.state.smartEventSaving;
      saveButton.textContent = deps.state.smartEventSaving ? deps.uiText("event.smartSaving", "Saving...") : deps.uiText("event.smartSave", "Review and save");
    }
  }

  function renderFamilySmartEventPanel(deps) {
    const selectedDate = deps.state.selectedDate || deps.ymd(new Date());
    const input = deps.state.smartEventInput || "";
    const proposals = familySmartEventProposals(deps, selectedDate);
    const canClean = Boolean(String(input).trim()) && !deps.state.smartEventAiLoading;
    return `
      <section class="panel familySmartEventPanel">
        <div class="panelHeader">
          <div>
            <p class="label">${deps.uiText("event.smartLabel", "Smart input")}</p>
            <h2>${deps.escapeHtml(deps.compactDateLabel(selectedDate))}</h2>
          </div>
        </div>
        <div class="panelBody">
          <textarea data-family-smart-event-input rows="4" autocomplete="off" aria-label="${deps.uiText("event.smartLabel", "Smart input")}" placeholder="${deps.uiText("event.smartPlaceholder", "연차/10:30 3교시 참관수업 / 2:30 스파예가")}">${deps.escapeHtml(input)}</textarea>
          <p class="formNote">${deps.uiText("event.smartHelp", "Review the preview, then save to the calendar.")}</p>
          <div class="familySmartEventPreview" data-family-smart-event-preview>
            <p class="label">${deps.uiText("event.smartPreview", "Preview")}</p>
            ${renderFamilySmartEventSourceNote(deps)}
            ${renderFamilySmartEventPreview(deps, proposals)}
          </div>
          <div class="formActions">
            <button class="openButton" type="button" data-add-event-mode="normal">${deps.uiText("event.manualFallback", "Manual input")}</button>
            <button class="openButton" type="button" data-family-smart-event-ai-preview ${canClean ? "" : "disabled"}>${deps.state.smartEventAiLoading ? deps.uiText("event.smartAiLoading", "Cleaning...") : deps.uiText("event.smartAiPreview", "AI clean")}</button>
            <button class="primaryButton" type="button" data-family-smart-event-save ${!proposals.length || deps.state.smartEventSaving ? "disabled" : ""}>${deps.state.smartEventSaving ? deps.uiText("event.smartSaving", "Saving...") : deps.uiText("event.smartSave", "Review and save")}</button>
          </div>
        </div>
      </section>
    `;
  }

  function renderFamilySmartEventSourceNote(deps) {
    if (deps.state.smartEventAiLoading) {
      return `<p class="formNote" data-family-smart-event-source>${deps.uiText("event.smartAiLoading", "Cleaning...")}</p>`;
    }
    if (deps.state.smartEventPreviewSource === "ai") {
      return `<p class="formNote" data-family-smart-event-source>${deps.uiText("event.smartSourceAi", "AI preview")}</p>`;
    }
    if (deps.state.smartEventAiError) {
      return `<p class="formNote" data-family-smart-event-source>${deps.uiText("event.smartSourceFallback", "AI unavailable; grammar preview is shown.")}</p>`;
    }
    return `<p class="formNote" data-family-smart-event-source>${deps.uiText("event.smartSourceGrammar", "Grammar preview")}</p>`;
  }

  function renderFamilySmartEventPreview(deps, proposals) {
    if (!proposals.length) return `<p class="taskMeta">${deps.uiText("event.smartEmpty", "Type one or more events to preview.")}</p>`;
    return `
      <ul class="timeline">
        ${proposals
          .map(
            (item, index) => `
              <li>
                <time class="${item.allDay ? "timelineAllDayPill" : ""}">${deps.escapeHtml(item.allDay ? deps.uiText("event.allDayPill", "All Day") : `${item.startTime}–${item.endTime}`)}</time>
                <span class="timelineLink familySmartEventPreviewBody">
                  <strong>${deps.escapeHtml(item.title)}</strong>
                  <span class="familySmartEventRange">${deps.escapeHtml(item.allDay ? deps.uiText("event.smartAllDayPreview", "All-day event") : `${item.startTime}–${item.endTime}`)}</span>
                  ${item.allDay ? "" : `
                    <span class="familySmartEventControls">
                      <button class="familySmartEventStep" type="button" data-family-smart-event-end-step="-60" data-family-smart-event-index="${index}" aria-label="${deps.uiText("event.smartShorter", "Shorten by one hour")}">&lt;&lt;</button>
                      <span class="familySmartEventDuration">${deps.escapeHtml(formatFamilySmartEventDuration(deps, item))}</span>
                      <button class="familySmartEventStep" type="button" data-family-smart-event-end-step="60" data-family-smart-event-index="${index}" aria-label="${deps.uiText("event.smartLonger", "Extend by one hour")}">&gt;&gt;</button>
                    </span>
                  `}
                </span>
              </li>
            `,
          )
          .join("")}
      </ul>
    `;
  }

  async function handleClick(deps, event) {
    const smartEventEndStep = event.target.closest("[data-family-smart-event-end-step]");
    if (smartEventEndStep) {
      const index = Number(smartEventEndStep.dataset.familySmartEventIndex);
      const step = Number(smartEventEndStep.dataset.familySmartEventEndStep);
      if (Number.isInteger(index) && Number.isInteger(step)) {
        const item = familySmartEventBaseProposals(deps, deps.state.selectedDate)[index];
        const currentOffset = Number(deps.state.smartEventEndOffsets[index] || 0);
        deps.state.smartEventEndOffsets[index] = item
          ? nextFamilySmartEventEndOffset(deps, item, currentOffset, step)
          : currentOffset + step;
        updateFamilySmartEventPreview(deps);
      }
      return true;
    }

    if (event.target.closest("[data-family-smart-event-ai-preview]")) {
      event.preventDefault();
      await requestFamilySmartEventAiPreview(deps);
      return true;
    }

    if (event.target.closest("[data-family-smart-event-save]")) {
      event.preventDefault();
      await saveFamilySmartEvents(deps);
      return true;
    }

    return false;
  }

  function handleInput(deps, event) {
    const smartEventInput = event.target.closest("[data-family-smart-event-input]");
    if (!smartEventInput) return false;
    deps.state.smartEventInput = smartEventInput.value;
    deps.state.smartEventAiProposals = null;
    deps.state.smartEventAiError = "";
    deps.state.smartEventPreviewSource = "grammar";
    deps.state.smartEventEndOffsets = {};
    updateFamilySmartEventPreview(deps);
    return true;
  }

  return {
    normalizeFamilySmartEventTime,
    cleanFamilySmartEventTitle,
    splitFamilySmartEventInput,
    splitFamilySmartEventWeakComma,
    familySmartEventCommaStartsNewEvent,
    parseFamilySmartEventInput,
    normalizeFamilySmartEventProposal,
    familySmartEventBaseProposals,
    adjustFamilySmartEventEnd,
    nextFamilySmartEventEndOffset,
    familySmartEventDurationMinutes,
    formatFamilySmartEventDuration,
    familySmartEventProposals,
    familySmartEventRangeLabel,
    familySmartEventPayload,
    familySmartEventSaveConfirmMessage,
    requestFamilySmartEventAiPreview,
    saveFamilySmartEvents,
    updateFamilySmartEventPreview,
    renderFamilySmartEventPanel,
    renderFamilySmartEventSourceNote,
    renderFamilySmartEventPreview,
    handleClick,
    handleInput,
  };
})();
