(function attachPortalTypography(global) {
  const fontOptions = Object.freeze([
    { id: "sarasa", label: "Sarasa Gothic Mono", translationKey: "settings.fontSarasa" },
    { id: "elice", label: "Elice Digital Baeum", translationKey: "settings.fontElice" },
    { id: "pretendard", label: "Pretendard", translationKey: "settings.fontPretendard" },
    { id: "orbit", label: "Orbit", translationKey: "settings.fontOrbit" },
    { id: "nanum", label: "NanumBarunPen", translationKey: "settings.fontNanum" },
    { id: "nixgon", label: "Nixgon", translationKey: "settings.fontNixgon" },
    { id: "skybori", label: "SKYBORI", translationKey: "settings.fontSkybori" },
    { id: "watermelon", label: "Watermelon", translationKey: "settings.fontWatermelon" },
    { id: "board-marker", label: "School Safe Board Marker", translationKey: "settings.fontBoardMarker" },
    { id: "milky-way", label: "School Safety Milky Way", translationKey: "settings.fontMilkyWay" },
    { id: "kita", label: "KITA", translationKey: "settings.fontKita" },
    { id: "free-time", label: "School Safety Free Time", translationKey: "settings.fontFreeTime" },
  ]);
  const fontIds = fontOptions.map((option) => option.id);
  const fontIdSet = new Set(fontIds);
  const familyTitleFontOptions = Object.freeze([
    { id: "subakhwa", label: "116수박화" },
    { id: "gultokki", label: "HS굴토끼" },
    { id: "jibtokki-round", label: "HS집토끼 둥근체" },
    { id: "lotteria", label: "롯데리아 딱붙어체" },
  ]);
  const familyTitleFontIds = new Set(familyTitleFontOptions.map((option) => option.id));
  const familyTitleFontFamilies = Object.freeze({
    subakhwa: '"116Subakhwa", sans-serif',
    gultokki: '"HsGultokki", sans-serif',
    "jibtokki-round": '"HsJibtokiRound", sans-serif',
    lotteria: '"Lotteria", sans-serif',
  });
  const familyTitleFontKey = "kaosgdd.v2.family.titleFont.v1";
  const familyTitleFontEnabledKey = "kaosgdd.v2.family.titleFontEnabled.v1";
  const fontScaleOptions = Object.freeze([80, 85, 90, 95, 100, 105, 110, 115, 120]);
  const profiles = Object.freeze({
    family: { fontKey: "kaosgdd.v2.family.font.v1", scaleKey: "kaosgdd.v2.family.fontScale.v1", fallback: "nanum" },
    main: { fontKey: "kaosgdd.v2.main.font.v1", scaleKey: "kaosgdd.v2.main.fontScale.v1", fallback: "sarasa" },
  });

  function activeProfile() {
    return global.location.hostname === "family.kaosgdd.net" ? "family" : "main";
  }

  function fontPreference(profile) {
    const config = profiles[profile];
    const stored = global.localStorage.getItem(config.fontKey) || "";
    return fontIdSet.has(stored) ? stored : config.fallback;
  }

  function applyFontPreference(profile, value = fontPreference(profile)) {
    const app = global.document.querySelector(".app");
    if (!app) return;
    const datasetKey = profile === "family" ? "familyFont" : "mainFont";
    if (activeProfile() !== profile) {
      delete app.dataset[datasetKey];
      return;
    }
    app.dataset[datasetKey] = fontIdSet.has(value) ? value : profiles[profile].fallback;
  }

  function setFontPreference(profile, value) {
    const config = profiles[profile];
    const normalized = fontIdSet.has(value) ? value : config.fallback;
    global.localStorage.setItem(config.fontKey, normalized);
    applyFontPreference(profile, normalized);
  }

  function familyTitleFontPreference() {
    const stored = global.localStorage.getItem(familyTitleFontKey) || "";
    return familyTitleFontIds.has(stored) ? stored : "subakhwa";
  }

  function familyTitleFontEnabled() {
    return global.localStorage.getItem(familyTitleFontEnabledKey) === "true";
  }

  function applyFamilyTitleFontPreference() {
    const app = global.document.querySelector(".app");
    if (!app || activeProfile() !== "family") {
      if (app) {
        delete app.dataset.familyTitleFont;
        delete app.dataset.familyTitleFontEnabled;
      }
      return;
    }
    const selectedFont = familyTitleFontPreference();
    app.dataset.familyTitleFont = selectedFont;
    app.dataset.familyTitleFontEnabled = String(familyTitleFontEnabled());
    app.style?.setProperty("--family-title-font", familyTitleFontFamilies[selectedFont]);
  }

  function setFamilyTitleFontPreference(value) {
    const normalized = familyTitleFontIds.has(value) ? value : "subakhwa";
    global.localStorage.setItem(familyTitleFontKey, normalized);
    applyFamilyTitleFontPreference();
  }

  function setFamilyTitleFontEnabled(value) {
    global.localStorage.setItem(familyTitleFontEnabledKey, String(Boolean(value)));
    applyFamilyTitleFontPreference();
  }

  function fontScalePreference(profile) {
    const stored = Number(global.localStorage.getItem(profiles[profile].scaleKey));
    return fontScaleOptions.includes(stored) ? stored : 100;
  }

  function applyFontScalePreference(profile, value = fontScalePreference(profile)) {
    const app = global.document.querySelector(".app");
    const normalized = fontScaleOptions.includes(Number(value)) ? Number(value) : 100;
    const datasetKey = profile === "family" ? "familyFontScale" : "mainFontScale";
    if (!app || activeProfile() !== profile) {
      if (app) delete app.dataset[datasetKey];
      return;
    }
    app.dataset[datasetKey] = String(normalized);
    global.document.documentElement.style.fontSize = `${normalized}%`;
  }

  function setFontScalePreference(profile, value) {
    const requested = Number(value);
    const normalized = fontScaleOptions.includes(requested) ? requested : 100;
    global.localStorage.setItem(profiles[profile].scaleKey, String(normalized));
    applyFontScalePreference(profile, normalized);
  }

  function stepFontScale(profile, direction) {
    const currentIndex = fontScaleOptions.indexOf(fontScalePreference(profile));
    const delta = Math.sign(Number(direction) || 0);
    const nextIndex = Math.max(0, Math.min(fontScaleOptions.length - 1, currentIndex + delta));
    setFontScalePreference(profile, fontScaleOptions[nextIndex]);
  }

  function applyPortalFontScalePreference() {
    global.document.documentElement.style.removeProperty("font-size");
    applyFontScalePreference("family");
    applyFontScalePreference("main");
  }

  global.KAOS_PORTAL_TYPOGRAPHY = Object.freeze({
    fontOptions,
    fontIds,
    fontIdSet,
    fontScaleOptions,
    familyTitleFontOptions,
    familyFontPreference: () => fontPreference("family"),
    applyFamilyFontPreference: (value) => applyFontPreference("family", value),
    setFamilyFontPreference: (value) => setFontPreference("family", value),
    familyTitleFontPreference,
    familyTitleFontEnabled,
    applyFamilyTitleFontPreference,
    setFamilyTitleFontPreference,
    setFamilyTitleFontEnabled,
    familyFontScalePreference: () => fontScalePreference("family"),
    applyFamilyFontScalePreference: (value) => applyFontScalePreference("family", value),
    setFamilyFontScalePreference: (value) => setFontScalePreference("family", value),
    stepFamilyFontScale: (direction) => stepFontScale("family", direction),
    mainFontPreference: () => fontPreference("main"),
    applyMainFontPreference: (value) => applyFontPreference("main", value),
    setMainFontPreference: (value) => setFontPreference("main", value),
    mainFontScalePreference: () => fontScalePreference("main"),
    applyMainFontScalePreference: (value) => applyFontScalePreference("main", value),
    setMainFontScalePreference: (value) => setFontScalePreference("main", value),
    stepMainFontScale: (direction) => stepFontScale("main", direction),
    applyPortalFontScalePreference,
  });
})(window);
