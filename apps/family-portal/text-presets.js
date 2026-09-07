window.KAOS_TEXT_PRESETS = (() => {
  const STORAGE_KEY = "kaosgdd.v2.family.textPresets.v1";
  const RANDOM_STATE_KEY = "kaosgdd.v2.family.textPresets.randomState.v1";
  const DEFAULT_CATEGORIES = Object.freeze([
    {
      id: "default",
      name: "기본",
      texts: [
        "오늘도 잘 부탁드립니다.",
        "확인했습니다. 감사합니다.",
        "공유해 주셔서 감사합니다.",
      ],
    },
  ]);

  function textList(deps, value) {
    return deps.normalizeFamilyTextPresets(value);
  }

  function normalizeTextboxes(value) {
    const source = Array.isArray(value)
      ? value
      : String(value || "").split(/\r?\n/);
    const texts = source.map((line) => String(line || "").trim());
    return texts.length ? texts : [""];
  }

  function defaultDocument() {
    return {
      categories: DEFAULT_CATEGORIES.map((category) => ({
        id: category.id,
        name: category.name,
        texts: [...category.texts],
      })),
    };
  }

  function normalizeCategory(deps, category, index = 0) {
    if (!category || typeof category !== "object") return null;
    const name = String(category.name || "").trim() || deps.uiText("textPresets.untitledCategory", "Untitled");
    return {
      id: String(category.id || `category-${index + 1}`),
      name,
      texts: normalizeTextboxes(category.texts),
    };
  }

  function normalizeDocument(deps, value) {
    if (Array.isArray(value)) {
      const texts = textList(deps, value);
      return {
        categories: [
          {
            id: "default",
            name: deps.uiText("textPresets.defaultCategory", "Default"),
            texts: texts.length ? texts : [...DEFAULT_CATEGORIES[0].texts],
          },
        ],
      };
    }
    if (!value || typeof value !== "object") return defaultDocument();
    const categories = Array.isArray(value.categories)
      ? value.categories.map((category, index) => normalizeCategory(deps, category, index)).filter(Boolean)
      : [];
    return categories.length ? { categories } : defaultDocument();
  }

  function localDocument(deps) {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      return normalizeDocument(deps, parsed);
    } catch {
      return defaultDocument();
    }
  }

  function cacheDocument(deps, presetDocument) {
    const normalized = normalizeDocument(deps, presetDocument);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
    return normalized;
  }

  function signature(deps, presetDocument) {
    return JSON.stringify(normalizeDocument(deps, presetDocument).categories);
  }

  function selectedCategory(deps, presetDocument = loadDocument(deps)) {
    const categories = presetDocument.categories;
    const selectedId = deps.state.textPresets.selectedCategoryId;
    const selected = categories.find((category) => category.id === selectedId) || categories[0];
    deps.state.textPresets.selectedCategoryId = selected?.id || "";
    if (deps.state.textPresets.selectedTextIndex < 0 || deps.state.textPresets.selectedTextIndex >= (selected?.texts.length || 1)) {
      deps.state.textPresets.selectedTextIndex = 0;
    }
    return selected;
  }

  function applyDocument(deps, payload) {
    const normalized = normalizeDocument(deps, payload);
    deps.state.textPresets.checked = true;
    deps.state.textPresets.loading = false;
    deps.state.textPresets.error = "";
    deps.state.textPresets.revision = Number.isInteger(payload?.revision) ? payload.revision : Math.max(0, Number(payload?.revision) || 0);
    deps.state.textPresets.updatedAt = String(payload?.updatedAt || "");
    deps.state.textPresets.categories = deps.cloneValue(normalized.categories);
    cacheDocument(deps, normalized);
    selectedCategory(deps, normalized);
    return { ...normalized, revision: deps.state.textPresets.revision, updatedAt: deps.state.textPresets.updatedAt };
  }

  function loadDocument(deps) {
    if (Array.isArray(deps.state.textPresets.categories) && deps.state.textPresets.categories.length) {
      return normalizeDocument(deps, { categories: deps.cloneValue(deps.state.textPresets.categories) });
    }
    return localDocument(deps);
  }

  function saveDocument(deps, presetDocument) {
    const normalized = normalizeDocument(deps, presetDocument);
    deps.state.textPresets.categories = deps.cloneValue(normalized.categories);
    cacheDocument(deps, normalized);
    return normalized;
  }

  async function maybeMigrateLocalToServer(deps, remoteDocument, localDocumentBeforeLoad) {
    if (!remoteDocument || remoteDocument.revision !== 0) return false;
    if (!localDocumentBeforeLoad) return false;
    if (signature(deps, localDocumentBeforeLoad) === signature(deps, defaultDocument())) return false;
    if (signature(deps, localDocumentBeforeLoad) === signature(deps, remoteDocument)) return false;
    await persist(deps, localDocumentBeforeLoad, { renderAfter: false });
    return true;
  }

  async function load(deps, { force = false } = {}) {
    if (deps.portalProfile() !== "family") return null;
    if (deps.state.textPresets.loading) return null;
    if (deps.state.textPresets.checked && !force) return true;
    deps.state.textPresets.loading = true;
    deps.state.textPresets.error = "";
    let localDocumentBeforeLoad = null;
    try {
      localDocumentBeforeLoad = window.localStorage.getItem(STORAGE_KEY)
        ? localDocument(deps)
        : null;
    } catch {
      localDocumentBeforeLoad = null;
    }

    try {
      const response = await fetch("/api/text-presets", { headers: { Accept: "application/json" } });
      const documentValue = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(documentValue.error || `HTTP ${response.status}`);
      const remoteDocument = applyDocument(deps, documentValue);
      try {
        await maybeMigrateLocalToServer(deps, remoteDocument, localDocumentBeforeLoad);
      } catch (error) {
        deps.state.textPresets.error = error.message || deps.uiText("textPresets.conflict", "Another device saved first. Reloaded server copy; try again.");
      }
    } catch (error) {
      deps.state.textPresets.checked = true;
      deps.state.textPresets.loading = false;
      deps.state.textPresets.error = error.message || deps.uiText("textPresets.unavailable", "Could not load preset text.");
      deps.state.textPresets.categories = deps.cloneValue(localDocument(deps).categories);
    }
    if (deps.getRoute() === "text-presets") deps.render();
    return !deps.state.textPresets.error;
  }

  async function persist(deps, presetDocument, { renderAfter = true } = {}) {
    const normalized = saveDocument(deps, presetDocument);
    const baseRevision = Number.isInteger(deps.state.textPresets.revision) ? deps.state.textPresets.revision : 0;
    deps.state.textPresets.saving = true;
    deps.state.textPresets.error = "";
    if (renderAfter && deps.getRoute() === "text-presets") deps.render();
    try {
      const response = await fetch("/api/text-presets", {
        method: "PUT",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ baseRevision, categories: normalized.categories }),
      });
      const documentValue = await response.json().catch(() => ({}));
      if (response.status === 409 && documentValue.document) {
        applyDocument(deps, documentValue.document);
        throw new Error(deps.uiText("textPresets.conflict", "Another device saved first. Reloaded server copy; try again."));
      }
      if (!response.ok) throw new Error(documentValue.error || `HTTP ${response.status}`);
      applyDocument(deps, documentValue);
      return loadDocument(deps);
    } catch (error) {
      deps.state.textPresets.error = error.message || deps.uiText("textPresets.saveError", "Could not save preset text.");
      throw error;
    } finally {
      deps.state.textPresets.saving = false;
      if (renderAfter && deps.getRoute() === "text-presets") deps.render();
    }
  }

  function saveEditorDraft(deps) {
    const form = document.querySelector("[data-family-text-preset-editor]");
    const documentValue = loadDocument(deps);
    if (!form) return documentValue;
    const categoryId = form.dataset.familyTextCategory || "";
    const textIndex = Number(form.dataset.familyTextIndex || "0");
    const textInput = form.querySelector("[data-family-text-current-text]");
    const category = documentValue.categories.find((item) => item.id === categoryId);
    if (!category || !Number.isInteger(textIndex) || textIndex < 0) return documentValue;
    while (category.texts.length <= textIndex) category.texts.push("");
    category.texts[textIndex] = String(textInput?.value || "").trim();
    return saveDocument(deps, documentValue);
  }

  function readRandomState() {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(RANDOM_STATE_KEY) || "null");
      return parsed && typeof parsed === "object" && parsed.categories && typeof parsed.categories === "object"
        ? parsed
        : { categories: {} };
    } catch {
      return { categories: {} };
    }
  }

  function writeRandomState(value) {
    try {
      window.localStorage.setItem(RANDOM_STATE_KEY, JSON.stringify(value));
    } catch {
      // Copying should still work if private-mode/localStorage quota blocks history.
    }
  }

  function shuffledIndexes(count) {
    const indexes = Array.from({ length: count }, (_value, index) => index);
    for (let index = indexes.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [indexes[index], indexes[swapIndex]] = [indexes[swapIndex], indexes[index]];
    }
    return indexes;
  }

  function randomPreset(deps, category) {
    const normalized = textList(deps, category?.texts || []);
    if (!normalized.length) return "";
    const categoryId = String(category?.id || category?.name || "default");
    const presetSignature = JSON.stringify(normalized);
    const randomState = readRandomState();
    const categoryState = randomState.categories[categoryId] && typeof randomState.categories[categoryId] === "object"
      ? randomState.categories[categoryId]
      : {};
    let remaining = Array.isArray(categoryState.remaining)
      ? categoryState.remaining.filter((index) => Number.isInteger(index) && index >= 0 && index < normalized.length)
      : [];
    if (categoryState.signature !== presetSignature || !remaining.length) {
      remaining = shuffledIndexes(normalized.length);
    }
    const selectedIndex = remaining.shift();
    randomState.categories[categoryId] = {
      signature: presetSignature,
      remaining,
    };
    writeRandomState(randomState);
    return normalized[selectedIndex] || normalized[0];
  }

  function renderCategoryButton(deps, category) {
    const count = textList(deps, category.texts).length;
    return `
      <button class="familyTextPresetCategory" type="button" data-family-text-category-copy="${deps.escapeHtml(category.id)}">
        <strong>${deps.escapeHtml(category.name)}</strong>
        <span>${deps.uiText("textPresets.copyRandom", "Copy random")}</span>
        <small>${deps.uiText("textPresets.textCount", "{count} texts", { count })}</small>
      </button>
    `;
  }

  function renderCategoryTabs(deps, documentValue, category) {
    return `
      <div class="familyTextPresetTabs" role="tablist" aria-label="${deps.uiText("textPresets.categories", "Categories")}">
        ${documentValue.categories.map((item) => `
          <button class="${item.id === category.id ? "isActive" : ""}" type="button" data-family-text-category-select="${deps.escapeHtml(item.id)}">
            ${deps.escapeHtml(item.name)}
          </button>
        `).join("")}
        <button type="button" data-family-text-category-add>+ ${deps.uiText("textPresets.category", "Category")}</button>
      </div>
    `;
  }

  function renderTextTabs(deps, category, selectedIndex) {
    const texts = category.texts.length ? category.texts : [""];
    return `
      <div class="familyTextPresetTabs isTextTabs" role="tablist" aria-label="${deps.uiText("textPresets.textTabs", "Preset text tabs")}">
        ${texts.map((text, index) => `
          <button class="${index === selectedIndex ? "isActive" : ""}" type="button" data-family-text-tab="${index}">
            ${index + 1}${String(text || "").trim() ? "" : "*"}
          </button>
        `).join("")}
        <button type="button" data-family-text-tab-add>+</button>
      </div>
    `;
  }

  function render(deps) {
    const documentValue = loadDocument(deps);
    const category = selectedCategory(deps, documentValue);
    const selectedIndex = Math.min(
      Math.max(0, deps.state.textPresets.selectedTextIndex),
      Math.max(0, (category?.texts.length || 1) - 1),
    );
    const selectedText = category?.texts[selectedIndex] || "";
    const totalCount = documentValue.categories.reduce((count, item) => count + textList(deps, item.texts).length, 0);
    const statusHtml = `
      ${deps.state.textPresets.loading ? `<p class="formNote">${deps.uiText("textPresets.loading", "Loading preset text...")}</p>` : ""}
      ${deps.state.textPresets.saving ? `<p class="formNote">${deps.uiText("textPresets.saving", "Saving preset text...")}</p>` : ""}
      ${deps.state.textPresets.error ? `
        <div class="caregiverError">
          ${deps.escapeHtml(deps.uiText("textPresets.unavailable", "Could not load preset text."))}: ${deps.escapeHtml(deps.state.textPresets.error)}
          <button type="button" data-family-text-presets-retry>${deps.uiText("common.retry", "Retry")}</button>
        </div>
        <p class="formNote">${deps.uiText("textPresets.localFallback", "Showing this device's cached copy until the server reconnects.")}</p>
      ` : ""}
    `;
    if (!deps.state.textPresets.managing) {
      return `
        <section class="panel familyTextPresetsPage">
          <div class="panelHeader">
            <div>
              <p class="label">${deps.uiText("textPresets.label", "Preset Text")}</p>
              <h2>${deps.uiText("textPresets.title", "차팅")}</h2>
            </div>
            <button class="openButton" type="button" data-family-text-presets-manage>${deps.uiText("textPresets.manage", "Manage")}</button>
          </div>
          <div class="panelBody">
            ${statusHtml}
            <p class="formNote">${deps.uiText("textPresets.help", "Tap a category to copy one random saved phrase.")}</p>
            <div class="familyTextPresetCategoryGrid">
              ${documentValue.categories.map((item) => renderCategoryButton(deps, item)).join("")}
            </div>
            <p class="formNote">${deps.uiText("textPresets.shared", "{categoryCount} categories · {textCount} texts · shared on the server", {
              categoryCount: documentValue.categories.length,
              textCount: totalCount,
            })}</p>
          </div>
        </section>
      `;
    }
    return `
      <section class="panel familyTextPresetsPage">
        <div class="panelHeader">
          <div>
            <p class="label">${deps.uiText("textPresets.label", "Preset Text")}</p>
            <h2>${deps.uiText("textPresets.manageTitle", "차팅 관리")}</h2>
          </div>
          <button class="openButton" type="button" data-family-text-presets-done>${deps.uiText("common.done", "Done")}</button>
        </div>
        <div class="panelBody">
          ${statusHtml}
          ${renderCategoryTabs(deps, documentValue, category)}
          <div class="familyTextPresetManageActions">
            <button class="openButton" type="button" data-family-text-category-rename>${deps.uiText("textPresets.renameCategory", "Rename category")}</button>
            <button class="dangerButton" type="button" data-family-text-category-delete>${deps.uiText("textPresets.deleteCategory", "Delete category")}</button>
          </div>
          <form class="familyTextPresetEditor" data-family-text-preset-editor data-family-text-category="${deps.escapeHtml(category.id)}" data-family-text-index="${selectedIndex}">
            ${renderTextTabs(deps, category, selectedIndex)}
            <label>
              <span>${deps.uiText("textPresets.text", "Text")}</span>
              <textarea data-family-text-current-text rows="6" spellcheck="false">${deps.escapeHtml(selectedText)}</textarea>
            </label>
            <div class="settingsActionRow">
              <button class="dangerButton" type="button" data-family-text-tab-delete>${deps.uiText("textPresets.deleteText", "Delete text")}</button>
              <button class="primaryButton" type="submit">${deps.uiText("common.save", "Save")}</button>
            </div>
          </form>
        </div>
      </section>
    `;
  }

  async function handleClick(deps, event) {
    const copyCategory = event.target.closest("[data-family-text-category-copy]");
    if (copyCategory) {
      const documentValue = loadDocument(deps);
      const category = documentValue.categories.find((item) => item.id === copyCategory.dataset.familyTextCategoryCopy);
      const preset = randomPreset(deps, category);
      if (!preset) {
        window.alert(deps.uiText("textPresets.emptyCategory", "This category has no saved text yet."));
        return true;
      }
      try {
        await deps.writeTextToClipboard(preset);
        window.alert(deps.uiText("textPresets.copied", "Preset text copied."));
      } catch {
        window.alert(deps.uiText("textPresets.copyError", "Could not copy preset text."));
      }
      return true;
    }

    if (event.target.closest("[data-family-text-presets-manage]")) {
      deps.state.textPresets.managing = true;
      selectedCategory(deps);
      deps.render();
      return true;
    }

    if (event.target.closest("[data-family-text-presets-retry]")) {
      deps.state.textPresets.checked = false;
      deps.state.textPresets.error = "";
      load(deps, { force: true });
      return true;
    }

    if (event.target.closest("[data-family-text-presets-done]")) {
      try {
        await persist(deps, saveEditorDraft(deps));
        deps.state.textPresets.managing = false;
        deps.render();
      } catch {
        window.alert(deps.uiText("textPresets.saveError", "Could not save preset text."));
      }
      return true;
    }

    const categoryTab = event.target.closest("[data-family-text-category-select]");
    if (categoryTab) {
      saveEditorDraft(deps);
      deps.state.textPresets.selectedCategoryId = categoryTab.dataset.familyTextCategorySelect || "";
      deps.state.textPresets.selectedTextIndex = 0;
      deps.render();
      return true;
    }

    if (event.target.closest("[data-family-text-category-add]")) {
      saveEditorDraft(deps);
      const name = window.prompt(deps.uiText("textPresets.categoryNamePrompt", "Category name?"), "");
      const normalizedName = String(name || "").trim();
      if (!normalizedName) return true;
      const documentValue = loadDocument(deps);
      const category = {
        id: deps.createId("text-preset-category"),
        name: normalizedName,
        texts: [""],
      };
      documentValue.categories.push(category);
      deps.state.textPresets.selectedCategoryId = category.id;
      deps.state.textPresets.selectedTextIndex = 0;
      deps.state.textPresets.managing = true;
      try {
        await persist(deps, documentValue);
      } catch {
        window.alert(deps.uiText("textPresets.saveError", "Could not save preset text."));
      }
      return true;
    }

    if (event.target.closest("[data-family-text-category-rename]")) {
      saveEditorDraft(deps);
      const documentValue = loadDocument(deps);
      const category = selectedCategory(deps, documentValue);
      const name = window.prompt(deps.uiText("textPresets.categoryNamePrompt", "Category name?"), category.name);
      const normalizedName = String(name || "").trim();
      if (!normalizedName) return true;
      category.name = normalizedName;
      try {
        await persist(deps, documentValue);
      } catch {
        window.alert(deps.uiText("textPresets.saveError", "Could not save preset text."));
      }
      return true;
    }

    if (event.target.closest("[data-family-text-category-delete]")) {
      saveEditorDraft(deps);
      const documentValue = loadDocument(deps);
      const category = selectedCategory(deps, documentValue);
      if (documentValue.categories.length <= 1) {
        window.alert(deps.uiText("textPresets.keepOneCategory", "Keep at least one category."));
        return true;
      }
      if (!window.confirm(deps.uiText("textPresets.deleteCategoryConfirm", "Delete this category?"))) return true;
      documentValue.categories = documentValue.categories.filter((item) => item.id !== category.id);
      deps.state.textPresets.selectedCategoryId = documentValue.categories[0]?.id || "";
      deps.state.textPresets.selectedTextIndex = 0;
      try {
        await persist(deps, documentValue);
      } catch {
        window.alert(deps.uiText("textPresets.saveError", "Could not save preset text."));
      }
      return true;
    }

    const textTab = event.target.closest("[data-family-text-tab]");
    if (textTab) {
      saveEditorDraft(deps);
      deps.state.textPresets.selectedTextIndex = Number(textTab.dataset.familyTextTab || "0") || 0;
      deps.render();
      return true;
    }

    if (event.target.closest("[data-family-text-tab-add]")) {
      const documentValue = saveEditorDraft(deps);
      const category = selectedCategory(deps, documentValue);
      category.texts.push("");
      deps.state.textPresets.selectedTextIndex = category.texts.length - 1;
      saveDocument(deps, documentValue);
      deps.render();
      return true;
    }

    if (event.target.closest("[data-family-text-tab-delete]")) {
      const documentValue = saveEditorDraft(deps);
      const category = selectedCategory(deps, documentValue);
      const selectedIndex = Math.min(Math.max(0, deps.state.textPresets.selectedTextIndex), Math.max(0, category.texts.length - 1));
      if (category.texts.length <= 1) category.texts = [""];
      else category.texts.splice(selectedIndex, 1);
      deps.state.textPresets.selectedTextIndex = Math.min(selectedIndex, Math.max(0, category.texts.length - 1));
      try {
        await persist(deps, documentValue);
      } catch {
        window.alert(deps.uiText("textPresets.saveError", "Could not save preset text."));
      }
      return true;
    }

    return false;
  }

  async function handleSubmit(deps, event) {
    const form = event.target.closest("[data-family-text-preset-editor]");
    if (!form) return false;
    event.preventDefault();
    try {
      await persist(deps, saveEditorDraft(deps));
      window.alert(deps.uiText("textPresets.saved", "Preset text saved."));
    } catch {
      window.alert(deps.uiText("textPresets.saveError", "Could not save preset text."));
    }
    return true;
  }

  return {
    load,
    render,
    handleClick,
    handleSubmit,
  };
})();
