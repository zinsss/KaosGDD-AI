window.KAOS_SUPPLIES_VIEW = (() => {
  function renderSupplyRow(deps, item) {
    const done = deps.state.supplies.mode === "done";
    return `
      <li class="supplyRow ${done ? "isDone" : ""}">
        <button class="checkButton supplyCheck" type="button" data-supply-${done ? "active" : "done"}="${deps.escapeHtml(item.id)}" aria-label="${done ? "Move back to active" : "Mark done"}"></button>
        <div class="supplyRowMain">
          <strong>${deps.escapeHtml(item.title || "Untitled supply")}</strong>
          <span>${deps.escapeHtml(done ? item.done_at_display || item.done_date_key || "Done" : item.created_at || "")}</span>
        </div>
        ${
          done
            ? `<button class="taskIconButton" type="button" data-supply-delete="${deps.escapeHtml(item.id)}" aria-label="Delete supply" title="Delete supply">×</button>`
            : ""
        }
      </li>
    `;
  }

  function renderSupplies(deps, options = {}) {
    const compact = options.compact === true;
    const active = deps.state.supplies.mode === "active";
    const loadingText = !deps.state.supplies.checked ? "Loading supplies..." : "";
    const emptyText = active ? "No supplies queued." : "No done supplies.";
    if (!compact) {
      const rows = deps.state.supplies.items
        .map((item) => {
          const date = deps.archiveDateParts(item.updatedAt || item.created || item.completed || item.lastModified || "");
          return `
            <li class="archiveRecord">
              <button class="archiveRecordButton" type="button" data-supply-${active ? "done" : "active"}="${deps.escapeHtml(item.id)}" aria-label="${active ? "Mark done" : "Move back to active"}">
                <span class="archiveRecordId">#${deps.escapeHtml(String(item.id || "").slice(0, 8) || "--")}</span>
                <time class="archiveRecordDate" datetime="${deps.escapeHtml(date.raw)}">${deps.escapeHtml(date.label)}</time>
                <strong class="archiveRecordTitle">${deps.escapeHtml(item.title || "Untitled supply")}</strong>
              </button>
              <button class="archiveSourceLink" type="button" data-supply-delete="${deps.escapeHtml(item.id)}" aria-label="Delete ${deps.escapeHtml(item.title || "supply")}">DEL</button>
            </li>
          `;
        })
        .join("");
      const summary = deps.state.supplies.checked && !deps.state.supplies.error
        ? `${deps.state.supplies.items.length} ITEMS // ${active ? "ACTIVE" : "DONE"} BOARD`
        : deps.state.supplies.loading
          ? "LOADING SUPPLY BOARD"
          : "SUPPLY BOARD STANDBY";
      return `
        <section class="archiveTerminal" data-archive-kind="supplies" aria-label="Supplies board">
          <div class="segmentedTabs archiveModeTabs" role="tablist" aria-label="Supply mode">
            <button type="button" role="tab" class="${active ? "isActive" : ""}" data-supplies-mode="active" aria-selected="${active}">Active</button>
            <button type="button" role="tab" class="${!active ? "isActive" : ""}" data-supplies-mode="done" aria-selected="${!active}">Done</button>
          </div>
          ${
            active && deps.state.supplies.presets.length
              ? `<div class="supplyPresets" aria-label="Recent supplies">
                  ${deps.state.supplies.presets
                    .map((preset) => `<button type="button" data-supply-preset="${deps.escapeHtml(preset.name)}">${deps.escapeHtml(preset.name)}</button>`)
                    .join("")}
                </div>`
              : ""
          }
          <section class="archiveIndex" aria-labelledby="suppliesIndexTitle" aria-busy="${deps.state.supplies.loading}">
            <header class="archiveIndexHeader">
              <h3 id="suppliesIndexTitle">RECORD BOARD</h3>
              <p class="archiveStatusMessage" role="status" aria-live="polite">${deps.escapeHtml(summary)}</p>
            </header>
            <div class="archiveColumnHeader" aria-hidden="true">
              <span>NO.</span><span>DATE</span><span>TITLE</span>
            </div>
            ${
              deps.state.supplies.error
                ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(deps.state.supplies.error)}</p><button class="archiveAction" type="button" data-supplies-retry>RETRY</button></div>`
                : loadingText
                  ? `<p class="archiveStatusMessage">${loadingText}</p>`
                  : deps.state.supplies.items.length
                    ? `<ol class="archiveRecordList">${rows}</ol>`
                    : `<p class="archiveStatusMessage">${emptyText}</p>`
            }
          </section>
        </section>
      `;
    }
    return `
      <section class="panel ${compact ? "embedSuppliesPanel" : ""}">
        <form class="composer supplyComposer" data-create-supply>
          <label>
            <span>Item</span>
            <input name="title" type="text" autocomplete="off" placeholder="gauze" required />
          </label>
          ${compact ? `<button class="openButton supplyAddButton" type="submit">Add</button>` : ""}
        </form>
        <div class="panelBody">
          <div class="segmentedTabs supplyModeTabs" role="group" aria-label="Supply mode">
            <button type="button" class="${active ? "isActive" : ""}" data-supplies-mode="active">Active</button>
            <button type="button" class="${!active ? "isActive" : ""}" data-supplies-mode="done">Done</button>
          </div>
          ${
            active && deps.state.supplies.presets.length
              ? `<div class="supplyPresets" aria-label="Recent supplies">
                  ${deps.state.supplies.presets
                    .map((preset) => `<button type="button" data-supply-preset="${deps.escapeHtml(preset.name)}">${deps.escapeHtml(preset.name)}</button>`)
                    .join("")}
                </div>`
              : ""
          }
          ${
            deps.state.supplies.error
              ? `<div class="emptyState">${deps.escapeHtml(deps.state.supplies.error)}</div>`
              : loadingText
                ? `<div class="emptyState">${loadingText}</div>`
                : deps.state.supplies.items.length
                  ? `<ul class="supplyList">
                      ${deps.state.supplies.items.map((item) => renderSupplyRow(deps, item)).join("")}
                    </ul>`
                  : `<div class="emptyState">${emptyText}</div>`
          }
        </div>
      </section>
    `;
  }

  function renderAddSupply(deps) {
    return `
      <form class="archiveTerminal archiveUploadPanel supplyAddPanel" data-create-supply aria-label="Add supply">
        <section class="archiveIndex">
          <header class="archiveIndexHeader">
            <div>
              <h3>ADD SUPPLY</h3>
              <p class="archiveStatusMessage">Supplies are stored as Radicale VTODO items in the supplies profile.</p>
            </div>
            <a class="archiveAction" href="#/supplies">BACK</a>
          </header>
          <div class="archiveFormRows">
            <label class="archiveFormRow">
              <span>ITEM</span>
              <input name="title" type="text" autocomplete="off" placeholder="gauze" required />
            </label>
          </div>
          <div class="archiveUploadActions">
            <button class="archiveAction isPrimary" type="submit">ADD</button>
            <a class="archiveAction" href="#/supplies">CANCEL</a>
          </div>
        </section>
      </form>
    `;
  }

  return {
    renderSupplyRow,
    renderSupplies,
    renderAddSupply,
  };
})();
