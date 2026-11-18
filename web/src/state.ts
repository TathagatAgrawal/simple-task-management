// The app's shared state (signals) and everything that changes it: loading data from the API and
// saving changes back. Components read the signals and call these functions; only this file and
// ``api/client.ts`` know how the server is reached.
import { effect, signal } from "@preact/signals";
import { alertState, forgetDevice, refreshPush, setIconBadge, showOsAlerts, showToasts, systemAlerts } from "./alerts";
import { api, ApiError, setCsrf, setSuccessHandler } from "./api/client";
import type {
  Board, Card, Me, Meta, Mode, Notification, Person, Settings, Status, Summary, Task, TaskIn,
  TaskPatch, Theme, UpdateInfo,
} from "./api/types";
import { recall, remember } from "./util";

export type Tab = "board" | "soon" | "alerts" | "me";
export type Seg = Status;
export type ModalName = "new-task" | "password" | "people" | "notif-settings" | "updates";

const TABS: Tab[] = ["board", "soon", "alerts", "me"];
const SEGS: Seg[] = ["todo", "doing", "done"];

/** A saved choice from localStorage, if it is still one of the allowed values. */
function remembered<T extends string>(key: string, allowed: T[], fallback: T): T {
  const value = recall(key);
  return allowed.find((a) => a === value) ?? fallback;
}

// ---- state ------------------------------------------------------------------------------
/** The signed-in person; ``undefined`` while we're still finding out, ``null`` when signed out. */
export const me = signal<Me | null | undefined>(undefined);
export const meta = signal<Meta | null>(null);
export const people = signal<Person[]>([]);

export const who = signal(recall("tb-who") ?? "me");
export const doneDays = signal(14);
export const board = signal<Board | null>(null);
export const summary = signal<Summary | null>(null);

export const openTaskId = signal<number | null>(null);
export const task = signal<Task | null>(null);

/** Whether a newer version is waiting on GitHub (admins only; null for everyone else). */
export const updateInfo = signal<UpdateInfo | null>(null);

export const notifications = signal<Notification[]>([]);
export const unread = signal(0);
export const newest = signal(0);
export const settings = signal<Settings | null>(null);

export const banner = signal("");
export const search = signal("");
/** What a screen reader should hear after something happens that has no visible message. */
export const liveMessage = signal("");
/** A card that should take keyboard focus once it has been re-rendered in its new column. */
export const focusCardId = signal<number | null>(null);
/** Where the last save of a task field stands, and the problem (if any) next to the field. */
export const saveStatus = signal<"idle" | "saving" | "saved" | "error">("idle");
export const fieldErrors = signal<Record<string, string>>({});
/** Whether the bell's panel is open (the bell reports it to assistive technology). */
export const panelOpen = signal(false);
export const modal = signal<ModalName | null>(null);
export const cardActions = signal<{ id: number; title: string; status: Status } | null>(null);
export const tab = signal<Tab>(remembered("tb-tab", TABS, "board"));
export const seg = signal<Seg>(remembered("tb-seg", SEGS, "todo"));

// While a card is being dragged or swiped, background refreshes wait so the board doesn't jump.
const drag = { active: false, dirty: false };

// ---- small helpers ---------------------------------------------------------------------
/** Show a message in the error banner. It stays until dismissed or the next change succeeds. */
export function showBanner(message: string): void {
  banner.value = message;
}

export function dismissBanner(): void {
  banner.value = "";
}

// Once something saves successfully again, an old error message is out of date.
setSuccessHandler(dismissBanner);

/** Show an error from the API in the banner. */
export function fail(error: unknown): void {
  showBanner(error instanceof ApiError ? error.message : "Something went wrong. Please try again.");
}

/** Run a refresh so that overlapping requests collapse into one extra run at most. */
function coalesced(load: () => Promise<void>): () => Promise<void> {
  let running = false;
  let again = false;
  return async function run() {
    if (running) {
      again = true;
      return;
    }
    running = true;
    try {
      await load();
    } catch (error) {
      fail(error);
    } finally {
      running = false;
    }
    if (again) {
      again = false;
      await run();
    }
  };
}

export function setTab(value: Tab): void {
  tab.value = value;
  remember("tb-tab", value);
  window.scrollTo(0, 0);
}

export function setSeg(value: Seg): void {
  seg.value = value;
  remember("tb-seg", value);
}

export function setWho(value: string): void {
  who.value = value;
  remember("tb-who", value);
  void refreshBoard();
}

let searchLoadedOlder = false;

/** Filter the board and the strip by title. Searching also loads older Done tasks, so they can be found. */
export function setSearch(query: string): void {
  search.value = query;
  if (query.trim() && doneDays.value < 1000) {
    doneDays.value = 3650;
    searchLoadedOlder = true;
    void refreshBoard();
  } else if (!query.trim() && searchLoadedOlder) {
    doneDays.value = 14;
    searchLoadedOlder = false;
    void refreshBoard();
  }
}

export function showOlder(): void {
  searchLoadedOlder = false;
  doneDays.value = 3650;
  void refreshBoard();
}

export function applyTheme(theme: Theme): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

// The phone layout's CSS keys off these attributes on <body>.
effect(() => {
  if (me.value && !me.value.must_change_password) {
    document.body.dataset.tab = tab.value;
    document.body.dataset.seg = seg.value;
  } else {
    delete document.body.dataset.tab;
    delete document.body.dataset.seg;
  }
});

effect(() => {
  document.title = unread.value ? `(${unread.value}) Tasks` : "Tasks";
});

// ---- drag / swipe pause --------------------------------------------------------------------
export function setDragging(active: boolean): void {
  drag.active = active;
  if (!active && drag.dirty) {
    drag.dirty = false;
    void refreshBoard();
  }
}

export function isDragging(): boolean {
  return drag.active;
}

// ---- loading ---------------------------------------------------------------------------------
export const refreshBoard = coalesced(async () => {
  if (!me.value || me.value.must_change_password) return;
  if (drag.active) {
    drag.dirty = true;
    return;
  }
  const [b, s] = await Promise.all([api.board(who.value, doneDays.value), api.summary(who.value)]);
  board.value = b;
  summary.value = s;
});

export const refreshTask = coalesced(async () => {
  const id = openTaskId.value;
  if (id === null) return;
  try {
    const t = await api.task(id);
    if (openTaskId.value === id) task.value = t;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      closeTask(); // it was deleted
      return;
    }
    throw error;
  }
});

export const refreshPeople = coalesced(async () => {
  people.value = await api.people();
});

export const refreshUpdate = coalesced(async () => {
  if (!me.value?.is_admin) return;
  updateInfo.value = await api.update();
});

export const refreshMeta = coalesced(async () => {
  meta.value = await api.meta();
});

// Announcements. A page remembers, in memory, the newest notification it has shown as a message,
// so each open tab announces on its own: two tabs never take each other's messages. A hidden tab
// announces nothing and waits, so what arrived meanwhile appears when the person comes back.
// Desktop alerts use a marker shared between tabs (so they fire once), and only move it when an
// alert was actually sent or the person was looking at the page.
let toastSeen: number | null = null;

export const refreshNotifications = coalesced(async () => {
  const user = me.value;
  if (!user) return;
  const [counts, list] = await Promise.all([api.unread(), api.notifications()]);
  unread.value = counts.unread;
  newest.value = counts.newest;
  notifications.value = list;

  const announceable = list.filter((n) => !n.read && n.announce);
  const looking = document.visibilityState === "visible";
  const focused = looking && document.hasFocus();

  // When this device gets system alerts (push), the page shows none of its own: only the bell number.
  const bySystem = systemAlerts();
  if (bySystem) setIconBadge(counts.unread);

  if (toastSeen === null) toastSeen = counts.newest; // a fresh page announces nothing old
  if (looking) {
    const fresh = announceable.filter((n) => n.id > (toastSeen ?? 0)).reverse();
    toastSeen = Math.max(toastSeen, counts.newest);
    // While the list itself is open the new row appears in it, so a message would only cover its tools.
    const listOpen = panelOpen.value || (tab.value === "alerts" && window.matchMedia("(max-width: 640px)").matches);
    if (fresh.length && !listOpen && !bySystem) showToasts(fresh);
  }

  const osKey = "tb-os-alerted-" + user.id;
  const stored = recall(osKey);
  const osSeen = stored === null ? counts.newest : Number(stored);
  if (alertState.value === "on" && !focused && !bySystem) {
    const fresh = announceable.filter((n) => n.id > osSeen).reverse();
    if (fresh.length) {
      showOsAlerts(fresh);
      remember(osKey, String(Math.max(osSeen, counts.newest)));
    }
  } else if (alertState.value !== "on" || looking || bySystem) {
    remember(osKey, String(Math.max(osSeen, counts.newest)));
  }
});

export const refreshSettings = coalesced(async () => {
  settings.value = await api.settings();
});

/** Reload everything the page shows. */
export async function refreshAll(): Promise<void> {
  await Promise.all([
    refreshBoard(),
    refreshTask(),
    refreshPeople(),
    refreshNotifications(),
    refreshMeta(),
    refreshUpdate(),
  ]);
}

// ---- signing in and out ----------------------------------------------------------------
/** Take a signed-in person: remember their CSRF token, apply their theme, load the page's data. */
export function startSession(user: Me): void {
  setCsrf(user.csrf_token);
  applyTheme(user.theme);
  me.value = user;
  if (!user.must_change_password) {
    void refreshAll();
    void refreshPush();
  }
}

export function endSession(): void {
  me.value = null;
  board.value = null;
  summary.value = null;
  task.value = null;
  openTaskId.value = null;
  notifications.value = [];
  unread.value = 0;
  newest.value = 0;
  modal.value = null;
  setIconBadge(0);
}

export async function signIn(username: string, password: string): Promise<void> {
  const session = await api.signIn(username, password);
  startSession(session.user);
}

export async function signOut(): Promise<void> {
  try {
    await forgetDevice();
    await api.signOut();
  } finally {
    endSession();
  }
}

export async function changeOwnPassword(current: string, next: string, again: string): Promise<void> {
  await api.changePassword(current, next, again);
  const fresh = await api.me();
  startSession(fresh);
}

export async function chooseTheme(theme: Theme): Promise<void> {
  applyTheme(theme);
  try {
    const updated = await api.setTheme(theme);
    me.value = updated;
  } catch (error) {
    fail(error);
  }
}

// ---- tasks -------------------------------------------------------------------------------
export function openTask(id: number): void {
  if (openTaskId.value === id) return;
  openTaskId.value = id;
  task.value = null;
  void refreshTask();
}

export function closeTask(): void {
  openTaskId.value = null;
  task.value = null;
}

let savedTimer: ReturnType<typeof setTimeout> | undefined;

function beginSave(): void {
  clearTimeout(savedTimer);
  saveStatus.value = "saving";
}

function finishSave(fields: string[]): void {
  const rest = { ...fieldErrors.value };
  for (const f of fields) delete rest[f];
  fieldErrors.value = rest;
  saveStatus.value = "saved";
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => (saveStatus.value = "idle"), 2500);
}

function failSave(fields: string[], error: unknown): void {
  const message = error instanceof ApiError ? error.message : "That didn't save. Please try again.";
  const next = { ...fieldErrors.value };
  for (const f of fields) next[f] = message;
  fieldErrors.value = next;
  saveStatus.value = "error";
}

/** Move a card to another column: the board updates at once, then the server confirms. */
export async function moveTask(id: number, status: Status, options: { keepFocus?: boolean } = {}): Promise<void> {
  const current = board.value;
  let title = "";
  if (current) {
    const card = (Object.values(current).flat() as Card[]).find((c) => c.id === id);
    if (card && card.status !== status) {
      title = card.title;
      const next: Board = { todo: [], doing: [], done: [] };
      for (const key of ["todo", "doing", "done"] as const) {
        next[key] = current[key].filter((c) => c.id !== id);
      }
      next[status] = [{ ...card, status }, ...next[status]];
      board.value = next;
      if (options.keepFocus) focusCardId.value = id;
    }
  }
  beginSave();
  try {
    await api.patchTask(id, { status });
    finishSave(["status"]);
    if (title) {
      const label = meta.value?.statuses.find((s) => s.value === status)?.label ?? status;
      liveMessage.value = `Moved “${title}” to ${label}`;
    }
  } catch (error) {
    failSave(["status"], error);
    fail(error);
  }
  void refreshBoard();
  void refreshTask();
  void refreshNotifications();
}

const FIELD_OF: Record<string, string> = {
  title: "title",
  notes: "notes",
  due: "due",
  repeat: "repeat",
  assignee_ids: "assignees",
  status: "status",
};

/** Save changes to a task; the drawer shows the server's version, and any problem beside the field. */
export async function saveTask(id: number, patch: TaskPatch): Promise<void> {
  const fields = Object.keys(patch).map((k) => FIELD_OF[k] ?? k);
  beginSave();
  try {
    const updated = await api.patchTask(id, patch);
    if (openTaskId.value === id) task.value = updated;
    finishSave(fields);
  } catch (error) {
    failSave(fields, error);
    void refreshTask(); // put the fields back to what the server has
  }
  void refreshBoard();
}

/** Post a comment. Returns null on success, or the problem written for the person. */
export async function postUpdate(id: number, body: string): Promise<string | null> {
  beginSave();
  try {
    const updated = await api.addUpdate(id, body);
    if (openTaskId.value === id) task.value = updated;
    void refreshBoard();
    finishSave(["comment"]);
    return null;
  } catch (error) {
    failSave(["comment"], error);
    return error instanceof ApiError ? error.message : "That didn't post. Please try again.";
  }
}

export async function deleteTask(id: number): Promise<void> {
  try {
    await api.deleteTask(id);
  } catch (error) {
    fail(error);
    return;
  }
  if (openTaskId.value === id) closeTask();
  void refreshBoard();
}

export async function createTask(body: TaskIn): Promise<void> {
  const created = await api.createTask(body);
  void refreshBoard();
  openTaskId.value = created.id;
  task.value = created; // open it, so it's visible whatever the filter
}

// ---- notifications ---------------------------------------------------------------------
async function notificationAction(action: () => Promise<void>): Promise<void> {
  try {
    await action();
  } catch (error) {
    fail(error);
  }
  void refreshNotifications();
}

export const markRead = (ids: number[]) =>
  notificationAction(async () => void (await Promise.all(ids.map((id) => api.markRead(id)))));
export const markUnread = (ids: number[]) =>
  notificationAction(async () => void (await Promise.all(ids.map((id) => api.markUnread(id)))));
export const dismissNotifications = (ids: number[]) =>
  notificationAction(async () => void (await Promise.all(ids.map((id) => api.dismiss(id)))));
export const markAllRead = () => notificationAction(() => api.readAll());
export const clearReadNotifications = () => notificationAction(() => api.clearRead());

/** Open a notification's task and mark it read. */
export function openNotification(taskId: number | null, id: number | null): void {
  if (id !== null) void markRead([id]);
  if (taskId !== null) openTask(taskId);
}

export async function saveNotificationSetting(kind: string, mode: Mode): Promise<void> {
  settings.value = await api.saveSettings({ [kind]: mode });
}

// ---- people (admin) ------------------------------------------------------------------------
/** Look at GitHub right now (a few seconds). */
export async function checkForUpdate(): Promise<void> {
  updateInfo.value = await api.checkUpdate();
}

export async function chooseAutoUpdate(on: boolean): Promise<void> {
  updateInfo.value = await api.setAutoUpdate(on);
}

export async function afterPeopleChange(): Promise<void> {
  await Promise.all([refreshPeople(), refreshBoard()]);
}
