const routes = {
  today: "Today",
  calendar: "Calendar",
  caregiver: "Caregiver",
  tasks: "Tasks",
  add: "Add",
  supplies: "Supplies",
  documents: "Document Inbox",
  "add-event": "Add Event",
  "edit-event": "Edit Event",
  "add-task": "Add Task",
  "edit-task": "Edit Task",
  services: "Utils",
  service: "Service",
  rouny: "Rouny",
  memos: "Memos",
  ledger: "Ledger",
  settings: "Settings",
};

const familyRoutes = {
  today: uiText("route.today", "Today"),
  calendar: uiText("route.calendar", "Calendar"),
  caregiver: uiText("route.caregiver", "Caregiver"),
  tasks: uiText("route.tasks", "Tasks"),
  add: uiText("route.add", "Add"),
  "add-event": uiText("route.addEvent", "Add Event"),
  "edit-event": uiText("route.editEvent", "Edit Event"),
  "add-task": uiText("route.addTask", "Add Task"),
  "edit-task": uiText("route.editTask", "Edit Task"),
  services: uiText("route.services", "Utils"),
  service: uiText("route.services", "Utils"),
  rouny: uiText("route.rouny", "Rouny"),
  memos: uiText("route.memos", "Memos"),
  ledger: uiText("route.ledger", "Ledger"),
  settings: uiText("route.settings", "Settings"),
};

const DEFAULT_TASK_DUE_TIME = "10:00";
const TASK_MEMO_PLACEHOLDER = "Plain memos or;\n-- active subtasks\n-x done subtasks";
const DEFAULT_EVENT_START_TIME = "09:00";
const DEFAULT_EVENT_END_TIME = "10:00";
const MEMOS_URL = "https://memos.kaosgdd.net";
const DESKTOP_MEDIA_QUERY = "(min-width: 1180px)";
const LEDGER_VIEWS = new Set(["all", "expense", "income"]);
const LEDGER_RANGES = new Set(["all", "year", "month", "week", "custom"]);
const LEDGER_EXPENSE_CATEGORIES = new Set(["계좌 지출", "현금 지출", "상품권 사용"]);
const LEDGER_INCOME_CATEGORIES = new Set(["계좌 수입", "현금 수입"]);
const ROUNY_TEMPLATE_STORAGE_KEY = "kaosgdd.v2.rouny.templates.v1";
const ROUNY_SELECTED_STORAGE_KEY = "kaosgdd.v2.rouny.selectedTemplateId.v1";
const ROUNY_INCLUDE_SATURDAY_KEY = "kaosgdd.v2.rouny.includeSaturday.v1";
const ROUNY_SYNC_REVISION_KEY = "kaosgdd.v2.rouny.syncRevision.v1";
const ROUNY_SYNC_DIRTY_KEY = "kaosgdd.v2.rouny.syncDirty.v1";
const EVENT_PRESET_STORAGE_KEY = "kaosgdd.v2.eventPresets.v1";
const COMPOSER_RECOVERY_STORAGE_KEY = "kaosgdd.v2.composerRecovery.v1";
const FAMILY_FONT_STORAGE_KEY = "kaosgdd.v2.family.font.v1";
const FAMILY_FONT_OPTIONS = new Set(["nanum", "pretendard", "nixgon", "skybori"]);
const MAIN_FONT_STORAGE_KEY = "kaosgdd.v2.main.font.v1";
const MAIN_FONT_OPTIONS = new Set(["pretendard", "orbit", "sarasa"]);
const WEATHER_LOCATION_STORAGE_KEY = "kaosgdd.v2.weather.location.v1";
const WEATHER_LOCATION_OPTIONS = [
  { id: "pohang", label: "Pohang", translationKey: "weather.locationPohang" },
  { id: "daegu", label: "Daegu", translationKey: "weather.locationDaegu" },
  { id: "yeongcheon", label: "Yeongcheon", translationKey: "weather.locationYeongcheon" },
  { id: "yeonghae", label: "Yeonghae", translationKey: "weather.locationYeonghae" },
];
const WEATHER_LOCATION_IDS = new Set(WEATHER_LOCATION_OPTIONS.map((location) => location.id));
const ROUNY_TIMELINE_DEFAULT_START_HOUR = 8;
const ROUNY_TIMELINE_DEFAULT_END_HOUR = 22;
const ROUNY_TIMELINE_HOUR_HEIGHT = 48;
const ROUNY_TIMELINE_SLOT_MINUTES = 10;
const ROUNY_DRAG_MOVE_THRESHOLD = 8;
const ROUNY_DRAG_HOLD_MS = 260;
const desktopMedia = window.matchMedia(DESKTOP_MEDIA_QUERY);
let rounyPointerDrag = null;
let suppressRounyGridClick = false;
let rounyRemoteLoadPromise = null;
let rounyRemoteSavePromise = null;
let rounyRemoteSavePending = false;

function isDesktopLayout() {
  return desktopMedia.matches;
}

const rounyDays = [
  { value: "1", label: "Mon", familyLabel: uiText("weekday.mon", "Mon") },
  { value: "2", label: "Tue", familyLabel: uiText("weekday.tue", "Tue") },
  { value: "3", label: "Wed", familyLabel: uiText("weekday.wed", "Wed") },
  { value: "4", label: "Thu", familyLabel: uiText("weekday.thu", "Thu") },
  { value: "5", label: "Fri", familyLabel: uiText("weekday.fri", "Fri") },
  { value: "6", label: "Sat", familyLabel: uiText("weekday.sat", "Sat") },
  { value: "0", label: "Sun", familyLabel: uiText("weekday.sun", "Sun") },
];

const rounyColors = ["pink", "peach", "yellow", "mint", "sky", "lavender", "gray"];
const rounyColorMap = {
  pink: "#f4c7df",
  peach: "#f6be9f",
  yellow: "#ebcb8b",
  mint: "#8fbcbb",
  sky: "#88c0d0",
  lavender: "#b48ead",
  gray: "#d8dee9",
};
const DEFAULT_ROUNY_COLOR = "#f4c7df";

const profileConfigs = {
  main: {
    label: "KaosGDD",
    defaultRoute: "today",
    nav: [
      { route: "today", label: "Today" },
      { route: "calendar", label: "Calendar" },
      { route: "tasks", label: "Tasks" },
      { route: "memos", label: "Memos" },
      { route: "services", label: "Utils" },
      { route: "settings", label: "Settings" },
    ],
  },
  family: {
    label: uiText("profile.family", "Family"),
    defaultRoute: "today",
    nav: [
      { route: "today", label: uiText("route.today", "Today") },
      { route: "calendar", label: uiText("route.calendar", "Calendar") },
      { route: "tasks", label: uiText("route.tasks", "Tasks") },
      { route: "rouny", label: uiText("route.rouny", "Rouny") },
      { route: "memos", label: uiText("route.memos", "Memos") },
      { route: "ledger", label: uiText("route.ledger", "Ledger") },
      { route: "settings", label: uiText("route.settings", "Settings") },
    ],
  },
};

const taskPriorityOptions = {
  none: { value: "", label: "None", rank: 10 },
  low: { value: "9", label: "Low", rank: 9 },
  medium: { value: "5", label: "Medium", rank: 5 },
  high: { value: "1", label: "High", rank: 1 },
};

const state = {
  selectedDate: ymd(new Date()),
  embedView: "calendar",
  currentCollection: "all",
  taskMode: "active",
  taskSort: "due",
  addKind: "event",
  addEventMode: "normal",
  addEventDraft: null,
  addTaskDraft: null,
  eventPresetDraft: null,
  addMonthExpanded: false,
  taskDueEnabled: false,
  editingEventId: "",
  editingTaskId: "",
  taskDescriptions: {},
  pendingTaskStatuses: {},
  remoteCalendar: {
    checked: false,
    configured: false,
    live: false,
    profile: "main",
    error: "",
    collections: [],
    events: [],
    tasks: [],
  },
  weatherLocation: weatherLocationPreference(),
  remoteWeather: {
    checked: false,
    live: false,
    key: "",
    loadingKey: "",
    error: "",
    items: [],
  },
  weatherSettings: {
    checked: false,
    loading: false,
    saving: false,
    error: "",
    version: 0,
  },
  governorSettings: {
    checked: false,
    loading: false,
    error: "",
    data: null,
  },
  weatherLocationPopup: {
    open: false,
    mode: "locations",
    key: "",
    date: "",
    loading: false,
    error: "",
    items: [],
  },
  caregiver: {
    key: "",
    loadingKey: "",
    error: "",
    data: null,
  },
  rouny: {
    checked: false,
    templates: [],
    selectedTemplateId: "",
    draft: null,
    undoStack: [],
    page: "list",
    editingItemId: "",
    editingItemDraft: null,
    dragTemplateId: "",
    includeSaturday: false,
    hasPersistedLocal: false,
    localRevision: null,
    localDirty: false,
    remoteChecked: false,
    remoteLoading: false,
    remoteLive: false,
    revision: 0,
    syncState: "local",
    syncError: "",
    remoteDocument: null,
  },
  eventPresets: {
    checked: false,
    loading: false,
    items: [],
    editingId: "",
    expanded: false,
    error: "",
  },
  recurringTasks: {
    checked: false,
    loading: false,
    items: [],
    editingId: "",
    expanded: false,
    error: "",
  },
  supplies: {
    checked: false,
    loading: false,
    mode: "active",
    error: "",
    items: [],
    presets: [],
  },
  documents: {
    checked: false,
    loading: false,
    error: "",
    items: [],
  },
  holidays: {
    checked: false,
    loading: false,
    syncing: false,
    expanded: false,
    error: "",
    items: [],
  },
  customEvents: {
    checked: false,
    loading: false,
    saving: false,
    expanded: false,
    error: "",
    marketDaysEnabled: true,
    claimDayEnabled: true,
    sync: null,
  },
  mailOrganizer: {
    checked: false,
    loading: false,
    saving: false,
    sending: false,
    expanded: false,
    enabled: false,
    configured: false,
    error: "",
    settings: {
      runsPerDay: 1,
      firstTime: "09:00",
      secondTime: "17:00",
    },
  },
  ledger: {
    checked: false,
    loading: false,
    saving: false,
    error: "",
    entries: [],
    balances: { account: 0, cash: 0, gift: 0 },
    categories: [],
    editingId: "",
    adding: false,
    view: "all",
    range: "month",
    rangeStart: "",
    rangeEnd: "",
  },
  desktopUtilsExpanded: null,
};

let remoteCalendarRequestId = 0;

const mockCalendarData = {
  collections: [],
  events: [],
  tasks: [],
  weather: [
    {
      city: "pohang",
      cityName: "Pohang",
      date: ymd(new Date()),
      glyph: "☀️",
      minTemp: 21,
      maxTemp: 32,
      dayparts: [
        { label: "Morning", glyph: "🌤️", minTemp: 22, maxTemp: 27 },
        { label: "Afternoon", glyph: "☀️", minTemp: 28, maxTemp: 32 },
        { label: "Evening", glyph: "🌧️", minTemp: 25, maxTemp: 29 },
        { label: "Night", glyph: "🌙", minTemp: 21, maxTemp: 24 },
      ],
    },
  ],
};

const mockAdapter = {
  getCollections() {
    return collectionViews();
  },

  getCurrentCollection() {
    return collectionViews().find((collection) => collection.id === state.currentCollection);
  },

  getEvents(collectionId = state.currentCollection) {
    return filterByCollectionView(activeCalendarData().events, collectionId).map(normalizeEvent).sort(sortByDateTime);
  },

  getTasks(collectionId = state.currentCollection) {
    return filterByCollectionView(activeCalendarData().tasks, collectionId).map(normalizeTask).sort(sortTasks);
  },

  createEvent(formData) {
    const title = String(formData.get("title") || "").trim();
    if (!title) return;
    const allDay = formData.get("allDay") === "on";
    const startDate = String(formData.get("startDate") || state.selectedDate);
    const endDate = String(formData.get("endDate") || startDate);
    const startTime = String(formData.get("startTime") || DEFAULT_EVENT_START_TIME);
    const endTime = String(formData.get("endTime") || DEFAULT_EVENT_END_TIME);
    activeCalendarData().events.push({
      uid: `event-${Date.now()}`,
      collection: writableCollectionIdFromForm(formData, "VEVENT"),
      summary: title,
      description: String(formData.get("memo") || "").trim(),
      dtstart: allDay ? startDate : `${startDate}T${startTime}:00`,
      dtend: allDay ? endDate : `${endDate}T${endTime}:00`,
      allDay,
      repeat: String(formData.get("repeat") || ""),
      alarm: String(formData.get("alarm") || ""),
    });
    state.selectedDate = startDate;
  },

  updateEvent(formData) {
    const uid = String(formData.get("uid") || "");
    const rawEvent = activeCalendarData().events.find((event) => event.uid === uid);
    if (!rawEvent) return;
    const allDay = formData.get("allDay") === "on";
    const startDate = String(formData.get("startDate") || state.selectedDate);
    const endDate = String(formData.get("endDate") || startDate);
    const startTime = String(formData.get("startTime") || DEFAULT_EVENT_START_TIME);
    const endTime = String(formData.get("endTime") || DEFAULT_EVENT_END_TIME);
    rawEvent.summary = String(formData.get("title") || "").trim();
    rawEvent.description = String(formData.get("memo") || "").trim();
    rawEvent.dtstart = allDay ? startDate : `${startDate}T${startTime}:00`;
    rawEvent.dtend = allDay ? endDate : `${endDate}T${endTime}:00`;
    rawEvent.startDate = startDate;
    rawEvent.startTime = allDay ? "" : startTime;
    rawEvent.endDate = endDate;
    rawEvent.endTime = allDay ? "" : endTime;
    rawEvent.allDay = allDay;
    rawEvent.repeat = String(formData.get("repeat") || "");
    rawEvent.alarmTime = String(formData.get("alarm") || "");
    rawEvent.lastModified = new Date().toISOString().slice(0, 19);
    state.selectedDate = startDate;
  },

  deleteEvent(uid) {
    const data = activeCalendarData();
    data.events = data.events.filter((event) => event.uid !== uid);
  },

  createTask(formData) {
    const title = String(formData.get("title") || "").trim();
    if (!title) return;
    const description = String(formData.get("memo") || "").trim();
    const due = taskDueFromForm(formData);
    activeCalendarData().tasks.push({
      uid: `task-${Date.now()}`,
      collection: writableCollectionIdFromForm(formData, "VTODO"),
      summary: title,
      description,
      due: due.date,
      dueTime: due.time,
      priority: taskPriorityFromForm(formData),
      status: "NEEDS-ACTION",
      lastModified: new Date().toISOString().slice(0, 19),
      categories: [],
    });
    state.taskMode = "active";
  },

  updateTask(formData) {
    const uid = String(formData.get("uid") || "");
    const rawTask = activeCalendarData().tasks.find((task) => task.uid === uid);
    if (!rawTask) return;
    const title = String(formData.get("title") || "").trim();
    if (!title) return;
    const due = taskDueFromForm(formData);
    rawTask.summary = title;
    rawTask.description = String(formData.get("memo") || "").trim();
    rawTask.due = due.date;
    rawTask.dueTime = due.time;
    rawTask.priority = taskPriorityFromForm(formData);
    rawTask.lastModified = new Date().toISOString().slice(0, 19);
    state.taskMode = rawTask.status === "COMPLETED" ? "done" : "active";
  },

  deleteTask(uid) {
    const data = activeCalendarData();
    data.tasks = data.tasks.filter((task) => task.uid !== uid);
  },

  getServices() {
    return [
      { id: "paperless", name: "Paperless", type: "Documents", href: "https://paperless.kaosgdd.net", meta: "Authoritative document archive", embed: true },
      { id: "sftpgo", name: "SFTPGo", type: "Files", href: "https://files.kaosgdd.net", meta: "Managed file access", embed: true },
      { id: "radicale", name: "Radicale", type: "Calendar", href: "https://calendar.kaosgdd.net", meta: "Calendar backend candidate", embed: true },
      { id: "vaultwarden", name: "Vaultwarden", type: "Passwords", href: "https://vault.kaosgdd.net", meta: "Credential vault", embed: false },
      { id: "stirling", name: "Stirling-PDF", type: "PDF", href: "https://pdf.kaosgdd.net", meta: "PDF workflows", embed: true },
    ];
  },
};

function serviceById(id) {
  return mockAdapter.getServices().find((service) => service.id === id) || null;
}

function serviceHref(service) {
  if (!service?.href || service.href.startsWith("#/") || !isDesktopLayout() || portalProfile() !== "main") {
    return service?.href || "";
  }
  if (service.embed === false) return service.href;
  return `#/service?service=${encodeURIComponent(service.id)}`;
}

function activeCalendarData() {
  if (state.remoteCalendar.live && state.remoteCalendar.collections.length) {
    return { ...state.remoteCalendar, weather: activeWeatherItems() };
  }
  return { ...mockCalendarData, weather: activeWeatherItems() };
}

function activeWeatherItems() {
  if (state.remoteWeather.live) return state.remoteWeather.items;
  return state.weatherLocation === "pohang" ? mockCalendarData.weather : [];
}

function collectionViews() {
  const data = activeCalendarData();
  const allIds = data.collections.map((collection) => collection.id);
  const views = [{ id: "all", name: uiText("collection.all", "All"), collectionIds: allIds }];
  if (portalProfile() === "family") return views;
  const ownerOrder = ["family", "zin", "wife"];
  const owners = [...new Set(data.collections.map((collection) => collection.owner).filter(Boolean))].sort((a, b) => {
    const rankA = ownerOrder.includes(a) ? ownerOrder.indexOf(a) : ownerOrder.length;
    const rankB = ownerOrder.includes(b) ? ownerOrder.indexOf(b) : ownerOrder.length;
    if (rankA !== rankB) return rankA - rankB;
    return a.localeCompare(b);
  });
  owners.forEach((owner) => {
    const collectionIds = data.collections.filter((collection) => collection.owner === owner).map((collection) => collection.id);
    if (collectionIds.length) {
      const ownerCollection = data.collections.find((collection) => collection.owner === owner);
      views.push({
        id: `owner:${owner}`,
        name: calendarOwnerLabel(owner, ownerCollection),
        collectionIds,
      });
    }
  });
  return views;
}

function calendarOwnerLabel(owner, collection = null) {
  const labels = {
    zin: "GDD_ZiN",
    family: uiText("collection.family", "Family"),
    wife: uiText("collection.wife", "Bling02"),
  };
  return labels[owner] || collection?.ownerLabel || collection?.name || owner || uiText("common.personal", "Personal");
}

function collectionForItem(item) {
  return activeCalendarData().collections.find((collection) => collection.id === item.collection) || null;
}

function collectionOwnerForItem(item) {
  const collection = collectionForItem(item);
  if (collection?.owner) return collection.owner;
  if (String(item.collection || "").includes("family")) return "family";
  if (String(item.collection || "").includes("wife") || String(item.collection || "").includes("bling")) return "wife";
  return defaultPersonalOwner();
}

function collectionPillForItem(item) {
  const collection = collectionForItem(item);
  const owner = collectionOwnerForItem(item);
  return {
    owner,
    ownerClass: String(owner || "personal").replace(/[^a-z0-9_-]/gi, "-").toLowerCase(),
    label: calendarOwnerLabel(owner, collection),
  };
}

function renderCollectionPill(item) {
  if (portalProfile() === "family") return "";
  const pill = collectionPillForItem(item);
  return `<span class="calendarPill is-${escapeHtml(pill.ownerClass)}">${escapeHtml(pill.label)}</span>`;
}

function renderAutomationPill(kind) {
  const labels = {
    brain: uiText("badge.brain", "Brain"),
    repeating: uiText("badge.repeating", "Repeating"),
  };
  return `<span class="calendarPill is-${escapeHtml(kind)}">${escapeHtml(labels[kind] || kind)}</span>`;
}

function filterByCollectionView(items, viewId) {
  const view = collectionViews().find((collection) => collection.id === viewId) || collectionViews()[0];
  if (view.id === "all") return items;
  return items.filter((item) => view.collectionIds.includes(item.collection));
}

function writableCollectionId() {
  const view = mockAdapter.getCurrentCollection();
  if (view?.id !== "all" && view?.collectionIds.length) return view.collectionIds[0];
  return activeCalendarData().collections[0]?.id || "zin";
}

function defaultPersonalOwner() {
  return portalProfile() === "family" ? "family" : "zin";
}

function defaultPersonalCollectionViewId() {
  return `owner:${defaultPersonalOwner()}`;
}

function ensureAddCollectionDefault() {
  if (state.currentCollection === "owner:family") return;
  const defaultView = defaultPersonalCollectionViewId();
  if (collectionViews().some((collection) => collection.id === defaultView)) {
    state.currentCollection = defaultView;
  }
}

function collectionIdsForOwner(owner) {
  return activeCalendarData().collections.filter((collection) => collection.owner === owner).map((collection) => collection.id);
}

function writableCollectionIdForOwner(owner, component) {
  const data = activeCalendarData();
  const collectionIds = collectionIdsForOwner(owner);
  const collections = collectionIds.length
    ? data.collections.filter((collection) => collectionIds.includes(collection.id))
    : data.collections;
  const typedCollection = collections.find((collection) => collection.components?.includes(component));
  if (typedCollection) return typedCollection.id;
  const namedCollection = collections.find((collection) =>
    component === "VTODO" ? /task|reminder/i.test(collection.name) : /calendar|event/i.test(collection.name),
  );
  if (namedCollection) return namedCollection.id;
  return collections[0]?.id || writableCollectionId();
}

function writableCollectionIdFromForm(formData, component) {
  const owner = formData.get("shareFamily") === "on" ? "family" : defaultPersonalOwner();
  return writableCollectionIdForOwner(owner, component);
}

function defaultEventPreset() {
  return {
    id: createId("event-preset"),
    name: "",
    title: "",
    allDay: true,
    startTime: DEFAULT_EVENT_START_TIME,
    endTime: DEFAULT_EVENT_END_TIME,
    alarm: "",
    memo: "",
    shareFamily: portalProfile() === "family",
  };
}

function normalizeEventPreset(preset) {
  if (!preset || typeof preset !== "object") return null;
  return {
    id: String(preset.id || ""),
    name: String(preset.name || preset.title || uiText("event.untitledPreset", "Untitled preset")).trim() || uiText("event.untitledPreset", "Untitled preset"),
    title: String(preset.title || ""),
    allDay: Boolean(preset.allDay),
    startTime: String(preset.startTime || DEFAULT_EVENT_START_TIME).slice(0, 5),
    endTime: String(preset.endTime || DEFAULT_EVENT_END_TIME).slice(0, 5),
    alarm: String(preset.alarm || "").slice(0, 5),
    memo: String(preset.memo || ""),
    shareFamily: Boolean(preset.shareFamily),
    owner: String(preset.owner || ""),
  };
}

function loadLocalEventPresets() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(EVENT_PRESET_STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.map(normalizeEventPreset).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function ensureEventPresets() {
  if (state.eventPresets.checked || state.eventPresets.loading) return;
  loadEventPresetsFromBrain();
}

function eventPresetSignature(preset) {
  return JSON.stringify([
    preset.name,
    preset.title,
    preset.allDay,
    preset.startTime,
    preset.endTime,
    preset.alarm,
    preset.memo,
    preset.shareFamily,
  ]);
}

function eventPresetPayload(preset) {
  return {
    name: preset.name,
    title: preset.title,
    allDay: preset.allDay,
    startTime: preset.startTime,
    endTime: preset.endTime,
    alarm: preset.alarm,
    memo: preset.memo,
    shareFamily: preset.shareFamily,
  };
}

async function requestEventPreset(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function migrateLocalEventPresets(remoteItems) {
  const localItems = loadLocalEventPresets();
  if (!localItems.length) return remoteItems;
  const merged = [...remoteItems];
  const signatures = new Set(merged.map(eventPresetSignature));
  for (const localItem of localItems) {
    const signature = eventPresetSignature(localItem);
    if (signatures.has(signature)) continue;
    const created = normalizeEventPreset(
      await requestEventPreset("/api/event-presets", {
        method: "POST",
        body: JSON.stringify(eventPresetPayload(localItem)),
      }),
    );
    if (created) {
      merged.push(created);
      signatures.add(eventPresetSignature(created));
    }
  }
  window.localStorage.removeItem(EVENT_PRESET_STORAGE_KEY);
  return merged;
}

async function loadEventPresetsFromBrain({ force = false } = {}) {
  if (state.eventPresets.loading) return;
  if (state.eventPresets.checked && !force) return;
  state.eventPresets.loading = true;
  try {
    const payload = await requestEventPreset("/api/event-presets");
    const remoteItems = Array.isArray(payload.items) ? payload.items.map(normalizeEventPreset).filter(Boolean) : [];
    const items = await migrateLocalEventPresets(remoteItems);
    state.eventPresets = {
      ...state.eventPresets,
      checked: true,
      loading: false,
      error: "",
      items,
    };
    if (state.eventPresets.editingId && !items.some((item) => item.id === state.eventPresets.editingId)) {
      state.eventPresets.editingId = "";
    }
  } catch (error) {
    state.eventPresets = {
      ...state.eventPresets,
      checked: true,
      loading: false,
      error: error.message || uiText("event.presetsUnavailable", "일정 프리셋을 불러올 수 없습니다"),
      items: [],
    };
  }
  if (["settings", "add-event"].includes(getRoute())) render();
}

function eventPresetFromForm(form) {
  const preset = normalizeEventPreset({
    id: form.dataset.eventPresetId || "",
    name: form.querySelector('[name="presetName"]')?.value || "",
    title: form.querySelector('[name="title"]')?.value || "",
    allDay: form.querySelector('[name="allDay"]')?.checked || false,
    startTime: form.querySelector('[name="startTime"]')?.value || DEFAULT_EVENT_START_TIME,
    endTime: form.querySelector('[name="endTime"]')?.value || DEFAULT_EVENT_END_TIME,
    alarm: form.querySelector('[name="alarm"]')?.value || "",
    memo: form.querySelector('[name="memo"]')?.value || "",
    shareFamily: form.querySelector('[name="shareFamily"]')?.checked || false,
  });
  return preset;
}

function addEventDraftFromForm(form) {
  if (!form) return state.addEventDraft || state.eventPresetDraft || defaultEventPreset();
  const base = state.addEventDraft || state.eventPresetDraft || defaultEventPreset();
  return {
    ...(state.addEventDraft || state.eventPresetDraft || defaultEventPreset()),
    id: base.id || createId("event-draft"),
    name: base.name || "",
    title: form.querySelector('[name="title"]')?.value || "",
    allDay: form.querySelector('[name="allDay"]')?.checked || false,
    startDate: form.querySelector('[name="startDate"]')?.value || state.selectedDate,
    startTime: form.querySelector('[name="startTime"]')?.value || DEFAULT_EVENT_START_TIME,
    endDate: form.querySelector('[name="endDate"]')?.value || form.querySelector('[name="startDate"]')?.value || state.selectedDate,
    endTime: form.querySelector('[name="endTime"]')?.value || DEFAULT_EVENT_END_TIME,
    repeat: form.querySelector('[name="repeat"]')?.value || "",
    alarm: form.querySelector('[name="alarm"]')?.value || "",
    memo: form.querySelector('[name="memo"]')?.value || "",
    shareFamily: form.querySelector('[name="shareFamily"]')?.checked || false,
  };
}

function collectAddEventDraft() {
  const form = document.querySelector("[data-create-event]");
  if (!form) return state.addEventDraft;
  state.addEventDraft = addEventDraftFromForm(form);
  return state.addEventDraft;
}

function addTaskDraftFromForm(form) {
  const previous = state.addTaskDraft || {};
  if (!form) return previous;
  return {
    ...previous,
    title: form.querySelector('[name="title"]')?.value || "",
    memo: form.querySelector('[name="memo"]')?.value || "",
    due: form.querySelector('[name="due"]')?.value || "",
    dueTime: form.querySelector('[name="dueTime"]')?.value || "",
    priority: form.querySelector('[name="priority"]')?.value || "",
    shareFamily: form.querySelector('[name="shareFamily"]')?.checked || false,
    selectedDate: state.selectedDate,
    dueEnabled: state.taskDueEnabled,
  };
}

function collectAddTaskDraft() {
  const form = document.querySelector("[data-create-task]");
  if (!form) return state.addTaskDraft;
  const previous = state.addTaskDraft || {};
  state.addTaskDraft = {
    ...previous,
    title: form.querySelector('[name="title"]')?.value || "",
    memo: form.querySelector('[name="memo"]')?.value || "",
    due: form.querySelector('[name="due"]')?.value || "",
    dueTime: form.querySelector('[name="dueTime"]')?.value || "",
    priority: form.querySelector('[name="priority"]')?.value || "",
    shareFamily: form.querySelector('[name="shareFamily"]')?.checked || false,
    selectedDate: state.selectedDate,
    dueEnabled: state.taskDueEnabled,
  };
  return state.addTaskDraft;
}

function persistComposerRecovery(kind, form) {
  if (kind === "event") collectAddEventDraft();
  if (kind === "task") collectAddTaskDraft();
  const snapshot = {
    savedAt: Date.now(),
    profile: portalProfile(),
    hash: window.location.hash,
    kind,
    selectedDate: state.selectedDate,
    currentCollection: state.currentCollection,
    taskDueEnabled: state.taskDueEnabled,
    addEventDraft: kind === "event" ? state.addEventDraft : null,
    addTaskDraft: kind === "task" ? state.addTaskDraft : null,
  };
  window.sessionStorage.setItem(COMPOSER_RECOVERY_STORAGE_KEY, JSON.stringify(snapshot));
}

function clearComposerRecovery() {
  window.sessionStorage.removeItem(COMPOSER_RECOVERY_STORAGE_KEY);
}

function restoreComposerRecovery() {
  let snapshot;
  try {
    snapshot = JSON.parse(window.sessionStorage.getItem(COMPOSER_RECOVERY_STORAGE_KEY) || "null");
  } catch (_error) {
    clearComposerRecovery();
    return;
  }
  clearComposerRecovery();
  if (
    !snapshot
    || snapshot.profile !== portalProfile()
    || Date.now() - Number(snapshot.savedAt || 0) > 60 * 60 * 1000
  ) return;
  state.selectedDate = snapshot.selectedDate || state.selectedDate;
  state.currentCollection = snapshot.currentCollection || state.currentCollection;
  state.taskDueEnabled = Boolean(snapshot.taskDueEnabled);
  if (snapshot.kind === "event" && snapshot.addEventDraft) {
    state.addKind = "event";
    state.addEventDraft = snapshot.addEventDraft;
  }
  if (snapshot.kind === "task" && snapshot.addTaskDraft) {
    state.addKind = "task";
    state.addTaskDraft = snapshot.addTaskDraft;
  }
  if (snapshot.hash) window.location.hash = snapshot.hash;
}

function isFetchConnectionError(error) {
  return error instanceof TypeError && /fetch|network|load/i.test(String(error.message || ""));
}

function recoverComposerConnection(error, kind, form) {
  if (!isFetchConnectionError(error)) return false;
  persistComposerRecovery(kind, form);
  if (window.confirm(uiText(
    "dialog.connectionLost",
    "Connection to Kaos or your sign-in session was lost. Reload and sign in again? Your draft will be kept.",
  ))) {
    window.location.reload();
  }
  return true;
}

async function upsertEventPreset(preset) {
  const saved = normalizeEventPreset(
    await requestEventPreset(
      preset.id ? `/api/event-presets/${encodeURIComponent(preset.id)}` : "/api/event-presets",
      {
        method: preset.id ? "PUT" : "POST",
        body: JSON.stringify(eventPresetPayload(preset)),
      },
    ),
  );
  if (!saved?.id) throw new Error("event_preset_invalid_response");
  state.eventPresets.checked = false;
  await loadEventPresetsFromBrain({ force: true });
  return saved;
}

async function deleteEventPresetFromBrain(id) {
  const payload = await requestEventPreset(`/api/event-presets/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!payload.ok) throw new Error(payload.error || "event_preset_delete_failed");
  state.eventPresets.checked = false;
  state.eventPresets.editingId = "";
  await loadEventPresetsFromBrain({ force: true });
}

function normalizeRecurringTask(item) {
  if (!item || typeof item !== "object") return null;
  return {
    id: String(item.id || ""),
    title: String(item.title || ""),
    memo: String(item.memo || ""),
    shareFamily: Boolean(item.shareFamily),
    owner: String(item.owner || ""),
    firstDueDate: String(item.firstDueDate || ""),
    dueTime: String(item.dueTime || DEFAULT_TASK_DUE_TIME).slice(0, 5),
    priority: String(item.priority || ""),
    frequency: String(item.frequency || "weekly"),
    creationPolicy: String(item.creationPolicy || "on_schedule"),
    enabled: item.enabled !== false,
    activeUid: String(item.activeUid || ""),
    activeDueDate: String(item.activeDueDate || ""),
    nextDueDate: String(item.nextDueDate || ""),
    error: String(item.error || ""),
  };
}

function defaultRecurringTask() {
  return {
    id: "",
    title: "",
    memo: "",
    shareFamily: portalProfile() === "family",
    owner: defaultPersonalOwner(),
    firstDueDate: ymd(new Date()),
    dueTime: DEFAULT_TASK_DUE_TIME,
    priority: "",
    frequency: "weekly",
    creationPolicy: "on_schedule",
    enabled: true,
    activeUid: "",
    activeDueDate: "",
    nextDueDate: "",
    error: "",
  };
}

async function loadRecurringTasks({ force = false } = {}) {
  if (state.recurringTasks.loading) return;
  if (state.recurringTasks.checked && !force) return;
  state.recurringTasks.loading = true;
  try {
    const response = await fetch("/api/recurring-tasks", { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.recurringTasks = {
      ...state.recurringTasks,
      checked: true,
      loading: false,
      error: "",
      items: Array.isArray(payload.items) ? payload.items.map(normalizeRecurringTask).filter(Boolean) : [],
    };
    if (state.recurringTasks.editingId && !state.recurringTasks.items.some((item) => item.id === state.recurringTasks.editingId)) {
      state.recurringTasks.editingId = "";
    }
  } catch (error) {
    state.recurringTasks = {
      ...state.recurringTasks,
      checked: true,
      loading: false,
      error: error.message || uiText("recurring.unavailable", "반복 할 일을 불러올 수 없습니다"),
    };
  }
  if (getRoute() === "settings") render();
}

function recurringTaskPayloadFromForm(form) {
  return {
    title: form.querySelector('[name="title"]')?.value || "",
    memo: form.querySelector('[name="memo"]')?.value || "",
    firstDueDate: form.querySelector('[name="firstDueDate"]')?.value || "",
    dueTime: form.querySelector('[name="dueTime"]')?.value || DEFAULT_TASK_DUE_TIME,
    priority: form.querySelector('[name="priority"]')?.value || "",
    frequency: form.querySelector('[name="frequency"]')?.value || "weekly",
    creationPolicy: form.querySelector('[name="creationPolicy"]')?.value || "on_schedule",
    shareFamily: form.querySelector('[name="shareFamily"]')?.checked || false,
    enabled: form.querySelector('[name="enabled"]')?.checked || false,
  };
}

async function saveRecurringTask(id, payload) {
  const response = await fetch(id ? `/api/recurring-tasks/${encodeURIComponent(id)}` : "/api/recurring-tasks", {
    method: id ? "PUT" : "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.id) throw new Error(result.error || `HTTP ${response.status}`);
  state.recurringTasks.checked = false;
  state.recurringTasks.editingId = "";
  await loadRecurringTasks({ force: true });
  window.setTimeout(() => {
    state.recurringTasks.checked = false;
    loadRecurringTasks({ force: true });
    loadRemoteCalendar();
  }, 1200);
}

async function deleteRecurringTask(id) {
  const response = await fetch(`/api/recurring-tasks/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.recurringTasks.checked = false;
  state.recurringTasks.editingId = "";
  await loadRecurringTasks({ force: true });
}

function normalizeHoliday(item) {
  if (!item || typeof item !== "object") return null;
  return {
    uid: String(item.uid || ""),
    title: String(item.title || ""),
    startDate: String(item.startDate || ""),
    endDate: String(item.endDate || item.startDate || ""),
    publicHoliday: Boolean(item.publicHoliday),
    categories: Array.isArray(item.categories) ? item.categories.map(String) : [],
  };
}

async function loadHolidays({ force = false } = {}) {
  if (state.holidays.loading) return;
  if (state.holidays.checked && !force) return;
  state.holidays.loading = true;
  try {
    const response = await fetch("/api/holidays", { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.holidays = {
      ...state.holidays,
      checked: true,
      loading: false,
      error: "",
      items: Array.isArray(payload.items) ? payload.items.map(normalizeHoliday).filter(Boolean) : [],
    };
  } catch (error) {
    state.holidays = {
      ...state.holidays,
      checked: true,
      loading: false,
      error: error.message || uiText("holidays.unavailable", "한국 기념일을 불러올 수 없습니다"),
    };
  }
  if (getRoute() === "settings") render();
}

async function syncHolidays() {
  if (state.holidays.syncing) return;
  state.holidays.syncing = true;
  render();
  try {
    const response = await fetch("/api/holidays/sync", {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.holidays.checked = false;
    await loadHolidays({ force: true });
    await loadRemoteCalendar();
  } finally {
    state.holidays.syncing = false;
    if (getRoute() === "settings") render();
  }
}

async function setHolidayClassification(uid, publicHoliday) {
  const response = await fetch(`/api/holidays/${encodeURIComponent(uid)}`, {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ publicHoliday: Boolean(publicHoliday) }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  const item = state.holidays.items.find((holiday) => holiday.uid === uid);
  if (item) item.publicHoliday = Boolean(publicHoliday);
  await loadRemoteCalendar();
}

async function loadCustomEvents({ force = false } = {}) {
  if (portalProfile() !== "main" || state.customEvents.loading) return;
  if (state.customEvents.checked && !force) return;
  state.customEvents.loading = true;
  try {
    const response = await fetch("/api/custom-events", { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.customEvents = {
      ...state.customEvents,
      checked: true,
      loading: false,
      error: "",
      marketDaysEnabled: payload.settings?.marketDaysEnabled !== false,
      claimDayEnabled: payload.settings?.claimDayEnabled !== false,
      sync: payload.sync || null,
    };
  } catch (error) {
    state.customEvents = {
      ...state.customEvents,
      checked: true,
      loading: false,
      error: error.message || uiText("customEvents.unavailable", "사용자 일정을 불러올 수 없습니다"),
    };
  }
  if (getRoute() === "settings") render();
}

async function saveCustomEvents(changes) {
  if (state.customEvents.saving) return;
  state.customEvents.saving = true;
  try {
    const response = await fetch("/api/custom-events", {
      method: "PUT",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        marketDaysEnabled: changes.marketDaysEnabled ?? state.customEvents.marketDaysEnabled,
        claimDayEnabled: changes.claimDayEnabled ?? state.customEvents.claimDayEnabled,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.customEvents.marketDaysEnabled = payload.settings?.marketDaysEnabled !== false;
    state.customEvents.claimDayEnabled = payload.settings?.claimDayEnabled !== false;
    state.customEvents.sync = payload.sync || state.customEvents.sync;
    state.customEvents.error = "";
    await loadRemoteCalendar();
  } finally {
    state.customEvents.saving = false;
    if (getRoute() === "settings") render();
  }
}

async function loadMailOrganizerSettings({ force = false } = {}) {
  if (portalProfile() !== "main" || state.mailOrganizer.loading) return;
  if (state.mailOrganizer.checked && !force) return;
  state.mailOrganizer.loading = true;
  try {
    const response = await fetch("/api/mail-organizer/settings", { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.mailOrganizer = {
      ...state.mailOrganizer,
      checked: true,
      loading: false,
      enabled: Boolean(payload.enabled),
      configured: Boolean(payload.configured),
      error: "",
      settings: {
        runsPerDay: Number(payload.settings?.runsPerDay) === 2 ? 2 : 1,
        firstTime: String(payload.settings?.firstTime || "09:00"),
        secondTime: String(payload.settings?.secondTime || "17:00"),
      },
    };
  } catch (error) {
    state.mailOrganizer = {
      ...state.mailOrganizer,
      checked: true,
      loading: false,
      error: error.message || uiText("mailOrganizer.unavailable", "메일 정리 설정을 불러올 수 없습니다"),
    };
  }
  if (getRoute() === "settings") render();
}

async function saveMailOrganizerSettings(form) {
  if (state.mailOrganizer.saving) return;
  const formData = new FormData(form);
  state.mailOrganizer.saving = true;
  if (getRoute() === "settings") render();
  try {
    const response = await fetch("/api/mail-organizer/settings", {
      method: "PUT",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        runsPerDay: Number(formData.get("runsPerDay")),
        firstTime: String(formData.get("firstTime") || ""),
        secondTime: String(formData.get("secondTime") || "17:00"),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.mailOrganizer.settings = {
      runsPerDay: Number(payload.settings?.runsPerDay) === 2 ? 2 : 1,
      firstTime: String(payload.settings?.firstTime || "09:00"),
      secondTime: String(payload.settings?.secondTime || "17:00"),
    };
    state.mailOrganizer.enabled = Boolean(payload.enabled);
    state.mailOrganizer.configured = Boolean(payload.configured);
    state.mailOrganizer.error = "";
  } finally {
    state.mailOrganizer.saving = false;
    if (getRoute() === "settings") render();
  }
}

async function sendMailOrganizerNow() {
  if (state.mailOrganizer.sending) return;
  state.mailOrganizer.sending = true;
  if (getRoute() === "settings") render();
  try {
    const response = await fetch("/api/mail-organizer/run", {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    window.alert(payload.sent === false
      ? "No unread Naver mail. Nothing was sent."
      : `Naver Mail organizer sent (${Number(payload.unreadCount || 0)} unread).`);
  } finally {
    state.mailOrganizer.sending = false;
    if (getRoute() === "settings") render();
  }
}

function writableTaskCollectionId() {
  const data = activeCalendarData();
  const view = mockAdapter.getCurrentCollection();
  const collectionIds = view?.id !== "all" && view?.collectionIds.length
    ? view.collectionIds
    : data.collections.map((collection) => collection.id);
  const typedTaskCollection = data.collections.find((collection) => collectionIds.includes(collection.id) && collection.components?.includes("VTODO"));
  if (typedTaskCollection) return typedTaskCollection.id;
  const taskCollectionIds = new Set(data.tasks.map((task) => task.collection));
  const taskCollection = data.collections.find((collection) => collectionIds.includes(collection.id) && taskCollectionIds.has(collection.id));
  if (taskCollection) return taskCollection.id;
  const namedTaskCollection = data.collections.find((collection) => collectionIds.includes(collection.id) && /task|reminder/i.test(collection.name));
  if (namedTaskCollection) return namedTaskCollection.id;
  return collectionIds[0] || writableCollectionId();
}

function writableEventCollectionId() {
  const data = activeCalendarData();
  const view = mockAdapter.getCurrentCollection();
  const collectionIds = view?.id !== "all" && view?.collectionIds.length
    ? view.collectionIds
    : data.collections.map((collection) => collection.id);
  const typedEventCollection = data.collections.find((collection) => collectionIds.includes(collection.id) && collection.components?.includes("VEVENT"));
  if (typedEventCollection) return typedEventCollection.id;
  const eventCollectionIds = new Set(data.events.map((event) => event.collection));
  const eventCollection = data.collections.find((collection) => collectionIds.includes(collection.id) && eventCollectionIds.has(collection.id));
  if (eventCollection) return eventCollection.id;
  const namedEventCollection = data.collections.find((collection) => collectionIds.includes(collection.id) && /calendar|event/i.test(collection.name));
  if (namedEventCollection) return namedEventCollection.id;
  return collectionIds[0] || writableCollectionId();
}

function findTaskById(taskId) {
  return activeCalendarData().tasks.map(normalizeTask).find((task) => task.id === taskId);
}

function findEventById(eventId) {
  return activeCalendarData().events.map(normalizeEvent).find((event) => event.id === eventId);
}

function applyPendingTaskStatuses(tasks) {
  const pending = state.pendingTaskStatuses || {};
  return (tasks || []).map((task) => {
    const override = pending[task.uid];
    if (!override) return task;
    const nextTask = { ...task, status: override.status };
    if (override.status === "COMPLETED") nextTask.completed = override.completed || new Date().toISOString().slice(0, 19);
    else delete nextTask.completed;
    return nextTask;
  });
}

async function loadRemoteCalendar() {
  const requestId = ++remoteCalendarRequestId;
  try {
    const response = await fetch("/api/calendar/bootstrap", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (requestId !== remoteCalendarRequestId) return;
    state.remoteCalendar = {
      checked: true,
      configured: Boolean(payload.configured),
      live: Boolean(payload.live && payload.collections?.length),
      profile: payload.profile || "main",
      error: "",
      collections: payload.collections || [],
      events: payload.events || [],
      tasks: applyPendingTaskStatuses(payload.tasks),
    };
    if (state.remoteCalendar.live && !collectionViews().some((collection) => collection.id === state.currentCollection)) {
      state.currentCollection = "all";
    }
  } catch (error) {
    if (requestId !== remoteCalendarRequestId) return;
    state.remoteCalendar = {
      ...state.remoteCalendar,
      checked: true,
      live: false,
      profile: state.remoteCalendar.profile,
      error: error.message || uiText("calendar.adapterUnavailable", "캘린더 서버에 연결할 수 없습니다"),
    };
  }
  render();
}

function visibleMonthRange(monthValue = state.selectedDate.slice(0, 7)) {
  const cells = monthCells(monthValue);
  return { start: cells[0]?.value || state.selectedDate, end: cells[cells.length - 1]?.value || state.selectedDate };
}

async function loadRemoteWeatherForSelectedMonth({ force = false } = {}) {
  const month = state.selectedDate.slice(0, 7);
  const range = visibleMonthRange(month);
  const key = `${state.weatherLocation}:${range.start}:${range.end}`;
  if (!force && (state.remoteWeather.key === key || state.remoteWeather.loadingKey === key)) return;
  state.remoteWeather.loadingKey = key;
  try {
    const params = new URLSearchParams({
      city: state.weatherLocation,
      start: range.start,
      end: range.end,
    });
    const response = await fetch(`/api/weather/month?${params.toString()}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.remoteWeather = {
      checked: true,
      live: Boolean(payload.ok && Array.isArray(payload.items)),
      key,
      loadingKey: "",
      error: payload.error || "",
      items: normalizeWeatherItems(payload.items || []),
    };
  } catch (error) {
    state.remoteWeather = {
      ...state.remoteWeather,
      checked: true,
      live: false,
      key,
      loadingKey: "",
      error: error.message || uiText("weather.unavailable", "날씨 정보 없음"),
    };
  }
  if (getRoute() === "calendar" || getRoute() === "today" || (getRoute() === "add-event" && isDesktopLayout())) render();
}

async function openWeatherLocationPopup(dateValue) {
  const locations = WEATHER_LOCATION_OPTIONS;
  const key = `${state.weatherLocation}:${dateValue}`;
  state.weatherLocationPopup = {
    open: true,
    mode: "locations",
    key,
    date: dateValue,
    loading: true,
    error: "",
    items: [],
  };
  render();
  document.querySelector("[data-close-weather-locations]")?.focus();

  const items = await Promise.all(
    locations.map(async (location) => {
      try {
        const params = new URLSearchParams({
          city: location.id,
          start: dateValue,
          end: dateValue,
        });
        const response = await fetch(`/api/weather/month?${params.toString()}`, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        const weather = normalizeWeatherItems(payload.items || []).find((item) => item.date === dateValue) || null;
        return { ...location, weather, error: payload.error || "" };
      } catch (error) {
        return { ...location, weather: null, error: error.message || uiText("weather.unavailable", "날씨 정보 없음") };
      }
    }),
  );

  if (state.weatherLocationPopup.key !== key) return;
  state.weatherLocationPopup = {
    ...state.weatherLocationPopup,
    loading: false,
    items,
  };
  if (state.weatherLocationPopup.open && getRoute() === "calendar") render();
}

function currentPosition() {
  if (!navigator.geolocation) {
    return Promise.reject(new Error(uiText("weather.locationUnsupported", "Current location is not supported.")));
  }
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: false,
      timeout: 12000,
      maximumAge: 300000,
    });
  });
}

function currentLocationErrorMessage(error) {
  if (error?.code === 1) return uiText("weather.locationPermissionDenied", "Location permission was denied.");
  if (error?.code === 2) return uiText("weather.locationUnavailable", "Current location is unavailable.");
  if (error?.code === 3) return uiText("weather.locationTimeout", "Current location timed out.");
  return error?.message || uiText("weather.unavailable", "날씨 정보 없음");
}

async function openCurrentLocationWeather(dateValue) {
  if (isPastDate(dateValue)) return;
  const key = `current:${dateValue}:${Date.now()}`;
  state.weatherLocationPopup = {
    open: true,
    mode: "current",
    key,
    date: dateValue,
    loading: true,
    error: "",
    items: [],
  };
  render();
  document.querySelector("[data-close-weather-locations]")?.focus();

  try {
    const position = await currentPosition();
    const response = await fetch("/api/weather/current", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        date: dateValue,
        language: portalProfile() === "family" ? "ko" : "en",
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok || !payload.item) throw new Error(payload.error || `HTTP ${response.status}`);
    const weather = normalizeWeatherItems([payload.item])[0] || null;
    if (state.weatherLocationPopup.key !== key) return;
    state.weatherLocationPopup = {
      ...state.weatherLocationPopup,
      loading: false,
      items: [
        {
          id: "current",
          label: weather.cityName || uiText("weather.currentLocation", "Current location"),
          translationKey: "",
          weather,
        },
      ],
    };
  } catch (error) {
    if (state.weatherLocationPopup.key !== key) return;
    state.weatherLocationPopup = {
      ...state.weatherLocationPopup,
      loading: false,
      error: currentLocationErrorMessage(error),
      items: [],
    };
  }
  if (state.weatherLocationPopup.open && getRoute() === "calendar") render();
}

function closeWeatherLocationPopup() {
  state.weatherLocationPopup = {
    ...state.weatherLocationPopup,
    open: false,
  };
  render();
}

function normalizeWeatherItems(items) {
  if (!Array.isArray(items)) return [];
  return items
    .map((item) => ({
      city: String(item?.city || ""),
      cityName: String(item?.cityName || item?.city || ""),
      date: String(item?.date || ""),
      glyph: String(item?.glyph || ""),
      condition: String(item?.condition || ""),
      minTemp: item?.minTemp ?? "",
      maxTemp: item?.maxTemp ?? "",
      source: String(item?.source || ""),
      locationAttribution: String(item?.locationAttribution || ""),
      dayparts: Array.isArray(item?.dayparts)
        ? item.dayparts.map((part) => ({
            label: String(part?.label || ""),
            glyph: String(part?.glyph || ""),
            condition: String(part?.condition || ""),
            minTemp: part?.minTemp ?? "",
            maxTemp: part?.maxTemp ?? "",
          }))
        : [],
    }))
    .filter((item) => item.date);
}

async function loadCaregiverMonth() {
  if (portalProfile() !== "family") return;
  const month = state.selectedDate.slice(0, 7);
  if (state.caregiver.key === month || state.caregiver.loadingKey === month) return;
  state.caregiver.loadingKey = month;
  try {
    const response = await fetch(`/api/caregiver/month?${new URLSearchParams({ month }).toString()}`, {
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.caregiver = {
      key: month,
      loadingKey: "",
      error: "",
      data: payload,
    };
  } catch (error) {
    state.caregiver = {
      key: month,
      loadingKey: "",
      error: error.message || uiText("caregiver.unavailable", "돌봄 내역을 불러올 수 없습니다"),
      data: null,
    };
  }
  if (getRoute() === "caregiver" || getRoute() === "calendar") render();
}

async function loadSupplies(options = {}) {
  if (portalProfile() !== "main") return;
  if (state.supplies.loading) return;
  if (state.supplies.checked && !options.force) return;
  state.supplies.loading = true;
  try {
    const params = new URLSearchParams({ mode: state.supplies.mode });
    const [itemsResponse, presetsResponse] = await Promise.all([
      fetch(`/api/supplies?${params.toString()}`, { headers: { Accept: "application/json" } }),
      fetch("/api/supplies/presets", { headers: { Accept: "application/json" } }),
    ]);
    const itemsPayload = await itemsResponse.json().catch(() => ({}));
    const presetsPayload = await presetsResponse.json().catch(() => ({}));
    if (!itemsResponse.ok) throw new Error(itemsPayload.error || `HTTP ${itemsResponse.status}`);
    state.supplies = {
      ...state.supplies,
      checked: true,
      loading: false,
      error: "",
      items: Array.isArray(itemsPayload.items) ? itemsPayload.items : [],
      presets: presetsResponse.ok && Array.isArray(presetsPayload.items) ? presetsPayload.items : [],
    };
  } catch (error) {
    state.supplies = {
      ...state.supplies,
      checked: true,
      loading: false,
      error: error.message || uiText("supplies.unavailable", "비품을 불러올 수 없습니다"),
      items: [],
    };
  }
  if (getRoute() === "supplies" || isAgendaSuppliesEmbed()) render();
}

async function createSupply(title) {
  const response = await fetch("/api/supplies", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.supplies.mode = "active";
  state.supplies.checked = false;
  await loadSupplies({ force: true });
}

async function useSupplyPreset(name) {
  const response = await fetch("/api/supplies/presets/use", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.supplies.mode = "active";
  state.supplies.checked = false;
  await loadSupplies({ force: true });
}

async function setSupplyState(id, mode) {
  const response = await fetch(`/api/supplies/${encodeURIComponent(id)}/${mode}`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.supplies.checked = false;
  await loadSupplies({ force: true });
}

async function deleteSupply(id) {
  const response = await fetch(`/api/supplies/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.supplies.checked = false;
  await loadSupplies({ force: true });
}

async function loadDocuments(options = {}) {
  if (portalProfile() !== "main") return;
  if (state.documents.loading) return;
  if (state.documents.checked && !options.force) return;
  state.documents.loading = true;
  try {
    const response = await fetch("/api/documents", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.documents = {
      checked: true,
      loading: false,
      error: "",
      items: Array.isArray(payload.items) ? payload.items : [],
    };
  } catch (error) {
    state.documents = {
      checked: true,
      loading: false,
      error: error.message || uiText("documents.unavailable", "문서 대기열을 불러올 수 없습니다"),
      items: [],
    };
  }
  if (getRoute() === "documents") render();
}

async function uploadDocument(file, source = "upload") {
  const params = new URLSearchParams({ filename: file.name || "document.pdf", source });
  const response = await fetch(`/api/documents?${params.toString()}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/pdf",
    },
    body: file,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.documents.checked = false;
  await loadDocuments({ force: true });
}

async function submitDocumentToPaperless(id) {
  const response = await fetch(`/api/documents/${encodeURIComponent(id)}/paperless`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.documents.checked = false;
  await loadDocuments({ force: true });
}

async function deleteQueuedDocument(id) {
  const response = await fetch(`/api/documents/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.documents.checked = false;
  await loadDocuments({ force: true });
}

function formatDocumentBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function formatDocumentDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function applyLedgerPayload(payload) {
  state.ledger = {
    ...state.ledger,
    checked: true,
    loading: false,
    saving: false,
    error: "",
    entries: Array.isArray(payload.entries) ? payload.entries : [],
    balances: payload.balances || { account: 0, cash: 0, gift: 0 },
    categories: Array.isArray(payload.categories) ? payload.categories : [],
  };
}

async function ledgerRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function loadLedger({ force = false } = {}) {
  if (portalProfile() !== "family" || state.ledger.loading) return;
  if (state.ledger.checked && !force) return;
  state.ledger.loading = true;
  try {
    applyLedgerPayload(await ledgerRequest("/api/ledger", { cache: "no-store" }));
  } catch (error) {
    state.ledger = {
      ...state.ledger,
      checked: true,
      loading: false,
      error: error.message || uiText("ledger.unavailable", "회비 장부를 불러올 수 없습니다"),
    };
  }
  if (getRoute() === "ledger") render();
}

function ledgerPayloadFromContainer(container) {
  const value = (name) => container.querySelector(`[name="${name}"]`)?.value || "";
  return {
    date: value("date"),
    category: value("category"),
    amount: value("amount").replace(/,/g, ""),
    details: value("details"),
    baseRevision: Number(container.dataset.ledgerRevision || 0),
  };
}

async function saveLedgerEntry(container) {
  if (state.ledger.saving) return;
  const entryId = container.dataset.ledgerId || "";
  const payload = ledgerPayloadFromContainer(container);
  state.ledger.saving = true;
  try {
    const result = await ledgerRequest(
      entryId ? `/api/ledger/entries/${encodeURIComponent(entryId)}` : "/api/ledger/entries",
      { method: entryId ? "PUT" : "POST", body: JSON.stringify(payload) },
    );
    applyLedgerPayload(result);
    state.ledger.editingId = "";
    state.ledger.adding = false;
    render();
  } catch (error) {
    state.ledger.saving = false;
    if (error.message === "ledger_revision_conflict") await loadLedger({ force: true });
    throw error;
  }
}

async function removeLedgerEntry(entry) {
  const payload = await ledgerRequest(`/api/ledger/entries/${encodeURIComponent(entry.id)}`, {
    method: "DELETE",
    body: JSON.stringify({ baseRevision: entry.revision }),
  });
  applyLedgerPayload(payload);
  state.ledger.editingId = "";
  render();
}

async function createLedgerBackup() {
  return ledgerRequest("/api/ledger/backups", { method: "POST" });
}

function formatLedgerMoney(value) {
  return `${new Intl.NumberFormat("ko-KR").format(Number(value) || 0)}원`;
}

async function saveCaregiverSettings(formData) {
  const month = state.selectedDate.slice(0, 7);
  const numericValue = (name) => Number(String(formData.get(name) || "").replace(/[^\d]/g, "")) || 0;
  const response = await fetch("/api/caregiver/settings", {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      month,
      hourlyWage: numericValue("hourlyWage"),
      transportFee: numericValue("transportFee"),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  state.caregiver = {
    key: month,
    loadingKey: "",
    error: "",
    data: payload,
  };
}

function caregiverDayRecordMatches(payload, record) {
  if (!record || record.date !== payload.date) return false;
  const normalizeSessions = (sessions) => (sessions || []).map((session) => ({
    start: String(session.start || ""),
    end: String(session.end || ""),
  }));
  const normalizeExtras = (extras) => (extras || []).map((extra) => ({
    label: String(extra.label || "").trim(),
    amount: Number(extra.amount) || 0,
  }));
  return JSON.stringify(normalizeSessions(record.sessions)) === JSON.stringify(normalizeSessions(payload.sessions))
    && JSON.stringify(normalizeExtras(record.extraItems)) === JSON.stringify(normalizeExtras(payload.extras));
}

async function requestCaregiverDayWrite(payload) {
  const response = await fetch("/api/caregiver/day", {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  if (!result.ok) throw new TypeError("caregiver_response_incomplete");
  return result;
}

async function verifyCaregiverDayWrite(payload) {
  const month = payload.date.slice(0, 7);
  const response = await fetch(`/api/caregiver/month?${new URLSearchParams({ month }).toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.ok) return null;
  const record = (result.daily || []).find((item) => item.date === payload.date);
  return caregiverDayRecordMatches(payload, record) ? result : null;
}

async function saveCaregiverDay(payload) {
  let result;
  try {
    result = await requestCaregiverDayWrite(payload);
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    result = await verifyCaregiverDayWrite(payload).catch(() => null);
    if (!result) {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      try {
        result = await requestCaregiverDayWrite(payload);
      } catch (retryError) {
        if (!(retryError instanceof TypeError)) throw retryError;
        result = await verifyCaregiverDayWrite(payload).catch(() => null);
        if (!result) {
          throw new Error(uiText(
            "caregiver.saveResponseLost",
            "The server response could not be confirmed. Reopen this date to check whether it was saved.",
          ));
        }
      }
    }
  }
  state.caregiver = {
    key: payload.date.slice(0, 7),
    loadingKey: "",
    error: "",
    data: result,
  };
}

async function deleteCaregiverDay(date) {
  const response = await fetch("/api/caregiver/day", {
    method: "DELETE",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ date }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  state.caregiver = {
    key: date.slice(0, 7),
    loadingKey: "",
    error: "",
    data: result,
  };
}

function formatCaregiverWon(value) {
  return `₩${Math.max(0, Math.round(Number(value) || 0)).toLocaleString("ko-KR")}`;
}

function formatCaregiverHours(minutes) {
  const safeMinutes = Math.max(0, Math.round(Number(minutes) || 0));
  const hours = Math.floor(safeMinutes / 60);
  const remainder = safeMinutes % 60;
  if (!remainder) return `${hours}${uiText("caregiver.hoursSuffix", "h")}`;
  return `${hours}${uiText("caregiver.hoursSuffix", "h")} ${remainder}${uiText("caregiver.minutesSuffix", "m")}`;
}

function caregiverTimeMinutes(value) {
  const match = String(value || "").match(/^(\d{2}):(\d{2})$/);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

function caregiverMinutesTime(value) {
  const safe = Math.max(0, Math.min(23 * 60 + 55, Number(value) || 0));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function caregiverSessionRowHtml(session = {}, index = 0) {
  return `
    <div class="caregiverSessionRow" data-caregiver-session>
      <span class="caregiverSessionNumber" data-caregiver-session-number>${index + 1}</span>
      <label class="caregiverTimeField">
        <input name="sessionStart" type="time" step="300" value="${escapeHtml(session.start || "09:00")}" aria-label="${uiText("caregiver.startTime", "Start")}" required />
      </label>
      <span class="caregiverSessionSeparator" aria-hidden="true">~</span>
      <label class="caregiverTimeField">
        <input name="sessionEnd" type="time" step="300" value="${escapeHtml(session.end || "10:00")}" aria-label="${uiText("caregiver.endTime", "End")}" required />
      </label>
      <button class="caregiverRemoveButton" type="button" data-caregiver-remove-session aria-label="${uiText("caregiver.removeTime", "Remove time")}" title="${uiText("caregiver.removeTime", "Remove time")}">×</button>
    </div>
  `;
}

function caregiverExtraRowHtml(extra = {}) {
  return `
    <div class="caregiverExtraRow" data-caregiver-extra>
      <input name="extraLabel" type="text" value="${escapeHtml(extra.label || "")}" placeholder="${uiText("caregiver.extraLabel", "Description")}" aria-label="${uiText("caregiver.extraLabel", "Description")}" />
      <input name="extraAmount" type="text" inputmode="numeric" value="${escapeHtml(extra.amount || "")}" placeholder="${uiText("caregiver.extraAmount", "Amount")}" aria-label="${uiText("caregiver.extraAmount", "Amount")}" />
      <button class="caregiverRemoveButton" type="button" data-caregiver-remove-extra aria-label="${uiText("caregiver.removeExtra", "Remove fee")}" title="${uiText("caregiver.removeExtra", "Remove fee")}">×</button>
    </div>
  `;
}

function caregiverDayPayloadFromForm(form) {
  const sessions = Array.from(form.querySelectorAll("[data-caregiver-session]")).map((row) => {
    const start = row.querySelector('[name="sessionStart"]')?.value || "";
    const end = row.querySelector('[name="sessionEnd"]')?.value || "";
    const startMinutes = caregiverTimeMinutes(start);
    const endMinutes = caregiverTimeMinutes(end);
    if (startMinutes === null || endMinutes === null || endMinutes <= startMinutes) {
      throw new Error(uiText("caregiver.invalidSession", "End time must be later than start time."));
    }
    return { start, end };
  });
  const extras = Array.from(form.querySelectorAll("[data-caregiver-extra]"))
    .map((row) => ({
      label: String(row.querySelector('[name="extraLabel"]')?.value || "").trim(),
      amount: Number(String(row.querySelector('[name="extraAmount"]')?.value || "").replace(/[^\d]/g, "")) || 0,
    }))
    .filter((extra) => extra.label || extra.amount);
  return {
    date: String(new FormData(form).get("date") || state.selectedDate),
    sessions,
    extras,
  };
}

function updateCaregiverDayFormTotals(form) {
  let minutes = 0;
  form.querySelectorAll("[data-caregiver-session]").forEach((row) => {
    const start = caregiverTimeMinutes(row.querySelector('[name="sessionStart"]')?.value);
    const end = caregiverTimeMinutes(row.querySelector('[name="sessionEnd"]')?.value);
    if (start !== null && end !== null && end > start) minutes += end - start;
  });
  const extras = Array.from(form.querySelectorAll('[name="extraAmount"]')).reduce(
    (total, input) => total + (Number(String(input.value || "").replace(/[^\d]/g, "")) || 0),
    0,
  );
  const timeTotal = form.querySelector("[data-caregiver-time-total]");
  const extraTotal = form.querySelector("[data-caregiver-extra-total]");
  if (timeTotal) timeTotal.textContent = formatCaregiverHours(minutes);
  if (extraTotal) extraTotal.textContent = formatCaregiverWon(extras);
}

async function createRemoteTask(formData) {
  const due = taskDueFromForm(formData);
  const response = await fetch("/api/calendar/tasks", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      collectionId: writableCollectionIdFromForm(formData, "VTODO"),
      title: String(formData.get("title") || "").trim(),
      memo: String(formData.get("memo") || "").trim(),
      dueDate: due.date,
      dueTime: due.time,
      priority: taskPriorityFromForm(formData),
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  state.taskMode = "active";
  window.location.hash = "#/tasks";
  await loadRemoteCalendar();
}

async function createRemoteEvent(formData) {
  const response = await fetch("/api/calendar/events", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      collectionId: writableCollectionIdFromForm(formData, "VEVENT"),
      title: String(formData.get("title") || "").trim(),
      allDay: formData.get("allDay") === "on",
      startDate: String(formData.get("startDate") || state.selectedDate),
      startTime: String(formData.get("startTime") || DEFAULT_EVENT_START_TIME),
      endDate: String(formData.get("endDate") || formData.get("startDate") || state.selectedDate),
      endTime: String(formData.get("endTime") || DEFAULT_EVENT_END_TIME),
      repeat: String(formData.get("repeat") || ""),
      alarmTime: String(formData.get("alarm") || ""),
      memo: String(formData.get("memo") || "").trim(),
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  state.selectedDate = String(formData.get("startDate") || state.selectedDate);
  window.location.hash = "#/calendar";
  await loadRemoteCalendar();
}

function eventPayloadFromForm(formData) {
  return {
    uid: String(formData.get("uid") || ""),
    collectionId: String(formData.get("collectionId") || ""),
    title: String(formData.get("title") || "").trim(),
    allDay: formData.get("allDay") === "on",
    startDate: String(formData.get("startDate") || state.selectedDate),
    startTime: String(formData.get("startTime") || DEFAULT_EVENT_START_TIME),
    endDate: String(formData.get("endDate") || formData.get("startDate") || state.selectedDate),
    endTime: String(formData.get("endTime") || DEFAULT_EVENT_END_TIME),
    repeat: String(formData.get("repeat") || ""),
    preserveRepeat: formData.get("preserveRepeat") === "1",
    alarmTime: String(formData.get("alarm") || ""),
    preserveAlarm: formData.get("preserveAlarm") === "1",
    memo: String(formData.get("memo") || "").trim(),
  };
}

async function updateRemoteEvent(formData) {
  const response = await fetch("/api/calendar/events", {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(eventPayloadFromForm(formData)),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  state.selectedDate = String(formData.get("startDate") || state.selectedDate);
  window.location.hash = "#/calendar";
  await loadRemoteCalendar();
}

async function deleteRemoteCalendarItem(kind, uid, collectionId) {
  const response = await fetch(`/api/calendar/${kind}`, {
    method: "DELETE",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ uid, collectionId }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  await loadRemoteCalendar();
}

async function updateRemoteTask(formData, options = {}) {
  const navigate = options.navigate !== false;
  const due = taskDueFromForm(formData);
  const response = await fetch("/api/calendar/tasks", {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      uid: String(formData.get("uid") || ""),
      collectionId: String(formData.get("collectionId") || ""),
      title: String(formData.get("title") || "").trim(),
      memo: String(formData.get("memo") || "").trim(),
      dueDate: due.date,
      dueTime: due.time,
      priority: taskPriorityFromForm(formData),
      status: String(formData.get("status") || "").trim(),
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  if (navigate) window.location.hash = "#/tasks";
  await loadRemoteCalendar();
}

function parseDateTime(value) {
  const raw = String(value || "");
  return {
    date: raw.slice(0, 10),
    time: raw.includes("T") ? raw.slice(11, 16) : "",
  };
}

function addLocalMinutes(dateValue, timeValue, minutes) {
  const date = new Date(`${dateValue}T${timeValue || DEFAULT_EVENT_START_TIME}:00`);
  date.setMinutes(date.getMinutes() + minutes);
  return {
    date: ymd(date),
    time: `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`,
  };
}

function formatDateTimeLabel(value) {
  const parsed = parseDateTime(value);
  if (!parsed.date) return "";
  if (parsed.date === state.selectedDate && parsed.time) return uiText("task.modifiedTime", "modified {time}", { time: parsed.time });
  return parsed.time
    ? uiText("task.modifiedDateTime", "modified {date} {time}", { date: parsed.date, time: parsed.time })
    : uiText("task.modifiedDate", "modified {date}", { date: parsed.date });
}

function normalizeEvent(event) {
  const categories = Array.isArray(event.categories) ? event.categories.map((value) => String(value).toUpperCase()) : [];
  if (event.date) {
    return {
      id: event.id || event.uid,
      collection: event.collection,
      date: event.date,
      time: event.time || "",
      startDate: event.date,
      startTime: event.time || "",
      endDate: event.endDate || event.date,
      endTime: event.endTime || "",
      allDay: Boolean(event.allDay || !event.time),
      title: event.title || event.summary || uiText("event.untitled", "Untitled event"),
      description: event.description || "",
      detail: event.location || event.description || "",
      repeat: event.repeat || "",
      preserveRepeat: Boolean(event.preserveRepeat),
      alarmTime: event.alarmTime || event.alarm || "",
      preserveAlarm: Boolean(event.preserveAlarm),
      editable: event.editable !== false,
      editReason: event.editReason || "",
      categories,
      systemManaged: Boolean(event.systemManaged || categories.includes("KAOS-SYSTEM")),
      publicHoliday: Boolean(event.publicHoliday || categories.includes("KAOS-PUBLIC-HOLIDAY")),
      observance: Boolean(event.observance || categories.includes("KAOS-OBSERVANCE")),
    };
  }
  const start = parseDateTime(event.startDate || event.dtstart);
  const end = parseDateTime(event.endDate || event.dtend);
  const allDay = Boolean(event.allDay || (event.dtstart && !String(event.dtstart).includes("T")));
  return {
    id: event.uid,
    collection: event.collection,
    date: event.startDate || start.date,
    time: allDay ? "" : event.startTime || start.time,
    startDate: event.startDate || start.date,
    startTime: allDay ? "" : event.startTime || start.time,
    endDate: event.endDate || end.date || event.startDate || start.date,
    endTime: allDay ? "" : event.endTime || end.time,
    allDay,
    title: event.summary || uiText("event.untitled", "Untitled event"),
    description: event.description || "",
    detail: event.location || event.description || "",
    repeat: event.repeat || "",
    preserveRepeat: Boolean(event.preserveRepeat),
    alarmTime: event.alarmTime || event.alarm || "",
    preserveAlarm: Boolean(event.preserveAlarm),
    editable: event.editable !== false,
    editReason: event.editReason || "",
    categories,
    systemManaged: Boolean(event.systemManaged || categories.includes("KAOS-SYSTEM")),
    publicHoliday: Boolean(event.publicHoliday || categories.includes("KAOS-PUBLIC-HOLIDAY")),
    observance: Boolean(event.observance || categories.includes("KAOS-OBSERVANCE")),
  };
}

function isGoogleHolidayEvent(event) {
  return Boolean(event?.categories?.includes("KAOS-GOOGLE-HOLIDAY"));
}

function isGeneratedCalendarEvent(event) {
  return Boolean(event?.categories?.includes("KAOS-GENERATED-CALENDAR"));
}

function isMarketDayEvent(event) {
  return isGeneratedCalendarEvent(event) && event.categories.includes("KAOS-MARKET-DAY");
}

function isPublicHolidayEvent(event) {
  return isGoogleHolidayEvent(event) && Boolean(event.publicHoliday);
}

function isObservanceEvent(event) {
  return isGoogleHolidayEvent(event) && !event.publicHoliday;
}

function parseLegacyDescription(description) {
  const lines = String(description || "").split(/\r?\n/);
  const notes = [];
  const subtasks = [];

  lines.forEach((line, index) => {
    const marker = legacySubtaskMarker(line);
    if (marker) {
      subtasks.push({ lineIndex: index, done: marker.done, text: marker.text });
    } else {
      notes.push(line);
    }
  });

  return {
    notes: notes.join("\n").trim(),
    subtasks,
  };
}

function legacySubtaskMarker(line) {
  const raw = String(line || "");
  const active = raw.match(/^\s*(?:--|[-\u2013\u2014]{2})\s*(.*)$/u);
  if (active) return { done: false, text: active[1].trim() };
  const done = raw.match(/^\s*(?:-x|[-\u2013\u2014]\s*x)\s+(.*)$/iu);
  if (done) return { done: true, text: done[1].trim() };
  return null;
}

function setLegacySubtaskLine(line, done) {
  const marker = legacySubtaskMarker(line);
  if (!marker) return line;
  return `${done ? "-x" : "--"} ${marker.text}`;
}

function taskDescription(task) {
  return state.taskDescriptions[task.uid] || task.description || "";
}

function taskDueFromForm(formData) {
  const rawDue = String(formData.get("due") || "");
  const rawTime = String(formData.get("dueTime") || "").trim();
  const date = rawDue || (rawTime ? ymd(new Date()) : "");
  const time = date ? rawTime || DEFAULT_TASK_DUE_TIME : "";
  return { date, time };
}

function taskDueHasPassed(due) {
  if (!due.date || !due.time) return false;
  return new Date(`${due.date}T${due.time}:00`).getTime() < Date.now();
}

function taskPriorityFromForm(formData) {
  const priority = String(formData.get("priority") || "");
  return Object.values(taskPriorityOptions).some((option) => option.value === priority) ? priority : "";
}

function taskPriorityRank(priority) {
  const value = Number(priority);
  if (!Number.isInteger(value) || value < 1 || value > 9) return taskPriorityOptions.none.rank;
  return value;
}

function taskPriorityLabel(priority) {
  const rank = taskPriorityRank(priority);
  if (rank <= 3) return "High";
  if (rank <= 6) return "Medium";
  if (rank <= 9) return "Low";
  return "";
}

function taskPriorityMark(priority) {
  const rank = taskPriorityRank(priority);
  if (rank <= 3) return "!!!";
  if (rank <= 6) return "!!";
  if (rank <= 9) return "!";
  return "";
}

function taskBucket(task, done) {
  if (done) return "done";
  if (task.due) return "dated";
  return "inbox";
}

function taskBadge(task, subtasks, done) {
  if (done) return "";
  const badgeParts = [];
  const priority = taskPriorityMark(task.priority);
  if (priority) badgeParts.push(priority);
  if (subtasks.length) {
    const completed = subtasks.filter((subtask) => subtask.done).length;
    badgeParts.push(`${completed}/${subtasks.length}`);
  }
  return badgeParts.join(" · ");
}

function taskMeta(task, parsed, done) {
  if (done && task.completed) return uiText("task.completedTime", "Done {time}", { time: parseDateTime(task.completed).time });
  const parts = [];
  if (task.due) {
    const dueDate = task.due === state.selectedDate
      ? uiText("task.dueToday", "due today")
      : uiText("task.dueDate", "due {date}", { date: task.due });
    parts.push(task.dueTime ? `${dueDate} ${task.dueTime}` : dueDate);
  }
  else if (task.lastModified || task.created) parts.push(formatDateTimeLabel(task.lastModified || task.created));
  if (parsed.subtasks.length) parts.push(uiText("task.subtasksCount", "{count} subtasks", { count: parsed.subtasks.length }));
  return parts.join(" · ");
}

function normalizeTask(task) {
  const description = taskDescription(task);
  const parsed = parseLegacyDescription(description);
  const done = task.status === "COMPLETED";
  return {
    id: task.uid,
    collection: task.collection,
    title: task.summary,
    description,
    due: task.due || "",
    dueTime: task.dueTime || "",
    priority: task.priority || "",
    priorityRank: taskPriorityRank(task.priority),
    priorityLabel: taskPriorityLabel(task.priority),
    priorityMark: taskPriorityMark(task.priority),
    created: task.created || "",
    lastModified: task.lastModified || task.created || "",
    notes: parsed.notes,
    subtasks: parsed.subtasks,
    meta: taskMeta(task, parsed, done),
    mode: taskBucket(task, done),
    done,
    badge: taskBadge(task, parsed.subtasks, done),
  };
}

function isRecurringTask(task) {
  return String(task?.id || task?.uid || "").toUpperCase().startsWith("KAOSGDD-REPEAT-");
}

function sortByDateTime(a, b) {
  return `${a.date}T${a.time || "00:00"}`.localeCompare(`${b.date}T${b.time || "00:00"}`);
}

function sortTasks(a, b) {
  if (a.done !== b.done) return a.done ? 1 : -1;
  if (state.taskSort === "created") return compareTasksByCreated(a, b);
  return compareTasksByDue(a, b);
}

function compareTasksByCreated(a, b) {
  const created = (a.created || a.lastModified || "").localeCompare(b.created || b.lastModified || "");
  if (created) return created;
  return a.title.localeCompare(b.title);
}

function compareTasksByDue(a, b) {
  if (a.due && b.due && a.due !== b.due) return a.due.localeCompare(b.due);
  if (a.due && b.due && a.dueTime !== b.dueTime) return (a.dueTime || "99:99").localeCompare(b.dueTime || "99:99");
  if (a.due && b.due) return compareTasksByCreated(a, b);
  if (a.due && !b.due) return -1;
  if (!a.due && b.due) return 1;
  if (!a.due && !b.due) return compareTasksByCreated(a, b);
  return a.title.localeCompare(b.title);
}

function taskMatchesMode(task, mode) {
  if (mode === "active") return !task.done;
  if (mode === "all") return true;
  return task.mode === mode;
}

function groupTasksByDue(tasks) {
  return tasks.reduce((groups, task) => {
    const due = task.due || uiText("task.noDueDate", "No due date");
    if (!groups[due]) groups[due] = [];
    groups[due].push(task);
    return groups;
  }, {});
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function getRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const route = raw.split("?", 1)[0];
  if (!routes[route]) return profileConfig().defaultRoute;
  if (portalProfile() === "family" && route === "services") return profileConfig().defaultRoute;
  if (portalProfile() === "family" && (route === "supplies" || route === "documents")) return profileConfig().defaultRoute;
  if (portalProfile() === "main" && (route === "rouny" || route === "caregiver" || route === "ledger")) return profileConfig().defaultRoute;
  return route;
}

function isAgendaSuppliesEmbed() {
  return false;
}

function portalProfile() {
  return window.location.hostname === "family.kaosgdd.net" ? "family" : "main";
}

function familyFontPreference() {
  const stored = window.localStorage.getItem(FAMILY_FONT_STORAGE_KEY) || "";
  return FAMILY_FONT_OPTIONS.has(stored) ? stored : "nanum";
}

function applyFamilyFontPreference(value = familyFontPreference()) {
  const app = document.querySelector(".app");
  if (!app) return;
  if (portalProfile() !== "family") {
    delete app.dataset.familyFont;
    return;
  }
  app.dataset.familyFont = FAMILY_FONT_OPTIONS.has(value) ? value : "nanum";
}

function setFamilyFontPreference(value) {
  const normalized = FAMILY_FONT_OPTIONS.has(value) ? value : "nanum";
  window.localStorage.setItem(FAMILY_FONT_STORAGE_KEY, normalized);
  applyFamilyFontPreference(normalized);
}

function mainFontPreference() {
  const stored = window.localStorage.getItem(MAIN_FONT_STORAGE_KEY) || "";
  return MAIN_FONT_OPTIONS.has(stored) ? stored : "pretendard";
}

function applyMainFontPreference(value = mainFontPreference()) {
  const app = document.querySelector(".app");
  if (!app) return;
  if (portalProfile() !== "main") {
    delete app.dataset.mainFont;
    return;
  }
  app.dataset.mainFont = MAIN_FONT_OPTIONS.has(value) ? value : "pretendard";
}

function setMainFontPreference(value) {
  const normalized = MAIN_FONT_OPTIONS.has(value) ? value : "pretendard";
  window.localStorage.setItem(MAIN_FONT_STORAGE_KEY, normalized);
  applyMainFontPreference(normalized);
}

function weatherLocationPreference() {
  const stored = window.localStorage.getItem(WEATHER_LOCATION_STORAGE_KEY) || "";
  return WEATHER_LOCATION_IDS.has(stored) ? stored : "pohang";
}

function weatherLocationLabel(locationId = state.weatherLocation) {
  const location = WEATHER_LOCATION_OPTIONS.find((item) => item.id === locationId) || WEATHER_LOCATION_OPTIONS[0];
  return uiText(location.translationKey, location.label);
}

function applyWeatherLocationPreference(value) {
  const normalized = WEATHER_LOCATION_IDS.has(value) ? value : "pohang";
  window.localStorage.setItem(WEATHER_LOCATION_STORAGE_KEY, normalized);
  const changed = state.weatherLocation !== normalized;
  state.weatherLocation = normalized;
  if (changed) {
    state.remoteWeather = {
      checked: false,
      live: false,
      key: "",
      loadingKey: "",
      error: "",
      items: [],
    };
  }
  return changed;
}

async function loadWeatherSettings({ force = false } = {}) {
  if (state.weatherSettings.loading) return;
  if (state.weatherSettings.checked && !force) return;
  state.weatherSettings.loading = true;
  try {
    const response = await fetch("/api/weather/settings", { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    const location = String(payload.settings?.location || "");
    const changed = applyWeatherLocationPreference(location);
    state.weatherSettings = {
      checked: true,
      loading: false,
      saving: false,
      error: "",
      version: Number(payload.version || 0),
    };
    if (changed) loadRemoteWeatherForSelectedMonth({ force: true });
  } catch (error) {
    state.weatherSettings = {
      ...state.weatherSettings,
      checked: true,
      loading: false,
      error: error.message || uiText("settings.weatherUnavailable", "날씨 설정을 불러올 수 없습니다"),
    };
  }
  if (getRoute() === "settings") render();
}

async function saveWeatherLocationPreference(value) {
  if (state.weatherSettings.saving) return;
  const previous = state.weatherLocation;
  applyWeatherLocationPreference(value);
  state.weatherSettings.saving = true;
  state.weatherSettings.error = "";
  render();
  try {
    const response = await fetch("/api/weather/settings", {
      method: "PUT",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ location: state.weatherLocation }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    applyWeatherLocationPreference(String(payload.settings?.location || state.weatherLocation));
    state.weatherSettings.version = Number(payload.version || state.weatherSettings.version);
    state.weatherSettings.checked = true;
    loadRemoteWeatherForSelectedMonth({ force: true });
  } catch (error) {
    applyWeatherLocationPreference(previous);
    state.weatherSettings.error = error.message || uiText("settings.weatherSaveFailed", "날씨 설정을 저장할 수 없습니다");
    window.alert(state.weatherSettings.error);
  } finally {
    state.weatherSettings.saving = false;
    if (getRoute() === "settings") render();
  }
}

async function loadGovernorSettingsStatus({ force = false } = {}) {
  if (state.governorSettings.loading) return;
  if (state.governorSettings.checked && !force) return;
  state.governorSettings.loading = true;
  try {
    const response = await fetch("/api/settings/status", { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.governorSettings = {
      checked: true,
      loading: false,
      error: "",
      data: payload,
    };
  } catch (error) {
    state.governorSettings = {
      ...state.governorSettings,
      checked: true,
      loading: false,
      error: error.message || uiText("settings.statusUnavailable", "Governor settings status is unavailable"),
    };
  }
  if (getRoute() === "settings") render();
}

function interpolateText(template, params = {}) {
  return String(template).replace(/\{(\w+)\}/g, (match, key) => (params[key] === undefined ? match : String(params[key])));
}

function uiText(key, english, params = {}) {
  const translated = portalProfile() === "family" ? window.KAOS_TRANSLATIONS?.ko?.[key] : null;
  return interpolateText(translated ?? english, params);
}

function calendarWeekdays() {
  return portalProfile() === "family"
    ? [
        uiText("weekday.sun", "S"),
        uiText("weekday.mon", "M"),
        uiText("weekday.tue", "T"),
        uiText("weekday.wed", "W"),
        uiText("weekday.thu", "T"),
        uiText("weekday.fri", "F"),
        uiText("weekday.sat", "S"),
      ]
    : ["S", "M", "T", "W", "T", "F", "S"];
}

function profileConfig() {
  return profileConfigs[portalProfile()];
}

function activeNavRoute(route) {
  if (route === "add" || route === "add-event" || route === "edit-event" || route === "caregiver") return "calendar";
  if (route === "add-task" || route === "edit-task") return "tasks";
  if (route === "supplies" || route === "documents" || route === "service") return "services";
  return route;
}

function renderTopNav(route) {
  const nav = document.getElementById("topNav");
  if (!nav) return;
  const activeRoute = activeNavRoute(route);
  if (isDesktopLayout() && portalProfile() === "main") {
    const utilsActive = activeRoute === "services";
    nav.innerHTML = profileConfig()
      .nav.map((item) => {
        if (item.route !== "services") {
          return `
            <a href="#/${item.route}" data-nav="${item.route}" class="${item.route === activeRoute ? "isActive" : ""}" aria-label="${escapeHtml(item.label)}">
              ${escapeHtml(item.label)}
            </a>
          `;
        }
        return `
          <div class="desktopNavGroup ${utilsActive ? "isActive" : ""}">
            <a
              href="#/services"
              class="desktopNavToggle desktopNavUtilsHeader ${utilsActive ? "isActive" : ""}"
              aria-controls="desktopUtilsMenu"
            >
              <span>${escapeHtml(item.label)}</span>
            </a>
            <div class="desktopNavSubmenu" id="desktopUtilsMenu">
              ${mockAdapter
                .getServices()
                .map((service) => {
                  const isCurrent = (route === "supplies" && service.id === "supplies")
                    || (route === "documents" && service.id === "documents")
                    || (route === "service" && hashParam("service") === service.id);
                  return service.href
                    ? `<a href="${escapeHtml(serviceHref(service))}" class="${isCurrent ? "isActive" : ""}">${escapeHtml(service.name)}</a>`
                    : `<span class="desktopNavUtility isDisabled" aria-disabled="true">${escapeHtml(service.name)}</span>`;
                })
                .join("")}
            </div>
          </div>
        `;
      })
      .join("");
    return;
  }
  nav.innerHTML = profileConfig()
    .nav.map(
      (item) => `
        <a href="#/${item.route}" data-nav="${item.route}" class="${item.route === activeRoute ? "isActive" : ""}" aria-label="${escapeHtml(item.label)}">
          ${escapeHtml(item.label)}
        </a>
      `,
    )
    .join("");
}

function hashParam(name) {
  const query = window.location.hash.split("?", 2)[1] || "";
  return new URLSearchParams(query).get(name) || "";
}

function ymd(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function compactDateLabel(dateValue) {
  const date = new Date(`${dateValue}T00:00:00`);
  const weekdays = portalProfile() === "family"
    ? [
        uiText("weekday.sun", "Sun"),
        uiText("weekday.mon", "Mon"),
        uiText("weekday.tue", "Tue"),
        uiText("weekday.wed", "Wed"),
        uiText("weekday.thu", "Thu"),
        uiText("weekday.fri", "Fri"),
        uiText("weekday.sat", "Sat"),
      ]
    : ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return `${dateValue.replace(/-/g, ".")} ${weekdays[date.getDay()]}`;
}

function monthTitle(monthValue) {
  const [year, month] = monthValue.split("-").map(Number);
  if (portalProfile() === "family") return uiText("date.monthTitle", "{month} {year}", { year, month });
  const date = new Date(year, month - 1, 1);
  return `${date.toLocaleString("en", { month: "long" })} ${year}`;
}

function shiftSelectedMonth(offset) {
  const [year, month, day] = state.selectedDate.split("-").map(Number);
  const target = new Date(year, month - 1 + offset, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(day, lastDay));
  state.selectedDate = ymd(target);
}

function selectToday() {
  state.selectedDate = ymd(new Date());
}

function monthCells(monthValue) {
  const [year, month] = monthValue.split("-").map(Number);
  const start = new Date(year, month - 1, 1);
  const gridStart = new Date(start);
  gridStart.setDate(start.getDate() - start.getDay());
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + index);
    return {
      label: String(date.getDate()),
      value: ymd(date),
      muted: date.getMonth() !== month - 1,
    };
  });
}

function addPageCells(monthValue) {
  const cells = monthCells(monthValue);
  if (state.addMonthExpanded) return cells;
  const selectedIndex = cells.findIndex((cell) => cell.value === state.selectedDate);
  const start = Math.max(0, Math.floor((selectedIndex < 0 ? 0 : selectedIndex) / 7) * 7);
  return cells.slice(start, start + 7);
}

function routeTitle(route) {
  const routeLabels = portalProfile() === "family" ? familyRoutes : routes;
  const selectedService = route === "service" ? serviceById(hashParam("service")) : null;
  const title = selectedService?.name || (route === "add-event" || route === "add-task" ? routeLabels.add : routeLabels[route]);
  document.getElementById("routeTitle").textContent = title;
  document.querySelector(".kicker").textContent = profileConfig().label;
  const app = document.querySelector(".app");
  app.dataset.route = route;
  app.dataset.profile = portalProfile();
  applyFamilyFontPreference();
  applyMainFontPreference();
  renderTopNav(route);
}

function renderAddDatePicker({ title, allowNoDate = false }) {
  const month = state.selectedDate.slice(0, 7);
  const cells = addPageCells(month);
  const dueEnabled = state.taskDueEnabled;
  const dueLabel = dueEnabled
    ? uiText("task.dueDate", "Due {date}", { date: state.selectedDate })
    : uiText("task.noDueDate", "No due date");
  return `
    <section class="panel">
      <div class="panelHeader">
        <div>
          <p class="label">${escapeHtml(title)}</p>
          <h2>${escapeHtml(monthTitle(month))}</h2>
        </div>
        <button class="openButton" type="button" data-toggle-add-month>${state.addMonthExpanded ? uiText("date.collapse", "Collapse") : uiText("date.monthView", "Month")}</button>
      </div>
      <div class="calendarGrid addCalendarGrid ${state.addMonthExpanded ? "isExpanded" : "isCollapsed"}" aria-label="${escapeHtml(title)}">
        ${calendarWeekdays().map((day) => `<span class="weekday">${day}</span>`).join("")}
        ${cells
          .map((cell) => {
            const classes = [
              "day",
              cell.muted ? "isMuted" : "",
              cell.value === ymd(new Date()) ? "isToday" : "",
              cell.value === state.selectedDate ? "isSelected" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return `<button class="${classes}" type="button" data-date="${cell.value}">${cell.label}</button>`;
          })
          .join("")}
      </div>
      ${
        allowNoDate
          ? `
            <div class="panelBody slimBody duePickerRow">
              <span class="formNote">${escapeHtml(dueLabel)}</span>
              ${
                dueEnabled
                  ? `<button class="iconTextButton" type="button" data-clear-task-due aria-label="${uiText("task.clearDueDate", "Clear due date")}">x</button>`
                  : `<button class="plainButton" type="button" data-use-selected-due>${uiText("task.useSelectedDate", "Use selected date")}</button>`
              }
            </div>
          `
          : ""
      }
    </section>
  `;
}

function renderCollectionRail() {
  if (portalProfile() === "family") return "";
  return `
    <section class="collectionRail" aria-label="${uiText("collection.aria", "Radicale collections")}">
      ${mockAdapter
        .getCollections()
        .map(
          (collection) => `
            <button class="${state.currentCollection === collection.id ? "isActive" : ""}" type="button" data-collection="${escapeHtml(collection.id)}">
              <span>${escapeHtml(collection.name)}</span>
            </button>
          `,
        )
        .join("")}
    </section>
  `;
}

function renderTimeline(events, emptyText = uiText("common.noItems", "No items"), options = {}) {
  if (!events.length) {
    return `<div class="panelBody"><p class="taskMeta">${escapeHtml(emptyText)}</p></div>`;
  }
  return `
    <div class="panelBody">
      <ol class="timeline">
        ${events
          .map((event) => {
            const timeLabel = event.allDay ? uiText("event.allDayPill", "All Day") : event.time;
            const holidayClass = isPublicHolidayEvent(event) ? "isPublicHoliday" : isObservanceEvent(event) ? "isObservance" : "";
            const generated = isGeneratedCalendarEvent(event);
            const content = `
              <span class="timelineTitleRow">
                <strong>${escapeHtml(event.title)}</strong>
                ${renderCollectionPill(event)}
                ${generated ? renderAutomationPill("brain") : ""}
              </span>
              ${!generated && event.detail ? `<span>${escapeHtml(event.detail)}</span>` : ""}
            `;
            return `
              <li class="${holidayClass}">
                <time class="${event.allDay ? "timelineAllDayPill" : ""}">${escapeHtml(timeLabel)}</time>
                ${event.systemManaged || options.readOnly
                  ? `<span class="timelineLink isReadOnly">${content}</span>`
                  : `<a class="timelineLink" href="#/edit-event?uid=${encodeURIComponent(event.id)}">${content}</a>`}
              </li>
            `;
          })
          .join("")}
      </ol>
    </div>
  `;
}

function renderTaskRows(tasks) {
  if (!tasks.length) {
    return `<p class="taskMeta">${uiText("task.noTasks", "No tasks")}</p>`;
  }
  return `
    <ul class="taskList">
      ${tasks
        .map((task) => {
          const done = task.done;
          const classes = ["taskRow", task.priorityLabel ? `priority${task.priorityLabel}` : "", done ? "isDone" : ""].filter(Boolean).join(" ");
          return `
            <li class="${classes}" data-task-id="${escapeHtml(task.id)}">
              <div class="taskRowMain">
                <button class="checkButton ${done ? "isDone" : ""}" type="button" aria-label="${uiText("task.toggle", "Toggle")} ${escapeHtml(task.title)}"></button>
                <a class="taskEditLink" href="#/edit-task?uid=${encodeURIComponent(task.id)}">
                  <span class="taskTitleRow">
                    <p class="taskTitle">${escapeHtml(task.title)}</p>
                    ${renderCollectionPill(task)}
                    ${isRecurringTask(task) ? renderAutomationPill("repeating") : ""}
                  </span>
                  <span class="taskMeta">${escapeHtml(task.meta)}</span>
                </a>
                <small class="taskBadge">${escapeHtml(task.badge)}</small>
              </div>
              ${
                task.subtasks.length
                  ? `
                    <ul class="legacySubtasks" aria-label="${uiText("task.subtasksFor", "Subtasks for")} ${escapeHtml(task.title)}">
                      ${task.subtasks
                        .map(
                          (subtask) => `
                            <li class="${subtask.done ? "isDone" : ""}">
                              <button class="subtaskToggle ${subtask.done ? "isDone" : ""}" type="button" data-subtask-line="${subtask.lineIndex}" aria-label="${uiText("task.toggle", "Toggle")} ${escapeHtml(subtask.text)}"></button>
                              <span>${escapeHtml(subtask.text)}</span>
                            </li>
                          `,
                        )
                        .join("")}
                    </ul>
                  `
                  : ""
              }
            </li>
          `;
        })
        .join("")}
    </ul>
  `;
}

function renderTaskGroups(tasks) {
  if (!tasks.length) return `<p class="taskMeta">${uiText("task.noDatedTasks", "No dated tasks")}</p>`;
  const groups = groupTasksByDue(tasks);
  return Object.keys(groups)
    .sort()
    .map(
      (due) => `
        <section class="taskGroup">
          <h3 class="taskGroupTitle">${escapeHtml(due)}</h3>
          ${renderTaskRows(groups[due])}
        </section>
      `,
    )
    .join("");
}

function renderCaregiverDayEditor() {
  if (portalProfile() !== "family") return "";
  const month = state.selectedDate.slice(0, 7);
  const data = state.caregiver.key === month ? state.caregiver.data : null;
  const currentError = state.caregiver.key === month ? state.caregiver.error : "";
  if (!data) {
    return `
      <div class="panelBody caregiverDayStatus withDivider">
        ${
          currentError
            ? `
              <span>${escapeHtml(currentError)}</span>
              <button class="openButton" type="button" data-caregiver-retry>${uiText("common.retry", "다시 시도")}</button>
            `
            : `<span>${uiText("caregiver.loading", "Loading caregiver records...")}</span>`
        }
      </div>
    `;
  }
  const record = (data.daily || []).find((item) => item.date === state.selectedDate) || {
    minutes: 0,
    extras: 0,
    sessions: [],
    extraItems: [],
  };
  const sessions = Array.isArray(record.sessions) && record.sessions.length
    ? record.sessions
    : [{ start: "09:00", end: "10:00" }];
  const extras = Array.isArray(record.extraItems) ? record.extraItems : [];
  const draftMinutes = sessions.reduce((total, session) => {
    const start = caregiverTimeMinutes(session.start);
    const end = caregiverTimeMinutes(session.end);
    return total + (start !== null && end !== null && end > start ? end - start : 0);
  }, 0);
  const hasRecord = Number(record.minutes) > 0 || Number(record.extras) > 0;
  const summary = hasRecord
    ? [
        Number(record.minutes) > 0 ? formatCaregiverHours(record.minutes) : "",
        Number(record.extras) > 0 ? `${uiText("caregiver.extraFees", "Extra")} ${formatCaregiverWon(record.extras)}` : "",
      ].filter(Boolean).join(" · ")
    : uiText("caregiver.noDayEntry", "No caregiver record");
  return `
    <details class="caregiverDayEditor">
      <summary class="caregiverDaySummary">
        <span>
          <strong>${uiText("caregiver.dayEntry", "Caregiver")}</strong>
          <small>${escapeHtml(summary)}</small>
        </span>
        <span>${hasRecord ? uiText("caregiver.editDay", "Edit") : uiText("caregiver.addDay", "Add")}</span>
      </summary>
      <form class="caregiverDayForm" data-caregiver-day-form>
        <input name="date" type="hidden" value="${escapeHtml(state.selectedDate)}" />
        <section class="caregiverDayFormSection">
          <div class="caregiverDaySectionHeader">
            <strong>${uiText("caregiver.careTime", "Care time")}</strong>
            <span>${uiText("caregiver.total", "Total")} <b data-caregiver-time-total>${formatCaregiverHours(draftMinutes)}</b></span>
          </div>
          <div class="caregiverSessionList" data-caregiver-session-list>
            ${sessions.map((session, index) => caregiverSessionRowHtml(session, index)).join("")}
          </div>
          <button class="caregiverAddLineButton" type="button" data-caregiver-add-session>+ ${uiText("caregiver.addTime", "Add time")}</button>
        </section>
        <section class="caregiverDayFormSection">
          <div class="caregiverDaySectionHeader">
            <strong>${uiText("caregiver.extraFees", "Extra fees")}</strong>
            <span>${uiText("caregiver.total", "Total")} <b data-caregiver-extra-total>${formatCaregiverWon(record.extras)}</b></span>
          </div>
          <div class="caregiverExtraList" data-caregiver-extra-list>
            ${extras.map((extra) => caregiverExtraRowHtml(extra)).join("")}
          </div>
          <button class="caregiverAddLineButton" type="button" data-caregiver-add-extra>+ ${uiText("caregiver.addExtra", "Add fee")}</button>
        </section>
        <div class="caregiverDayActions">
          <button class="primaryButton" type="submit">${uiText("caregiver.saveDay", "Save caregiver record")}</button>
          ${
            hasRecord
              ? `<button class="dangerButton" type="button" data-caregiver-clear-day>${uiText("caregiver.clearDay", "Clear record")}</button>`
              : ""
          }
        </div>
      </form>
    </details>
  `;
}

function renderCalendarAgenda(events, tasks) {
  const weather = weatherForDate(state.selectedDate);
  const caregiver = renderCaregiverDayEditor();
  if (!events.length && !tasks.length && !weather && !caregiver) return `<div class="panelBody"><p class="taskMeta">${uiText("common.noItems", "No items")}</p></div>`;
  return `
    ${weather ? renderSelectedWeather(weather) : ""}
    ${events.length ? renderTimeline(events, "") : ""}
    ${
      tasks.length
        ? `
          <div class="panelBody ${events.length ? "withDivider" : ""}">
            <p class="label sectionLabel">${uiText("task.tasksDue", "Tasks due")}</p>
            ${renderTaskRows(tasks)}
          </div>
        `
        : ""
    }
    ${caregiver}
  `;
}

function weatherForDate(dateValue) {
  return activeCalendarData().weather?.find((weather) => weather.date === dateValue) || null;
}

function countByDate(items, dateKey) {
  return items.reduce((counts, item) => {
    const value = item[dateKey];
    if (value) counts[value] = (counts[value] || 0) + 1;
    return counts;
  }, {});
}

function hasDutyEvent(event) {
  const title = String(event.title || event.summary || "").trim();
  const detail = String(event.detail || event.description || "").trim();
  const categories = Array.isArray(event.categories) ? event.categories : [];
  const dutyName = window.KAOS_TRANSLATIONS?.ko?.["event.dutyName"] || "duty";
  return title === dutyName || detail === dutyName || categories.some((category) => String(category).trim() === dutyName);
}

function dateTone(dateValue) {
  const date = new Date(`${dateValue}T00:00:00`);
  const day = date.getDay();
  if (day === 0) return "isSunday";
  if (day === 6) return "isSaturday";
  return "";
}

function tempRange(item) {
  if (!item || item.minTemp === undefined || item.maxTemp === undefined || item.minTemp === "" || item.maxTemp === "") return "";
  return `${item.minTemp}-${item.maxTemp}`;
}

function weatherGlyph(weather) {
  const raw = String(weather?.glyph || weather?.condition || "").toLowerCase();
  const condition = String(weather?.condition || "").toLowerCase();
  const value = `${raw} ${condition}`;
  if (value.includes("thunder") || value.includes("storm") || value.includes("⛈")) return "\ue31d";
  if (value.includes("snow") || value.includes("sleet") || value.includes("❄")) return "\ue31a";
  if (value.includes("rain") || value.includes("shower") || value.includes("drizzle") || value.includes("🌧") || value.includes("☔")) return "\ue318";
  if (value.includes("cloud") || value.includes("overcast") || value.includes("☁")) return "\ue312";
  if (value.includes("part") || value.includes("few") || value.includes("🌤") || value.includes("⛅")) return "\ue302";
  if (value.includes("night") || value.includes("moon") || value.includes("🌙")) return "\ue32b";
  if (value.includes("fog") || value.includes("mist") || value.includes("haze")) return "\ue313";
  if (value.includes("sun") || value.includes("clear") || value.includes("☀")) return "\ue30d";
  return raw ? "\ue371" : "";
}

function isPastDate(dateValue) {
  return String(dateValue || "") < ymd(new Date());
}

function hasDetailedForecastLayout(weather) {
  return (
    weather
    && !isPastDate(weather.date)
    && Array.isArray(weather.dayparts)
    && weather.dayparts.length > 0
  );
}

function renderWeatherParts(dayparts) {
  return ["Morning", "Afternoon", "Evening", "Night"]
    .map((label) => {
      const part = dayparts.find((item) => item.label === label) || {};
      const localizedLabel = {
        Morning: uiText("weather.morning", "Morning"),
        Afternoon: uiText("weather.afternoon", "Afternoon"),
        Evening: uiText("weather.evening", "Evening"),
        Night: uiText("weather.night", "Night"),
      }[label];
      return `
        <div class="weatherPart">
          <span class="weatherPartLabel">${escapeHtml(localizedLabel)}</span>
          <span class="weatherPartValue">${escapeHtml([weatherGlyph(part), tempRange(part)].filter(Boolean).join(" "))}</span>
        </div>
      `;
    })
    .join("");
}

function renderWeatherLocationRows(items) {
  return items
    .map(({ id, translationKey, label, weather }) => {
      const cityLabel = translationKey ? uiText(translationKey, label) : label;
      return `
        <article class="weatherLocationRow" data-weather-location="${escapeHtml(id)}">
          <strong class="weatherLocationName">${escapeHtml(cityLabel)}</strong>
          ${
            weather
              ? `
                <div class="weatherLocationSummary">
                  <span class="weatherLocationGlyph">${escapeHtml(weatherGlyph(weather))}</span>
                  <span class="weatherLocationRange">${escapeHtml(tempRange(weather))}</span>
                </div>
                ${
                  hasDetailedForecastLayout(weather)
                    ? `<div class="weatherLocationParts">${renderWeatherParts(weather.dayparts || [])}</div>`
                    : `<span class="weatherLocationPastLabel">${uiText("weather.dailySummary", "Daily summary")}</span>`
                }
              `
              : `<span class="weatherLocationUnavailable">${uiText("weather.unavailable", "날씨 정보 없음")}</span>`
          }
        </article>
      `;
    })
    .join("");
}

function renderPastWeatherLocationGrid(items) {
  return `
    <div class="weatherLocationPastGrid">
      ${items
        .map(({ id, translationKey, label, weather }) => {
          const cityLabel = translationKey ? uiText(translationKey, label) : label;
          return `
            <article class="weatherLocationPastItem" data-weather-location="${escapeHtml(id)}">
              <strong class="weatherLocationName">${escapeHtml(cityLabel)}</strong>
              ${
                weather
                  ? `
                    <span class="weatherLocationGlyph">${escapeHtml(weatherGlyph(weather))}</span>
                    <span class="weatherLocationRange">${escapeHtml(tempRange(weather))}</span>
                  `
                  : `<span class="weatherLocationUnavailable">${uiText("weather.unavailable", "날씨 정보 없음")}</span>`
              }
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderWeatherLocationPopup() {
  const popup = state.weatherLocationPopup;
  if (!popup.open) return "";
  const currentMode = popup.mode === "current";
  const locationAttribution = currentMode ? popup.items[0]?.weather?.locationAttribution : "";
  return `
    <div class="weatherLocationOverlay">
      <div class="weatherLocationBackdrop" data-close-weather-locations></div>
      <section
        class="weatherLocationPopup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="weatherLocationPopupTitle"
      >
        <header class="weatherLocationPopupHeader">
          <div>
            <p class="label">${escapeHtml(compactDateLabel(popup.date))}</p>
            <h2 id="weatherLocationPopupTitle">
              ${currentMode ? uiText("weather.currentLocation", "Current location") : uiText("weather.allLocations", "All locations")}
            </h2>
          </div>
          <button
            class="weatherLocationClose"
            type="button"
            data-close-weather-locations
            aria-label="${uiText("common.close", "Close")}"
          >×</button>
        </header>
        <div class="weatherLocationList">
          ${
            popup.loading
              ? `<p class="weatherLocationStatus">${
                  currentMode
                    ? uiText("weather.locating", "Getting current location...")
                    : uiText("weather.loadingOtherLocations", "Loading other locations...")
                }</p>`
              : popup.error
                ? `<p class="weatherLocationStatus isError">${escapeHtml(popup.error)}</p>`
              : !currentMode && isPastDate(popup.date)
                ? renderPastWeatherLocationGrid(popup.items)
                : renderWeatherLocationRows(popup.items)
          }
          ${
            locationAttribution
              ? `
                <p class="weatherLocationAttribution">
                  <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
                    ${escapeHtml(locationAttribution)}
                  </a>
                </p>
              `
              : ""
          }
        </div>
      </section>
    </div>
  `;
}

function renderCurrentLocationWeatherButton(dateValue) {
  if (isPastDate(dateValue)) return "";
  const label = uiText("weather.getCurrentLocation", "Get weather for current location");
  return `
    <button
      class="currentLocationWeatherButton"
      type="button"
      data-current-location-weather="${escapeHtml(dateValue)}"
      aria-label="${escapeHtml(label)}"
      title="${escapeHtml(label)}"
    >&#xe248;</button>
  `;
}

function renderSelectedWeatherDate(dateValue) {
  const [year, month, day] = dateValue.split("-").map(Number);
  const weekday = new Intl.DateTimeFormat(portalProfile() === "family" ? "ko-KR" : "en-US", {
    weekday: "long",
    timeZone: "Asia/Seoul",
  }).format(new Date(`${dateValue}T12:00:00+09:00`));
  return `
    <time class="selectedWeatherDate" datetime="${escapeHtml(dateValue)}">
      <span>${year}</span>
      <strong>${month}/${day}</strong>
      <span>${escapeHtml(weekday)}</span>
    </time>
  `;
}

function renderSelectedWeather(weather) {
  const dayparts = weather.dayparts || [];
  const locationLabel = weatherLocationLabel(weather.city || state.weatherLocation);
  const actionAttributes = `
    data-open-weather-locations="${escapeHtml(weather.date)}"
    role="button"
    tabindex="0"
    aria-label="${uiText("weather.selectedDayAria", "Selected day weather")}. ${uiText("weather.openOtherLocations", "Open weather for other locations")}"
  `;
  if (isPastDate(weather.date) || !dayparts.length) {
    return `
      <div class="selectedWeatherCompact weatherPopupTrigger" ${actionAttributes}>
        <span>${escapeHtml(locationLabel)}</span>
        <strong>${escapeHtml(weatherGlyph(weather))}</strong>
        <em>${escapeHtml(tempRange(weather))}</em>
        ${renderCurrentLocationWeatherButton(weather.date)}
      </div>
    `;
  }
  if (hasDetailedForecastLayout(weather)) {
    return `
      <div class="selectedDayWeather weatherPopupTrigger" ${actionAttributes}>
        ${renderSelectedWeatherDate(weather.date)}
        <div class="selectedWeatherSummary">
          <span class="selectedWeatherLocation">${escapeHtml(locationLabel)}</span>
          <span class="selectedWeatherGlyph">${escapeHtml(weatherGlyph(weather))}</span>
          <span class="selectedWeatherRange">${escapeHtml(tempRange(weather))}</span>
          ${renderCurrentLocationWeatherButton(weather.date)}
        </div>
        <div class="selectedWeatherParts">
          ${renderWeatherParts(dayparts)}
        </div>
      </div>
    `;
  }
  return `
    <div class="selectedWeather weatherPopupTrigger" ${actionAttributes}>
      <div class="selectedWeatherSummary">
        <span class="selectedWeatherLocation">${escapeHtml(locationLabel)}</span>
        <span class="selectedWeatherGlyph">${escapeHtml(weatherGlyph(weather))}</span>
        <span class="selectedWeatherRange">${escapeHtml(tempRange(weather))}</span>
        ${renderCurrentLocationWeatherButton(weather.date)}
      </div>
      <div class="selectedWeatherParts">
        ${renderWeatherParts(dayparts)}
      </div>
    </div>
  `;
}

function addDaysToDateValue(dateValue, days) {
  const date = new Date(`${dateValue}T00:00:00`);
  date.setDate(date.getDate() + days);
  return ymd(date);
}

function familyAgendaDateLabel(dateValue) {
  const date = new Date(`${dateValue}T00:00:00`);
  const weekday = rounyDays.find((day) => day.value === String(date.getDay()))?.familyLabel || "";
  return `${date.getMonth() + 1}/${date.getDate()} ${weekday}`.trim();
}

function familyAgendaEventTime(event) {
  if (event.allDay) return "";
  const start = event.startTime || event.time || "";
  return start && event.endTime ? `${start} - ${event.endTime}` : start;
}

function familyAgendaMixedItems(events, tasks) {
  return [
    ...events.map((event) => ({ kind: "event", date: event.date, time: event.time || "00:00", event })),
    ...tasks.map((task) => ({ kind: "task", date: task.due, time: task.dueTime || "99:99", task })),
  ].sort((a, b) => {
    if (a.date !== b.date) return a.date.localeCompare(b.date);
    if (a.time !== b.time) return a.time.localeCompare(b.time);
    if (a.kind !== b.kind) return a.kind === "event" ? -1 : 1;
    const aTitle = a.event?.title || a.task?.title || "";
    const bTitle = b.event?.title || b.task?.title || "";
    return aTitle.localeCompare(bTitle);
  });
}

function renderFamilyAgendaMixedRow(item) {
  if (item.kind === "event") {
    const event = item.event;
    const eventLabel = uiText("agenda.eventMarker", "Event");
    const timeLabel = event.allDay ? "" : familyAgendaEventTime(event);
    const holidayClass = isPublicHolidayEvent(event) ? "isPublicHoliday" : isObservanceEvent(event) ? "isObservance" : "";
    const generated = isGeneratedCalendarEvent(event);
    const content = `
      <span class="taskTitleRow">
        <strong>${escapeHtml(event.title)}</strong>
        ${generated ? renderAutomationPill("brain") : ""}
      </span>
      ${!generated && event.detail ? `<span>${escapeHtml(event.detail)}</span>` : ""}
    `;
    return `
      <li class="familyAgendaMixedRow isEvent ${timeLabel ? "hasTime" : "isTimeless"} ${holidayClass}">
        <span class="familyAgendaEntryControl familyAgendaEventMarker" role="img" aria-label="${escapeHtml(eventLabel)}" title="${escapeHtml(eventLabel)}">&#xEAB0;</span>
        ${timeLabel ? `<time class="familyAgendaMixedTime">${escapeHtml(timeLabel)}</time>` : ""}
        ${event.systemManaged
          ? `<span class="familyAgendaMixedLink isReadOnly">${content}</span>`
          : `<a class="familyAgendaMixedLink" href="#/edit-event?uid=${encodeURIComponent(event.id)}">${content}</a>`}
        <span class="familyAgendaMixedBadge"></span>
      </li>
    `;
  }
  const task = item.task;
  return `
    <li class="familyAgendaMixedRow isTask ${task.dueTime ? "hasTime" : "isTimeless"} ${task.priorityLabel ? `priority${task.priorityLabel}` : ""}" data-task-id="${escapeHtml(task.id)}">
      <button class="checkButton familyAgendaEntryControl" type="button" aria-label="${uiText("task.toggle", "Toggle")} ${escapeHtml(task.title)}"></button>
      ${task.dueTime ? `<time class="familyAgendaMixedTime">${escapeHtml(task.dueTime)}</time>` : ""}
      <a class="familyAgendaMixedLink" href="#/edit-task?uid=${encodeURIComponent(task.id)}">
        <span class="taskTitleRow">
          <strong>${escapeHtml(task.title)}</strong>
          ${renderCollectionPill(task)}
        </span>
        ${task.subtasks.length ? `<span>${uiText("task.subtasksCount", "{count} subtasks", { count: task.subtasks.length })}</span>` : ""}
      </a>
      <small class="familyAgendaMixedBadge">${escapeHtml(task.badge)}</small>
    </li>
  `;
}

function renderFamilyAgendaDateWeather(date) {
  const weather = weatherForDate(date);
  if (!weather) return "";
  return `<span class="familyAgendaDateWeather"><b>${escapeHtml(weatherGlyph(weather))}</b> ${escapeHtml(tempRange(weather))}</span>`;
}

function renderFamilyAgendaMixedList(events, tasks) {
  const items = familyAgendaMixedItems(events, tasks);
  if (!items.length) return `<p class="taskMeta">${uiText("agenda.noUpcomingItems", "No upcoming items")}</p>`;
  const groups = items.reduce((result, item) => {
    if (!result[item.date]) result[item.date] = [];
    result[item.date].push(item);
    return result;
  }, {});
  return Object.keys(groups).sort().map((date) => `
    <section class="familyAgendaDateGroup">
      <h3>
        <span>${escapeHtml(`${date} ${familyAgendaDateLabel(date).split(" ").slice(-1)[0]}`)}</span>
        ${renderFamilyAgendaDateWeather(date)}
      </h3>
      <ul class="familyAgendaMixedList">
        ${groups[date].map(renderFamilyAgendaMixedRow).join("")}
      </ul>
    </section>
  `).join("");
}

function familyAgendaRounyStatus(now = new Date()) {
  ensureRounyState();
  if (!state.rouny.hasPersistedLocal && !state.rouny.remoteLive) return null;
  const template = state.rouny.templates.find((item) => item.id === state.rouny.selectedTemplateId)
    || state.rouny.templates[0];
  if (!template) return null;
  const dayOfWeek = String(now.getDay());
  const currentMinutes = now.getHours() * 60 + now.getMinutes();
  const slots = template.items
    .flatMap((item) => (item.slots || [])
      .filter((slot) => slot.dayOfWeek === dayOfWeek)
      .map((slot) => ({ item, slot, start: rounyMinutes(slot.startTime), end: rounyMinutes(slot.endTime) })))
    .filter((entry) => entry.end > entry.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const current = slots.find((entry) => entry.start <= currentMinutes && currentMinutes < entry.end);
  if (current) return { ...current, mode: "current" };
  const next = slots.find((entry) => entry.start > currentMinutes);
  return next ? { ...next, mode: "next" } : null;
}

function renderFamilyAgendaRouny(now = new Date()) {
  const status = familyAgendaRounyStatus(now);
  if (!status) return "";
  const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return `
    <section class="panel familyAgendaRouny">
      <div class="panelHeader">
        <p class="label">${uiText("agenda.currentRouny", "Rouny now")}</p>
        <time data-family-agenda-now>${time}</time>
      </div>
      <a class="familyAgendaRounyBody" href="#/rouny">
        <span class="familyAgendaRounyMarker" style="background:${escapeHtml(normalizeRounyColor(status.item.color))}"></span>
        <span class="familyAgendaRounyText is-${status.mode}">
          ${status.mode === "next" ? `<small>${uiText("agenda.next", "Next")}</small>` : ""}
          <strong>${escapeHtml(status.item.title || uiText("common.untitled", "Untitled"))}</strong>
          <span>${escapeHtml(status.slot.startTime)}-${escapeHtml(status.slot.endTime)}</span>
        </span>
      </a>
    </section>
  `;
}

function renderFamilyAgendaSection(title, body) {
  return `
    <section class="panel familyAgendaSection">
      <div class="panelHeader">
        <h2>${escapeHtml(title)}</h2>
      </div>
      <div class="panelBody">${body}</div>
    </section>
  `;
}

function renderFamilyAgendaUpcoming(events, tasks) {
  return `
    <section class="panel familyAgendaUpcoming">
      <div class="panelHeader">
        <h2>${uiText("agenda.upcomingItems", "Upcoming")}</h2>
      </div>
      <div class="panelBody">${renderFamilyAgendaMixedList(events, tasks)}</div>
    </section>
  `;
}

function renderFamilyAgenda() {
  const today = ymd(new Date());
  state.selectedDate = today;
  const endDate = addDaysToDateValue(today, 6);
  const events = mockAdapter.getEvents()
    .filter((event) => event.date >= today && event.date <= endDate)
    .sort(sortByDateTime);
  const activeTasks = mockAdapter.getTasks().filter((task) => !task.done);
  const upcomingTasks = activeTasks
    .filter((task) => task.due && task.due >= today && task.due <= endDate)
    .sort(compareTasksByDue);
  const otherTasks = activeTasks
    .filter((task) => !task.due)
    .sort(compareTasksByCreated);
  const weather = weatherForDate(today);
  const weatherSummary = weather
    ? `${weatherLocationLabel(weather.city || state.weatherLocation)} ${tempRange(weather)}`
    : uiText("weather.unavailable", "날씨 정보 없음");
  return `
    <div class="familyAgendaPage">
      <section class="panel familyAgendaOverview">
        <div>
          <p class="label">${uiText("agenda.today", "Today")}</p>
          <h2>${escapeHtml(compactDateLabel(today))}</h2>
        </div>
        <div class="familyAgendaWeather">
          ${weather ? `<span class="overviewWeatherGlyph">${escapeHtml(weatherGlyph(weather))}</span>` : ""}
          <strong>${escapeHtml(weatherSummary)}</strong>
        </div>
      </section>
      ${renderFamilyAgendaUpcoming(events, upcomingTasks)}
      ${renderFamilyAgendaSection(uiText("agenda.otherTasks", "Other tasks"), renderTaskRows(otherTasks))}
      ${renderFamilyAgendaRouny()}
    </div>
  `;
}

function renderToday() {
  if (portalProfile() === "family") return renderFamilyAgenda();
  const today = ymd(new Date());
  state.selectedDate = today;
  const endDate = addDaysToDateValue(today, 6);
  const events = mockAdapter.getEvents()
    .filter((event) => event.date >= today && event.date <= endDate)
    .sort(sortByDateTime);
  const tasks = mockAdapter.getTasks()
    .filter((task) => !task.done && task.due && (
      (task.due >= today && task.due <= endDate) || isRecurringTask(task)
    ))
    .sort(compareTasksByDue);
  const weather = weatherForDate(today);
  const weatherSummary = [weather?.cityName || weatherLocationLabel(), tempRange(weather)]
    .filter(Boolean)
    .join(" ");
  return `
    <div class="todayDesktopGrid">
      <section class="panel">
        <div class="panelHeader">
          <div>
            <p class="label">Overview</p>
            <h2>
              ${escapeHtml(compactDateLabel(today))} · ${escapeHtml(weatherSummary)}
              ${weather ? `<span class="overviewWeatherGlyph">${escapeHtml(weatherGlyph(weather))}</span>` : ""}
            </h2>
          </div>
        </div>
        <div class="panelBody">
          <div class="summaryGrid">
            <div class="metric"><strong>${events.length}</strong><span>events</span></div>
            <div class="metric"><strong>${tasks.length}</strong><span>tasks</span></div>
            <div class="metric"><strong>7</strong><span>services</span></div>
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="panelHeader">
          <h2>Agenda</h2>
        </div>
        <div class="panelBody">${renderFamilyAgendaMixedList(events, [])}</div>
      </section>
      <section class="panel">
        <div class="panelHeader">
          <h2>Tasks</h2>
        </div>
        <div class="panelBody">${renderTaskRows(tasks)}</div>
      </section>
    </div>
  `;
}

function renderCalendarMonthPanel(options = {}) {
  const compact = options.compact === true;
  const month = state.selectedDate.slice(0, 7);
  const events = mockAdapter.getEvents();
  const regularEvents = events.filter((event) => !isGoogleHolidayEvent(event) && !isGeneratedCalendarEvent(event));
  const publicHolidayDates = new Set(
    activeCalendarData().events.map(normalizeEvent).filter(isPublicHolidayEvent).map((event) => event.date),
  );
  const datedTasks = mockAdapter.getTasks().filter((task) => task.due);
  const eventCounts = countByDate(regularEvents, "date");
  const taskCounts = countByDate(datedTasks, "due");
  const dutyDates = new Set(regularEvents.filter(hasDutyEvent).map((event) => event.date));
  const marketDates = new Set(events.filter(isMarketDayEvent).map((event) => event.date));
  const caregiverDays = new Set(
    portalProfile() === "family" && state.caregiver.key === month
      ? (state.caregiver.data?.daily || [])
          .filter((item) => Number(item.minutes) > 0 || Number(item.extras) > 0)
          .map((item) => item.date)
      : [],
  );
  const weatherByDate = compact
    ? new Map()
    : new Map((activeCalendarData().weather || []).map((weather) => [weather.date, weather]));
  return `
    <section class="panel calendarMonthPanel ${compact ? "isCompact" : ""}">
      <div class="panelHeader">
        <div>
          <p class="label">${uiText("calendar.label", "Calendar")}</p>
          <h2>${escapeHtml(monthTitle(month))}</h2>
        </div>
        <div class="calendarHeaderActions" aria-label="${uiText("calendar.actionsAria", "Calendar actions")}">
          <div class="monthNav" aria-label="${uiText("calendar.monthNavigationAria", "Month navigation")}">
            <button class="monthNavButton" type="button" data-month-shift="-1" aria-label="${uiText("calendar.previousMonth", "Previous month")}">&lt;&lt;</button>
            <button class="monthTodayButton" type="button" data-month-today>${uiText("calendar.today", "Today")}</button>
            <button class="monthNavButton" type="button" data-month-shift="1" aria-label="${uiText("calendar.nextMonth", "Next month")}">&gt;&gt;</button>
          </div>
          ${!compact && portalProfile() === "family" ? `<a class="openButton" href="#/caregiver">${uiText("caregiver.label", "Caregiver")}</a>` : ""}
          ${!compact ? `<a class="openButton" href="#/add-event">${uiText("common.add", "Add")}</a>` : ""}
        </div>
      </div>
      <div class="calendarGrid" aria-label="${uiText("calendar.monthGridAria", "Month grid")}">
        ${calendarWeekdays().map((day) => `<span class="weekday">${day}</span>`).join("")}
        ${monthCells(month)
          .map((cell) => {
            const hasDuty = dutyDates.has(cell.value);
            const hasCaregiver = caregiverDays.has(cell.value);
            const hasMarket = marketDates.has(cell.value);
            const classes = [
              "day",
              cell.muted ? "isMuted" : "",
              cell.value === ymd(new Date()) ? "isToday" : "",
              cell.value === state.selectedDate ? "isSelected" : "",
              hasDuty ? "isDuty" : "",
              publicHolidayDates.has(cell.value) ? "isPublicHoliday" : "",
              dateTone(cell.value),
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
                ${weatherGlyph(weather) ? `<span class="dayWeatherGlyph">${escapeHtml(weatherGlyph(weather))}</span>` : ""}
                ${
                  hasCaregiver || hasMarket || eventCount || taskCount
                    ? `
                      <span class="dayMarkers">
                        ${hasCaregiver ? `<span class="dayCaregiverMark" aria-label="${uiText("caregiver.dayMarker", "Caregiver record")}">•</span>` : ""}
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

function renderCalendarAgendaPanel() {
  const events = mockAdapter.getEvents().filter((event) => event.date === state.selectedDate);
  const tasks = mockAdapter.getTasks().filter((task) => task.due === state.selectedDate);
  const weather = weatherForDate(state.selectedDate);
  return `
    <section class="panel calendarAgendaPanel desktopContextPane">
      ${
        hasDetailedForecastLayout(weather)
          ? ""
          : `
            <div class="panelHeader">
              <div>
                <p class="label">${uiText("calendar.agenda", "Agenda")}</p>
                <h2>${escapeHtml(state.selectedDate)}</h2>
              </div>
            </div>
          `
      }
      ${renderCalendarAgenda(events, tasks)}
    </section>
  `;
}

function renderCalendarWorkspace(contextHtml = renderCalendarAgendaPanel()) {
  return `
    ${renderCollectionRail()}
    <div class="calendarDesktopGrid workspaceSplit">
      ${renderCalendarMonthPanel()}
      ${contextHtml}
    </div>
    ${renderWeatherLocationPopup()}
  `;
}

function renderCalendar() {
  return renderCalendarWorkspace();
}

function renderTaskFilters() {
  return `
    <section class="taskFilters" aria-label="${uiText("task.filtersAria", "Task filters")}">
      <label>
        <span>${uiText("task.label", "Tasks")}</span>
        <select data-task-mode>
          <option value="active" ${state.taskMode === "active" ? "selected" : ""}>${uiText("task.active", "Active")}</option>
          <option value="done" ${state.taskMode === "done" ? "selected" : ""}>${uiText("task.completed", "Completed")}</option>
        </select>
      </label>
      <label>
        <span>${uiText("task.order", "Order")}</span>
        <select data-task-sort>
          <option value="due" ${state.taskSort === "due" ? "selected" : ""}>${uiText("task.due", "Due")}</option>
          <option value="created" ${state.taskSort === "created" ? "selected" : ""}>${uiText("task.creation", "Creation")}</option>
        </select>
      </label>
      <a class="openButton taskAddButton" href="#/add-task">${uiText("common.add", "Add")}</a>
    </section>
  `;
}

function renderTaskListPanel(tasks) {
  return `
    <section class="panel taskListPanel">
      <div class="panelBody">${renderTaskRows(tasks)}</div>
    </section>
  `;
}

function renderTaskEmptyContext() {
  return `
    <section class="panel desktopContextPane taskEmptyContext">
      <div class="panelHeader">
        <div>
          <p class="label">${uiText("task.details", "Task details")}</p>
          <h2>${uiText("task.selectTask", "Select a task")}</h2>
        </div>
      </div>
      <div class="panelBody">
        <p class="taskMeta">${uiText("task.selectTaskHelp", "Choose a task from the list to view or edit it.")}</p>
      </div>
    </section>
  `;
}

function renderTaskWorkspace(contextHtml = renderTaskEmptyContext()) {
  const tasks = mockAdapter.getTasks().filter((task) => taskMatchesMode(task, state.taskMode));
  return `
    ${renderCollectionRail()}
    <div class="taskDesktopGrid workspaceSplit">
      <div class="taskMiddlePane">
        ${renderTaskFilters()}
        ${renderTaskListPanel(tasks)}
      </div>
      ${contextHtml}
    </div>
  `;
}

function renderTasks() {
  return isDesktopLayout() ? renderTaskWorkspace() : `
    ${renderCollectionRail()}
    ${renderTaskFilters()}
    ${renderTaskListPanel(mockAdapter.getTasks().filter((task) => taskMatchesMode(task, state.taskMode)))}
  `;
}

function renderAdd() {
  return state.addKind === "task" ? renderAddTask() : renderAddEvent();
}

function renderAddEvent() {
  ensureAddCollectionDefault();
  ensureEventPresets();
  const draft = {
    ...defaultEventPreset(),
    ...(state.eventPresetDraft || {}),
    ...(state.addEventDraft || {}),
  };
  const shareFamily = Boolean(draft.shareFamily || state.currentCollection === "owner:family");
  const allDay = Boolean(draft.allDay);
  const contextBody = state.addEventMode === "preset"
    ? renderEventPresetPanel()
    : renderEventFormPanel(draft, shareFamily, allDay);
  if (isDesktopLayout()) {
    return renderCalendarWorkspace(`
      <aside class="desktopContextPane contextPaneStack">
        ${renderContextHeader(uiText("calendar.label", "Calendar"), uiText("route.addEvent", "Add Event"), "#/calendar")}
        ${renderAddEventTabs()}
        ${contextBody}
      </aside>
    `);
  }
  return `${renderCollectionRail()}${renderAddEventTabs()}${contextBody}`;
}

function renderContextHeader(label, title, closeHref) {
  return `
    <section class="panel">
      <div class="panelHeader">
        <div>
          <p class="label">${escapeHtml(label)}</p>
          <h2>${escapeHtml(title)}</h2>
        </div>
        <a class="openButton" href="${escapeHtml(closeHref)}">${uiText("common.close", "Close")}</a>
      </div>
    </section>
  `;
}

function renderEventPresetPanel() {
  return `
    <section class="panel">
      <div class="panelHeader">
        <div>
          <p class="label">${uiText("event.preset", "Preset")}</p>
          <h2>${uiText("event.templates", "Event templates")}</h2>
        </div>
        <a class="openButton" href="#/settings">${uiText("common.manage", "Manage")}</a>
      </div>
      <div class="panelBody">
        ${renderEventPresetChoices()}
      </div>
    </section>
  `;
}

function renderEventFormPanel(draft, shareFamily, allDay) {
  const editing = Boolean(draft.eventId);
  const startDate = draft.startDate || state.selectedDate;
  const endDate = draft.endDate || startDate;
  const customRepeat = draft.repeat === "custom";
  return `
    <section class="panel">
      <form class="composer" ${editing ? "data-edit-event" : "data-create-event"}>
        ${editing ? `<input name="uid" type="hidden" value="${escapeHtml(draft.eventId)}" />` : ""}
        ${editing ? `<input name="collectionId" type="hidden" value="${escapeHtml(draft.collection)}" />` : ""}
        ${editing ? "" : renderFamilyShareToggle(shareFamily, "event")}
        <label>
          <span>${uiText("common.title", "Title")}</span>
          <input name="title" type="text" autocomplete="off" placeholder="${uiText("event.new", "New event")}" value="${escapeHtml(draft.title)}" required />
        </label>
        <label class="toggleLine">
          <span>${uiText("event.allDay", "All-day")}</span>
          <input name="allDay" type="checkbox" data-all-day-toggle ${allDay ? "checked" : ""} />
        </label>
        <div class="formGrid">
          <label>
            <span>${uiText("event.startDate", "Start date")}</span>
            <input name="startDate" type="date" value="${escapeHtml(startDate)}" required />
          </label>
          <label data-event-time-field ${allDay ? 'class="isDisabled"' : ""}>
            <span>${uiText("event.startTime", "Start time")}</span>
            <input name="startTime" type="time" value="${escapeHtml(draft.startTime)}" step="300" ${allDay ? "disabled" : ""} />
          </label>
          <label>
            <span>${uiText("event.endDate", "End date")}</span>
            <input name="endDate" type="date" value="${escapeHtml(endDate)}" required />
          </label>
          <label data-event-time-field ${allDay ? 'class="isDisabled"' : ""}>
            <span>${uiText("event.endTime", "End time")}</span>
            <input name="endTime" type="time" value="${escapeHtml(draft.endTime)}" step="300" ${allDay ? "disabled" : ""} />
          </label>
        </div>
        <label>
          <span>${uiText("event.repeat", "Repeat")}</span>
          <select name="repeat" ${customRepeat ? "disabled" : ""}>
            <option value="" ${!draft.repeat ? "selected" : ""}>${uiText("common.none", "None")}</option>
            <option value="weekly" ${draft.repeat === "weekly" ? "selected" : ""}>${uiText("event.weekly", "Weekly")}</option>
            <option value="monthly" ${draft.repeat === "monthly" ? "selected" : ""}>${uiText("event.monthly", "Monthly")}</option>
            <option value="yearly" ${draft.repeat === "yearly" ? "selected" : ""}>${uiText("event.yearly", "Yearly")}</option>
            ${customRepeat ? `<option value="custom" selected>${uiText("event.customRepeat", "Custom (preserved)")}</option>` : ""}
          </select>
          ${draft.preserveRepeat ? `<input name="preserveRepeat" type="hidden" value="1" />` : ""}
        </label>
        <label data-event-time-field ${draft.preserveAlarm ? "data-preserve-disabled" : ""} ${allDay || draft.preserveAlarm ? 'class="isDisabled"' : ""}>
          <span>${uiText("event.alarmTime", "Alarm time")}</span>
          <input name="alarm" type="time" step="300" value="${escapeHtml(draft.alarm)}" ${allDay || draft.preserveAlarm ? "disabled" : ""} />
          ${draft.preserveAlarm ? `<input name="preserveAlarm" type="hidden" value="1" /><small class="formNote">${uiText("event.alarmPreserved", "Existing alarm is preserved")}</small>` : ""}
        </label>
        <label>
          <span>${uiText("common.memo", "Memo")}</span>
          <textarea name="memo" rows="5" placeholder="${uiText("event.notes", "Event notes")}">${escapeHtml(draft.memo)}</textarea>
        </label>
        <div class="formActions">
          ${editing ? `<button class="dangerButton" type="button" data-delete-event data-event-id="${escapeHtml(draft.eventId)}" data-collection-id="${escapeHtml(draft.collection)}">${uiText("event.delete", "Delete event")}</button>` : ""}
          <button class="primaryButton" type="submit">${editing ? uiText("event.save", "Save event") : uiText("event.create", "Create event")}</button>
        </div>
      </form>
    </section>
  `;
}

function renderEditEvent() {
  const eventId = hashParam("uid");
  const calendarEvent = findEventById(eventId);
  if (!calendarEvent) {
    const notFound = `
      <section class="panel desktopContextPane">
        <div class="panelBody"><p class="taskMeta">${uiText("event.notFound", "Event not found")}</p></div>
      </section>
    `;
    return isDesktopLayout() ? renderCalendarWorkspace(notFound) : `${renderCollectionRail()}${notFound}`;
  }

  if (state.editingEventId !== calendarEvent.id) {
    state.editingEventId = calendarEvent.id;
    state.selectedDate = calendarEvent.startDate || calendarEvent.date;
  }

  const header = renderContextHeader(uiText("event.details", "Event details"), uiText("route.editEvent", "Edit Event"), "#/calendar");
  let body;
  if (!calendarEvent.editable) {
    body = `
      <section class="panel">
        <div class="panelBody eventReadOnly">
          <strong>${escapeHtml(calendarEvent.title)}</strong>
          <span>${escapeHtml([calendarEvent.startDate, calendarEvent.startTime].filter(Boolean).join(" "))}</span>
          ${calendarEvent.description ? `<p>${escapeHtml(calendarEvent.description)}</p>` : ""}
          <p class="formNote">${uiText("event.nativeClientRequired", "This event has recurrence or timezone data that must be edited in a native calendar client.")}</p>
          <button class="dangerButton" type="button" data-delete-event data-event-id="${escapeHtml(calendarEvent.id)}" data-collection-id="${escapeHtml(calendarEvent.collection)}">${uiText("event.deleteSeries", "Delete event or series")}</button>
        </div>
      </section>
    `;
  } else {
    const fallbackEnd = addLocalMinutes(calendarEvent.startDate, calendarEvent.startTime, 60);
    body = renderEventFormPanel(
      {
        eventId: calendarEvent.id,
        collection: calendarEvent.collection,
        title: calendarEvent.title,
        memo: calendarEvent.description,
        allDay: calendarEvent.allDay,
        startDate: calendarEvent.startDate,
        startTime: calendarEvent.startTime || DEFAULT_EVENT_START_TIME,
        endDate: calendarEvent.allDay || calendarEvent.endTime ? calendarEvent.endDate : fallbackEnd.date,
        endTime: calendarEvent.endTime || fallbackEnd.time,
        repeat: calendarEvent.repeat,
        preserveRepeat: calendarEvent.preserveRepeat,
        alarm: calendarEvent.alarmTime,
        preserveAlarm: calendarEvent.preserveAlarm,
      },
      false,
      calendarEvent.allDay,
    );
  }

  const context = `<aside class="desktopContextPane contextPaneStack">${header}${body}</aside>`;
  return isDesktopLayout() ? renderCalendarWorkspace(context) : `${renderCollectionRail()}${header}${body}`;
}

function renderAddEventTabs() {
  return `
    <section class="segmentedTabs" aria-label="${uiText("event.addModeAria", "Add event mode")}">
      <button class="${state.addEventMode === "normal" ? "isActive" : ""}" type="button" data-add-event-mode="normal">${uiText("event.normal", "Normal")}</button>
      <button class="${state.addEventMode === "preset" ? "isActive" : ""}" type="button" data-add-event-mode="preset">${uiText("event.preset", "Preset")}</button>
    </section>
  `;
}

function renderEventPresetChoices() {
  if (state.eventPresets.loading && !state.eventPresets.checked) {
    return `<p class="taskMeta">${uiText("event.presetsLoading", "Loading event presets...")}</p>`;
  }
  if (state.eventPresets.error) {
    return `<div class="caregiverError"><span>${escapeHtml(state.eventPresets.error)}</span><button class="openButton" type="button" data-event-presets-retry>${uiText("common.retry", "다시 시도")}</button></div>`;
  }
  if (!state.eventPresets.items.length) {
    return `<p class="taskMeta">${uiText("event.noPresets", "No event presets yet.")}</p>`;
  }
  return `
    <div class="presetList">
      ${state.eventPresets.items
        .map(
          (preset) => `
            <button class="presetChoice" type="button" data-use-event-preset="${escapeHtml(preset.id)}">
              <strong>${escapeHtml(preset.name)}</strong>
              <span>${escapeHtml([preset.title || uiText("common.untitled", "Untitled"), preset.allDay ? uiText("event.allDay", "all-day") : `${preset.startTime}-${preset.endTime}`, preset.shareFamily ? uiText("common.family", "Family") : uiText("common.personal", "Personal")].join(" · "))}</span>
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderAddTask() {
  ensureAddCollectionDefault();
  const form = renderTaskEditorForm(null, state.addTaskDraft || {});
  if (isDesktopLayout()) {
    return renderTaskWorkspace(`
      <aside class="desktopContextPane contextPaneStack">
        ${renderContextHeader(uiText("task.details", "Task details"), uiText("route.addTask", "Add Task"), "#/tasks")}
        ${form}
      </aside>
    `);
  }
  return `${renderCollectionRail()}${form}`;
}

function renderFamilyShareToggle(checked = state.currentCollection === "owner:family", kind = "task") {
  if (portalProfile() === "family") {
    return '<input name="shareFamily" type="hidden" value="on" />';
  }
  const label =
    kind === "event"
      ? uiText("event.shareFamily", "Share to Family")
      : uiText("task.shareFamily", "Family shared");
  return `
    <label class="toggleLine shareLine">
      <span>${label}</span>
      <input name="shareFamily" type="checkbox" data-share-family ${checked ? "checked" : ""} />
    </label>
  `;
}

function renderEditTask() {
  const taskId = hashParam("uid");
  const task = findTaskById(taskId);
  if (!task) {
    const notFound = `
      <section class="panel">
        <div class="panelBody">
          <p class="taskMeta">${uiText("task.notFound", "Task not found")}</p>
        </div>
      </section>
    `;
    return isDesktopLayout() ? renderTaskWorkspace(notFound) : `${renderCollectionRail()}${notFound}`;
  }

  if (state.editingTaskId !== task.id) {
    state.editingTaskId = task.id;
    state.taskDueEnabled = Boolean(task.due);
    state.selectedDate = task.due || ymd(new Date());
  }

  const form = renderTaskEditorForm(task);
  if (isDesktopLayout()) {
    return renderTaskWorkspace(`
      <aside class="desktopContextPane contextPaneStack">
        ${renderContextHeader(uiText("task.details", "Task details"), uiText("route.editTask", "Edit Task"), "#/tasks")}
        ${form}
      </aside>
    `);
  }
  return `${renderCollectionRail()}${form}`;
}

function renderTaskEditorForm(task = null, draft = {}) {
  const dueEnabled = state.taskDueEnabled;
  const editing = Boolean(task);
  const title = editing ? task.title : draft.title || "";
  const memo = editing ? task.description : draft.memo || "";
  const dueTime = editing ? task.dueTime : draft.dueTime || "";
  const priority = editing ? task.priority : draft.priority || "";
  const shareFamily = editing ? false : Boolean(draft.shareFamily || state.currentCollection === "owner:family");
  return `
    <form class="taskComposer taskContextComposer" ${editing ? "data-edit-task" : "data-create-task"}>
      ${editing ? `<input name="uid" type="hidden" value="${escapeHtml(task.id)}" />` : ""}
      ${editing ? `<input name="collectionId" type="hidden" value="${escapeHtml(task.collection)}" />` : ""}
      <input name="due" type="hidden" value="${dueEnabled ? escapeHtml(state.selectedDate) : ""}" />
      <section class="panel">
        <div class="composer">
          ${editing ? "" : renderFamilyShareToggle(shareFamily)}
          <label>
            <span>${uiText("task.label", "Task")}</span>
            <input name="title" type="text" autocomplete="off" value="${escapeHtml(title)}" placeholder="${uiText("task.new", "New task")}" required />
          </label>
          <label>
            <span>${uiText("common.memo", "Memo")}</span>
            <textarea name="memo" rows="6" placeholder="${escapeHtml(uiText("task.memoPlaceholder", TASK_MEMO_PLACEHOLDER))}">${escapeHtml(memo)}</textarea>
          </label>
        </div>
      </section>
      ${renderAddDatePicker({ title: uiText("task.due", "Task due"), allowNoDate: true })}
      <section class="panel">
        <div class="composer">
          <label>
            <span>${uiText("task.time", "Time")}</span>
            <input name="dueTime" type="time" value="${dueEnabled ? escapeHtml(dueTime) : ""}" step="300" />
          </label>
          <p class="formNote">${uiText("task.defaultTime", "Default time 10:00 am")}</p>
          <label>
            <span>${uiText("task.priority", "Priority")}</span>
            <select name="priority">
              <option value="" ${!priority ? "selected" : ""}>${uiText("common.none", "None")}</option>
              <option value="9" ${priority === "9" ? "selected" : ""}>${uiText("task.priorityLow", "Low")} (!)</option>
              <option value="5" ${priority === "5" ? "selected" : ""}>${uiText("task.priorityMedium", "Medium")} (!!)</option>
              <option value="1" ${priority === "1" ? "selected" : ""}>${uiText("task.priorityHigh", "High")} (!!!)</option>
            </select>
          </label>
          <div class="formActions">
            ${editing ? `<button class="dangerButton" type="button" data-delete-task data-task-id="${escapeHtml(task.id)}" data-collection-id="${escapeHtml(task.collection)}">${uiText("task.delete", "Delete task")}</button>` : ""}
            <button class="primaryButton" type="submit">${editing ? uiText("common.save", "Save task") : uiText("task.create", "Create local task")}</button>
          </div>
        </div>
      </section>
    </form>
  `;
}

function renderServices() {
  return `
    <section class="panel">
      <div class="panelHeader">
        <div>
          <p class="label">Services</p>
          <h2>Kaos platform</h2>
        </div>
      </div>
      <div class="panelBody">
        <div class="servicesGrid">
          ${mockAdapter
            .getServices()
            .map(
              (service) => `
                <div class="serviceRow">
                  <div>
                    <strong>${escapeHtml(service.name)}</strong>
                    <span class="serviceMeta">${escapeHtml(service.meta)}</span>
                  </div>
                  <div class="serviceActions">
                    <span class="serviceType">${escapeHtml(service.type)}</span>
                    ${
                      service.href
                        ? `<a class="openButton" href="${escapeHtml(serviceHref(service))}">Open</a>`
                        : `<span class="openButton" aria-label="No direct service link">Hold</span>`
                    }
                  </div>
                </div>
              `,
            )
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function renderDesktopService() {
  const service = serviceById(hashParam("service"));
  if (!service?.href || service.href.startsWith("#/")) return renderServices();
  const openAction = `<a class="openButton" href="${escapeHtml(service.href)}" target="_blank" rel="noopener">Open</a>`;
  if (!isDesktopLayout() || portalProfile() !== "main" || service.embed === false) {
    return `
      <section class="panel desktopServiceFallback">
        <div class="panelHeader">
          <div>
            <p class="label">${escapeHtml(service.type)}</p>
            <h2>${escapeHtml(service.name)}</h2>
          </div>
          ${openAction}
        </div>
      </section>
    `;
  }
  return `
    <section class="panel desktopServiceWorkspace">
      <div class="desktopServiceToolbar">
        <div>
          <p class="label">${escapeHtml(service.type)}</p>
          <h2>${escapeHtml(service.name)}</h2>
        </div>
        <div class="desktopServiceActions">
          <button class="openButton" type="button" data-reload-service-frame>Reload</button>
          ${openAction}
        </div>
      </div>
      <iframe
        class="desktopServiceFrame"
        src="${escapeHtml(service.href)}"
        title="${escapeHtml(service.name)}"
        allow="clipboard-read; clipboard-write"
        referrerpolicy="strict-origin-when-cross-origin"
      ></iframe>
    </section>
  `;
}

function renderSupplies(options = {}) {
  const compact = options.compact === true;
  const active = state.supplies.mode === "active";
  const loadingText = !state.supplies.checked ? "Loading supplies..." : "";
  const emptyText = active ? "No supplies queued." : "No done supplies.";
  return `
    <section class="panel ${compact ? "embedSuppliesPanel" : ""}">
      ${compact ? "" : `<div class="panelHeader">
        <div>
          <p class="label">Supplies</p>
          <h2>Buy list</h2>
        </div>
        <a class="openButton" href="#/services">Utils</a>
      </div>`}
      <form class="composer supplyComposer" data-create-supply>
        <label>
          <span>Item</span>
          <input name="title" type="text" autocomplete="off" placeholder="gauze" required />
        </label>
        <button class="openButton supplyAddButton" type="submit">Add</button>
      </form>
      <div class="panelBody">
        <div class="segmentedTabs supplyModeTabs" role="group" aria-label="Supply mode">
          <button type="button" class="${active ? "isActive" : ""}" data-supplies-mode="active">Active</button>
          <button type="button" class="${!active ? "isActive" : ""}" data-supplies-mode="done">Done</button>
        </div>
        ${
          active && state.supplies.presets.length
            ? `<div class="supplyPresets" aria-label="Recent supplies">
                ${state.supplies.presets
                  .map((preset) => `<button type="button" data-supply-preset="${escapeHtml(preset.name)}">${escapeHtml(preset.name)}</button>`)
                  .join("")}
              </div>`
            : ""
        }
        ${
          state.supplies.error
            ? `<div class="emptyState">${escapeHtml(state.supplies.error)}</div>`
            : loadingText
              ? `<div class="emptyState">${loadingText}</div>`
              : state.supplies.items.length
                ? `<ul class="supplyList">
                    ${state.supplies.items.map((item) => renderSupplyRow(item)).join("")}
                  </ul>`
                : `<div class="emptyState">${emptyText}</div>`
        }
      </div>
    </section>
  `;
}

function renderEmbedStatus(title, detail, action = "") {
  return `
    <section class="panel embedStatusPanel">
      <div class="panelBody">
        <strong>${escapeHtml(title)}</strong>
        ${detail ? `<p class="taskMeta">${escapeHtml(detail)}</p>` : ""}
        ${action}
      </div>
    </section>
  `;
}

function renderEmbedTaskEditor(route) {
  if (route === "edit-task") {
    const task = findTaskById(hashParam("uid"));
    if (!task) {
      return renderEmbedStatus("Task not found", "Refresh the agenda and select the task again.", '<a class="openButton" href="#/tasks">Back</a>');
    }
    if (state.editingTaskId !== task.id) {
      state.editingTaskId = task.id;
      state.taskDueEnabled = Boolean(task.due);
      state.selectedDate = task.due || ymd(new Date());
    }
    return `
      <div class="embedEditorHeader">
        <strong>Edit task</strong>
        <a class="openButton" href="#/tasks">Close</a>
      </div>
      ${renderTaskEditorForm(task)}
    `;
  }

  ensureAddCollectionDefault();
  return `
    <div class="embedEditorHeader">
      <strong>Add task</strong>
      <a class="openButton" href="#/tasks">Close</a>
    </div>
    ${renderTaskEditorForm(null, state.addTaskDraft || {})}
  `;
}

function renderEmbedCalendar() {
  if (!state.remoteCalendar.checked) {
    return renderEmbedStatus(uiText("calendar.loadingTitle", "캘린더를 불러오는 중..."), uiText("calendar.loadingDetail", "캘린더 데이터를 읽는 중입니다."));
  }
  if (state.remoteCalendar.error || !state.remoteCalendar.live) {
    const detail = state.remoteCalendar.error || uiText("calendar.adapterUnavailable", "캘린더 서버에 연결할 수 없습니다");
    return renderEmbedStatus(
      uiText("calendar.unavailableTitle", "캘린더를 불러올 수 없습니다"),
      detail,
      `<button class="openButton" type="button" data-embed-refresh>${uiText("common.retry", "다시 시도")}</button>`,
    );
  }

  const events = mockAdapter.getEvents().filter((item) => item.date === state.selectedDate);
  return `
    ${renderCalendarMonthPanel({ compact: true })}
    <section class="panel embedCalendarDetailPanel">
      <div class="panelHeader embedSectionHeader">
        <div>
          <p class="label">Selected day</p>
          <h2>${escapeHtml(state.selectedDate)}</h2>
        </div>
      </div>
      ${renderTimeline(events, uiText("common.noItems", "No items"), { readOnly: true })}
    </section>
  `;
}

function renderEmbedTasks() {
  if (!state.remoteCalendar.checked) {
    return renderEmbedStatus(uiText("tasks.loadingTitle", "할 일을 불러오는 중..."), uiText("tasks.loadingDetail", "할 일 데이터를 읽는 중입니다."));
  }
  if (state.remoteCalendar.error || !state.remoteCalendar.live) {
    const detail = state.remoteCalendar.error || uiText("calendar.adapterUnavailable", "캘린더 서버에 연결할 수 없습니다");
    return renderEmbedStatus(
      uiText("tasks.unavailableTitle", "할 일을 불러올 수 없습니다"),
      detail,
      `<button class="openButton" type="button" data-embed-refresh>${uiText("common.retry", "다시 시도")}</button>`,
    );
  }
  const tasks = mockAdapter.getTasks().filter((task) => taskMatchesMode(task, state.taskMode));
  return `${renderTaskFilters()}${renderTaskListPanel(tasks)}`;
}

function renderCalendarTasksSuppliesEmbed() {
  const route = getRoute();
  if (route === "add-task" || route === "edit-task") return renderEmbedTaskEditor(route);
  const calendarActive = state.embedView === "calendar";
  const tasksActive = state.embedView === "tasks";
  return `
    <div class="embedToolbar">
      <div class="embedSwitcher" role="tablist" aria-label="Retired embed view">
        <button type="button" role="tab" data-embed-view="calendar" aria-selected="${calendarActive}" class="${calendarActive ? "isActive" : ""}">Calendar</button>
        <button type="button" role="tab" data-embed-view="tasks" aria-selected="${tasksActive}" class="${tasksActive ? "isActive" : ""}">Tasks</button>
        <button type="button" role="tab" data-embed-view="supplies" aria-selected="${state.embedView === "supplies"}" class="${state.embedView === "supplies" ? "isActive" : ""}">Supplies</button>
      </div>
      <button class="openButton embedRefreshButton" type="button" data-embed-refresh>Refresh</button>
    </div>
    ${calendarActive ? renderEmbedCalendar() : tasksActive ? renderEmbedTasks() : renderSupplies({ compact: true })}
  `;
}

function renderDocuments() {
  const rows = state.documents.items
    .map((item) => {
      const submitted = item.status === "submitted";
      return `
        <div class="documentQueueRow">
          <div class="documentQueueMain">
            <strong>${escapeHtml(item.filename || "document.pdf")}</strong>
            <div class="documentQueueMeta">
              <span class="documentSourcePill">${escapeHtml(item.source || "upload")}</span>
              <span>${escapeHtml(formatDocumentBytes(item.sizeBytes))}</span>
              <span>${escapeHtml(formatDocumentDate(item.createdAt))}</span>
              ${submitted ? `<span class="documentSubmittedPill">Sent to Paperless</span>` : ""}
            </div>
          </div>
          <div class="documentQueueActions">
            <a class="openButton" href="${escapeHtml(item.contentUrl)}" target="_blank" rel="noopener">View</a>
            ${
              submitted
                ? `<span class="openButton isDisabled" aria-disabled="true">Sent</span>`
                : `<button class="primaryButton" type="button" data-document-paperless="${escapeHtml(item.id)}">Paperless</button>`
            }
            <button class="dangerButton" type="button" data-document-delete="${escapeHtml(item.id)}">Delete</button>
          </div>
        </div>
      `;
    })
    .join("");
  return `
    <section class="panel documentInbox">
      <div class="panelHeader">
        <div>
          <p class="label">Brain</p>
          <h2>Document Inbox</h2>
        </div>
        <button class="openButton" type="button" data-documents-refresh>Refresh</button>
      </div>
      <form class="documentUploadForm" data-document-upload>
        <label>
          <span>PDF</span>
          <input name="document" type="file" accept="application/pdf,.pdf" required />
        </label>
        <button class="openButton" type="submit">Upload</button>
      </form>
      <div class="panelBody">
        <p class="documentQueueNote">HWP conversions and Stirling results wait here until you view, archive, or delete them. Unsent files expire after 48 hours.</p>
        ${state.documents.loading && !state.documents.checked ? `<p class="taskMeta">Loading documents...</p>` : ""}
        ${
          state.documents.error
            ? `<div class="documentQueueError"><p>${escapeHtml(state.documents.error)}</p><button class="openButton" type="button" data-documents-refresh>${uiText("common.retry", "다시 시도")}</button></div>`
            : ""
        }
        ${!state.documents.error && state.documents.checked && !rows ? `<p class="taskMeta">No temporary PDFs.</p>` : ""}
        ${rows ? `<div class="documentQueueList">${rows}</div>` : ""}
      </div>
    </section>
  `;
}

function renderSupplyRow(item) {
  const done = state.supplies.mode === "done";
  return `
    <li class="supplyRow ${done ? "isDone" : ""}">
      <button class="checkButton supplyCheck" type="button" data-supply-${done ? "active" : "done"}="${escapeHtml(item.id)}" aria-label="${done ? "Move back to active" : "Mark done"}"></button>
      <div class="supplyRowMain">
        <strong>${escapeHtml(item.title || "Untitled supply")}</strong>
        <span>${escapeHtml(done ? item.done_at_display || item.done_date_key || "Done" : item.created_at || "")}</span>
      </div>
      ${
        done
          ? `<button class="taskIconButton" type="button" data-supply-delete="${escapeHtml(item.id)}" aria-label="Delete supply" title="Delete supply">×</button>`
          : ""
      }
    </li>
  `;
}

function createId(prefix = "id") {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function cloneValue(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function defaultRounyItem() {
  const slot = defaultRounySlot();
  return {
    id: createId("rouny-item"),
    title: "",
    dayOfWeek: slot.dayOfWeek,
    startTime: slot.startTime,
    endTime: slot.endTime,
    slots: [slot],
    memo: "",
    color: DEFAULT_ROUNY_COLOR,
  };
}

function defaultRounySlot() {
  return {
    id: createId("rouny-slot"),
    dayOfWeek: "1",
    startTime: "09:00",
    endTime: "09:50",
  };
}

function defaultRounyTemplate(name = uiText("rouny.newTemplate", "New template")) {
  const now = new Date().toISOString();
  return {
    id: createId("rouny-template"),
    name,
    items: [defaultRounyItem()],
    createdAt: now,
    updatedAt: now,
  };
}

function normalizeRounyItem(item) {
  if (!item || typeof item !== "object") return null;
  const slots = Array.isArray(item.slots) ? item.slots.map(normalizeRounySlot).filter(Boolean) : [];
  const fallbackSlot = normalizeRounySlot({
    dayOfWeek: item.dayOfWeek,
    startTime: item.startTime,
    endTime: item.endTime,
  });
  const normalizedSlots = slots.length ? slots : [fallbackSlot];
  const firstSlot = normalizedSlots[0] || defaultRounySlot();
  return {
    id: String(item.id || createId("rouny-item")),
    title: String(item.title || ""),
    dayOfWeek: firstSlot.dayOfWeek,
    startTime: firstSlot.startTime,
    endTime: firstSlot.endTime,
    slots: normalizedSlots,
    memo: String(item.memo || ""),
    color: normalizeRounyColor(item.color),
  };
}

function normalizeRounySlot(slot) {
  if (!slot || typeof slot !== "object") return defaultRounySlot();
  return {
    id: String(slot.id || createId("rouny-slot")),
    dayOfWeek: rounyDays.some((day) => day.value === String(slot.dayOfWeek)) ? String(slot.dayOfWeek) : "1",
    startTime: snapRounyTimeValue(slot.startTime, "09:00"),
    endTime: snapRounyTimeValue(slot.endTime, "09:50"),
  };
}

function normalizeRounyColor(color) {
  const value = String(color || "").trim().toLowerCase();
  if (rounyColorMap[value]) return rounyColorMap[value];
  if (/^#[0-9a-f]{6}$/.test(value)) return value;
  return DEFAULT_ROUNY_COLOR;
}

function normalizeRounyTemplate(template) {
  if (!template || typeof template !== "object") return null;
  const now = new Date().toISOString();
  const items = Array.isArray(template.items) ? template.items.map(normalizeRounyItem).filter(Boolean) : [];
  return {
    id: String(template.id || createId("rouny-template")),
    name: String(template.name || uiText("rouny.untitledTemplate", "Untitled template")).trim() || uiText("rouny.untitledTemplate", "Untitled template"),
    items: items.length ? items : [defaultRounyItem()],
    createdAt: String(template.createdAt || now),
    updatedAt: String(template.updatedAt || template.createdAt || now),
  };
}

function readLocalRounyDocument() {
  try {
    const raw = window.localStorage.getItem(ROUNY_TEMPLATE_STORAGE_KEY);
    const parsed = JSON.parse(raw || "[]");
    const templates = Array.isArray(parsed) ? parsed.map(normalizeRounyTemplate).filter(Boolean) : [];
    const revisionValue = window.localStorage.getItem(ROUNY_SYNC_REVISION_KEY);
    const revision = revisionValue !== null && /^\d+$/.test(revisionValue) ? Number(revisionValue) : null;
    return {
      exists: raw !== null && templates.length > 0,
      templates,
      revision,
      dirty: window.localStorage.getItem(ROUNY_SYNC_DIRTY_KEY) === "true",
    };
  } catch {
    return { exists: false, templates: [], revision: null, dirty: false };
  }
}

function persistRounyTemplates(templates, { revision, dirty } = {}) {
  window.localStorage.setItem(ROUNY_TEMPLATE_STORAGE_KEY, JSON.stringify(templates));
  state.rouny.hasPersistedLocal = templates.length > 0;
  if (revision !== undefined) {
    state.rouny.localRevision = revision;
    window.localStorage.setItem(ROUNY_SYNC_REVISION_KEY, String(revision));
  }
  if (dirty !== undefined) {
    state.rouny.localDirty = dirty;
    window.localStorage.setItem(ROUNY_SYNC_DIRTY_KEY, String(dirty));
  }
}

function rounyTemplatesSignature(templates) {
  return JSON.stringify((templates || []).map(normalizeRounyTemplate).filter(Boolean));
}

function applyRemoteRounyDocument(document) {
  const templates = Array.isArray(document?.templates)
    ? document.templates.map(normalizeRounyTemplate).filter(Boolean)
    : [];
  const revision = Math.max(0, Number(document?.revision) || 0);
  state.rouny.revision = revision;
  state.rouny.localRevision = revision;
  state.rouny.localDirty = false;
  state.rouny.remoteDocument = null;
  if (templates.length) {
    state.rouny.templates = templates;
    if (!templates.some((template) => template.id === state.rouny.selectedTemplateId)) {
      state.rouny.selectedTemplateId = templates[0].id;
    }
    const selected = templates.find((template) => template.id === state.rouny.selectedTemplateId) || templates[0];
    state.rouny.draft = cloneValue(selected);
    window.localStorage.setItem(ROUNY_SELECTED_STORAGE_KEY, selected.id);
    persistRounyTemplates(templates, { revision, dirty: false });
  } else {
    window.localStorage.setItem(ROUNY_SYNC_REVISION_KEY, String(revision));
    window.localStorage.setItem(ROUNY_SYNC_DIRTY_KEY, "false");
  }
}

function updateRounySyncStatus() {
  const status = document.querySelector("[data-rouny-sync-status]");
  if (status) status.outerHTML = renderRounySyncStatus();
}

async function loadRemoteRounyTemplates({ force = false } = {}) {
  if (portalProfile() !== "family") return null;
  if (rounyRemoteLoadPromise && !force) return rounyRemoteLoadPromise;
  state.rouny.remoteLoading = true;
  state.rouny.syncState = "loading";
  state.rouny.syncError = "";
  updateRounySyncStatus();

  rounyRemoteLoadPromise = (async () => {
    try {
      const response = await fetch("/api/rouny/templates", { headers: { Accept: "application/json" } });
      const document = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(document.error || `HTTP ${response.status}`);

      const serverTemplates = Array.isArray(document.templates)
        ? document.templates.map(normalizeRounyTemplate).filter(Boolean)
        : [];
      const serverRevision = Math.max(0, Number(document.revision) || 0);
      const localSignature = rounyTemplatesSignature(state.rouny.templates);
      const serverSignature = rounyTemplatesSignature(serverTemplates);
      state.rouny.remoteChecked = true;
      state.rouny.remoteLoading = false;
      state.rouny.remoteLive = true;
      state.rouny.revision = serverRevision;
      state.rouny.syncError = "";

      if (!serverTemplates.length) {
        if (state.rouny.hasPersistedLocal) {
          state.rouny.syncState = "saving";
          queueRounyRemoteSave();
        } else {
          state.rouny.localRevision = serverRevision;
          state.rouny.localDirty = false;
          state.rouny.syncState = "connected";
          window.localStorage.setItem(ROUNY_SYNC_REVISION_KEY, String(serverRevision));
          window.localStorage.setItem(ROUNY_SYNC_DIRTY_KEY, "false");
        }
      } else if (!state.rouny.hasPersistedLocal || localSignature === serverSignature) {
        applyRemoteRounyDocument(document);
        state.rouny.syncState = "synced";
      } else if (state.rouny.localDirty && state.rouny.localRevision === serverRevision) {
        state.rouny.syncState = "saving";
        queueRounyRemoteSave();
      } else if (!state.rouny.localDirty && state.rouny.localRevision !== null) {
        applyRemoteRounyDocument(document);
        state.rouny.syncState = "synced";
      } else {
        state.rouny.remoteDocument = { ...document, templates: serverTemplates };
        state.rouny.syncState = "conflict";
      }
    } catch (error) {
      state.rouny.remoteChecked = true;
      state.rouny.remoteLoading = false;
      state.rouny.remoteLive = false;
      state.rouny.syncState = "offline";
      state.rouny.syncError = error.message || uiText("rouny.unavailable", "로운이 기록을 불러올 수 없습니다");
    }
    if (getRoute() === "rouny" || (portalProfile() === "family" && getRoute() === "today")) render();
    return state.rouny.remoteLive;
  })().finally(() => {
    rounyRemoteLoadPromise = null;
  });
  return rounyRemoteLoadPromise;
}

function queueRounyRemoteSave() {
  if (portalProfile() !== "family" || state.rouny.syncState === "conflict") return;
  rounyRemoteSavePending = true;
  if (rounyRemoteSavePromise) return;

  rounyRemoteSavePromise = (async () => {
    if (!state.rouny.remoteChecked) await loadRemoteRounyTemplates();
    while (rounyRemoteSavePending && state.rouny.remoteLive && state.rouny.syncState !== "conflict") {
      rounyRemoteSavePending = false;
      const templates = cloneValue(state.rouny.templates);
      const signature = rounyTemplatesSignature(templates);
      state.rouny.syncState = "saving";
      state.rouny.syncError = "";
      updateRounySyncStatus();
      try {
        const response = await fetch("/api/rouny/templates", {
          method: "PUT",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({ baseRevision: state.rouny.revision, templates }),
        });
        const document = await response.json().catch(() => ({}));
        if (response.status === 409) {
          state.rouny.remoteDocument = document.document || null;
          state.rouny.syncState = "conflict";
          state.rouny.syncError = document.error || "rouny_revision_conflict";
          break;
        }
        if (!response.ok) throw new Error(document.error || `HTTP ${response.status}`);
        state.rouny.revision = Math.max(0, Number(document.revision) || 0);
        const changedAgain = signature !== rounyTemplatesSignature(state.rouny.templates);
        persistRounyTemplates(state.rouny.templates, { revision: state.rouny.revision, dirty: changedAgain });
        state.rouny.syncState = changedAgain ? "saving" : "synced";
        if (changedAgain) rounyRemoteSavePending = true;
      } catch (error) {
        state.rouny.remoteLive = false;
        state.rouny.syncState = "offline";
        state.rouny.syncError = error.message || uiText("rouny.unavailable", "로운이 기록을 불러올 수 없습니다");
        break;
      }
      updateRounySyncStatus();
    }
  })().finally(() => {
    rounyRemoteSavePromise = null;
    updateRounySyncStatus();
  });
}

function saveRounyTemplates(templates) {
  const normalized = templates.map(normalizeRounyTemplate).filter(Boolean);
  state.rouny.templates = normalized;
  persistRounyTemplates(normalized, { dirty: true });
  if (state.rouny.selectedTemplateId) window.localStorage.setItem(ROUNY_SELECTED_STORAGE_KEY, state.rouny.selectedTemplateId);
  queueRounyRemoteSave();
}

function ensureRounyState() {
  if (!state.rouny.checked) {
    const local = readLocalRounyDocument();
    state.rouny.templates = local.templates.length
      ? local.templates
      : [defaultRounyTemplate(uiText("rouny.basic", "Basic"))];
    state.rouny.hasPersistedLocal = local.exists;
    state.rouny.localRevision = local.revision;
    state.rouny.localDirty = local.dirty;
    state.rouny.selectedTemplateId = window.localStorage.getItem(ROUNY_SELECTED_STORAGE_KEY) || state.rouny.templates[0]?.id || "";
    state.rouny.includeSaturday = window.localStorage.getItem(ROUNY_INCLUDE_SATURDAY_KEY) === "true";
    if (!state.rouny.templates.some((template) => template.id === state.rouny.selectedTemplateId)) {
      state.rouny.selectedTemplateId = state.rouny.templates[0]?.id || "";
    }
    state.rouny.checked = true;
    window.setTimeout(() => loadRemoteRounyTemplates(), 0);
  }
  if (!state.rouny.draft) {
    const selected = state.rouny.templates.find((template) => template.id === state.rouny.selectedTemplateId) || state.rouny.templates[0];
    state.rouny.draft = cloneValue(selected || defaultRounyTemplate(uiText("rouny.basic", "Basic")));
    state.rouny.selectedTemplateId = state.rouny.draft.id;
  }
}

function collectRounyDraft() {
  const form = document.querySelector("[data-rouny-editor]");
  if (!form || !state.rouny.draft) return state.rouny.draft;
  state.rouny.draft = normalizeRounyTemplate({
    ...state.rouny.draft,
    name: form.querySelector('[name="templateName"]')?.value || state.rouny.draft.name,
  });
  return state.rouny.draft;
}

function rounyDraftSignature(draft = state.rouny.draft) {
  return JSON.stringify(draft || null);
}

function savedRounyDraft() {
  const draftId = state.rouny.draft?.id || state.rouny.selectedTemplateId;
  return state.rouny.templates.find((template) => template.id === draftId) || null;
}

function rounyDraftDiffersFromSaved() {
  if (!state.rouny.draft) return false;
  const saved = savedRounyDraft();
  return saved ? rounyDraftSignature(saved) !== rounyDraftSignature(state.rouny.draft) : true;
}

function canUndoRounyDraft() {
  return Boolean(state.rouny.undoStack?.length) || rounyDraftDiffersFromSaved();
}

function pushRounyUndo() {
  const draft = collectRounyDraft();
  if (!draft) return;
  const snapshot = cloneValue(draft);
  const stack = state.rouny.undoStack || [];
  if (rounyDraftSignature(stack[stack.length - 1]) === rounyDraftSignature(snapshot)) return;
  state.rouny.undoStack = [...stack.slice(-24), snapshot];
}

function undoRounyDraft() {
  const stack = state.rouny.undoStack || [];
  const previous = stack[stack.length - 1] || savedRounyDraft();
  if (!previous || (!stack.length && !rounyDraftDiffersFromSaved())) return false;
  state.rouny.undoStack = stack.length ? stack.slice(0, -1) : [];
  state.rouny.draft = cloneValue(previous);
  state.rouny.selectedTemplateId = state.rouny.draft.id;
  state.rouny.editingItemId = "";
  state.rouny.editingItemDraft = null;
  return true;
}

function resetRounyDraftToSaved() {
  const saved = savedRounyDraft();
  if (!saved) return false;
  if (!window.confirm(uiText("dialog.resetTemplate", "Reset this timetable to the last saved version?"))) return false;
  state.rouny.draft = cloneValue(saved);
  state.rouny.selectedTemplateId = saved.id;
  state.rouny.undoStack = [];
  state.rouny.editingItemId = "";
  state.rouny.editingItemDraft = null;
  return true;
}

function openRounyClassEditor(itemId) {
  const draft = collectRounyDraft();
  if (!draft?.items?.some((item) => item.id === itemId)) return false;
  state.rouny.editingItemId = itemId;
  state.rouny.editingItemDraft = null;
  render();
  return true;
}

function selectRounyTemplate(templateId) {
  const template = state.rouny.templates.find((item) => item.id === templateId);
  if (!template) return;
  state.rouny.selectedTemplateId = template.id;
  state.rouny.draft = cloneValue(template);
  state.rouny.undoStack = [];
  state.rouny.page = "detail";
  state.rouny.editingItemId = "";
  state.rouny.editingItemDraft = null;
  window.localStorage.setItem(ROUNY_SELECTED_STORAGE_KEY, template.id);
}

function saveRounyDraft({ asCopy = false } = {}) {
  const draft = collectRounyDraft();
  if (!draft?.name.trim()) {
    window.alert(uiText("dialog.templateNameRequired", "Template name is required."));
    return false;
  }
  const validation = validateRounyTemplateTimes(draft);
  if (validation.invalidCount) {
    window.alert(uiText("rouny.fixInvalidBeforeSave", "Fix invalid time ranges before saving."));
    return false;
  }
  if (
    validation.conflictCount
    && !window.confirm(
      uiText("rouny.confirmOverlapSave", "{count} time conflict(s) found. Save anyway?", {
        count: validation.conflictCount,
      }),
    )
  ) {
    return false;
  }
  if (
    !window.confirm(
      asCopy
        ? uiText("dialog.saveTemplateAs", "Save this timetable as a new template?")
        : uiText("dialog.saveTemplate", "Save this timetable?"),
    )
  ) {
    return false;
  }
  const now = new Date().toISOString();
  const originalTemplate = state.rouny.templates.find((template) => template.id === draft.id);
  const saveAsName = asCopy && originalTemplate?.name === draft.name ? `${draft.name} copy` : draft.name;
  const nextDraft = normalizeRounyTemplate({
    ...draft,
    id: asCopy ? createId("rouny-template") : draft.id,
    name: saveAsName,
    createdAt: asCopy ? now : draft.createdAt,
    updatedAt: now,
  });
  const exists = !asCopy && state.rouny.templates.some((template) => template.id === nextDraft.id);
  const templates = exists
    ? state.rouny.templates.map((template) => (template.id === nextDraft.id ? nextDraft : template))
    : [...state.rouny.templates, nextDraft];
  state.rouny.selectedTemplateId = nextDraft.id;
  state.rouny.draft = cloneValue(nextDraft);
  state.rouny.undoStack = [];
  saveRounyTemplates(templates);
  return true;
}

function deleteRounyTemplate(templateId) {
  if (state.rouny.templates.length <= 1) {
    window.alert(uiText("dialog.keepOneTemplate", "Keep at least one template."));
    return;
  }
  if (!window.confirm(uiText("dialog.deleteTemplate", "Delete this template?"))) return;
  const templates = state.rouny.templates.filter((template) => template.id !== templateId);
  state.rouny.selectedTemplateId = templates[0]?.id || "";
  state.rouny.draft = cloneValue(templates[0] || defaultRounyTemplate(uiText("rouny.basic", "Basic")));
  state.rouny.page = "list";
  state.rouny.editingItemId = "";
  state.rouny.editingItemDraft = null;
  saveRounyTemplates(templates);
}

function reorderRounyTemplates(sourceId, targetId) {
  if (!sourceId || !targetId || sourceId === targetId) return;
  const templates = [...state.rouny.templates];
  const from = templates.findIndex((template) => template.id === sourceId);
  const to = templates.findIndex((template) => template.id === targetId);
  if (from < 0 || to < 0) return;
  const [moved] = templates.splice(from, 1);
  templates.splice(to, 0, moved);
  saveRounyTemplates(templates);
}

function rounyMinutes(timeValue) {
  return parseRounyMinutes(timeValue) ?? 0;
}

function parseRounyMinutes(timeValue) {
  const match = String(timeValue || "").match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return null;
  return hour * 60 + minute;
}

function rounySlotValidationKey(itemId, slotId) {
  return `${itemId}:${slotId}`;
}

function validateRounyTemplateTimes(template) {
  const invalidKeys = new Set();
  const conflictKinds = new Map();
  const slotsByDay = new Map();
  let conflictCount = 0;

  (template?.items || []).forEach((item) => {
    (item.slots || []).forEach((slot) => {
      const key = rounySlotValidationKey(item.id, slot.id);
      const start = parseRounyMinutes(slot.startTime);
      const end = parseRounyMinutes(slot.endTime);
      if (start === null || end === null || end <= start) {
        invalidKeys.add(key);
        return;
      }
      const daySlots = slotsByDay.get(slot.dayOfWeek) || [];
      daySlots.push({ itemId: item.id, slotId: slot.id, key, start, end });
      slotsByDay.set(slot.dayOfWeek, daySlots);
    });
  });

  const addConflict = (record, kind) => {
    const kinds = conflictKinds.get(record.key) || new Set();
    kinds.add(kind);
    conflictKinds.set(record.key, kinds);
  };

  slotsByDay.forEach((daySlots) => {
    daySlots.sort((a, b) => a.start - b.start || a.end - b.end);
    daySlots.forEach((record, index) => {
      for (let nextIndex = index + 1; nextIndex < daySlots.length; nextIndex += 1) {
        const next = daySlots[nextIndex];
        if (next.start >= record.end) break;
        if (record.start >= next.end) continue;
        const kind = record.itemId === next.itemId ? "same" : "other";
        addConflict(record, kind);
        addConflict(next, kind);
        conflictCount += 1;
      }
    });
  });

  return {
    invalidKeys,
    conflictKinds,
    invalidCount: invalidKeys.size,
    conflictCount,
  };
}

function rounyTemplateWithItem(template, item) {
  const items = template?.items || [];
  const exists = items.some((candidate) => candidate.id === item.id);
  return {
    ...template,
    items: exists
      ? items.map((candidate) => (candidate.id === item.id ? item : candidate))
      : [...items, item],
  };
}

function rounySlotIssueText(validation, itemId, slotId) {
  const key = rounySlotValidationKey(itemId, slotId);
  if (validation.invalidKeys.has(key)) {
    return uiText("rouny.invalidTime", "End time must be later than start time.");
  }
  const kinds = validation.conflictKinds.get(key);
  if (kinds?.has("same") && kinds.has("other")) {
    return uiText("rouny.sameAndOtherOverlap", "Overlaps this class and another class.");
  }
  if (kinds?.has("same")) return uiText("rouny.sameClassOverlap", "Overlaps another time in this class.");
  if (kinds?.has("other")) return uiText("rouny.otherClassOverlap", "Overlaps another class.");
  return "";
}

function renderRounyValidationSummary(validation) {
  if (!validation.invalidCount && !validation.conflictCount) return "";
  const messages = [];
  if (validation.invalidCount) {
    messages.push(uiText("rouny.invalidSummary", "{count} invalid time range(s)", { count: validation.invalidCount }));
  }
  if (validation.conflictCount) {
    messages.push(uiText("rouny.overlapSummary", "{count} time conflict(s)", { count: validation.conflictCount }));
  }
  return `
    <div class="rounyValidationSummary ${validation.invalidCount ? "hasInvalidTime" : "hasConflict"}" role="status">
      <strong>!</strong>
      <span>${escapeHtml(messages.join(" · "))}</span>
    </div>
  `;
}

function sortRounyItems(items) {
  return [...items].sort((a, b) => Number(a.dayOfWeek) - Number(b.dayOfWeek) || rounyMinutes(a.startTime) - rounyMinutes(b.startTime));
}

function updateRounyDraftItem(itemId, patch) {
  ensureRounyState();
  state.rouny.draft.items = state.rouny.draft.items.map((item) =>
    item.id === itemId ? normalizeRounyItem({ ...item, ...patch }) : item,
  );
}

function moveRounyDraftSlot(itemId, slotId, dayOfWeek, startMinutes) {
  const moving = state.rouny.draft?.items.find((item) => item.id === itemId);
  if (!moving || !rounyDays.some((day) => day.value === String(dayOfWeek))) return;
  const movingSlot = moving.slots.find((slot) => slot.id === slotId);
  if (!movingSlot) return;
  const duration = Math.max(
    ROUNY_TIMELINE_SLOT_MINUTES,
    rounyMinutes(movingSlot.endTime) - rounyMinutes(movingSlot.startTime),
  );
  updateRounyDraftItem(itemId, {
    slots: moving.slots.map((slot) =>
      slot.id === slotId
        ? normalizeRounySlot({
            ...slot,
            dayOfWeek: String(dayOfWeek),
            startTime: rounyTimeFromMinutes(startMinutes),
            endTime: rounyTimeFromMinutes(startMinutes + duration),
          })
        : slot,
    ),
  });
}

function rounyTimeFromMinutes(totalMinutes) {
  const bounded = Math.max(0, Math.min(24 * 60 - 1, Number(totalMinutes) || 0));
  const hour = Math.floor(bounded / 60);
  const minute = bounded % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function snapRounyTimeValue(timeValue, fallback = "09:00") {
  const minutes = parseRounyMinutes(timeValue);
  if (minutes === null) return fallback;
  const snapped = Math.round(minutes / ROUNY_TIMELINE_SLOT_MINUTES) * ROUNY_TIMELINE_SLOT_MINUTES;
  return rounyTimeFromMinutes(Math.min(23 * 60 + 50, Math.max(0, snapped)));
}

function snapRounyTimeInput(input) {
  if (
    !(input instanceof HTMLInputElement || input instanceof HTMLSelectElement)
    || !["slotStart", "slotEnd"].includes(input.name)
  ) return;
  if (!input.value) return;
  const snapped = snapRounyTimeValue(input.value, input.name === "slotEnd" ? "09:50" : "09:00");
  if (input.value !== snapped) input.value = snapped;
}

function snapRounyClassFormTimes(form) {
  form.querySelectorAll('[name="slotStart"], [name="slotEnd"]').forEach(snapRounyTimeInput);
}

function renderRounyTimeOptions(selectedValue) {
  const selected = snapRounyTimeValue(selectedValue);
  return Array.from({ length: (24 * 60) / ROUNY_TIMELINE_SLOT_MINUTES }, (_, index) => {
    const value = rounyTimeFromMinutes(index * ROUNY_TIMELINE_SLOT_MINUTES);
    return `<option value="${value}" ${value === selected ? "selected" : ""}>${value}</option>`;
  }).join("");
}

function rounyTimeLabel(item) {
  return `${String(item.startTime || "").slice(0, 5)}-${String(item.endTime || "").slice(0, 5)}`;
}

function rounyColorClass(color) {
  return rounyColors.includes(color) ? `is${color[0].toUpperCase()}${color.slice(1)}` : "isPink";
}

function rounyColorStyle(color) {
  return `style="background:${escapeHtml(normalizeRounyColor(color))}"`;
}

function rounyGridDays() {
  return rounyDays.filter((day) => Number(day.value) >= 1 && Number(day.value) <= (state.rouny.includeSaturday ? 6 : 5));
}

function rounyTimelineRange(template) {
  const slots = template.items.flatMap((item) => item.slots || []);
  const startMinutes = slots.map((slot) => rounyMinutes(slot.startTime));
  const endMinutes = slots.map((slot) => rounyMinutes(slot.endTime));
  const earliest = Math.min(ROUNY_TIMELINE_DEFAULT_START_HOUR * 60, ...startMinutes);
  const latest = Math.max(ROUNY_TIMELINE_DEFAULT_END_HOUR * 60, ...endMinutes);
  const startHour = Math.max(0, Math.floor(earliest / 60));
  const endHour = Math.min(24, Math.max(startHour + 1, Math.ceil(latest / 60)));
  return {
    startHour,
    endHour,
    startMinutes: startHour * 60,
    endMinutes: endHour * 60,
    bodyHeight: (endHour - startHour) * ROUNY_TIMELINE_HOUR_HEIGHT,
  };
}

function rounyTimelineBlockStyle(item, slot, range) {
  const start = Math.max(range.startMinutes, Math.min(range.endMinutes - ROUNY_TIMELINE_SLOT_MINUTES, rounyMinutes(slot.startTime)));
  const duration = Math.max(
    ROUNY_TIMELINE_SLOT_MINUTES,
    rounyMinutes(slot.endTime) - rounyMinutes(slot.startTime),
  );
  const end = Math.min(range.endMinutes, start + duration);
  const top = ((start - range.startMinutes) / 60) * ROUNY_TIMELINE_HOUR_HEIGHT;
  const height = Math.max(20, ((end - start) / 60) * ROUNY_TIMELINE_HOUR_HEIGHT);
  return `style="background:${escapeHtml(normalizeRounyColor(item.color))};top:${top}px;height:${height}px"`;
}

function renderRounyGrid(template) {
  const validation = validateRounyTemplateTimes(template);
  const grouped = rounyDays.reduce((days, day) => ({ ...days, [day.value]: [] }), {});
  const visibleDays = rounyGridDays();
  const range = rounyTimelineRange(template);
  const hours = Array.from({ length: range.endHour - range.startHour + 1 }, (_, index) => range.startHour + index);
  template.items.forEach((item) => {
    item.slots.forEach((slot) => {
      grouped[slot.dayOfWeek]?.push({ item, slot });
    });
  });
  Object.keys(grouped).forEach((day) => {
    grouped[day].sort((a, b) => rounyMinutes(a.slot.startTime) - rounyMinutes(b.slot.startTime));
  });
  return `
    <section class="panel">
      <div class="panelHeader">
        <h2>${uiText("rouny.week", "Week")}</h2>
        <label class="rounyGridToggle">
          <input type="checkbox" data-rouny-saturday ${state.rouny.includeSaturday ? "checked" : ""} />
          <span>${uiText("rouny.saturday", "Sat")}</span>
        </label>
      </div>
      ${renderRounyValidationSummary(validation)}
      <div
        class="rounyTimelineGrid ${state.rouny.includeSaturday ? "hasSaturday" : "isWeekdays"}"
        data-rouny-timeline
        data-start-minutes="${range.startMinutes}"
        data-end-minutes="${range.endMinutes}"
        aria-label="${uiText("rouny.weeklyAria", "Rouny weekly timetable")}"
        style="--rouny-timeline-height:${range.bodyHeight}px"
      >
        <span class="rounyTimelineCorner" aria-hidden="true"></span>
        ${visibleDays.map((day) => `<span class="rounyTimelineDayHeader">${escapeHtml(portalProfile() === "family" ? day.familyLabel : day.label)}</span>`).join("")}
        <div class="rounyTimelineTimeRail" aria-hidden="true">
          ${hours
            .slice(1, -1)
            .map(
              (hour) => `
                <span class="rounyTimelineHourLabel" style="top:${(hour - range.startHour) * ROUNY_TIMELINE_HOUR_HEIGHT}px">
                  ${String(hour).padStart(2, "0")}:00
                </span>
              `,
            )
            .join("")}
        </div>
        ${visibleDays
          .map(
            (day) => `
              <div class="rounyTimelineDayColumn" data-rouny-time-column data-rouny-day="${escapeHtml(day.value)}">
                ${hours
                  .slice(0, -1)
                  .map(
                    (hour) => `
                      <span class="rounyTimelineHour" style="top:${(hour - range.startHour) * ROUNY_TIMELINE_HOUR_HEIGHT}px" aria-hidden="true">
                        <i></i><i></i><i></i><i></i><i></i>
                      </span>
                    `,
                  )
                  .join("")}
                <span class="rounyTimelineDropMarker" data-rouny-drop-marker aria-hidden="true"></span>
                ${grouped[day.value]
                  .map(
                    ({ item, slot }) => {
                      const key = rounySlotValidationKey(item.id, slot.id);
                      const issue = rounySlotIssueText(validation, item.id, slot.id);
                      const validationClass = validation.invalidKeys.has(key)
                        ? "hasInvalidTime"
                        : validation.conflictKinds.has(key)
                          ? "hasTimeConflict"
                          : "";
                      return `
                      <div
                        class="rounyBlock ${validationClass}"
                        ${rounyTimelineBlockStyle(item, slot, range)}
                        role="button"
                        tabindex="0"
                        draggable="false"
                        data-rouny-grid-item="${escapeHtml(item.id)}"
                        data-rouny-slot-id="${escapeHtml(slot.id)}"
                        title="${escapeHtml(`${item.title || uiText("common.untitled", "Untitled")} ${rounyTimeLabel(slot)}${issue ? ` · ${issue}` : ""}`)}"
                      >
                        <strong>${escapeHtml(item.title || uiText("common.untitled", "Untitled"))}</strong>
                      </div>
                    `;
                    },
                  )
                  .join("")}
              </div>
            `,
          )
          .join("")}
      </div>
      <span class="rounyTimelineDragReadout" data-rouny-drag-readout hidden></span>
    </section>
  `;
}

function rounyDragTargetFromPoint(clientX, clientY) {
  if (!rounyPointerDrag) return null;
  const column = document
    .elementsFromPoint(clientX, clientY)
    .find((element) => element instanceof HTMLElement && element.matches("[data-rouny-time-column]"));
  if (!column) return null;
  const dayOfWeek = column.dataset.rounyDay || "";
  if (!rounyDays.some((day) => day.value === dayOfWeek)) return null;
  const timeline = column.closest("[data-rouny-timeline]");
  const startMinutes = Number(timeline?.dataset.startMinutes);
  const endMinutes = Number(timeline?.dataset.endMinutes);
  if (!Number.isFinite(startMinutes) || !Number.isFinite(endMinutes)) return null;
  const rect = column.getBoundingClientRect();
  const pointerMinutes = startMinutes + ((clientY - rect.top) / ROUNY_TIMELINE_HOUR_HEIGHT) * 60;
  const snappedMinutes = Math.floor(pointerMinutes / ROUNY_TIMELINE_SLOT_MINUTES) * ROUNY_TIMELINE_SLOT_MINUTES;
  const latestEnd = Math.min(endMinutes, 24 * 60 - 1);
  const latestStart = Math.max(startMinutes, latestEnd - rounyPointerDrag.duration);
  return {
    column,
    dayOfWeek,
    startMinutes: Math.max(startMinutes, Math.min(latestStart, snappedMinutes)),
    rangeStartMinutes: startMinutes,
  };
}

function updateRounyDragFeedback(target, clientX, clientY) {
  document.querySelectorAll("[data-rouny-time-column].isDropTarget").forEach((column) => column.classList.remove("isDropTarget"));
  document.querySelectorAll("[data-rouny-drop-marker].isVisible").forEach((marker) => marker.classList.remove("isVisible"));
  const readout = document.querySelector("[data-rouny-drag-readout]");
  if (!target || !rounyPointerDrag) {
    if (readout) readout.hidden = true;
    return;
  }
  target.column.classList.add("isDropTarget");
  const marker = target.column.querySelector("[data-rouny-drop-marker]");
  if (marker) {
    marker.style.top = `${((target.startMinutes - target.rangeStartMinutes) / 60) * ROUNY_TIMELINE_HOUR_HEIGHT}px`;
    marker.classList.add("isVisible");
  }
  if (readout) {
    const day = rounyDays.find((item) => item.value === target.dayOfWeek);
    const dayLabel = portalProfile() === "family" ? day?.familyLabel : day?.label;
    readout.textContent = `${dayLabel || ""} ${rounyTimeFromMinutes(target.startMinutes)}-${rounyTimeFromMinutes(target.startMinutes + rounyPointerDrag.duration)}`.trim();
    readout.style.left = `${clientX}px`;
    readout.style.top = `${Math.max(24, clientY - 72)}px`;
    readout.hidden = false;
  }
}

function clearRounyPointerDrag() {
  const drag = rounyPointerDrag;
  if (drag?.holdTimer) window.clearTimeout(drag.holdTimer);
  if (drag?.element?.hasPointerCapture?.(drag.pointerId)) drag.element.releasePointerCapture(drag.pointerId);
  drag?.element?.classList.remove("isDragging");
  document.body.classList.remove("isRounyDragging");
  updateRounyDragFeedback(null, 0, 0);
  rounyPointerDrag = null;
}

function renderRounySyncStatus() {
  const status = state.rouny.syncState;
  let label = uiText("rouny.syncLocal", "Saved on this device");
  let actions = "";
  if (status === "loading") label = uiText("rouny.syncLoading", "Loading saved timetables...");
  else if (status === "saving") label = uiText("rouny.syncSaving", "Saving...");
  else if (status === "connected") label = uiText("rouny.syncConnected", "Brain connected");
  else if (status === "synced") label = uiText("rouny.syncSaved", "Saved to Brain");
  else if (status === "offline") {
    label = uiText("rouny.syncOffline", "Offline; saved on this device");
    actions = `<button class="plainButton" type="button" data-rouny-sync-retry>${uiText("common.retry", "다시 시도")}</button>`;
  } else if (status === "conflict") {
    label = uiText("rouny.syncConflict", "Choose which timetable copy to keep");
    actions = `
      <button class="plainButton" type="button" data-rouny-use-server>${uiText("rouny.useServerCopy", "Use server")}</button>
      <button class="plainButton" type="button" data-rouny-use-local>${uiText("rouny.useDeviceCopy", "Use this device")}</button>
    `;
  }
  return `
    <div class="rounySyncStatus is-${escapeHtml(status)}" data-rouny-sync-status role="status">
      <span>${escapeHtml(label)}</span>
      <div>${actions}</div>
    </div>
  `;
}

function renderRouny() {
  ensureRounyState();
  if (state.rouny.page !== "detail") return renderRounyTemplateList();
  return renderRounyTemplateDetail();
}

function renderRounyTemplateList() {
  ensureRounyState();
  return `
    <section class="panel">
      <div class="panelHeader">
        <div>
          <p class="label">${uiText("rouny.label", "Rouny")}</p>
          <h2>${uiText("rouny.templates", "Templates")}</h2>
        </div>
        <button class="openButton" type="button" data-rouny-new>${uiText("rouny.newTemplate", "New")}</button>
      </div>
      <div class="panelBody">
        ${renderRounySyncStatus()}
        <div class="rounyTemplateList" aria-label="${uiText("rouny.savedTemplatesAria", "Saved Rouny templates")}">
          ${state.rouny.templates
            .map(
              (template) => `
                <div class="rounyTemplateRow ${template.id === state.rouny.selectedTemplateId ? "isActive" : ""}" draggable="true" data-rouny-template-id="${escapeHtml(template.id)}">
                  <button class="rounyDragHandle" type="button" aria-label="${uiText("rouny.dragTemplateAria", "Drag template")}">≡</button>
                  <button class="rounyTemplateButton" type="button" data-rouny-select="${escapeHtml(template.id)}">
                    <strong>${escapeHtml(template.name)}</strong>
                    <span>${uiText("rouny.classCount", `{count} class${template.items.length === 1 ? "" : "es"}`, { count: template.items.length })}</span>
                  </button>
                  <button class="plainButton" type="button" data-rouny-delete="${escapeHtml(template.id)}">${uiText("common.delete", "Delete")}</button>
                </div>
              `,
            )
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function renderRounyTemplateDetail() {
  const draft = state.rouny.draft;
  return `
    <form class="rounyEditor" data-rouny-editor>
      <section class="panel rounyTemplateHeaderPanel">
        <div class="rounyTemplateHeader">
          <button class="plainButton rounyBackButton" type="button" data-rouny-back>&lt;&lt; ${uiText("rouny.backToList", "Back to list")}</button>
          <div class="rounyTemplateNameRow">
            <h2>${escapeHtml(draft.name)}</h2>
            <button class="openButton" type="button" data-rouny-rename>${uiText("rouny.rename", "Rename")}</button>
          </div>
          ${renderRounySyncStatus()}
        </div>
      </section>
      ${renderRounyGrid(draft)}
      <section class="rounyActions">
        <button class="openButton" type="button" data-rouny-add-item>${uiText("rouny.addClass", "Add class")}</button>
        <button class="openButton" type="button" data-rouny-undo ${canUndoRounyDraft() ? "" : "disabled"}>${uiText("rouny.undo", "Undo")}</button>
        <button class="openButton" type="button" data-rouny-reset>${uiText("rouny.reset", "Reset")}</button>
        <button class="openButton" type="button" data-rouny-print>${uiText("rouny.print", "Print")}</button>
        <button class="primaryButton" type="button" data-rouny-save>${uiText("common.save", "Save")}</button>
        <button class="openButton" type="button" data-rouny-save-as>${uiText("rouny.saveAs", "Save as")}</button>
      </section>
    </form>
  `;
}

function currentRounyEditingItem() {
  const draft = state.rouny.draft;
  if (!draft || !state.rouny.editingItemId) return null;
  return draft.items.find((item) => item.id === state.rouny.editingItemId) || state.rouny.editingItemDraft;
}

function renderRounyOverlay() {
  const editingItem = currentRounyEditingItem();
  if (!editingItem) return "";
  return renderRounyClassLayer(editingItem, !state.rouny.draft.items.some((item) => item.id === editingItem.id));
}

function renderRounyClassLayer(item, isNew = false) {
  const validation = validateRounyTemplateTimes(rounyTemplateWithItem(state.rouny.draft, item));
  return `
    <div class="rounyLayerBackdrop" data-rouny-close-layer></div>
    <aside class="rounyLayer" aria-label="${isNew ? uiText("rouny.addClass", "Add class") : uiText("rouny.editClass", "Edit class")}">
      <div class="panelHeader">
        <div>
          <p class="label">${uiText("rouny.label", "Rouny")}</p>
          <h2>${isNew ? uiText("rouny.addClass", "Add class") : uiText("rouny.editClass", "Edit class")}</h2>
        </div>
        <button class="iconTextButton" type="button" data-rouny-close-layer aria-label="${uiText("common.close", "Close")}">×</button>
      </div>
      <form class="rounyLayerForm" data-rouny-class-form data-rouny-item-id="${escapeHtml(item.id)}">
        ${renderRounyItem(item, validation)}
        <div class="rounyActions">
          ${isNew ? "" : `<button class="plainButton" type="button" data-rouny-remove-item="${escapeHtml(item.id)}">${uiText("common.delete", "Delete")}</button>`}
          <button class="primaryButton" type="submit">${uiText("common.done", "Done")}</button>
        </div>
      </form>
    </aside>
  `;
}

function itemFromRounyClassForm(form) {
  const itemId = form.dataset.rounyItemId || createId("rouny-item");
  const slots = [...form.querySelectorAll("[data-rouny-slot-row]")]
    .map((row) =>
      normalizeRounySlot({
        id: row.dataset.rounySlotId || createId("rouny-slot"),
        dayOfWeek: row.querySelector('[name="slotDay"]')?.value || "1",
        startTime: row.querySelector('[name="slotStart"]')?.value || "09:00",
        endTime: row.querySelector('[name="slotEnd"]')?.value || "09:50",
      }),
    )
    .filter(Boolean);
  return normalizeRounyItem({
    id: itemId,
    title: form.querySelector('[name="title"]')?.value || "",
    slots: slots.length ? slots : [defaultRounySlot()],
    memo: form.querySelector('[name="memo"]')?.value || "",
    color: form.querySelector('[name="color"]')?.value || DEFAULT_ROUNY_COLOR,
  });
}

function upsertRounyDraftItem(item) {
  const exists = state.rouny.draft.items.some((draftItem) => draftItem.id === item.id);
  state.rouny.draft.items = exists
    ? state.rouny.draft.items.map((draftItem) => (draftItem.id === item.id ? item : draftItem))
    : [...state.rouny.draft.items, item];
}

function renderRounyItem(item, validation = validateRounyTemplateTimes(rounyTemplateWithItem(state.rouny.draft, item))) {
  return `
    <div class="rounyItem" data-rouny-item-id="${escapeHtml(item.id)}">
      <label class="rounyTitleField">
        <span>${uiText("rouny.classTitle", "Title")}</span>
        <input name="title" type="text" autocomplete="off" value="${escapeHtml(item.title)}" placeholder="${uiText("rouny.activity", "Activity")}" />
      </label>
      <div class="rounySlots">
        ${item.slots.map((slot) => renderRounySlot(slot, item.slots.length, item.id, validation)).join("")}
      </div>
      <button class="openButton" type="button" data-rouny-add-slot>+ ${uiText("rouny.addTime", "Add")}</button>
      <div class="rounyMetaGrid">
        <label>
          <span>${uiText("rouny.color", "Color")}</span>
          <input name="color" type="color" value="${escapeHtml(normalizeRounyColor(item.color))}" />
        </label>
      </div>
      <label class="rounyMemo">
        <span>${uiText("common.memo", "Memo")}</span>
        <input name="memo" type="text" autocomplete="off" value="${escapeHtml(item.memo)}" placeholder="${uiText("rouny.optional", "Optional")}" />
      </label>
    </div>
  `;
}

function renderRounySlot(slot, slotCount, itemId, validation) {
  const key = rounySlotValidationKey(itemId, slot.id);
  const issue = rounySlotIssueText(validation, itemId, slot.id);
  const validationClass = validation.invalidKeys.has(key)
    ? "hasInvalidTime"
    : validation.conflictKinds.has(key)
      ? "hasTimeConflict"
      : "";
  return `
    <div class="rounySlotRow ${validationClass}" data-rouny-slot-row data-rouny-slot-id="${escapeHtml(slot.id)}">
      <label>
        <span>${uiText("rouny.day", "Day")}</span>
        <select name="slotDay">
          ${rounyDays.map((day) => `<option value="${day.value}" ${slot.dayOfWeek === day.value ? "selected" : ""}>${portalProfile() === "family" ? day.familyLabel : day.label}</option>`).join("")}
        </select>
      </label>
      <label>
        <span>${uiText("rouny.start", "Start")}</span>
        <select name="slotStart">${renderRounyTimeOptions(slot.startTime)}</select>
      </label>
      <label>
        <span>${uiText("rouny.end", "End")}</span>
        <select name="slotEnd">${renderRounyTimeOptions(slot.endTime)}</select>
      </label>
      <button class="iconTextButton" type="button" data-rouny-remove-slot="${escapeHtml(slot.id)}" aria-label="${uiText("rouny.removeTimeAria", "Remove time")}" ${slotCount <= 1 ? "disabled" : ""}>×</button>
      <span class="rounySlotValidation" data-rouny-slot-validation ${issue ? "" : "hidden"}>${escapeHtml(issue)}</span>
    </div>
  `;
}

function updateRounyClassFormValidation(form) {
  const item = itemFromRounyClassForm(form);
  const validation = validateRounyTemplateTimes(rounyTemplateWithItem(state.rouny.draft, item));
  form.querySelectorAll("[data-rouny-slot-row]").forEach((row) => {
    const key = rounySlotValidationKey(item.id, row.dataset.rounySlotId);
    const invalid = validation.invalidKeys.has(key);
    const conflict = validation.conflictKinds.has(key);
    row.classList.toggle("hasInvalidTime", invalid);
    row.classList.toggle("hasTimeConflict", !invalid && conflict);
    row.querySelectorAll('input[type="time"]').forEach((input) => {
      if (invalid) input.setAttribute("aria-invalid", "true");
      else input.removeAttribute("aria-invalid");
    });
    const message = row.querySelector("[data-rouny-slot-validation]");
    if (message) {
      message.textContent = rounySlotIssueText(validation, item.id, row.dataset.rounySlotId);
      message.hidden = !message.textContent;
    }
  });
  return { item, validation };
}

function ledgerCategoryOptions(selected) {
  const categories = state.ledger.categories.length
    ? state.ledger.categories
    : ["현금 지출", "현금 수입", "계좌 지출", "계좌 수입", "현금 인출", "계좌 입금", "상품권 구입 - 현금", "상품권 구입 - 계좌", "상품권 사용"];
  return categories
    .map((category) => `<option value="${escapeHtml(category)}" ${category === selected ? "selected" : ""}>${escapeHtml(category)}</option>`)
    .join("");
}

function renderLedgerBalances() {
  const balances = state.ledger.balances;
  return `
    <div class="ledgerBalances" aria-label="${escapeHtml(uiText("ledger.currentBalances", "Current balances"))}">
      <div><span>${escapeHtml(uiText("ledger.account", "Account"))}</span><strong>${formatLedgerMoney(balances.account)}</strong></div>
      <div><span>${escapeHtml(uiText("ledger.cash", "Cash"))}</span><strong>${formatLedgerMoney(balances.cash)}</strong></div>
      <div><span>${escapeHtml(uiText("ledger.gift", "Gift certificates"))}</span><strong>${formatLedgerMoney(balances.gift)}</strong></div>
    </div>
  `;
}

function ledgerEntriesForView() {
  let entries = state.ledger.entries;
  if (state.ledger.view === "expense") {
    entries = entries.filter((entry) => LEDGER_EXPENSE_CATEGORIES.has(entry.category));
  } else if (state.ledger.view === "income") {
    entries = entries.filter((entry) => LEDGER_INCOME_CATEGORIES.has(entry.category));
  }
  const today = ymd(new Date());
  let start = "";
  let end = today;
  if (state.ledger.range === "year") start = addDaysToDateValue(today, -365);
  if (state.ledger.range === "month") {
    const date = new Date(`${today}T00:00:00`);
    date.setMonth(date.getMonth() - 1);
    start = ymd(date);
  }
  if (state.ledger.range === "week") start = addDaysToDateValue(today, -7);
  if (state.ledger.range === "custom") {
    start = state.ledger.rangeStart;
    end = state.ledger.rangeEnd;
  }
  if (!start && state.ledger.range === "all") return entries;
  return entries.filter((entry) => (!start || entry.date >= start) && (!end || entry.date <= end));
}

function formatLedgerRangeDate(value) {
  const [year, month, day] = String(value || "").split("-");
  if (!year || !month || !day) return "";
  return `${year}.${Number(month)}.${Number(day)}`;
}

function renderLedgerViewFilters() {
  const views = [
    ["all", uiText("ledger.viewAll", "All")],
    ["expense", uiText("ledger.viewExpense", "Expenses")],
    ["income", uiText("ledger.viewIncome", "Income")],
  ];
  const ranges = [
    ["all", uiText("ledger.rangeAll", "All")],
    ["year", uiText("ledger.rangeYear", "1 Year")],
    ["month", uiText("ledger.rangeMonth", "1 Month")],
    ["week", uiText("ledger.rangeWeek", "1 Week")],
    ["custom", uiText("ledger.rangeCustom", "Custom")],
  ];
  return `
    <div class="ledgerFilterStack">
      <div class="ledgerFilterToolbar">
        <div class="ledgerViewFilters" aria-label="${escapeHtml(uiText("ledger.view", "View"))}">
        ${views.map(([value, label]) => `
          <button
            type="button"
            class="${state.ledger.view === value ? "isActive" : ""}"
            data-ledger-view="${value}"
            aria-pressed="${state.ledger.view === value ? "true" : "false"}"
          >${escapeHtml(label)}</button>
        `).join("")}
        </div>
        <select
          class="ledgerRangeSelect"
          data-ledger-range-select
          aria-label="${escapeHtml(uiText("ledger.range", "Duration"))}"
        >
          ${ranges.map(([value, label]) => `
            <option value="${value}" ${state.ledger.range === value ? "selected" : ""}>${escapeHtml(label)}</option>
          `).join("")}
        </select>
      </div>
      ${state.ledger.range === "custom" ? `
        <div class="ledgerCustomRange">
          <label class="ledgerRangeDate">
            <span class="ledgerRangeDateText" aria-hidden="true">${escapeHtml(formatLedgerRangeDate(state.ledger.rangeStart))}</span>
            <span class="ledgerRangeLabel">${escapeHtml(uiText("ledger.rangeStart", "Start"))}</span>
            <input type="date" value="${escapeHtml(state.ledger.rangeStart)}" data-ledger-range-start />
          </label>
          <label class="ledgerRangeDate ledgerRangeDateEnd">
            <span class="ledgerRangeDateText" aria-hidden="true">${escapeHtml(formatLedgerRangeDate(state.ledger.rangeEnd))}</span>
            <span class="ledgerRangeLabel">${escapeHtml(uiText("ledger.rangeEnd", "End"))}</span>
            <input type="date" value="${escapeHtml(state.ledger.rangeEnd)}" data-ledger-range-end />
          </label>
        </div>
      ` : ""}
    </div>
  `;
}

function renderLedgerEditor(entry = null) {
  const draft = entry || {
    id: "",
    date: ymd(new Date()),
    category: "현금 지출",
    amount: "",
    details: "",
    revision: 0,
  };
  return `
    <form
      class="ledgerEditor panel"
      data-ledger-editor
      data-ledger-id="${escapeHtml(draft.id || "")}"
      data-ledger-revision="${Number(draft.revision || 0)}"
    >
      <div class="panelHeader">
        <div>
          <p class="label">${escapeHtml(uiText("ledger.entry", "Entry"))}</p>
          <h2>${escapeHtml(entry ? uiText("ledger.edit", "Edit entry") : uiText("ledger.add", "Add entry"))}</h2>
        </div>
        <button class="openButton" type="button" data-ledger-cancel>${escapeHtml(uiText("common.close", "Close"))}</button>
      </div>
      <div class="ledgerEditorFields">
        <label><span>${escapeHtml(uiText("ledger.date", "Date"))}</span><input name="date" type="date" value="${escapeHtml(draft.date)}" required /></label>
        <label><span>${escapeHtml(uiText("ledger.category", "Category"))}</span><select name="category">${ledgerCategoryOptions(draft.category)}</select></label>
        <label><span>${escapeHtml(uiText("ledger.amount", "Amount"))}</span><input name="amount" type="text" inputmode="numeric" value="${draft.amount ?? ""}" required /></label>
        <label class="ledgerDetailsField"><span>${escapeHtml(uiText("ledger.details", "Details"))}</span><input name="details" type="text" value="${escapeHtml(draft.details || "")}" /></label>
      </div>
      <div class="ledgerEditorActions">
        ${entry && !entry.locked ? `<button class="dangerButton" type="button" data-ledger-delete="${escapeHtml(entry.id)}">${escapeHtml(uiText("common.delete", "Delete"))}</button>` : ""}
        <button class="primaryButton" type="submit">${escapeHtml(uiText("common.save", "Save"))}</button>
      </div>
    </form>
  `;
}

function renderLedgerDesktopTable(entries) {
  return `
    <div class="ledgerDesktopTableWrap">
      <table class="ledgerTable">
        <thead>
          <tr>
            <th>${escapeHtml(uiText("ledger.date", "Date"))}</th>
            <th>${escapeHtml(uiText("ledger.category", "Category"))}</th>
            <th>${escapeHtml(uiText("ledger.amount", "Amount"))}</th>
            <th>${escapeHtml(uiText("ledger.details", "Details"))}</th>
            <th>${escapeHtml(uiText("ledger.account", "Account"))}</th>
            <th>${escapeHtml(uiText("ledger.cash", "Cash"))}</th>
            <th>${escapeHtml(uiText("ledger.gift", "Gift certificates"))}</th>
            <th><span class="srOnly">${escapeHtml(uiText("ledger.actions", "Actions"))}</span></th>
          </tr>
        </thead>
        <tbody>
          ${entries.map((entry) => `
            <tr data-ledger-row data-ledger-id="${escapeHtml(entry.id)}" data-ledger-revision="${entry.revision}" class="${entry.locked ? "isLocked" : ""}">
              <td><input name="date" type="date" value="${escapeHtml(entry.date)}" ${entry.locked ? "disabled" : ""} /></td>
              <td>${entry.locked
                ? `<span class="ledgerLockedValue">${escapeHtml(entry.category)}</span>`
                : `<select name="category">${ledgerCategoryOptions(entry.category)}</select>`}</td>
              <td>${entry.locked
                ? `<span class="ledgerLockedValue">-</span>`
                : `<input name="amount" type="text" inputmode="numeric" value="${entry.amount ?? ""}" />`}</td>
              <td>${entry.locked
                ? `<span class="ledgerLockedValue">${escapeHtml(entry.details || "")}</span>`
                : `<input name="details" type="text" value="${escapeHtml(entry.details || "")}" />`}</td>
              <td class="ledgerMoney">${formatLedgerMoney(entry.account)}</td>
              <td class="ledgerMoney">${formatLedgerMoney(entry.cash)}</td>
              <td class="ledgerMoney">${formatLedgerMoney(entry.gift)}</td>
              <td class="ledgerRowActions">${entry.locked ? `<span title="${escapeHtml(uiText("ledger.openingLocked", "Opening balance is locked"))}">${escapeHtml(uiText("ledger.locked", "Locked"))}</span>` : `
                <button type="button" class="ledgerSaveButton" data-ledger-save-row title="${escapeHtml(uiText("common.save", "Save"))}">✓</button>
                <button type="button" class="ledgerDeleteButton" data-ledger-delete="${escapeHtml(entry.id)}" title="${escapeHtml(uiText("common.delete", "Delete"))}">×</button>
              `}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderLedgerMobileList(entries) {
  return `
    <div class="ledgerMobileList">
      ${entries.length ? [...entries].reverse().map((entry) => `
        <button class="ledgerMobileRow" type="button" data-ledger-edit="${escapeHtml(entry.id)}" ${entry.locked ? "disabled" : ""}>
          <span class="ledgerMobileDate">${escapeHtml(entry.date)}</span>
          <span class="ledgerMobileMain"><strong>${escapeHtml(entry.category)}</strong><small>${escapeHtml(entry.details || uiText("ledger.noDetails", "No details"))}</small></span>
          <span class="ledgerMobileAmount">${entry.amount === null ? "-" : formatLedgerMoney(entry.amount)}</span>
        </button>
      `).join("") : `<p class="ledgerEmpty">${escapeHtml(uiText("ledger.noMatchingEntries", "No matching entries"))}</p>`}
    </div>
  `;
}

function renderLedger() {
  if (state.ledger.loading && !state.ledger.checked) {
    return `<section class="panel emptyState"><p>${escapeHtml(uiText("ledger.loading", "Loading ledger..."))}</p></section>`;
  }
  if (state.ledger.error) {
    return `<section class="panel emptyState"><p>${escapeHtml(state.ledger.error)}</p><button class="openButton" type="button" data-ledger-retry>${escapeHtml(uiText("common.retry", "다시 시도"))}</button></section>`;
  }
  const editingEntry = state.ledger.entries.find((entry) => entry.id === state.ledger.editingId) || null;
  const visibleEntries = ledgerEntriesForView();
  return `
    <section class="ledgerPage">
      <header class="ledgerToolbar panel">
        <div>
          <p class="label">${escapeHtml(uiText("ledger.label", "Ledger"))}</p>
          <h2>${escapeHtml(uiText("ledger.title", "Medical association ledger"))}</h2>
        </div>
        <div class="ledgerToolbarActions">
          <a class="openButton" href="/api/ledger/export.xlsx" download data-ledger-export>${escapeHtml(uiText("ledger.export", "XLSX"))}</a>
          <button class="openButton" type="button" data-ledger-backup>${escapeHtml(uiText("ledger.backup", "Backup"))}</button>
          <button class="primaryButton" type="button" data-ledger-add>${escapeHtml(uiText("common.add", "Add"))}</button>
        </div>
      </header>
      ${renderLedgerBalances()}
      ${renderLedgerViewFilters()}
      <div class="ledgerDetailsScroller">
        ${(state.ledger.adding || editingEntry) ? renderLedgerEditor(editingEntry) : ""}
        <section class="ledgerSheet panel">
          ${renderLedgerDesktopTable(visibleEntries)}
          ${renderLedgerMobileList(visibleEntries)}
        </section>
      </div>
    </section>
  `;
}

function renderMemos() {
  return `
    <section class="memosWorkspace">
      <iframe
        class="memosFrame"
        src="/memos-app/"
        title="${escapeHtml(uiText("memos.label", "Memos"))}"
        allow="clipboard-read; clipboard-write"
        referrerpolicy="strict-origin-when-cross-origin"
      ></iframe>
    </section>
  `;
}

function renderGovernorSettingsStatus() {
  const status = state.governorSettings;
  if (!status.checked || (status.loading && !status.checked)) {
    return `<div class="settingsPolicyNote"><strong>KaosGovernor</strong><span>${escapeHtml(uiText("settings.statusLoading", "Loading Governor settings..."))}</span></div>`;
  }
  if (status.error) {
    return `
      <div class="caregiverError">
        <span>${escapeHtml(status.error)}</span>
        <button class="openButton" type="button" data-governor-settings-retry>${uiText("common.retry", "다시 시도")}</button>
      </div>
    `;
  }
  const data = status.data || {};
  const weather = data.weather || {};
  const generated = data.generatedCalendar || {};
  const presets = data.eventPresets || {};
  const recurring = data.recurringTasks || {};
  return `
    <section class="settingsStatusPanel">
      <div class="settingsStatusHeader">
        <strong>KaosGovernor</strong>
        <small>${escapeHtml(data.updatedAt ? `Updated ${data.updatedAt}` : uiText("settings.governorBacked", "Governor-backed"))}</small>
      </div>
      <div class="settingsStatusGrid">
        <div>
          <span>${escapeHtml(uiText("settings.defaultWeather", "Default weather"))}</span>
          <strong>${escapeHtml(weather.locationLabel || weatherLocationLabel())}</strong>
        </div>
        <div>
          <span>${escapeHtml(uiText("settings.generatedEvents", "Generated events"))}</span>
          <strong>${escapeHtml([generated.marketDaysEnabled === false ? "" : "Market", generated.claimDayEnabled === false ? "" : "Claim"].filter(Boolean).join(" + ") || "Off")}</strong>
        </div>
        <div>
          <span>${escapeHtml(uiText("event.presets", "Event presets"))}</span>
          <strong>${escapeHtml(`${Number(presets.count || 0)} total · ${Number(presets.familyCount || 0)} family`)}</strong>
        </div>
        <div>
          <span>${escapeHtml(uiText("recurring.title", "Repeating tasks"))}</span>
          <strong>${escapeHtml(`${Number(recurring.enabledCount || 0)} active · ${Number(recurring.onScheduleCount || 0)} scheduled`)}</strong>
        </div>
      </div>
    </section>
  `;
}

function renderGeneratedCalendarPolicyStatus() {
  const generated = state.governorSettings.data?.generatedCalendar || {};
  const marketEnabled = generated.marketDaysEnabled !== false;
  const claimEnabled = generated.claimDayEnabled !== false;
  return `
    <details class="settingsDisclosure" data-generated-calendar-policy>
      <summary>
        <span><strong>${escapeHtml(uiText("settings.generatedEvents", "Generated events"))}</strong><small>${escapeHtml([marketEnabled ? "Market Days" : "", claimEnabled ? "Claim Day" : ""].filter(Boolean).join(" + ") || "Disabled")}</small></span>
      </summary>
      <div class="settingsDisclosureBody">
        <div class="settingsPolicyNote">
          <strong>Policy</strong>
          <span>KaosGovernor writes deterministic VEVENTs to Radicale. Family can view this policy here; editing remains in KaosGDD main settings.</span>
        </div>
        <dl class="customEventPolicy">
          <div>
            <dt>Market Day</dt>
            <dd>${escapeHtml(generated.marketDayPolicy || "Every month on 5, 10, 15, 20, 25, and 30.")}</dd>
          </div>
          <div>
            <dt>Claim Day</dt>
            <dd>${escapeHtml(generated.claimDayPolicy || "Every Friday, adjusted by market days and public holidays.")}</dd>
          </div>
        </dl>
      </div>
    </details>
  `;
}

function renderSettings() {
  ensureEventPresets();
  const config = profileConfig();
  const items =
    portalProfile() === "family"
      ? [
          [uiText("settings.portal", "Portal"), uiText("settings.familyPortal", "Family")],
          [uiText("settings.calendar", "Calendar"), uiText("settings.familyCalendarValue", "Family shared")],
          [uiText("settings.tasks", "Tasks"), uiText("settings.familyTasksValue", "Family shared")],
          [uiText("settings.theme", "Theme"), uiText("settings.familyThemeValue", "Pastel family")],
        ]
      : [
          ["Portal", "KaosGDD"],
          ["Calendar", "ZiN + Family shared"],
          ["Tasks", "ZiN + Family shared"],
          ["Generated events", "Market day + Claim day"],
          ["Event presets", "Governor-owned templates"],
        ];
  return `
    <section class="panel">
      <div class="panelHeader">
        <div>
          <p class="label">${escapeHtml(config.label)}</p>
          <h2>${uiText("common.settings", "Settings")}</h2>
        </div>
      </div>
      <div class="panelBody">
        <dl class="settingsList">
          ${items
            .map(
              ([label, value]) => `
                <div>
                  <dt>${escapeHtml(label)}</dt>
                  <dd>${escapeHtml(value)}</dd>
                </div>
              `,
            )
            .join("")}
          <div>
            <dt>${uiText("settings.defaultWeather", "Default weather")}</dt>
            <dd>
              <select data-weather-location-setting aria-label="${uiText("settings.defaultWeather", "Default weather")}">
                ${WEATHER_LOCATION_OPTIONS.map(
                  (location) => `
                    <option value="${location.id}" ${state.weatherLocation === location.id ? "selected" : ""} ${state.weatherSettings.saving ? "disabled" : ""}>
                      ${uiText(location.translationKey, location.label)}
                    </option>
                  `,
                ).join("")}
              </select>
              ${
                state.weatherSettings.saving
                  ? `<small>${uiText("settings.saving", "Saving...")}</small>`
                  : state.weatherSettings.error
                    ? `<small>${escapeHtml(state.weatherSettings.error)}</small>`
                    : state.weatherSettings.checked
                      ? `<small>${uiText("settings.governorBacked", "Governor-backed")}</small>`
                      : ""
              }
            </dd>
          </div>
          ${
            portalProfile() === "family"
              ? `
                <div>
                  <dt>${uiText("settings.font", "Font")}</dt>
                  <dd>
                    <select data-family-font-setting aria-label="${uiText("settings.font", "Font")}">
                      <option value="nanum" ${familyFontPreference() === "nanum" ? "selected" : ""}>${uiText("settings.fontNanum", "NanumBarunPen")}</option>
                      <option value="pretendard" ${familyFontPreference() === "pretendard" ? "selected" : ""}>${uiText("settings.fontPretendard", "Pretendard")}</option>
                      <option value="nixgon" ${familyFontPreference() === "nixgon" ? "selected" : ""}>${uiText("settings.fontNixgon", "Nixgon")}</option>
                      <option value="skybori" ${familyFontPreference() === "skybori" ? "selected" : ""}>${uiText("settings.fontSkybori", "SKYBORI")}</option>
                    </select>
                  </dd>
                </div>
              `
              : `
                <div>
                  <dt>Font</dt>
                  <dd>
                    <select data-main-font-setting aria-label="Font">
                      <option value="pretendard" ${mainFontPreference() === "pretendard" ? "selected" : ""}>Pretendard</option>
                      <option value="orbit" ${mainFontPreference() === "orbit" ? "selected" : ""}>Orbit</option>
                      <option value="sarasa" ${mainFontPreference() === "sarasa" ? "selected" : ""}>Sarasa Gothic</option>
                    </select>
                  </dd>
                </div>
              `
          }
        </dl>
        ${renderGovernorSettingsStatus()}
        ${renderHolidaySettings()}
        ${portalProfile() === "main" ? renderMailOrganizerSettings() : ""}
        ${portalProfile() === "main" ? renderCustomEventSettings() : renderGeneratedCalendarPolicyStatus()}
        ${renderEventPresetSettings()}
        ${renderRecurringTaskSettings()}
      </div>
    </section>
  `;
}

function renderMailOrganizerSettings() {
  const organizer = state.mailOrganizer;
  const settings = organizer.settings;
  const summary = Number(settings.runsPerDay) === 2
    ? `Twice daily · ${settings.firstTime} / ${settings.secondTime}`
    : `Once daily · ${settings.firstTime}`;
  const body = organizer.loading && !organizer.checked
    ? `<p class="taskMeta">Loading mail organizer...</p>`
    : organizer.error
      ? `<div class="caregiverError"><span>${escapeHtml(organizer.error)}</span><button class="openButton" type="button" data-mail-organizer-retry>${uiText("common.retry", "다시 시도")}</button></div>`
      : `
        <form class="mailOrganizerForm" data-mail-organizer-form>
          <label>
            <span>Frequency</span>
            <select name="runsPerDay">
              <option value="1" ${Number(settings.runsPerDay) === 1 ? "selected" : ""}>Once daily</option>
              <option value="2" ${Number(settings.runsPerDay) === 2 ? "selected" : ""}>Twice daily</option>
            </select>
          </label>
          <label>
            <span>First digest</span>
            <input type="time" name="firstTime" step="300" value="${escapeHtml(settings.firstTime)}" required />
          </label>
          <label class="${Number(settings.runsPerDay) === 2 ? "" : "isDisabled"}">
            <span>Second digest</span>
            <input type="time" name="secondTime" step="300" value="${escapeHtml(settings.secondTime)}" ${Number(settings.runsPerDay) === 2 ? "required" : "disabled"} />
          </label>
          <p class="formNote">Unread Naver INBOX mail only. Actions are limited to the configured Telegram user.</p>
          <div class="mailOrganizerActions">
            <button class="openButton" type="button" data-mail-organizer-send ${organizer.sending || !organizer.enabled || !organizer.configured ? "disabled" : ""}>${organizer.sending ? "Sending..." : "Send now"}</button>
            <button class="primaryButton" type="submit" ${organizer.saving ? "disabled" : ""}>${organizer.saving ? "Saving..." : "Save"}</button>
          </div>
        </form>
      `;
  return `
    <details class="settingsDisclosure" data-mail-organizer ${organizer.expanded ? "open" : ""}>
      <summary>
        <span><strong>Naver Mail Organizer</strong><small>${escapeHtml(summary)}</small></span>
      </summary>
      <div class="settingsDisclosureBody">${body}</div>
    </details>
  `;
}

function renderCustomEventSettings() {
  const custom = state.customEvents;
  const summary = [
    custom.marketDaysEnabled ? "Market Days" : "",
    custom.claimDayEnabled ? "Claim Day" : "",
  ].filter(Boolean).join(" + ") || "Disabled";
  const sync = custom.sync || {};
  const lastResult = sync.lastResult || sync;
  const syncTotal = Number(lastResult.total);
  const syncSummary = Number.isFinite(syncTotal)
    ? `${syncTotal} generated · ${Number(lastResult.unchanged || 0)} unchanged`
    : "Generated by KaosGovernor";
  const body = custom.loading && !custom.checked
    ? `<p class="taskMeta">Loading custom events...</p>`
    : custom.error
      ? `<div class="caregiverError"><span>${escapeHtml(custom.error)}</span><button class="openButton" type="button" data-custom-events-retry>${uiText("common.retry", "다시 시도")}</button></div>`
      : `
        <div class="settingsPolicyNote">
          <strong>Policy</strong>
          <span>KaosGovernor writes deterministic VEVENTs to Radicale. The LLM never owns these events.</span>
        </div>
        <dl class="customEventPolicy">
          <div>
            <dt>Market Day</dt>
            <dd>Every month on 5, 10, 15, 20, 25, and 30.</dd>
          </div>
          <div>
            <dt>Claim Day</dt>
            <dd>Every Friday. If Saturday is a market day, it moves to Saturday unless that date is a public holiday. Public holidays move it earlier.</dd>
          </div>
          <div>
            <dt>Sync</dt>
            <dd>${escapeHtml(syncSummary)}</dd>
          </div>
        </dl>
        <div class="customEventSettingList">
          <label class="customEventSettingRow">
            <span><strong>Market Days</strong><small>Blue dot on 5, 10, 15, 20, 25, and 30</small></span>
            <input type="checkbox" data-custom-event-setting="marketDaysEnabled" ${custom.marketDaysEnabled ? "checked" : ""} ${custom.saving ? "disabled" : ""} />
          </label>
          <label class="customEventSettingRow">
            <span><strong>Claim Day</strong><small>Friday, adjusted for Market Saturday and public holidays</small></span>
            <input type="checkbox" data-custom-event-setting="claimDayEnabled" ${custom.claimDayEnabled ? "checked" : ""} ${custom.saving ? "disabled" : ""} />
          </label>
        </div>
      `;
  return `
    <details class="settingsDisclosure" data-custom-events ${custom.expanded ? "open" : ""}>
      <summary>
        <span><strong>Generated calendar events</strong><small>${escapeHtml(summary)}</small></span>
      </summary>
      <div class="settingsDisclosureBody">${body}</div>
    </details>
  `;
}

function renderHolidaySettings() {
  const holidays = state.holidays;
  const publicCount = holidays.items.filter((item) => item.publicHoliday).length;
  const groups = holidays.items.reduce((result, item) => {
    const year = item.startDate.slice(0, 4) || uiText("holidays.unknownYear", "Other");
    if (!result[year]) result[year] = [];
    result[year].push(item);
    return result;
  }, {});
  const body = holidays.loading && !holidays.checked
    ? `<p class="taskMeta">${uiText("holidays.loading", "Loading Korean calendar...")}</p>`
    : holidays.error
      ? `<div class="caregiverError"><span>${escapeHtml(holidays.error)}</span><button class="openButton" type="button" data-holidays-retry>${uiText("common.retry", "다시 시도")}</button></div>`
      : holidays.items.length
        ? Object.keys(groups).sort().map((year) => `
            <section class="holidayYearGroup">
              <h3>${escapeHtml(year)}</h3>
              <div class="holidaySettingList">
                ${groups[year].map((item) => `
                  <label class="holidaySettingRow">
                    <span>
                      <time>${escapeHtml(item.startDate.slice(5))}</time>
                      <strong>${escapeHtml(item.title)}</strong>
                    </span>
                    <input
                      type="checkbox"
                      data-holiday-classification="${escapeHtml(item.uid)}"
                      aria-label="${escapeHtml(uiText("holidays.publicHolidayAria", "Mark {title} as a public holiday", { title: item.title }))}"
                      ${item.publicHoliday ? "checked" : ""}
                    />
                  </label>
                `).join("")}
              </div>
            </section>
          `).join("")
        : `<p class="taskMeta">${uiText("holidays.none", "No Korean calendar entries imported yet.")}</p>`;
  return `
    <details class="settingsDisclosure" data-holidays ${holidays.expanded ? "open" : ""}>
      <summary>
        <span>
          <strong>${uiText("holidays.title", "Korean calendar")}</strong>
          <small>${uiText("holidays.summary", "{publicCount} public holidays · {total} entries", {
            publicCount,
            total: holidays.items.length,
          })}</small>
        </span>
      </summary>
      <div class="settingsDisclosureBody">
        <div class="holidaySettingsIntro">
          <p>${uiText("holidays.help", "Checked dates are red public holidays. Unchecked entries remain dim calendar information.")}</p>
          <button class="openButton" type="button" data-holidays-sync ${holidays.syncing ? "disabled" : ""}>
            ${holidays.syncing ? uiText("holidays.syncing", "Syncing...") : uiText("holidays.sync", "Sync Google calendar")}
          </button>
        </div>
        ${body}
      </div>
    </details>
  `;
}

function renderEventPresetSettings() {
  const editing = state.eventPresets.items.find((preset) => preset.id === state.eventPresets.editingId) || defaultEventPreset();
  const isEditing = Boolean(state.eventPresets.editingId);
  const presetCount = state.eventPresets.items.length;
  const statusBody = state.eventPresets.loading && !state.eventPresets.checked
    ? `<p class="taskMeta">${uiText("event.presetsLoading", "Loading event presets...")}</p>`
    : state.eventPresets.error
      ? `<div class="caregiverError"><span>${escapeHtml(state.eventPresets.error)}</span><button class="openButton" type="button" data-event-presets-retry>${uiText("common.retry", "다시 시도")}</button></div>`
      : "";
  return `
    <details class="settingsDisclosure" data-event-presets ${state.eventPresets.expanded ? "open" : ""}>
      <summary>
        <span>
          <strong>${uiText("event.presets", "Event presets")}</strong>
          <small>${presetCount ? uiText("event.savedCount", "{count} saved", { count: presetCount }) : uiText("event.noneSaved", "None saved")}</small>
        </span>
      </summary>
      <div class="settingsDisclosureBody">
        ${statusBody}
        <div class="settingsPolicyNote">
          <strong>Policy</strong>
          <span>Presets are Governor-owned calendar templates. Radicale owns the actual events created from them.</span>
        </div>
        ${isEditing ? `<div class="presetInlineActions"><button class="openButton" type="button" data-event-preset-new>${uiText("event.newPreset", "New")}</button></div>` : ""}
        ${
          presetCount
            ? `
              <div class="presetList">
                ${state.eventPresets.items
                  .map(
                    (preset) => `
                      <div class="presetRow">
                        <button class="presetChoice ${preset.id === state.eventPresets.editingId ? "isActive" : ""}" type="button" data-edit-event-preset="${escapeHtml(preset.id)}">
                          <strong>${escapeHtml(preset.name)}</strong>
                          <span>${escapeHtml([preset.title || uiText("common.untitled", "Untitled"), preset.allDay ? uiText("event.allDay", "all-day") : `${preset.startTime}-${preset.endTime}`, preset.shareFamily ? uiText("common.family", "Family") : uiText("common.personal", "Personal")].join(" · "))}</span>
                        </button>
                        <button class="plainButton" type="button" data-delete-event-preset="${escapeHtml(preset.id)}">${uiText("common.delete", "Delete")}</button>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            `
            : !statusBody ? `<p class="taskMeta">${uiText("event.noPresets", "No event presets yet.")}</p>` : ""
        }
        ${state.eventPresets.error ? "" : `
        <form class="composer presetEditor" data-event-preset-form data-event-preset-id="${isEditing ? escapeHtml(editing.id) : ""}">
        <label>
          <span>${uiText("event.presetName", "Preset name")}</span>
          <input name="presetName" type="text" autocomplete="off" value="${isEditing ? escapeHtml(editing.name) : ""}" placeholder="${uiText("event.dutyName", "Duty")}" required />
        </label>
        <label>
          <span>${uiText("common.title", "Title")}</span>
          <input name="title" type="text" autocomplete="off" value="${isEditing ? escapeHtml(editing.title) : ""}" placeholder="${uiText("event.titlePlaceholder", "Event title")}" required />
        </label>
        ${renderFamilyShareToggle(Boolean(isEditing && editing.shareFamily), "event")}
        <label class="toggleLine">
          <span>${uiText("event.allDay", "All-day")}</span>
          <input name="allDay" type="checkbox" data-all-day-toggle ${!isEditing || editing.allDay ? "checked" : ""} />
        </label>
        <div class="formGrid">
          <label data-event-time-field ${!isEditing || editing.allDay ? 'class="isDisabled"' : ""}>
            <span>${uiText("event.startTime", "Start time")}</span>
            <input name="startTime" type="time" value="${escapeHtml(isEditing ? editing.startTime : DEFAULT_EVENT_START_TIME)}" step="300" ${!isEditing || editing.allDay ? "disabled" : ""} />
          </label>
          <label data-event-time-field ${!isEditing || editing.allDay ? 'class="isDisabled"' : ""}>
            <span>${uiText("event.endTime", "End time")}</span>
            <input name="endTime" type="time" value="${escapeHtml(isEditing ? editing.endTime : DEFAULT_EVENT_END_TIME)}" step="300" ${!isEditing || editing.allDay ? "disabled" : ""} />
          </label>
        </div>
        <label data-event-time-field ${!isEditing || editing.allDay ? 'class="isDisabled"' : ""}>
          <span>${uiText("event.alarmTime", "Alarm time")}</span>
          <input name="alarm" type="time" value="${escapeHtml(isEditing ? editing.alarm : "")}" step="300" ${!isEditing || editing.allDay ? "disabled" : ""} />
        </label>
        <label>
          <span>${uiText("common.memo", "Memo")}</span>
          <textarea name="memo" rows="4" placeholder="${uiText("event.notes", "Event notes")}">${isEditing ? escapeHtml(editing.memo) : ""}</textarea>
        </label>
        <button class="primaryButton" type="submit">${isEditing ? uiText("event.savePreset", "Save preset") : uiText("event.createPreset", "Create preset")}</button>
        </form>
        `}
      </div>
    </details>
  `;
}

function recurringFrequencyLabel(frequency) {
  const labels = {
    daily: uiText("recurring.daily", "Daily"),
    weekly: uiText("recurring.weekly", "Weekly"),
    monthly: uiText("recurring.monthly", "Monthly"),
    yearly: uiText("recurring.yearly", "Yearly"),
  };
  return labels[frequency] || frequency;
}

function recurringCreationPolicyLabel(policy) {
  const labels = {
    on_schedule: uiText("recurring.onSchedule", "정해진 날짜에 생성"),
    on_completion: uiText("recurring.onCompletion", "완료하면 다음 항목 생성"),
  };
  return labels[policy] || labels.on_schedule;
}

function recurringOwnerLabel(item) {
  if (item.shareFamily || item.owner === "family") return uiText("common.family", "Family");
  if (item.owner === "wife") return uiText("collection.wife", "Bling02");
  return "ZiN";
}

function renderRecurringTaskSettings() {
  const recurring = state.recurringTasks;
  const editing = recurring.items.find((item) => item.id === recurring.editingId) || defaultRecurringTask();
  const isEditing = Boolean(recurring.editingId);
  const taskCount = recurring.items.length;
  const statusBody = recurring.loading && !recurring.checked
    ? `<p class="taskMeta">${uiText("recurring.loading", "Loading repeating tasks...")}</p>`
    : recurring.error
      ? `<div class="caregiverError"><span>${escapeHtml(recurring.error)}</span><button class="openButton" type="button" data-recurring-retry>${uiText("common.retry", "다시 시도")}</button></div>`
      : "";
  return `
    <details class="settingsDisclosure" data-recurring-tasks ${recurring.expanded ? "open" : ""}>
      <summary>
        <span>
          <strong>${uiText("recurring.title", "Repeating tasks")}</strong>
          <small>${taskCount ? uiText("recurring.savedCount", "{count} saved", { count: taskCount }) : uiText("recurring.noneSaved", "None saved")}</small>
        </span>
      </summary>
      <div class="settingsDisclosureBody">
        ${statusBody}
        ${isEditing ? `<div class="presetInlineActions"><button class="openButton" type="button" data-recurring-new>${uiText("recurring.new", "New")}</button></div>` : ""}
        ${
          taskCount
            ? `
              <div class="presetList">
                ${recurring.items
                  .map((item) => {
                    const due = item.activeDueDate || item.nextDueDate || item.firstDueDate;
                    const stateLabel = item.enabled ? "" : ` · ${uiText("recurring.paused", "Paused")}`;
                    const policyLabel = recurringCreationPolicyLabel(item.creationPolicy);
                    return `
                      <div class="presetRow">
                        <button class="presetChoice ${item.id === recurring.editingId ? "isActive" : ""}" type="button" data-edit-recurring="${escapeHtml(item.id)}">
                          <strong>${escapeHtml(item.title)}</strong>
                          <span>${escapeHtml(`${recurringFrequencyLabel(item.frequency)} · ${policyLabel} · ${due} ${item.dueTime} · ${recurringOwnerLabel(item)}${stateLabel}`)}</span>
                        </button>
                        <button class="plainButton" type="button" data-delete-recurring="${escapeHtml(item.id)}">${uiText("common.delete", "Delete")}</button>
                      </div>
                    `;
                  })
                  .join("")}
              </div>
            `
            : !statusBody ? `<p class="taskMeta">${uiText("recurring.noTasks", "No repeating tasks yet.")}</p>` : ""
        }
        <form class="composer presetEditor" data-recurring-form data-recurring-id="${isEditing ? escapeHtml(editing.id) : ""}">
          <label>
            <span>${uiText("task.label", "Task")}</span>
            <input name="title" type="text" autocomplete="off" value="${isEditing ? escapeHtml(editing.title) : ""}" placeholder="${uiText("task.new", "New task")}" required />
          </label>
          <label>
            <span>${uiText("common.memo", "Memo")}</span>
            <textarea name="memo" rows="5" placeholder="${escapeHtml(uiText("task.memoPlaceholder", TASK_MEMO_PLACEHOLDER))}">${isEditing ? escapeHtml(editing.memo) : ""}</textarea>
          </label>
          ${renderFamilyShareToggle(Boolean(isEditing && editing.shareFamily))}
          <div class="formGrid">
            <label>
              <span>${uiText("recurring.firstDueDate", "First due date")}</span>
              <input name="firstDueDate" type="date" value="${escapeHtml(editing.firstDueDate)}" required />
            </label>
            <label>
              <span>${uiText("task.time", "Time")}</span>
              <input name="dueTime" type="time" value="${escapeHtml(editing.dueTime || DEFAULT_TASK_DUE_TIME)}" step="300" required />
            </label>
          </div>
          <div class="formGrid">
            <label>
              <span>${uiText("task.priority", "Priority")}</span>
              <select name="priority">
                <option value="" ${!editing.priority ? "selected" : ""}>${uiText("common.none", "None")}</option>
                <option value="9" ${editing.priority === "9" ? "selected" : ""}>${uiText("task.priorityLow", "Low")} (!)</option>
                <option value="5" ${editing.priority === "5" ? "selected" : ""}>${uiText("task.priorityMedium", "Medium")} (!!)</option>
                <option value="1" ${editing.priority === "1" ? "selected" : ""}>${uiText("task.priorityHigh", "High")} (!!!)</option>
              </select>
            </label>
            <label>
              <span>${uiText("recurring.frequency", "Repeat")}</span>
              <select name="frequency">
                <option value="daily" ${editing.frequency === "daily" ? "selected" : ""}>${uiText("recurring.daily", "Daily")}</option>
                <option value="weekly" ${editing.frequency === "weekly" ? "selected" : ""}>${uiText("recurring.weekly", "Weekly")}</option>
                <option value="monthly" ${editing.frequency === "monthly" ? "selected" : ""}>${uiText("recurring.monthly", "Monthly")}</option>
                <option value="yearly" ${editing.frequency === "yearly" ? "selected" : ""}>${uiText("recurring.yearly", "Yearly")}</option>
              </select>
            </label>
            <label>
              <span>${uiText("recurring.creationPolicy", "다음 항목 생성")}</span>
              <select name="creationPolicy">
                <option value="on_schedule" ${editing.creationPolicy === "on_schedule" ? "selected" : ""}>${uiText("recurring.onSchedule", "정해진 날짜에 생성")}</option>
                <option value="on_completion" ${editing.creationPolicy === "on_completion" ? "selected" : ""}>${uiText("recurring.onCompletion", "완료하면 다음 항목 생성")}</option>
              </select>
            </label>
          </div>
          <label class="toggleLine">
            <span>${uiText("recurring.enabled", "Enabled")}</span>
            <input name="enabled" type="checkbox" ${editing.enabled ? "checked" : ""} />
          </label>
          ${editing.error ? `<p class="formNote recurringError">${escapeHtml(editing.error)}</p>` : ""}
          <button class="primaryButton" type="submit">${isEditing ? uiText("recurring.save", "Save repeating task") : uiText("recurring.create", "Create repeating task")}</button>
        </form>
      </div>
    </details>
  `;
}

function renderCaregiver() {
  const month = state.selectedDate.slice(0, 7);
  const data = state.caregiver.key === month ? state.caregiver.data : null;
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
  const currentError = state.caregiver.key === month ? state.caregiver.error : "";
  const isLoading = state.caregiver.loadingKey === month || (!data && !currentError);
  const statusBody = isLoading
    ? `<p class="taskMeta">${uiText("caregiver.loading", "Loading monthly summary...")}</p>`
    : currentError
      ? `
          <div class="caregiverError">
            <span>${escapeHtml(currentError)}</span>
            <button class="openButton" type="button" data-caregiver-retry>${uiText("common.retry", "다시 시도")}</button>
          </div>
        `
      : "";
  return `
    <div class="caregiverPage">
      <section class="panel caregiverSummaryPanel">
        <div class="panelHeader">
          <div>
            <p class="label">${uiText("caregiver.label", "Caregiver")}</p>
            <h2>${escapeHtml(monthTitle(month))}</h2>
          </div>
          <div class="calendarHeaderActions">
            <div class="monthNav" aria-label="${uiText("calendar.monthNavigationAria", "Month navigation")}">
              <button class="monthNavButton" type="button" data-month-shift="-1" aria-label="${uiText("calendar.previousMonth", "Previous month")}">&lt;&lt;</button>
              <button class="monthTodayButton" type="button" data-month-today>${uiText("calendar.today", "Today")}</button>
              <button class="monthNavButton" type="button" data-month-shift="1" aria-label="${uiText("calendar.nextMonth", "Next month")}">&gt;&gt;</button>
            </div>
            <a class="openButton" href="#/calendar">${uiText("caregiver.backToCalendar", "Calendar")}</a>
          </div>
        </div>
        <div class="panelBody">
          ${statusBody}
          ${
            data
              ? `
                <form class="caregiverSummaryForm" data-caregiver-settings-form>
                  <div class="caregiverSummaryRow">
                    <span>${uiText("caregiver.totalTime", "Total care time")}</span>
                    <strong>${summary.days}${uiText("caregiver.daysSuffix", "d")} / ${formatCaregiverHours(summary.minutes)}</strong>
                  </div>
                  <label class="caregiverSummaryRow">
                    <span>${uiText("caregiver.hourlyWage", "Hourly wage")}</span>
                    <span class="caregiverMoneyInput">
                      <input name="hourlyWage" type="text" inputmode="numeric" value="${escapeHtml(settings.hourlyWage)}" />
                      <span>${uiText("caregiver.wonSuffix", "won")}</span>
                    </span>
                  </label>
                  <div class="caregiverSummaryRow">
                    <span>${uiText("caregiver.basePay", "Base pay")}</span>
                    <strong>${formatCaregiverWon(summary.basePay)}</strong>
                  </div>
                  <div class="caregiverSummaryRow">
                    <span>${uiText("caregiver.extras", "Extra fees")}</span>
                    <strong>${formatCaregiverWon(summary.extras)}</strong>
                  </div>
                  <label class="caregiverSummaryRow">
                    <span>${uiText("caregiver.transportFee", "Transport fee")}</span>
                    <span class="caregiverMoneyInput">
                      <input name="transportFee" type="text" inputmode="numeric" value="${escapeHtml(settings.transportFee)}" />
                      <span>${uiText("caregiver.wonSuffix", "won")}</span>
                    </span>
                  </label>
                  <div class="caregiverSummaryRow caregiverTotalRow">
                    <span>${uiText("caregiver.totalPay", "Total payment")}</span>
                    <strong>${formatCaregiverWon(summary.total)}</strong>
                  </div>
                  <button class="primaryButton caregiverSettingsSave" type="submit">${uiText("common.save", "Save")}</button>
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
              <summary class="caregiverDetailSummary">${uiText("caregiver.details", "Monthly details")}</summary>
              <div class="panelBody caregiverDetailBody">
                <div class="caregiverMonthGrid" aria-label="${uiText("caregiver.monthGridAria", "Monthly care hours")}">
                  ${calendarWeekdays().map((day) => `<span class="caregiverWeekday">${day}</span>`).join("")}
                  ${monthCells(month)
                    .map((cell) => {
                      if (cell.muted) return '<span class="caregiverMonthDay isMuted" aria-hidden="true"></span>';
                      const item = dailyByDate.get(cell.value);
                      return `
                        <span class="caregiverMonthDay">
                          <span>${cell.label}</span>
                          <strong>${item?.minutes ? escapeHtml(formatCaregiverHours(item.minutes)) : ""}</strong>
                        </span>
                      `;
                    })
                    .join("")}
                </div>
                <div class="caregiverDailyList" aria-label="${uiText("caregiver.dailyBreakdownAria", "Daily care details")}">
                  ${
                    recordedDays.length
                      ? recordedDays
                          .map(
                            (item) => `
                              <div class="caregiverDailyRow">
                                <div class="caregiverDailyHeading">
                                  <strong>${escapeHtml(item.date.slice(5))} ${escapeHtml(item.weekday)}</strong>
                                  <span>${escapeHtml(formatCaregiverHours(item.minutes))}</span>
                                </div>
                                <div class="caregiverDailyAmounts">
                                  <span>${uiText("caregiver.basePay", "Base pay")} ${formatCaregiverWon(item.basePay)}</span>
                                  <span>${uiText("caregiver.extras", "Extra fees")} ${formatCaregiverWon(item.extras)}</span>
                                </div>
                                ${item.notes ? `<p>${escapeHtml(item.notes)}</p>` : ""}
                              </div>
                            `,
                          )
                          .join("")
                      : `<p class="taskMeta">${uiText("caregiver.noRecords", "No care records this month.")}</p>`
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

function render() {
  const route = getRoute();
  const view = document.getElementById("view");
  const overlayRoot = document.getElementById("overlayRoot");
  const app = document.querySelector(".app");
  if (isAgendaSuppliesEmbed()) {
    app.dataset.embed = "agenda-supplies";
    app.dataset.profile = "main";
    app.dataset.route = "embed";
    document.documentElement.classList.add("isAgendaSuppliesEmbed");
    view.innerHTML = renderCalendarTasksSuppliesEmbed();
    if (overlayRoot) overlayRoot.innerHTML = "";
    if (state.embedView === "supplies") loadSupplies();
    return;
  }
  delete app.dataset.embed;
  document.documentElement.classList.remove("isAgendaSuppliesEmbed");
  routeTitle(route);
  if (route === "calendar") view.innerHTML = renderCalendar();
  else if (route === "caregiver") view.innerHTML = renderCaregiver();
  else if (route === "tasks") view.innerHTML = renderTasks();
  else if (route === "add") view.innerHTML = renderAdd();
  else if (route === "add-event") {
    state.addKind = "event";
    view.innerHTML = renderAddEvent();
  }
  else if (route === "edit-event") view.innerHTML = renderEditEvent();
  else if (route === "add-task") {
    state.addKind = "task";
    view.innerHTML = renderAddTask();
  }
  else if (route === "edit-task") view.innerHTML = renderEditTask();
  else if (route === "services") view.innerHTML = renderServices();
  else if (route === "service") view.innerHTML = renderDesktopService();
  else if (route === "supplies") view.innerHTML = renderSupplies();
  else if (route === "documents") view.innerHTML = renderDocuments();
  else if (route === "rouny") view.innerHTML = renderRouny();
  else if (route === "memos") view.innerHTML = renderMemos();
  else if (route === "ledger") view.innerHTML = renderLedger();
  else if (route === "settings") view.innerHTML = renderSettings();
  else view.innerHTML = renderToday();
  if (overlayRoot) overlayRoot.innerHTML = route === "rouny" ? renderRounyOverlay() : "";
  updateOverlayMetrics();
  if (route === "calendar" || route === "today" || ((route === "add-event" || route === "edit-event") && isDesktopLayout())) {
    loadRemoteWeatherForSelectedMonth();
  }
  if (route === "caregiver" || (route === "calendar" && portalProfile() === "family")) loadCaregiverMonth();
  if (route === "supplies") loadSupplies();
  if (route === "documents") loadDocuments();
  if (route === "ledger") loadLedger();
  if (route === "settings") {
    loadGovernorSettingsStatus();
    loadWeatherSettings();
    loadHolidays();
    loadCustomEvents();
    loadMailOrganizerSettings();
    loadRecurringTasks();
  }
  document.querySelector(".ledgerDetailsScroller")?.addEventListener("scroll", updateTopBarShadow, { passive: true });
  updateTopBarShadow();
}

function updateOverlayMetrics() {
  const topBar = document.querySelector(".appTop");
  const bottom = topBar?.getBoundingClientRect().bottom || 0;
  document.documentElement.style.setProperty("--kaos-overlay-top", `${Math.ceil(bottom)}px`);
}

function updateTopBarShadow() {
  const view = document.getElementById("view");
  const ledgerScroller = document.querySelector(".ledgerDetailsScroller");
  const scrollTop = ledgerScroller?.scrollTop || view?.scrollTop || 0;
  const hasScrolled = scrollTop > 4;
  document.querySelector(".appTop")?.classList.toggle("hasScrolled", !ledgerScroller && hasScrolled);
  document.querySelector(".ledgerFilterStack")?.classList.toggle("hasScrolled", hasScrolled);
}

document.addEventListener("click", async (event) => {
  const embedView = event.target.closest("[data-embed-view]");
  if (embedView) {
    const nextView = embedView.dataset.embedView;
    state.embedView = ["calendar", "tasks", "supplies"].includes(nextView) ? nextView : "calendar";
    render();
    if (state.embedView === "supplies") await loadSupplies();
    return;
  }

  if (event.target.closest("[data-embed-refresh]")) {
    if (state.embedView === "supplies") {
      state.supplies.checked = false;
      await loadSupplies({ force: true });
    } else {
      state.remoteCalendar.checked = false;
      state.remoteCalendar.error = "";
      render();
      await loadRemoteCalendar();
    }
    return;
  }

  const exportLedger = event.target.closest("[data-ledger-export]");
  if (exportLedger) {
    event.preventDefault();
    if (!window.confirm(uiText("dialog.ledgerExportConfirm", "Download the Excel file to this device?"))) return;
    const link = document.createElement("a");
    link.href = exportLedger.href;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
    return;
  }

  const ledgerView = event.target.closest("[data-ledger-view]");
  if (ledgerView) {
    const view = ledgerView.dataset.ledgerView || "all";
    if (!LEDGER_VIEWS.has(view) || state.ledger.view === view) return;
    state.ledger.view = view;
    render();
    return;
  }

  if (event.target.closest("[data-ledger-add]")) {
    state.ledger.adding = true;
    state.ledger.editingId = "";
    render();
    document.querySelector("[data-ledger-editor]")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  const editLedger = event.target.closest("[data-ledger-edit]");
  if (editLedger) {
    state.ledger.editingId = editLedger.dataset.ledgerEdit || "";
    state.ledger.adding = false;
    render();
    document.querySelector("[data-ledger-editor]")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  if (event.target.closest("[data-ledger-cancel]")) {
    state.ledger.adding = false;
    state.ledger.editingId = "";
    render();
    return;
  }

  if (event.target.closest("[data-ledger-retry]")) {
    state.ledger.checked = false;
    state.ledger.error = "";
    await loadLedger({ force: true });
    return;
  }

  const saveLedgerRow = event.target.closest("[data-ledger-save-row]");
  if (saveLedgerRow) {
    const row = saveLedgerRow.closest("[data-ledger-row]");
    if (!row) return;
    try {
      await saveLedgerEntry(row);
    } catch (error) {
      window.alert(uiText("dialog.ledgerSaveError", "Could not save ledger entry: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const deleteLedger = event.target.closest("[data-ledger-delete]");
  if (deleteLedger) {
    const entry = state.ledger.entries.find((item) => item.id === deleteLedger.dataset.ledgerDelete);
    if (!entry || !window.confirm(uiText("dialog.deleteLedgerEntry", "Delete this ledger entry?"))) return;
    try {
      await removeLedgerEntry(entry);
    } catch (error) {
      window.alert(uiText("dialog.ledgerDeleteError", "Could not delete ledger entry: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  if (event.target.closest("[data-ledger-backup]")) {
    if (!window.confirm(uiText("dialog.ledgerBackupConfirm", "Create an XLSX backup in Brain storage?"))) return;
    try {
      await createLedgerBackup();
      window.alert(uiText("dialog.ledgerBackupComplete", "XLSX backup created."));
    } catch (error) {
      window.alert(uiText("dialog.ledgerBackupError", "Could not create backup: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  if (event.target.closest("[data-documents-refresh]")) {
    state.documents.checked = false;
    await loadDocuments({ force: true });
    return;
  }

  const paperlessDocument = event.target.closest("[data-document-paperless]");
  if (paperlessDocument) {
    if (!window.confirm("Send this PDF to Paperless?")) return;
    try {
      await submitDocumentToPaperless(paperlessDocument.dataset.documentPaperless || "");
    } catch (error) {
      window.alert(`Could not send to Paperless: ${error.message || "unknown error"}`);
    }
    return;
  }

  const deleteDocument = event.target.closest("[data-document-delete]");
  if (deleteDocument) {
    if (!window.confirm("Delete this temporary PDF?")) return;
    try {
      await deleteQueuedDocument(deleteDocument.dataset.documentDelete || "");
    } catch (error) {
      window.alert(`Could not delete PDF: ${error.message || "unknown error"}`);
    }
    return;
  }

  if (event.target.closest("[data-reload-service-frame]")) {
    const frame = document.querySelector(".desktopServiceFrame");
    if (frame) frame.src = frame.src;
    return;
  }

  const suppliesMode = event.target.closest("[data-supplies-mode]");
  if (suppliesMode) {
    state.supplies.mode = suppliesMode.dataset.suppliesMode === "done" ? "done" : "active";
    state.supplies.checked = false;
    render();
    await loadSupplies({ force: true });
    return;
  }

  const supplyPreset = event.target.closest("[data-supply-preset]");
  if (supplyPreset) {
    try {
      await useSupplyPreset(supplyPreset.dataset.supplyPreset || "");
    } catch (error) {
      window.alert(`Could not add supply: ${error.message || "unknown error"}`);
    }
    return;
  }

  const supplyDone = event.target.closest("[data-supply-done]");
  if (supplyDone) {
    try {
      await setSupplyState(supplyDone.dataset.supplyDone || "", "done");
    } catch (error) {
      window.alert(`Could not update supply: ${error.message || "unknown error"}`);
    }
    return;
  }

  const supplyActive = event.target.closest("[data-supply-active]");
  if (supplyActive) {
    if (!window.confirm("Move this supply back to Active?")) return;
    try {
      await setSupplyState(supplyActive.dataset.supplyActive || "", "active");
    } catch (error) {
      window.alert(`Could not update supply: ${error.message || "unknown error"}`);
    }
    return;
  }

  const supplyDelete = event.target.closest("[data-supply-delete]");
  if (supplyDelete) {
    if (!window.confirm("Delete this supply?")) return;
    try {
      await deleteSupply(supplyDelete.dataset.supplyDelete || "");
    } catch (error) {
      window.alert(`Could not delete supply: ${error.message || "unknown error"}`);
    }
    return;
  }

  const currentLocationWeather = event.target.closest("[data-current-location-weather]");
  if (currentLocationWeather) {
    await openCurrentLocationWeather(currentLocationWeather.dataset.currentLocationWeather || state.selectedDate);
    return;
  }

  if (event.target.closest("[data-close-weather-locations]")) {
    closeWeatherLocationPopup();
    return;
  }

  const openWeatherLocations = event.target.closest("[data-open-weather-locations]");
  if (openWeatherLocations) {
    await openWeatherLocationPopup(openWeatherLocations.dataset.openWeatherLocations || state.selectedDate);
    return;
  }

  const addCaregiverSession = event.target.closest("[data-caregiver-add-session]");
  if (addCaregiverSession) {
    const form = addCaregiverSession.closest("[data-caregiver-day-form]");
    const list = form?.querySelector("[data-caregiver-session-list]");
    if (!form || !list) return;
    const rows = Array.from(list.querySelectorAll("[data-caregiver-session]"));
    const previousEnd = caregiverTimeMinutes(rows.at(-1)?.querySelector('[name="sessionEnd"]')?.value);
    const start = Math.min(previousEnd ?? 9 * 60, 22 * 60 + 55);
    list.insertAdjacentHTML(
      "beforeend",
      caregiverSessionRowHtml({ start: caregiverMinutesTime(start), end: caregiverMinutesTime(start + 60) }, rows.length),
    );
    updateCaregiverDayFormTotals(form);
    return;
  }

  const removeCaregiverSession = event.target.closest("[data-caregiver-remove-session]");
  if (removeCaregiverSession) {
    const form = removeCaregiverSession.closest("[data-caregiver-day-form]");
    if (!form) return;
    removeCaregiverSession.closest("[data-caregiver-session]")?.remove();
    form.querySelectorAll("[data-caregiver-session-number]").forEach((number, index) => {
      number.textContent = String(index + 1);
    });
    updateCaregiverDayFormTotals(form);
    return;
  }

  const addCaregiverExtra = event.target.closest("[data-caregiver-add-extra]");
  if (addCaregiverExtra) {
    const form = addCaregiverExtra.closest("[data-caregiver-day-form]");
    const list = form?.querySelector("[data-caregiver-extra-list]");
    if (!form || !list) return;
    list.insertAdjacentHTML("beforeend", caregiverExtraRowHtml());
    list.querySelector("[data-caregiver-extra]:last-child input")?.focus();
    updateCaregiverDayFormTotals(form);
    return;
  }

  const removeCaregiverExtra = event.target.closest("[data-caregiver-remove-extra]");
  if (removeCaregiverExtra) {
    const form = removeCaregiverExtra.closest("[data-caregiver-day-form]");
    if (!form) return;
    removeCaregiverExtra.closest("[data-caregiver-extra]")?.remove();
    updateCaregiverDayFormTotals(form);
    return;
  }

  const clearCaregiverDay = event.target.closest("[data-caregiver-clear-day]");
  if (clearCaregiverDay) {
    if (!window.confirm(uiText("caregiver.confirmClear", "Clear this caregiver record?"))) return;
    try {
      await deleteCaregiverDay(state.selectedDate);
      render();
    } catch (error) {
      window.alert(uiText("dialog.caregiverDaySaveError", "Could not save caregiver record: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  if (event.target.closest("[data-caregiver-retry]")) {
    state.caregiver = { key: "", loadingKey: "", error: "", data: null };
    render();
    return;
  }

  const addEventMode = event.target.closest("[data-add-event-mode]");
  if (addEventMode) {
    if (state.addEventMode === "normal") collectAddEventDraft();
    state.addEventMode = addEventMode.dataset.addEventMode === "preset" ? "preset" : "normal";
    if (state.addEventMode === "normal") state.eventPresetDraft = null;
    render();
    return;
  }

  const useEventPreset = event.target.closest("[data-use-event-preset]");
  if (useEventPreset) {
    ensureEventPresets();
    const preset = state.eventPresets.items.find((item) => item.id === useEventPreset.dataset.useEventPreset);
    if (!preset) return;
    state.eventPresetDraft = cloneValue(preset);
    state.addEventDraft = cloneValue(preset);
    state.addEventMode = "normal";
    state.currentCollection = preset.shareFamily ? "owner:family" : defaultPersonalCollectionViewId();
    render();
    return;
  }

  const editEventPreset = event.target.closest("[data-edit-event-preset]");
  if (editEventPreset) {
    state.eventPresets.editingId = editEventPreset.dataset.editEventPreset;
    state.eventPresets.expanded = true;
    render();
    return;
  }

  if (event.target.closest("[data-event-preset-new]")) {
    state.eventPresets.editingId = "";
    state.eventPresets.expanded = true;
    render();
    return;
  }

  if (event.target.closest("[data-event-presets-retry]")) {
    state.eventPresets.checked = false;
    state.eventPresets.error = "";
    loadEventPresetsFromBrain({ force: true });
    return;
  }

  const deleteEventPreset = event.target.closest("[data-delete-event-preset]");
  if (deleteEventPreset) {
    if (!window.confirm(uiText("dialog.deleteEventPreset", "Delete this event preset?"))) return;
    try {
      await deleteEventPresetFromBrain(deleteEventPreset.dataset.deleteEventPreset || "");
      state.eventPresets.expanded = true;
    } catch (error) {
      window.alert(uiText("dialog.eventPresetError", "Could not update event preset: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const editRecurring = event.target.closest("[data-edit-recurring]");
  if (editRecurring) {
    state.recurringTasks.editingId = editRecurring.dataset.editRecurring || "";
    state.recurringTasks.expanded = true;
    render();
    return;
  }

  if (event.target.closest("[data-recurring-new]")) {
    state.recurringTasks.editingId = "";
    state.recurringTasks.expanded = true;
    render();
    return;
  }

  if (event.target.closest("[data-recurring-retry]")) {
    state.recurringTasks.checked = false;
    state.recurringTasks.error = "";
    loadRecurringTasks({ force: true });
    return;
  }

  if (event.target.closest("[data-holidays-retry]")) {
    state.holidays.checked = false;
    state.holidays.error = "";
    loadHolidays({ force: true });
    return;
  }

  if (event.target.closest("[data-custom-events-retry]")) {
    state.customEvents.checked = false;
    state.customEvents.error = "";
    loadCustomEvents({ force: true });
    return;
  }

  if (event.target.closest("[data-governor-settings-retry]")) {
    state.governorSettings.checked = false;
    state.governorSettings.error = "";
    loadGovernorSettingsStatus({ force: true });
    return;
  }

  if (event.target.closest("[data-mail-organizer-retry]")) {
    state.mailOrganizer.checked = false;
    state.mailOrganizer.error = "";
    loadMailOrganizerSettings({ force: true });
    return;
  }

  if (event.target.closest("[data-mail-organizer-send]")) {
    try {
      await sendMailOrganizerNow();
    } catch (error) {
      window.alert(`Could not send mail organizer: ${error.message || "unknown error"}`);
    }
    return;
  }

  if (event.target.closest("[data-holidays-sync]")) {
    if (!window.confirm(uiText("dialog.syncHolidays", "Sync Korean calendar entries from Google now?"))) return;
    try {
      await syncHolidays();
    } catch (error) {
      window.alert(uiText("dialog.holidayError", "Could not update Korean calendar: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const deleteRecurring = event.target.closest("[data-delete-recurring]");
  if (deleteRecurring) {
    if (!window.confirm(uiText("dialog.deleteRecurringTask", "Delete this repeating task rule? The current task remains in Radicale."))) return;
    try {
      await deleteRecurringTask(deleteRecurring.dataset.deleteRecurring || "");
    } catch (error) {
      window.alert(uiText("dialog.recurringTaskError", "Could not update repeating task: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const deleteEvent = event.target.closest("[data-delete-event]");
  if (deleteEvent) {
    if (!window.confirm(uiText("dialog.deleteEvent", "Delete this event? Repeating events will be deleted as a series."))) return;
    const uid = deleteEvent.dataset.eventId || "";
    const collectionId = deleteEvent.dataset.collectionId || "";
    try {
      if (state.remoteCalendar.live) await deleteRemoteCalendarItem("events", uid, collectionId);
      else mockAdapter.deleteEvent(uid);
      window.location.hash = "#/calendar";
      render();
    } catch (error) {
      window.alert(uiText("dialog.radicaleDeleteError", "Could not delete from Radicale: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const deleteTask = event.target.closest("[data-delete-task]");
  if (deleteTask) {
    if (!window.confirm(uiText("dialog.deleteTask", "Delete this task?"))) return;
    const uid = deleteTask.dataset.taskId || "";
    const collectionId = deleteTask.dataset.collectionId || "";
    try {
      if (state.remoteCalendar.live) await deleteRemoteCalendarItem("tasks", uid, collectionId);
      else mockAdapter.deleteTask(uid);
      window.location.hash = "#/tasks";
      render();
    } catch (error) {
      window.alert(uiText("dialog.radicaleDeleteError", "Could not delete from Radicale: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  if (event.target.closest("[data-rouny-new]")) {
    collectRounyDraft();
    state.rouny.draft = defaultRounyTemplate(uiText("rouny.newTemplate", "New template"));
    state.rouny.selectedTemplateId = state.rouny.draft.id;
    state.rouny.undoStack = [];
    state.rouny.page = "detail";
    state.rouny.editingItemId = "";
    state.rouny.editingItemDraft = null;
    render();
    return;
  }

  if (event.target.closest("[data-rouny-sync-retry]")) {
    state.rouny.remoteChecked = false;
    state.rouny.remoteLive = false;
    state.rouny.syncState = "loading";
    render();
    loadRemoteRounyTemplates({ force: true });
    return;
  }

  if (event.target.closest("[data-rouny-use-server]")) {
    if (!state.rouny.remoteDocument) return;
    applyRemoteRounyDocument(state.rouny.remoteDocument);
    state.rouny.syncState = "synced";
    render();
    return;
  }

  if (event.target.closest("[data-rouny-use-local]")) {
    const revision = Math.max(0, Number(state.rouny.remoteDocument?.revision) || state.rouny.revision || 0);
    state.rouny.revision = revision;
    state.rouny.remoteDocument = null;
    state.rouny.remoteLive = true;
    state.rouny.syncState = "saving";
    persistRounyTemplates(state.rouny.templates, { revision, dirty: true });
    queueRounyRemoteSave();
    render();
    return;
  }

  if (event.target.closest("[data-rouny-back]")) {
    collectRounyDraft();
    state.rouny.page = "list";
    state.rouny.editingItemId = "";
    state.rouny.editingItemDraft = null;
    render();
    return;
  }

  if (event.target.closest("[data-rouny-rename]")) {
    collectRounyDraft();
    const nextName = window.prompt(
      uiText("dialog.renameTemplate", "New template name"),
      state.rouny.draft.name,
    );
    if (nextName === null) return;
    const normalizedName = nextName.trim();
    if (!normalizedName) {
      window.alert(uiText("dialog.templateNameRequired", "Template name is required."));
      return;
    }
    pushRounyUndo();
    state.rouny.draft = normalizeRounyTemplate({
      ...state.rouny.draft,
      name: normalizedName,
    });
    render();
    return;
  }

  const rounySelect = event.target.closest("[data-rouny-select]");
  if (rounySelect) {
    selectRounyTemplate(rounySelect.dataset.rounySelect);
    render();
    return;
  }

  const rounyDelete = event.target.closest("[data-rouny-delete]");
  if (rounyDelete) {
    deleteRounyTemplate(rounyDelete.dataset.rounyDelete);
    render();
    return;
  }

  if (event.target.closest("[data-rouny-add-item]")) {
    collectRounyDraft();
    const item = defaultRounyItem();
    state.rouny.editingItemId = item.id;
    state.rouny.editingItemDraft = item;
    render();
    return;
  }

  const rounyGridItem = event.target.closest("[data-rouny-grid-item]");
  if (rounyGridItem) {
    event.preventDefault();
    if (suppressRounyGridClick) return;
    openRounyClassEditor(rounyGridItem.dataset.rounyGridItem);
    return;
  }

  if (event.target.closest("[data-rouny-close-layer]")) {
    state.rouny.editingItemId = "";
    state.rouny.editingItemDraft = null;
    render();
    return;
  }

  const rounyRemoveItem = event.target.closest("[data-rouny-remove-item]");
  if (rounyRemoveItem) {
    collectRounyDraft();
    pushRounyUndo();
    if (state.rouny.draft.items.length <= 1) {
      state.rouny.draft.items = [defaultRounyItem()];
    } else {
      state.rouny.draft.items = state.rouny.draft.items.filter((item) => item.id !== rounyRemoveItem.dataset.rounyRemoveItem);
    }
    state.rouny.editingItemId = "";
    state.rouny.editingItemDraft = null;
    render();
    return;
  }

  if (event.target.closest("[data-rouny-add-slot]")) {
    const form = event.target.closest("[data-rouny-class-form]");
    if (!form) return;
    const item = itemFromRounyClassForm(form);
    if (state.rouny.draft.items.some((draftItem) => draftItem.id === item.id)) pushRounyUndo();
    item.slots.push(defaultRounySlot());
    if (state.rouny.draft.items.some((draftItem) => draftItem.id === item.id)) upsertRounyDraftItem(item);
    else state.rouny.editingItemDraft = item;
    state.rouny.editingItemId = item.id;
    render();
    return;
  }

  const rounyRemoveSlot = event.target.closest("[data-rouny-remove-slot]");
  if (rounyRemoveSlot) {
    const form = event.target.closest("[data-rouny-class-form]");
    if (!form) return;
    const item = itemFromRounyClassForm(form);
    if (state.rouny.draft.items.some((draftItem) => draftItem.id === item.id)) pushRounyUndo();
    item.slots = item.slots.length <= 1 ? item.slots : item.slots.filter((slot) => slot.id !== rounyRemoveSlot.dataset.rounyRemoveSlot);
    if (state.rouny.draft.items.some((draftItem) => draftItem.id === item.id)) upsertRounyDraftItem(item);
    else state.rouny.editingItemDraft = item;
    state.rouny.editingItemId = item.id;
    render();
    return;
  }

  if (event.target.closest("[data-rouny-save]")) {
    if (saveRounyDraft()) render();
    return;
  }

  if (event.target.closest("[data-rouny-save-as]")) {
    if (saveRounyDraft({ asCopy: true })) render();
    return;
  }

  if (event.target.closest("[data-rouny-undo]")) {
    if (undoRounyDraft()) render();
    return;
  }

  if (event.target.closest("[data-rouny-reset]")) {
    if (resetRounyDraftToSaved()) render();
    return;
  }

  if (event.target.closest("[data-rouny-print]")) {
    collectRounyDraft();
    render();
    window.setTimeout(() => window.print(), 50);
    return;
  }

  const day = event.target.closest("[data-date]");
  if (day) {
    const previousMonth = state.selectedDate.slice(0, 7);
    if (getRoute() === "add-event" || (getRoute() === "add" && state.addKind === "event")) collectAddEventDraft();
    if (getRoute() === "add-task" || (getRoute() === "add" && state.addKind === "task")) collectAddTaskDraft();
    state.selectedDate = day.dataset.date;
    if (getRoute() === "add-task" || getRoute() === "edit-task" || (getRoute() === "add" && state.addKind === "task")) state.taskDueEnabled = true;
    if (state.addTaskDraft) {
      state.addTaskDraft.selectedDate = state.selectedDate;
      state.addTaskDraft.due = state.taskDueEnabled ? state.selectedDate : "";
      state.addTaskDraft.dueEnabled = state.taskDueEnabled;
    }
    render();
    if (state.selectedDate.slice(0, 7) !== previousMonth) loadRemoteWeatherForSelectedMonth();
    return;
  }

  const collection = event.target.closest("[data-collection]");
  if (collection) {
    if (getRoute() === "add-event" || (getRoute() === "add" && state.addKind === "event")) collectAddEventDraft();
    if (getRoute() === "add-task" || (getRoute() === "add" && state.addKind === "task")) collectAddTaskDraft();
    state.currentCollection = collection.dataset.collection;
    render();
    return;
  }

  const monthShift = event.target.closest("[data-month-shift]");
  if (monthShift) {
    const previousMonth = state.selectedDate.slice(0, 7);
    if (getRoute() === "add-event" || (getRoute() === "add" && state.addKind === "event")) collectAddEventDraft();
    if (getRoute() === "add-task" || (getRoute() === "add" && state.addKind === "task")) collectAddTaskDraft();
    shiftSelectedMonth(Number(monthShift.dataset.monthShift));
    if (state.addTaskDraft && state.taskDueEnabled) state.addTaskDraft.due = state.selectedDate;
    render();
    if (getRoute() !== "caregiver" && state.selectedDate.slice(0, 7) !== previousMonth) loadRemoteWeatherForSelectedMonth();
    return;
  }

  if (event.target.closest("[data-month-today]")) {
    const previousMonth = state.selectedDate.slice(0, 7);
    if (getRoute() === "add-event" || (getRoute() === "add" && state.addKind === "event")) collectAddEventDraft();
    if (getRoute() === "add-task" || (getRoute() === "add" && state.addKind === "task")) collectAddTaskDraft();
    selectToday();
    if (state.addTaskDraft && state.taskDueEnabled) state.addTaskDraft.due = state.selectedDate;
    render();
    if (getRoute() !== "caregiver" && state.selectedDate.slice(0, 7) !== previousMonth) loadRemoteWeatherForSelectedMonth();
    return;
  }

  if (event.target.closest("[data-toggle-add-month]")) {
    if (getRoute() === "add-event" || (getRoute() === "add" && state.addKind === "event")) collectAddEventDraft();
    if (getRoute() === "add-task" || (getRoute() === "add" && state.addKind === "task")) collectAddTaskDraft();
    state.addMonthExpanded = !state.addMonthExpanded;
    render();
    return;
  }

  if (event.target.closest("[data-clear-task-due]")) {
    collectAddTaskDraft();
    state.taskDueEnabled = false;
    const form = event.target.closest("form");
    const timeInput = form?.querySelector('input[name="dueTime"]');
    if (timeInput) {
      timeInput.value = "";
    }
    if (state.addTaskDraft) {
      state.addTaskDraft.due = "";
      state.addTaskDraft.dueTime = "";
      state.addTaskDraft.dueEnabled = false;
    }
    render();
    return;
  }

  if (event.target.closest("[data-use-selected-due]")) {
    collectAddTaskDraft();
    state.taskDueEnabled = true;
    if (state.addTaskDraft) {
      state.addTaskDraft.due = state.selectedDate;
      state.addTaskDraft.dueEnabled = true;
    }
    render();
    return;
  }

  const check = event.target.closest(".checkButton");
  if (check) {
    const row = check.closest("[data-task-id]");
    if (!row) return;
    const rawTask = activeCalendarData().tasks.find((task) => task.uid === row.dataset.taskId);
    if (!rawTask) return;
    const previousStatus = rawTask.status || "NEEDS-ACTION";
    const previousCompleted = rawTask.completed;
    if (rawTask.status === "COMPLETED") {
      rawTask.status = "NEEDS-ACTION";
      delete rawTask.completed;
    } else {
      rawTask.status = "COMPLETED";
      rawTask.completed = new Date().toISOString().slice(0, 19);
    }
    state.pendingTaskStatuses[rawTask.uid] = {
      status: rawTask.status,
      completed: rawTask.completed || "",
    };
    render();
    if (state.remoteCalendar.live) {
      try {
        const formData = new FormData();
        formData.set("uid", rawTask.uid);
        formData.set("collectionId", rawTask.collection || "");
        formData.set("title", rawTask.summary || "");
        formData.set("memo", taskDescription(rawTask));
        formData.set("due", rawTask.due || "");
        formData.set("dueTime", rawTask.dueTime || "");
        formData.set("priority", rawTask.priority || "");
        formData.set("status", rawTask.status || "NEEDS-ACTION");
        await updateRemoteTask(formData, { navigate: false });
        delete state.pendingTaskStatuses[rawTask.uid];
      } catch (error) {
        delete state.pendingTaskStatuses[rawTask.uid];
        rawTask.status = previousStatus;
        if (previousCompleted) rawTask.completed = previousCompleted;
        else delete rawTask.completed;
        window.alert(uiText("dialog.taskSaveError", "Could not save task: {error}", {
          error: error.message || uiText("dialog.unknownError", "unknown error"),
        }));
        await loadRemoteCalendar();
        render();
      }
    } else {
      delete state.pendingTaskStatuses[rawTask.uid];
    }
    return;
  }

  const subtaskToggle = event.target.closest("[data-subtask-line]");
  if (subtaskToggle) {
    const row = subtaskToggle.closest("[data-task-id]");
    const rawTask = activeCalendarData().tasks.find((task) => task.uid === row?.dataset.taskId);
    if (!rawTask) return;

    const lineIndex = Number(subtaskToggle.dataset.subtaskLine);
    const lines = taskDescription(rawTask).split(/\r?\n/);
    const line = lines[lineIndex] || "";
    const marker = legacySubtaskMarker(line);
    if (!marker) return;

    const previousDescription = taskDescription(rawTask);
    lines[lineIndex] = setLegacySubtaskLine(line, !marker.done);
    const nextDescription = lines.join("\n");
    rawTask.description = nextDescription;
    state.taskDescriptions[rawTask.uid] = nextDescription;
    render();
    if (state.remoteCalendar.live) {
      try {
        const formData = new FormData();
        formData.set("uid", rawTask.uid);
        formData.set("collectionId", rawTask.collection || "");
        formData.set("title", rawTask.summary || "");
        formData.set("memo", nextDescription);
        formData.set("due", rawTask.due || "");
        formData.set("dueTime", rawTask.dueTime || "");
        formData.set("priority", rawTask.priority || "");
        await updateRemoteTask(formData, { navigate: false });
      } catch (error) {
        rawTask.description = previousDescription;
        state.taskDescriptions[rawTask.uid] = previousDescription;
        window.alert(uiText("dialog.taskSaveError", "Could not save task: {error}", {
          error: error.message || uiText("dialog.unknownError", "unknown error"),
        }));
        await loadRemoteCalendar();
        render();
      }
    }
  }
});

document.addEventListener("submit", async (event) => {
  const mailOrganizerForm = event.target.closest("[data-mail-organizer-form]");
  if (mailOrganizerForm) {
    event.preventDefault();
    try {
      await saveMailOrganizerSettings(mailOrganizerForm);
    } catch (error) {
      window.alert(`Could not update mail organizer: ${error.message || "unknown error"}`);
    }
    return;
  }

  const ledgerEditor = event.target.closest("[data-ledger-editor]");
  if (ledgerEditor) {
    event.preventDefault();
    try {
      await saveLedgerEntry(ledgerEditor);
    } catch (error) {
      window.alert(uiText("dialog.ledgerSaveError", "Could not save ledger entry: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const documentUploadForm = event.target.closest("[data-document-upload]");
  if (documentUploadForm) {
    event.preventDefault();
    const input = documentUploadForm.querySelector('input[type="file"]');
    const file = input?.files?.[0];
    if (!file) return;
    if (file.type && file.type !== "application/pdf") {
      window.alert("Select a PDF file.");
      return;
    }
    const button = documentUploadForm.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      await uploadDocument(file);
      documentUploadForm.reset();
    } catch (error) {
      window.alert(`Could not upload PDF: ${error.message || "unknown error"}`);
    } finally {
      if (button) button.disabled = false;
    }
    return;
  }

  const supplyForm = event.target.closest("[data-create-supply]");
  if (supplyForm) {
    event.preventDefault();
    const formData = new FormData(supplyForm);
    try {
      await createSupply(String(formData.get("title") || "").trim());
      supplyForm.reset();
    } catch (error) {
      window.alert(`Could not add supply: ${error.message || "unknown error"}`);
    }
    return;
  }

  const caregiverDayForm = event.target.closest("[data-caregiver-day-form]");
  if (caregiverDayForm) {
    event.preventDefault();
    try {
      await saveCaregiverDay(caregiverDayPayloadFromForm(caregiverDayForm));
      render();
    } catch (error) {
      window.alert(uiText("dialog.caregiverDaySaveError", "Could not save caregiver record: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const caregiverSettingsForm = event.target.closest("[data-caregiver-settings-form]");
  if (caregiverSettingsForm) {
    event.preventDefault();
    try {
      await saveCaregiverSettings(new FormData(caregiverSettingsForm));
      render();
    } catch (error) {
      window.alert(uiText("dialog.caregiverSaveError", "Could not save caregiver settings: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const eventPresetForm = event.target.closest("[data-event-preset-form]");
  if (eventPresetForm) {
    event.preventDefault();
    const preset = eventPresetFromForm(eventPresetForm);
    if (!preset.name.trim() || !preset.title.trim()) {
      window.alert(uiText("dialog.presetFieldsRequired", "Preset name and title are required."));
      return;
    }
    try {
      await upsertEventPreset(preset);
      state.eventPresets.editingId = "";
      state.eventPresets.expanded = true;
    } catch (error) {
      window.alert(uiText("dialog.eventPresetError", "Could not update event preset: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const recurringForm = event.target.closest("[data-recurring-form]");
  if (recurringForm) {
    event.preventDefault();
    try {
      await saveRecurringTask(recurringForm.dataset.recurringId || "", recurringTaskPayloadFromForm(recurringForm));
      state.recurringTasks.expanded = true;
    } catch (error) {
      window.alert(uiText("dialog.recurringTaskError", "Could not update repeating task: {error}", {
        error: error.message || uiText("dialog.unknownError", "unknown error"),
      }));
    }
    return;
  }

  const rounyClassForm = event.target.closest("[data-rouny-class-form]");
  if (rounyClassForm) {
    event.preventDefault();
    snapRounyClassFormTimes(rounyClassForm);
    const { item, validation } = updateRounyClassFormValidation(rounyClassForm);
    const hasInvalidItemTime = item.slots.some((slot) =>
      validation.invalidKeys.has(rounySlotValidationKey(item.id, slot.id)),
    );
    if (hasInvalidItemTime) {
      window.alert(uiText("rouny.fixInvalidClassTime", "End time must be later than start time."));
      rounyClassForm.querySelector(".rounySlotRow.hasInvalidTime [name=\"slotEnd\"]")?.focus();
      return;
    }
    pushRounyUndo();
    upsertRounyDraftItem(item);
    state.rouny.editingItemId = "";
    state.rouny.editingItemDraft = null;
    render();
    return;
  }

  if (event.target.closest("[data-rouny-editor]")) {
    event.preventDefault();
    if (saveRounyDraft()) render();
    return;
  }

  const eventForm = event.target.closest("[data-create-event]");
  if (eventForm) {
    event.preventDefault();
    const formData = new FormData(eventForm);
    if (state.remoteCalendar.live) {
      persistComposerRecovery("event", eventForm);
      try {
        await createRemoteEvent(formData);
        clearComposerRecovery();
        state.eventPresetDraft = null;
        state.addEventDraft = null;
      } catch (error) {
        if (!recoverComposerConnection(error, "event", eventForm)) {
          clearComposerRecovery();
          window.alert(uiText("dialog.radicaleSaveError", "Could not save to Radicale: {error}", {
            error: error.message || uiText("dialog.unknownError", "unknown error"),
          }));
        }
      }
      return;
    }
    mockAdapter.createEvent(formData);
    state.eventPresetDraft = null;
    state.addEventDraft = null;
    window.location.hash = "#/calendar";
    render();
    return;
  }

  const editEventForm = event.target.closest("[data-edit-event]");
  if (editEventForm) {
    event.preventDefault();
    const formData = new FormData(editEventForm);
    if (state.remoteCalendar.live) {
      try {
        await updateRemoteEvent(formData);
      } catch (error) {
        window.alert(uiText("dialog.radicaleSaveError", "Could not save to Radicale: {error}", {
          error: error.message || uiText("dialog.unknownError", "unknown error"),
        }));
      }
      return;
    }
    mockAdapter.updateEvent(formData);
    window.location.hash = "#/calendar";
    render();
    return;
  }

  const taskForm = event.target.closest("[data-create-task]");
  if (taskForm) {
    event.preventDefault();
    const formData = new FormData(taskForm);
    const due = taskDueFromForm(formData);
    if (taskDueHasPassed(due) && !window.confirm(uiText("dialog.createPastDue", "This due time has already passed. Create it anyway?"))) return;
    if (state.remoteCalendar.live) {
      persistComposerRecovery("task", taskForm);
      try {
        await createRemoteTask(formData);
        clearComposerRecovery();
        state.addTaskDraft = null;
      } catch (error) {
        if (!recoverComposerConnection(error, "task", taskForm)) {
          clearComposerRecovery();
          window.alert(uiText("dialog.radicaleSaveError", "Could not save to Radicale: {error}", {
            error: error.message || uiText("dialog.unknownError", "unknown error"),
          }));
        }
      }
      return;
    }
    mockAdapter.createTask(formData);
    state.addTaskDraft = null;
    window.location.hash = "#/tasks";
    render();
  }

  const editTaskForm = event.target.closest("[data-edit-task]");
  if (editTaskForm) {
    event.preventDefault();
    const formData = new FormData(editTaskForm);
    const due = taskDueFromForm(formData);
    if (taskDueHasPassed(due) && !window.confirm(uiText("dialog.savePastDue", "This due time has already passed. Save it anyway?"))) return;
    if (state.remoteCalendar.live) {
      try {
        await updateRemoteTask(formData);
      } catch (error) {
        window.alert(uiText("dialog.radicaleSaveError", "Could not save to Radicale: {error}", {
          error: error.message || uiText("dialog.unknownError", "unknown error"),
        }));
      }
      return;
    }
    mockAdapter.updateTask(formData);
    window.location.hash = "#/tasks";
    render();
  }
});

document.addEventListener("keydown", (event) => {
  const block = event.target.closest("[data-rouny-grid-item]");
  if (!block || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  openRounyClassEditor(block.dataset.rounyGridItem);
});

document.addEventListener("pointerdown", (event) => {
  const block = event.target.closest("[data-rouny-grid-item]");
  if (!block || (event.pointerType === "mouse" && event.button !== 0)) return;
  const item = state.rouny.draft?.items.find((candidate) => candidate.id === block.dataset.rounyGridItem);
  const slot = item?.slots?.find((candidate) => candidate.id === block.dataset.rounySlotId);
  if (!item || !slot) return;
  const duration = Math.max(
    ROUNY_TIMELINE_SLOT_MINUTES,
    rounyMinutes(slot.endTime) - rounyMinutes(slot.startTime),
  );
  block.setPointerCapture?.(event.pointerId);
  const holdTimer = window.setTimeout(() => {
    if (rounyPointerDrag?.pointerId === event.pointerId) rounyPointerDrag.canDrag = true;
  }, ROUNY_DRAG_HOLD_MS);
  rounyPointerDrag = {
    itemId: item.id,
    slotId: slot.id,
    duration,
    pointerId: event.pointerId,
    holdTimer,
    canDrag: false,
    startX: event.clientX,
    startY: event.clientY,
    moved: false,
    target: null,
    element: block,
  };
});

document.addEventListener("pointermove", (event) => {
  const drag = rounyPointerDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  if (!drag.canDrag) return;
  const moved =
    drag.moved ||
    Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >= ROUNY_DRAG_MOVE_THRESHOLD;
  if (!moved) return;
  event.preventDefault();
  drag.moved = true;
  drag.element.classList.add("isDragging");
  document.body.classList.add("isRounyDragging");
  drag.target = rounyDragTargetFromPoint(event.clientX, event.clientY);
  updateRounyDragFeedback(drag.target, event.clientX, event.clientY);
});

document.addEventListener("pointerup", (event) => {
  const drag = rounyPointerDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  if (drag.moved) {
    event.preventDefault();
    collectRounyDraft();
    if (drag.target) {
      pushRounyUndo();
      moveRounyDraftSlot(drag.itemId, drag.slotId, drag.target.dayOfWeek, drag.target.startMinutes);
    }
  }
  const moved = drag.moved;
  const itemId = drag.itemId;
  clearRounyPointerDrag();
  if (!moved) {
    event.preventDefault();
    suppressRounyGridClick = true;
    openRounyClassEditor(itemId);
    window.setTimeout(() => {
      suppressRounyGridClick = false;
    }, 80);
    return;
  }
  suppressRounyGridClick = true;
  render();
  window.setTimeout(() => {
    suppressRounyGridClick = false;
  }, 80);
});

document.addEventListener("pointercancel", (event) => {
  if (!rounyPointerDrag || rounyPointerDrag.pointerId !== event.pointerId) return;
  clearRounyPointerDrag();
});

document.addEventListener("dragstart", (event) => {
  const row = event.target.closest("[data-rouny-template-id]");
  if (!row) return;
  state.rouny.dragTemplateId = row.dataset.rounyTemplateId;
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", state.rouny.dragTemplateId);
});

document.addEventListener("dragover", (event) => {
  const row = event.target.closest("[data-rouny-template-id]");
  if (!row || !state.rouny.dragTemplateId) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
});

document.addEventListener("drop", (event) => {
  const row = event.target.closest("[data-rouny-template-id]");
  if (!row || !state.rouny.dragTemplateId) return;
  event.preventDefault();
  reorderRounyTemplates(state.rouny.dragTemplateId, row.dataset.rounyTemplateId);
  state.rouny.dragTemplateId = "";
  render();
});

document.addEventListener("dragend", () => {
  state.rouny.dragTemplateId = "";
});

document.addEventListener(
  "toggle",
  (event) => {
    const disclosure = event.target;
    if (!(disclosure instanceof HTMLDetailsElement)) return;
    if (disclosure.matches("[data-event-presets]")) state.eventPresets.expanded = disclosure.open;
    if (disclosure.matches("[data-recurring-tasks]")) state.recurringTasks.expanded = disclosure.open;
    if (disclosure.matches("[data-holidays]")) state.holidays.expanded = disclosure.open;
    if (disclosure.matches("[data-custom-events]")) state.customEvents.expanded = disclosure.open;
    if (disclosure.matches("[data-mail-organizer]")) state.mailOrganizer.expanded = disclosure.open;
  },
  true,
);

document.addEventListener("input", (event) => {
  const caregiverForm = event.target.closest("[data-caregiver-day-form]");
  if (caregiverForm) updateCaregiverDayFormTotals(caregiverForm);

  const rounyClassForm = event.target.closest("[data-rouny-class-form]");
  if (rounyClassForm) updateRounyClassFormValidation(rounyClassForm);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.weatherLocationPopup.open) {
    closeWeatherLocationPopup();
    return;
  }
  const weatherTrigger = event.target.closest("[data-open-weather-locations]");
  if (
    !weatherTrigger
    || event.target.closest("[data-current-location-weather]")
    || (event.key !== "Enter" && event.key !== " ")
  ) return;
  event.preventDefault();
  weatherTrigger.click();
});

document.addEventListener("change", async (event) => {
  const organizerFrequency = event.target.closest('[data-mail-organizer-form] [name="runsPerDay"]');
  if (organizerFrequency) {
    const form = organizerFrequency.closest("[data-mail-organizer-form]");
    state.mailOrganizer.settings.firstTime = form?.querySelector('[name="firstTime"]')?.value || state.mailOrganizer.settings.firstTime;
    state.mailOrganizer.settings.secondTime = form?.querySelector('[name="secondTime"]')?.value || state.mailOrganizer.settings.secondTime;
    state.mailOrganizer.settings.runsPerDay = Number(organizerFrequency.value) === 2 ? 2 : 1;
    render();
    return;
  }

  const customEventToggle = event.target.closest("[data-custom-event-setting]");
  if (customEventToggle) {
    const key = customEventToggle.dataset.customEventSetting || "";
    const checked = customEventToggle.checked;
    customEventToggle.disabled = true;
    saveCustomEvents({ [key]: checked }).catch((error) => {
      customEventToggle.checked = !checked;
      window.alert(`Could not update custom events: ${error.message || "unknown error"}`);
    });
    return;
  }

  const holidayToggle = event.target.closest("[data-holiday-classification]");
  if (holidayToggle) {
    const uid = holidayToggle.dataset.holidayClassification || "";
    const checked = holidayToggle.checked;
    holidayToggle.disabled = true;
    setHolidayClassification(uid, checked)
      .catch((error) => {
        holidayToggle.checked = !checked;
        window.alert(uiText("dialog.holidayError", "Could not update Korean calendar: {error}", {
          error: error.message || uiText("dialog.unknownError", "unknown error"),
        }));
      })
      .finally(() => {
        holidayToggle.disabled = false;
        if (getRoute() === "settings") render();
      });
    return;
  }

  const ledgerRange = event.target.closest("[data-ledger-range-select]");
  if (ledgerRange) {
    const range = ledgerRange.value || "all";
    if (!LEDGER_RANGES.has(range) || state.ledger.range === range) return;
    state.ledger.range = range;
    if (range === "custom" && (!state.ledger.rangeStart || !state.ledger.rangeEnd)) {
      const today = ymd(new Date());
      const start = new Date(`${today}T00:00:00`);
      start.setMonth(start.getMonth() - 1);
      state.ledger.rangeStart = ymd(start);
      state.ledger.rangeEnd = today;
    }
    render();
    return;
  }

  const ledgerRangeStart = event.target.closest("[data-ledger-range-start]");
  if (ledgerRangeStart) {
    state.ledger.rangeStart = ledgerRangeStart.value;
    if (state.ledger.rangeEnd && state.ledger.rangeStart > state.ledger.rangeEnd) {
      state.ledger.rangeEnd = state.ledger.rangeStart;
    }
    render();
    return;
  }

  const ledgerRangeEnd = event.target.closest("[data-ledger-range-end]");
  if (ledgerRangeEnd) {
    state.ledger.rangeEnd = ledgerRangeEnd.value;
    if (state.ledger.rangeStart && state.ledger.rangeEnd < state.ledger.rangeStart) {
      state.ledger.rangeStart = state.ledger.rangeEnd;
    }
    render();
    return;
  }

  const caregiverForm = event.target.closest("[data-caregiver-day-form]");
  if (caregiverForm) updateCaregiverDayFormTotals(caregiverForm);

  const rounyClassForm = event.target.closest("[data-rouny-class-form]");
  if (rounyClassForm) {
    snapRounyTimeInput(event.target);
    updateRounyClassFormValidation(rounyClassForm);
  }

  const weatherLocation = event.target.closest("[data-weather-location-setting]");
  if (weatherLocation) {
    await saveWeatherLocationPreference(weatherLocation.value);
    return;
  }

  const mainFont = event.target.closest("[data-main-font-setting]");
  if (mainFont) {
    setMainFontPreference(mainFont.value);
    return;
  }

  const familyFont = event.target.closest("[data-family-font-setting]");
  if (familyFont) {
    setFamilyFontPreference(familyFont.value);
    return;
  }

  const shareFamily = event.target.closest("[data-share-family]");
  if (shareFamily) {
    const eventForm = shareFamily.closest("[data-create-event]");
    const taskForm = shareFamily.closest("[data-create-task]");
    if (eventForm || taskForm) {
      if (eventForm) {
        collectAddEventDraft();
        if (state.addEventDraft) state.addEventDraft.shareFamily = shareFamily.checked;
      }
      if (taskForm) {
        collectAddTaskDraft();
        if (state.addTaskDraft) state.addTaskDraft.shareFamily = shareFamily.checked;
      }
      state.currentCollection = shareFamily.checked ? "owner:family" : defaultPersonalCollectionViewId();
      render();
    }
    return;
  }

  const rounySaturday = event.target.closest("[data-rouny-saturday]");
  if (rounySaturday) {
    state.rouny.includeSaturday = rounySaturday.checked;
    window.localStorage.setItem(ROUNY_INCLUDE_SATURDAY_KEY, String(state.rouny.includeSaturday));
    render();
    return;
  }

  const taskMode = event.target.closest("[data-task-mode]");
  if (taskMode) {
    state.taskMode = taskMode.value;
    render();
    return;
  }

  const taskSort = event.target.closest("[data-task-sort]");
  if (taskSort) {
    state.taskSort = taskSort.value;
    render();
    return;
  }

  const allDayToggle = event.target.closest("[data-all-day-toggle]");
  if (!allDayToggle) return;
  const form = allDayToggle.closest("[data-create-event], [data-edit-event], [data-event-preset-form]");
  if (!form) return;
  form.querySelectorAll("[data-event-time-field]").forEach((field) => {
    const disabled = allDayToggle.checked || field.hasAttribute("data-preserve-disabled");
    field.classList.toggle("isDisabled", disabled);
    field.querySelectorAll("input").forEach((input) => {
      input.disabled = disabled && input.type !== "hidden";
    });
  });
});

document.getElementById("view")?.addEventListener("scroll", updateTopBarShadow, { passive: true });
desktopMedia.addEventListener("change", render);
window.addEventListener("resize", updateOverlayMetrics, { passive: true });

window.setInterval(() => {
  if (portalProfile() === "family" && getRoute() === "today") render();
}, 60_000);

window.addEventListener("hashchange", () => {
  const view = document.getElementById("view");
  if (view) view.scrollTop = 0;
  render();
});

restoreComposerRecovery();
loadWeatherSettings();

if (isAgendaSuppliesEmbed()) {
  document.documentElement.classList.add("isAgendaSuppliesEmbed");
  render();
} else if (!window.location.hash) {
  window.location.hash = `#/${profileConfig().defaultRoute}`;
} else {
  render();
}

loadRemoteCalendar();
