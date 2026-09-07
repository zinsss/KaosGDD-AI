window.KAOS_AI_TASKS_VIEW = (() => {
  function labelsForProfile(deps) {
    return deps.portalProfile() === "family"
      ? {
          page: "AI 도움",
          note: "질문만 입력하면 공식/의학 자료를 찾아 요약해요. PDF가 있으면 파일을 더할 수 있어요.",
          prompt: "질문",
          details: "자료 추가",
          detailsHint: "URL / 원문",
          sourceText: "원문",
          running: "AI 작업 중",
          failed: "AI 작업 실패",
          result: "결과",
          partialResult: "일부 결과",
          generalWeb: "웹 참고자료",
          archive: "AI 기록",
          memoPreview: "메모 미리보기",
          memoText: "메모 내용",
          copy: "복사",
          saveMemo: "메모 저장",
          saving: "저장 중",
          saved: "저장됨",
          run: "실행",
          starting: "시작 중",
          clear: "지우기",
          back: "뒤로",
          searchWeb: "웹 검색",
          searching: "검색 중",
          count: (count) => `${count}개 기록`,
          loading: "AI 기록을 불러오는 중",
          standby: "AI 기록 대기",
          empty: "아직 저장된 AI 기록이 없어요.",
          reading: "AI 기록을 읽는 중...",
          sourceNote: "추가 웹 참고자료입니다. 중요한 판단은 공식 자료로 다시 확인하세요.",
          sourceQuality: "자료 종류",
          guideline: "진료지침",
          official: "공식자료",
          textbook: "교과서",
          pubmed: "PubMed 초록",
          review: "임상 리뷰",
          web: "웹",
        }
      : {
          page: "AI TASK",
          note: "Prompt-only searches official sources. Add PDF or open Details for URL/source text.",
          prompt: "PROMPT",
          details: "DETAILS",
          detailsHint: "URL / source text",
          sourceText: "TEXT",
          running: "AI TASK RUNNING",
          failed: "AI TASK FAILED",
          result: "RESULT",
          partialResult: "PARTIAL RESULT",
          generalWeb: "GENERAL WEB CONTEXT",
          archive: "AI TASK ARCHIVE",
          memoPreview: "MEMO PREVIEW",
          memoText: "MEMO TEXT",
          copy: "copy",
          saveMemo: "SAVE MEMO",
          saving: "SAVING",
          saved: "SAVED",
          run: "RUN",
          starting: "STARTING",
          clear: "CLEAR",
          back: "BACK",
          searchWeb: "SEARCH WEB",
          searching: "SEARCHING",
          count: (count) => `${count} TASKS`,
          loading: "LOADING AI TASKS",
          standby: "AI TASK BOARD STANDBY",
          empty: "No AI tasks archived yet.",
          reading: "Reading AI task archive...",
          sourceNote: "Supplemental web context. Verify important decisions against official sources.",
          sourceQuality: "SOURCE QUALITY",
          guideline: "GUIDELINE",
          official: "OFFICIAL",
          textbook: "TEXTBOOK",
          pubmed: "PUBMED ABSTRACT",
          review: "CLINICAL REVIEW",
          web: "WEB",
        };
  }

  function aiTaskSourceHost(url) {
    try {
      return new URL(String(url || "")).hostname;
    } catch (_error) {
      return "";
    }
  }

  function aiTaskSourceQualityKey(source) {
    const sourceType = String(source?.type || "").toLowerCase();
    const url = String(source?.url || "");
    const host = aiTaskSourceHost(url).toLowerCase();
    const title = String(source?.title || source?.citation || source?.book || "").toLowerCase();
    const combined = `${host} ${url.toLowerCase()} ${title} ${sourceType}`;
    if (sourceType.includes("pubmed") || host === "pubmed.ncbi.nlm.nih.gov") return "pubmed";
    if (
      combined.includes("guideline") ||
      combined.includes("clinical-practice-guideline") ||
      combined.includes("clinical practice guideline") ||
      combined.includes("진료지침") ||
      combined.includes("가이드라인") ||
      host.includes("guideline.or.kr") ||
      host.includes("komgi.kr") ||
      host.includes("nice.org.uk") ||
      host.includes("entnet.org") ||
      host.includes("aasm.org") ||
      host.includes("jcsm.aasm.org")
    ) {
      return "guideline";
    }
    if (
      host.endsWith(".go.kr") ||
      host.endsWith(".gov") ||
      host.includes("kdca.go.kr") ||
      host.includes("mohw.go.kr") ||
      host.includes("hira.or.kr") ||
      host.includes("nhis.or.kr") ||
      host.includes("mfds.go.kr") ||
      host.includes("health.kr") ||
      host.includes("nih.gov") ||
      host.includes("cdc.gov")
    ) {
      return "official";
    }
    if (host.includes("aafp.org") || combined.includes("american family physician") || combined.includes("review")) {
      return "review";
    }
    return "web";
  }

  function aiTaskSourceQualityCounts(sources, textbookSources) {
    const counts = { guideline: 0, official: 0, textbook: 0, pubmed: 0, review: 0, web: 0 };
    if (Array.isArray(sources)) {
      for (const source of sources) {
        counts[aiTaskSourceQualityKey(source)] += 1;
      }
    }
    if (Array.isArray(textbookSources)) {
      counts.textbook += textbookSources.length;
    }
    return counts;
  }

  function renderAiTaskSourceQuality(deps, sources, textbookSources, labels = {}) {
    const counts = aiTaskSourceQualityCounts(sources, textbookSources);
    const entries = [
      ["guideline", labels.guideline || "GUIDELINE"],
      ["official", labels.official || "OFFICIAL"],
      ["textbook", labels.textbook || "TEXTBOOK"],
      ["pubmed", labels.pubmed || "PUBMED ABSTRACT"],
      ["review", labels.review || "CLINICAL REVIEW"],
      ["web", labels.web || "WEB"],
    ].filter(([key]) => counts[key] > 0);
    if (!entries.length) return "";
    return `
      <section class="aiTaskSourceQuality" aria-label="${deps.escapeHtml(labels.title || "Source quality")}">
        <p>${deps.escapeHtml(labels.title || "SOURCE QUALITY")}</p>
        <div>
          ${entries.map(([key, label]) => `<span class="aiTaskQualityChip is-${deps.escapeHtml(key)}">${deps.escapeHtml(label)} <small>${counts[key]}</small></span>`).join("")}
        </div>
      </section>
    `;
  }

  function renderAiTaskPlan(deps, plan) {
    if (!plan || typeof plan !== "object") return "";
    const alternates = Array.isArray(plan.alternateQueries) ? plan.alternateQueries.join(" // ") : "";
    const domains = Array.isArray(plan.preferredDomains) ? plan.preferredDomains.join(" // ") : "";
    return `
      <dl class="archiveMetadata aiTaskPlan">
        ${deps.archiveMeta("Query", plan.query || "")}
        ${deps.archiveMeta("Also", alternates)}
        ${deps.archiveMeta("Domains", domains)}
        ${deps.archiveMeta("Task", plan.task || "")}
      </dl>
    `;
  }

  function renderAiTaskSources(deps, sources) {
    if (!Array.isArray(sources) || !sources.length) return "";
    return `
      <details class="aiTaskSources" open>
        <summary><span>SOURCES</span><small>${sources.length}</small></summary>
        <ol>
          ${sources
            .map((source) => {
              const title = String(source?.title || source?.url || "source");
              const url = String(source?.url || "#");
              const host = aiTaskSourceHost(url);
              return `
                <li>
                  <a class="archiveInlineLink" href="${deps.escapeHtml(url)}" target="_blank" rel="noreferrer">${deps.escapeHtml(title)}</a>
                  ${host ? `<small>${deps.escapeHtml(host)}</small>` : ""}
                </li>
              `;
            })
            .join("")}
        </ol>
      </details>
    `;
  }

  function renderAiTaskTextbookSources(deps, sources) {
    if (!Array.isArray(sources) || !sources.length) return "";
    return `
      <details class="aiTaskSources aiTaskTextbookSources" open>
        <summary><span>TEXTBOOK BACKGROUND</span><small>${sources.length}</small></summary>
        <ol>
          ${sources
            .map((source) => {
              const title = String(source?.citation || source?.title || "textbook source");
              const book = String(source?.book || "");
              const edition = String(source?.edition || "");
              const page = source?.page ? `p. ${source.page}` : "";
              const excerpt = String(source?.excerpt || "").trim();
              const meta = [book, edition, page].filter(Boolean).join(" // ");
              return `
                <li>
                  <strong>${deps.escapeHtml(title)}</strong>
                  ${meta ? `<small>${deps.escapeHtml(meta)}</small>` : ""}
                  ${excerpt ? `<pre>${deps.escapeHtml(excerpt)}</pre>` : ""}
                </li>
              `;
            })
            .join("")}
        </ol>
      </details>
    `;
  }

  function renderAiTaskStatePanel(deps, preview, labels = null) {
    const status = String(preview?.status || "");
    if (status !== "running" && status !== "failed") return "";
    const text = labels || {
      running: "AI TASK RUNNING",
      failed: "AI TASK FAILED",
      back: "BACK",
      searchWeb: "SEARCH WEB",
      copy: "copy",
      partialResult: "PARTIAL RESULT",
      sourceQuality: "SOURCE QUALITY",
      runningMessage: "Governor is searching/fetching sources and waiting for KaosBrain. This card will refresh automatically.",
    };
    const isRunning = status === "running";
    const result = preview?.result && typeof preview.result === "object" ? preview.result : {};
    const sourceInfo = preview?.source && typeof preview.source === "object" ? preview.source : {};
    const resultSources = Array.isArray(result.sources)
      ? result.sources
      : Array.isArray(sourceInfo.sources)
        ? sourceInfo.sources
        : [];
    const textbookSources = Array.isArray(result.textbookSources)
      ? result.textbookSources
      : Array.isArray(sourceInfo.textbookSources)
        ? sourceInfo.textbookSources
        : [];
    const resultContent = String(result.content || "").trim();
    const canCopy = Boolean(resultContent);
    const canSearchGeneralWeb = !isRunning && deps.aiTaskIsOfficialWebPreview(preview) && resultSources.length > 0;
    return `
      <section class="archiveDetail aiTaskPreview aiTaskStatePanel" aria-label="AI task ${deps.escapeHtml(status)}">
        <header class="archiveDetailHeader">
          <div>
            <p>${deps.escapeHtml(isRunning ? text.running : text.failed)}</p>
            <h3>${deps.escapeHtml(preview?.title || preview?.prompt || "AI Task")}</h3>
          </div>
          <div class="archiveActions">
            ${preview?.archived ? `<button class="archiveAction" type="button" data-ai-task-close>${deps.escapeHtml(text.back)}</button>` : ""}
            ${canSearchGeneralWeb ? `<button class="archiveAction" type="button" data-ai-task-general-web>${deps.escapeHtml(text.searchWeb)}</button>` : ""}
            ${canCopy ? `<button class="archiveAction" type="button" data-ai-task-copy>${deps.escapeHtml(text.copy)}</button>` : ""}
            <button class="archiveAction" type="button" data-ai-tasks-refresh>↻</button>
          </div>
        </header>
        <dl class="archiveMetadata">
          ${deps.archiveMeta("Status", status)}
          ${deps.archiveMeta("Started", preview?.createdAt || "")}
          ${deps.archiveMeta("Updated", preview?.updatedAt || "")}
          ${deps.archiveMeta("Source", sourceInfo.type || "")}
        </dl>
        <div class="${isRunning ? "archiveNotice" : "archiveError"}" data-ai-task-detail role="status" tabindex="0">
          <p>${isRunning ? deps.escapeHtml(text.runningMessage) : deps.escapeHtml(deps.aiTaskErrorMessage(preview?.error || "ai_task_background_failed"))}</p>
        </div>
        ${renderAiTaskPlan(deps, sourceInfo.plan)}
        ${renderAiTaskSourceQuality(deps, resultSources, textbookSources, {
          title: text.sourceQuality,
        })}
        ${resultContent ? `<div class="archiveOcrRegion" role="region" aria-label="AI task partial result"><p>${deps.escapeHtml(text.partialResult)}</p><pre>${deps.escapeHtml(resultContent)}</pre></div>` : ""}
        ${renderAiTaskSources(deps, resultSources)}
        ${renderAiTaskTextbookSources(deps, textbookSources)}
      </section>
    `;
  }

  function renderAiTasks(deps) {
    const aiTasks = deps.state.aiTasks;
    const familyAiTasks = deps.portalProfile() === "family";
    const labels = labelsForProfile(deps);
    const selectedId = String(aiTasks.selectedId || "");
    const rows = aiTasks.items
      .map((item) => {
        const date = deps.archiveDateParts(item.createdAt);
        return `
          <li class="archiveRecord ${selectedId === String(item.id) ? "isSelected" : ""}">
            <button class="archiveRecordButton" type="button" data-ai-task-open="${deps.escapeHtml(item.id)}" aria-current="${selectedId === String(item.id) ? "true" : "false"}">
              <span class="archiveRecordId">#${deps.escapeHtml(item.id)}</span>
              <time class="archiveRecordDate" datetime="${deps.escapeHtml(date.raw)}">${deps.escapeHtml(date.label)}</time>
              <strong class="archiveRecordTitle">${deps.escapeHtml(item.title)}</strong>
              <span class="archiveRecordStatus ${deps.archiveStatusClass(item.status)}">${deps.escapeHtml(item.status.toUpperCase())}</span>
            </button>
          </li>
        `;
      })
      .join("");
    const preview = aiTasks.preview;
    const memo = preview?.memo || {};
    const result = preview?.result || {};
    const sourceInfo = preview?.source && typeof preview.source === "object" ? preview.source : {};
    const resultSources = Array.isArray(result.sources)
      ? result.sources
      : Array.isArray(sourceInfo.sources)
        ? sourceInfo.sources
        : [];
    const textbookSources = Array.isArray(result.textbookSources)
      ? result.textbookSources
      : Array.isArray(sourceInfo.textbookSources)
        ? sourceInfo.textbookSources
        : [];
    const webResult = {
      title: String(result.title || memo.title || preview?.title || "AI Task"),
      content: String(result.content || memo.content || ""),
      checkedAt: String(result.checkedAt || sourceInfo.checkedAt || ""),
      model: String(result.model || preview?.provider || ""),
      sources: resultSources,
      textbookSources,
    };
    const isArchivedPreview = Boolean(preview?.archived);
    const isAppliedPreview = String(preview?.status || "") === "applied";
    const canSavePreview = Boolean(preview && !isAppliedPreview && String(preview.taskId || "").trim() && deps.aiTaskMemoContentFromPreview(preview));
    const isResultPreview = deps.aiTaskIsResultPreview(preview);
    const isGeneralWebPreview = preview?.kind === "general_web" || String(sourceInfo.type || "") === "general_web_search";
    const canSearchGeneralWeb = deps.aiTaskIsOfficialWebPreview(preview);
    const statePanel = renderAiTaskStatePanel(deps, preview, {
      ...labels,
      runningMessage: familyAiTasks
        ? "자료를 찾고 KaosBrain 답변을 기다리는 중이에요. 이 카드는 자동으로 새로고침됩니다."
        : "Governor is searching/fetching sources and waiting for KaosBrain. This card will refresh automatically.",
    });
    return `
      <section class="archiveTerminal" data-archive-kind="ai-tasks" aria-label="${deps.escapeHtml(familyAiTasks ? "Family AI Tasks" : "AI Tasks")}">
        <form class="archiveIndex aiTaskComposer" data-ai-task-unified>
          <header class="archiveIndexHeader">
            <div>
              <h3>${deps.escapeHtml(labels.page)}</h3>
              <p class="archiveStatusMessage">${deps.escapeHtml(labels.note)}</p>
            </div>
            <button class="archiveAction" type="button" data-ai-tasks-refresh ${aiTasks.loading ? "disabled" : ""}>↻</button>
          </header>
          <label class="archiveCommandLine aiTaskPrompt">
            <span>${deps.escapeHtml(labels.prompt)}</span>
            <textarea name="prompt" rows="4" placeholder="예: 알모그란정 급여기준과 차트 기재 추천">${deps.escapeHtml(aiTasks.prompt)}</textarea>
          </label>
          <label class="archiveCommandLine">
            <span>PDF</span>
            <input name="sourcePdf" type="file" accept="application/pdf,.pdf" />
          </label>
          <label class="archiveInlineToggle aiTaskLanguageToggle">
            <input name="outputKorean" type="checkbox" ${aiTasks.korean ? "checked" : ""} />
            <span>한국어</span>
          </label>
          <details class="aiTaskSourceDetails">
            <summary><span>${deps.escapeHtml(labels.details)}</span><small>${deps.escapeHtml(labels.detailsHint)}</small></summary>
            <div class="aiTaskSourceDetailsBody">
              <label class="archiveCommandLine">
                <span>URL</span>
                <input name="sourceUrl" type="url" inputmode="url" autocomplete="url" placeholder="optional official source URL" value="${deps.escapeHtml(aiTasks.sourceUrl)}" />
              </label>
              <label class="archiveCommandLine aiTaskSourceText">
                <span>${deps.escapeHtml(labels.sourceText)}</span>
                <textarea name="sourceText" rows="4" placeholder="optional pasted source text">${deps.escapeHtml(aiTasks.sourceText)}</textarea>
              </label>
            </div>
          </details>
          ${
            aiTasks.error
              ? `<div class="archiveError" role="alert"><p>${deps.escapeHtml(aiTasks.error)}</p></div>`
              : ""
          }
          <div class="archiveActions">
            <button class="archiveAction isActive" type="submit" ${aiTasks.previewing ? "disabled" : ""}>${aiTasks.previewing ? deps.escapeHtml(labels.starting) : deps.escapeHtml(labels.run)}</button>
            <button class="archiveAction" type="button" data-ai-task-clear>${deps.escapeHtml(labels.clear)}</button>
          </div>
        </form>
        ${
          statePanel
            ? statePanel
            : isResultPreview
            ? `
              <section class="archiveDetail aiTaskPreview" aria-label="AI task result">
                <header class="archiveDetailHeader">
                  <div>
                    <p>${deps.escapeHtml(isGeneralWebPreview ? labels.generalWeb : isArchivedPreview ? labels.archive : labels.result)}</p>
                    <h3>${deps.escapeHtml(webResult.title)}</h3>
                  </div>
                  <div class="archiveActions">
                    ${isArchivedPreview ? `<button class="archiveAction" type="button" data-ai-task-close>${deps.escapeHtml(labels.back)}</button>` : ""}
                    ${
                      canSearchGeneralWeb
                        ? `<button class="archiveAction" type="button" data-ai-task-general-web ${aiTasks.previewing ? "disabled" : ""}>${aiTasks.previewing ? deps.escapeHtml(labels.searching) : deps.escapeHtml(labels.searchWeb)}</button>`
                        : ""
                    }
                    <button class="archiveAction" type="button" data-ai-task-copy>${deps.escapeHtml(labels.copy)}</button>
                    ${
                      canSavePreview
                        ? `<button class="archiveAction isActive" type="button" data-ai-task-save-memo ${aiTasks.applying ? "disabled" : ""}>${aiTasks.applying ? deps.escapeHtml(labels.saving) : deps.escapeHtml(labels.saveMemo)}</button>`
                        : isAppliedPreview
                          ? `<span class="archiveAction isDisabled">${deps.escapeHtml(labels.saved)}</span>`
                          : ""
                    }
                  </div>
                </header>
                <dl class="archiveMetadata">
                  ${deps.archiveMeta("Status", preview?.status || "")}
                  ${deps.archiveMeta("Checked", webResult.checkedAt)}
                  ${deps.archiveMeta("Model", webResult.model)}
                  ${deps.archiveMeta("Memo", result.memoName || "")}
                </dl>
                ${
                  isGeneralWebPreview
                    ? `<div class="archiveNotice"><p>${deps.escapeHtml(labels.sourceNote)}</p></div>`
                    : ""
                }
                ${renderAiTaskPlan(deps, sourceInfo.plan)}
                ${renderAiTaskSourceQuality(deps, webResult.sources, webResult.textbookSources, {
                  title: labels.sourceQuality,
                  guideline: labels.guideline,
                  official: labels.official,
                  textbook: labels.textbook,
                  pubmed: labels.pubmed,
                  review: labels.review,
                  web: labels.web,
                })}
                <div class="archiveOcrRegion" data-ai-task-detail role="region" aria-label="AI task result" tabindex="0">
                  <p>${deps.escapeHtml(labels.result)}</p>
                  <pre>${deps.escapeHtml(webResult.content)}</pre>
                </div>
                ${renderAiTaskSources(deps, webResult.sources)}
                ${renderAiTaskTextbookSources(deps, webResult.textbookSources)}
              </section>
            `
            : preview
            ? `
              <section class="archiveDetail aiTaskPreview" aria-label="AI memo preview">
                <header class="archiveDetailHeader">
                  <div>
                    <p>${deps.escapeHtml(isArchivedPreview ? labels.archive : labels.memoPreview)}</p>
                    <h3>${deps.escapeHtml(memo.title || "AI memo")}</h3>
                  </div>
                  <div class="archiveActions">
                    ${isArchivedPreview ? `<button class="archiveAction" type="button" data-ai-task-close>${deps.escapeHtml(labels.back)}</button>` : ""}
                    <button class="archiveAction" type="button" data-ai-task-copy>${deps.escapeHtml(labels.copy)}</button>
                    ${
                      canSavePreview
                        ? `<button class="archiveAction isActive" type="button" data-ai-task-save-memo ${aiTasks.applying ? "disabled" : ""}>${aiTasks.applying ? deps.escapeHtml(labels.saving) : deps.escapeHtml(labels.saveMemo)}</button>`
                        : isAppliedPreview
                          ? `<span class="archiveAction isDisabled">${deps.escapeHtml(labels.saved)}</span>`
                          : ""
                    }
                  </div>
                </header>
                <dl class="archiveMetadata">
                  ${deps.archiveMeta("Status", preview?.status || "")}
                  ${deps.archiveMeta("Source", memo.sourceTitle || sourceInfo.title || "")}
                  ${deps.archiveMeta("URL", memo.sourceUrl || sourceInfo.url || "")}
                  ${deps.archiveMeta("Checked", memo.checkedAt || "")}
                  ${deps.archiveMeta("Memo", result.memoName || "")}
                </dl>
                <div class="archiveOcrRegion" data-ai-task-detail role="region" aria-label="AI memo content" tabindex="0">
                  <p>${deps.escapeHtml(labels.memoText)}</p>
                  <pre>${deps.escapeHtml(memo.content || "")}</pre>
                </div>
              </section>
            `
            : ""
        }
        <section class="archiveIndex" aria-labelledby="aiTasksArchiveTitle" aria-busy="${aiTasks.loading}">
          <header class="archiveIndexHeader">
            <h3 id="aiTasksArchiveTitle">${deps.escapeHtml(labels.archive)}</h3>
            <p class="archiveStatusMessage" role="status" aria-live="polite">${deps.escapeHtml(aiTasks.checked && !aiTasks.error ? labels.count(aiTasks.items.length) : aiTasks.loading ? labels.loading : labels.standby)}</p>
          </header>
          <div class="archiveColumnHeader" aria-hidden="true">
            <span>NO.</span><span>DATE</span><span>TITLE</span>
          </div>
          ${
            aiTasks.loading && !aiTasks.checked
              ? `<p class="archiveStatusMessage">${deps.escapeHtml(labels.reading)}</p>`
              : aiTasks.checked && !rows
                ? `<p class="archiveStatusMessage">${deps.escapeHtml(labels.empty)}</p>`
                : rows
                  ? `<ol class="archiveRecordList">${rows}</ol>`
                  : ""
          }
        </section>
      </section>
    `;
  }

  return {
    labelsForProfile,
    aiTaskSourceHost,
    aiTaskSourceQualityKey,
    aiTaskSourceQualityCounts,
    renderAiTaskSourceQuality,
    renderAiTaskPlan,
    renderAiTaskSources,
    renderAiTaskTextbookSources,
    renderAiTaskStatePanel,
    renderAiTasks,
  };
})();
