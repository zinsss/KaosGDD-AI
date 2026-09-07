window.KAOS_CAREGIVER_VIEW = (() => {
  function renderCaregiver(deps) {
    const month = deps.state.selectedDate.slice(0, 7);
    const data = deps.state.caregiver.key === month ? deps.state.caregiver.data : null;
    const summary = data?.summary || {
      days: 0,
      minutes: 0,
      hourlyWage: 0,
      basePay: 0,
      extras: 0,
      transportFee: 0,
      total: 0,
    };
    const settings = data?.settings || {
      hourlyWage: 0,
      transportFee: 0,
    };
    const daily = Array.isArray(data?.daily) ? data.daily : [];
    const dailyByDate = new Map(daily.map((item) => [item.date, item]));
    const recordedDays = daily.filter((item) => Number(item.minutes) > 0 || Number(item.extras) > 0);
    const currentError = deps.state.caregiver.key === month ? deps.state.caregiver.error : "";
    const isLoading = deps.state.caregiver.loadingKey === month || (!data && !currentError);
    const statusBody = isLoading
      ? `<p class="taskMeta">${deps.uiText("caregiver.loading", "Loading monthly summary...")}</p>`
      : currentError
        ? `
            <div class="caregiverError">
              <span>${deps.escapeHtml(currentError)}</span>
              <button class="openButton" type="button" data-caregiver-retry>${deps.uiText("common.retry", "다시 시도")}</button>
            </div>
          `
        : "";
    return `
      <div class="caregiverPage">
        <section class="panel caregiverSummaryPanel">
          <div class="panelHeader">
            <div>
              <p class="label">${deps.uiText("caregiver.label", "Caregiver")}</p>
              <h2>${deps.escapeHtml(deps.monthTitle(month))}</h2>
            </div>
            <div class="calendarHeaderActions">
              <div class="monthNav" aria-label="${deps.uiText("calendar.monthNavigationAria", "Month navigation")}">
                <button class="monthNavButton" type="button" data-month-shift="-1" aria-label="${deps.uiText("calendar.previousMonth", "Previous month")}">&lt;&lt;</button>
                <button class="monthTodayButton" type="button" data-month-today>${deps.uiText("calendar.today", "Today")}</button>
                <button class="monthNavButton" type="button" data-month-shift="1" aria-label="${deps.uiText("calendar.nextMonth", "Next month")}">&gt;&gt;</button>
              </div>
              <a class="openButton" href="#/calendar">${deps.uiText("caregiver.backToCalendar", "Calendar")}</a>
            </div>
          </div>
          <div class="panelBody">
            ${statusBody}
            ${
              data
                ? `
                  <form class="caregiverSummaryForm" data-caregiver-settings-form>
                    <div class="caregiverSummaryRow">
                      <span>${deps.uiText("caregiver.totalTime", "Total care time")}</span>
                      <strong>${summary.days}${deps.uiText("caregiver.daysSuffix", "d")} / ${deps.formatCaregiverHours(summary.minutes)}</strong>
                    </div>
                    <label class="caregiverSummaryRow">
                      <span>${deps.uiText("caregiver.hourlyWage", "Hourly wage")}</span>
                      <span class="caregiverMoneyInput">
                        <input name="hourlyWage" type="text" inputmode="numeric" value="${deps.escapeHtml(settings.hourlyWage)}" />
                        <span>${deps.uiText("caregiver.wonSuffix", "won")}</span>
                      </span>
                    </label>
                    <div class="caregiverSummaryRow">
                      <span>${deps.uiText("caregiver.basePay", "Base pay")}</span>
                      <strong>${deps.formatCaregiverWon(summary.basePay)}</strong>
                    </div>
                    <div class="caregiverSummaryRow">
                      <span>${deps.uiText("caregiver.extras", "Extra fees")}</span>
                      <strong>${deps.formatCaregiverWon(summary.extras)}</strong>
                    </div>
                    <label class="caregiverSummaryRow">
                      <span>${deps.uiText("caregiver.transportFee", "Transport fee")}</span>
                      <span class="caregiverMoneyInput">
                        <input name="transportFee" type="text" inputmode="numeric" value="${deps.escapeHtml(settings.transportFee)}" />
                        <span>${deps.uiText("caregiver.wonSuffix", "won")}</span>
                      </span>
                    </label>
                    <div class="caregiverSummaryRow caregiverTotalRow">
                      <span>${deps.uiText("caregiver.totalPay", "Total payment")}</span>
                      <strong>${deps.formatCaregiverWon(summary.total)}</strong>
                    </div>
                    <button class="primaryButton caregiverSettingsSave" type="submit">${deps.uiText("common.save", "Save")}</button>
                  </form>
                `
                : ""
            }
          </div>
        </section>
        ${
          data
            ? `
              <details class="panel caregiverDetailPanel">
                <summary class="caregiverDetailSummary">${deps.uiText("caregiver.details", "Monthly details")}</summary>
                <div class="panelBody caregiverDetailBody">
                  <div class="caregiverDetailTools">
                    <span>${deps.escapeHtml(deps.monthTitle(month))} 공유용 요약</span>
                    <button class="openButton" type="button" data-caregiver-copy-month>복사</button>
                  </div>
                  <div class="caregiverMonthGrid" aria-label="${deps.uiText("caregiver.monthGridAria", "Monthly care hours")}">
                    ${deps.calendarWeekdays().map((day) => `<span class="caregiverWeekday">${day}</span>`).join("")}
                    ${deps.monthCells(month)
                      .map((cell) => {
                        if (cell.muted) return '<span class="caregiverMonthDay isMuted" aria-hidden="true"></span>';
                        const item = dailyByDate.get(cell.value);
                        return `
                          <span class="caregiverMonthDay">
                            <span>${cell.label}</span>
                            <strong>${item?.minutes ? deps.formatCaregiverMonthCellHours(item.minutes) : ""}</strong>
                          </span>
                        `;
                      })
                      .join("")}
                  </div>
                  <div class="caregiverDailyList" aria-label="${deps.uiText("caregiver.dailyBreakdownAria", "Daily care details")}">
                    ${
                      recordedDays.length
                        ? recordedDays
                            .map(
                              (item) => `
                                <div class="caregiverDailyRow">
                                  <div class="caregiverDailyHeading">
                                    <strong>${deps.escapeHtml(item.date.slice(5))} ${deps.escapeHtml(item.weekday)}</strong>
                                    <span>${deps.escapeHtml(deps.formatCaregiverHours(item.minutes))}</span>
                                  </div>
                                  <div class="caregiverDailyAmounts">
                                    <span>${deps.uiText("caregiver.basePay", "Base pay")} ${deps.formatCaregiverWon(item.basePay)}</span>
                                    <span>${deps.uiText("caregiver.extras", "Extra fees")} ${deps.formatCaregiverWon(item.extras)}</span>
                                  </div>
                                  ${item.notes ? `<p>${deps.escapeHtml(item.notes)}</p>` : ""}
                                </div>
                              `,
                            )
                            .join("")
                        : `<p class="taskMeta">${deps.uiText("caregiver.noRecords", "No care records this month.")}</p>`
                    }
                  </div>
                </div>
              </details>
            `
            : ""
        }
      </div>
    `;
  }

  return { renderCaregiver };
})();
