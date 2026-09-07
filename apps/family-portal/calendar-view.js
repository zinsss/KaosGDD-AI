window.KAOS_CALENDAR_VIEW = (() => {
  function renderCalendarMonthPanel(deps, options = {}) {
    const compact = options.compact === true;
    const month = deps.state.selectedDate.slice(0, 7);
    const events = deps.mockAdapter.getEvents();
    const regularEvents = events.filter((event) => !deps.isGoogleHolidayEvent(event) && !deps.isGeneratedCalendarEvent(event));
    const publicHolidayDates = new Set(
      deps.activeCalendarData().events.map(deps.normalizeEvent).filter(deps.isPublicHolidayEvent).map((event) => event.date),
    );
    const datedTasks = deps.mockAdapter.getTasks().filter((task) => task.due);
    const eventCounts = deps.countByDate(regularEvents, "date");
    const taskCounts = deps.countByDate(datedTasks, "due");
    const dutyDates = new Set(regularEvents.filter(deps.hasDutyEvent).map((event) => event.date));
    const marketDates = new Set(events.filter(deps.isMarketDayEvent).map((event) => event.date));
    const caregiverDays = new Set(
      deps.portalProfile() === "family" && deps.state.caregiver.key === month
        ? (deps.state.caregiver.data?.daily || [])
            .filter((item) => Number(item.minutes) > 0 || Number(item.extras) > 0)
            .map((item) => item.date)
        : [],
    );
    const weatherByDate = compact
      ? new Map()
      : new Map((deps.activeCalendarData().weather || []).map((weather) => [weather.date, weather]));
    return `
      <section class="panel calendarMonthPanel ${compact ? "isCompact" : ""}">
        <div class="panelHeader">
          <div>
            <p class="label">${deps.uiText("calendar.label", "Calendar")}</p>
            ${deps.renderCalendarMonthTitle(month)}
            ${deps.renderCalendarPicker(month)}
          </div>
          <div class="calendarHeaderActions" aria-label="${deps.uiText("calendar.actionsAria", "Calendar actions")}">
            <div class="monthNav" aria-label="${deps.uiText("calendar.monthNavigationAria", "Month navigation")}">
              <button class="monthNavButton" type="button" data-month-shift="-1" aria-label="${deps.uiText("calendar.previousMonth", "Previous month")}">&lt;&lt;</button>
              <button class="monthTodayButton" type="button" data-month-today>${deps.uiText("calendar.today", "Today")}</button>
              <button class="monthNavButton" type="button" data-month-shift="1" aria-label="${deps.uiText("calendar.nextMonth", "Next month")}">&gt;&gt;</button>
            </div>
            ${!compact && deps.portalProfile() === "family" ? `<a class="openButton" href="#/caregiver">${deps.uiText("caregiver.label", "Caregiver")}</a>` : ""}
            ${!compact && deps.portalProfile() === "family" ? `<a class="openButton" href="#/add-event" data-calendar-add-event>${deps.uiText("common.add", "Add")}</a>` : ""}
          </div>
        </div>
        <div class="calendarGrid" aria-label="${deps.uiText("calendar.monthGridAria", "Month grid")}">
          ${deps.calendarWeekdays().map((day) => `<span class="weekday">${day}</span>`).join("")}
          ${deps.monthCells(month)
            .map((cell) => {
              const hasDuty = dutyDates.has(cell.value);
              const hasCaregiver = caregiverDays.has(cell.value);
              const hasMarket = marketDates.has(cell.value);
              const classes = [
                "day",
                cell.muted ? "isMuted" : "",
                cell.value === deps.ymd(new Date()) ? "isToday" : "",
                cell.value === deps.state.selectedDate ? "isSelected" : "",
                hasDuty ? "isDuty" : "",
                publicHolidayDates.has(cell.value) ? "isPublicHoliday" : "",
                deps.dateTone(cell.value),
              ]
                .filter(Boolean)
                .join(" ");
              const weather = weatherByDate.get(cell.value);
              const eventCount = eventCounts[cell.value] || 0;
              const taskCount = taskCounts[cell.value] || 0;
              return `
                <button class="${classes}" type="button" data-date="${cell.value}">
                  <span class="dayHeader">
                    <span class="dayNumber">${cell.label}</span>
                  </span>
                  ${deps.weatherGlyph(weather) ? `<span class="dayWeatherGlyph">${deps.escapeHtml(deps.weatherGlyph(weather))}</span>` : ""}
                  ${
                    hasCaregiver || hasMarket || eventCount || taskCount
                      ? `
                        <span class="dayMarkers">
                          ${hasCaregiver ? `<span class="dayCaregiverMark" aria-label="${deps.uiText("caregiver.dayMarker", "Caregiver record")}">•</span>` : ""}
                          ${hasMarket ? `<span class="dayMarketMark" aria-label="Market Day">•</span>` : ""}
                          ${eventCount ? `<span class="dayEventCount">${eventCount}</span>` : ""}
                          ${taskCount ? `<span class="dayTaskCount">${taskCount}</span>` : ""}
                        </span>
                      `
                      : ""
                  }
                </button>
              `;
            })
            .join("")}
        </div>
      </section>
    `;
  }

  return { renderCalendarMonthPanel };
})();
