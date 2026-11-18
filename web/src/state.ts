// The app's shared state (signals) and everything that changes it: loading data from the API and
// saving changes back. Components read the signals and call these functions; only this file and
// ``api/client.ts`` know how the server is reached.
import { effect, signal } from "@preact/signals";
import { announce } from "./alerts";
import { api, ApiError, setCsrf } from "./api/client";
import type {
  Board, Card, Me, Meta, Mode, Notification, Person, Settings, Status, Summary, Task, TaskIn,
  TaskPatch, Theme,
} from "./api/types";
import { recall, remember } from "./util";

export type Tab = "board" | "soon" | "alerts" | "me";
export type Seg = Status;
export type ModalName = "new-task" | "password" | "people" | "notif-settings";

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

export const notifications = signal<Notification[]>([]);
export const unread = signal(0);
export const newest = signal(0);
export const settings = signal<Settings | null>(null);

export const banner = signal("");
export const modal = signal<ModalName | null>(null);
export const cardActions = signal<{ id: number; title: string; status: Status } | null>(null);
export const tab = signal<Tab>(remembered("tb-tab", TABS, "board"));
export const seg = signal<Seg>(remembered("tb-seg", SEGS, "todo"));

// While a card is being dragged or swiped, background refreshes wait so the board doesn't jump.
const drag = { active: false, dirty: false };

// ---- small helpers ---------------------------------------------------------------------
let bannerTimer: ReturnType<typeof setTimeout> | undefined;

/** Show a message in the error banner at the top of the page for a few seconds. */
export function showBanner(message: string): void {
  banner.value = message;
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => (banner.value = ""), 6000);
}

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

export function showOlder(): void {
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

export const refreshMeta = coalesced(async () => {
  meta.value = await api.meta();
});

let announcedKey = "";
export const refreshNotifications = coalesced(async () => {
  const user = me.value;
  if (!user) return;
  const [counts, list] = await Promise.all([api.unread(), api.notifications()]);
  unread.value = counts.unread;
  newest.value = counts.newest;
  notifications.value = list;
  // Each browser remembers the newest notification it has announced. A first visit announces
  // nothing old; later ones announce only what arrived since.
  announcedKey = "tb-alerted-" + user.id;
  const stored = recall(announcedKey);
  const seen = stored === null ? counts.newest : Number(stored);
  remember(announcedKey, String(Math.max(seen, counts.newest)));
  const fresh = list.filter((n) => n.id > seen && !n.read && n.announce).reverse();
  if (fresh.length) announce(fresh);
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
  ]);
}

// ---- signing in and out ----------------------------------------------------------------
/** Take a signed-in person: remember their CSRF token, apply their theme, load the page's data. */
export function startSession(user: Me): void {
  setCsrf(user.csrf_token);
  applyTheme(user.theme);
  me.value = user;
  if (!user.must_change_password) void refreshAll();
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
}

export async function signIn(username: string, password: string): Promise<void> {
  const session = await api.signIn(username, password);
  startSession(session.user);
}

export async function signOut(): Promise<void> {
  try {
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

/** Move a card to another column: the board updates at once, then the server confirms. */
export async function moveTask(id: number, status: Status): Promise<void> {
  const current = board.value;
  if (current) {
    const card = (Object.values(current).flat() as Card[]).find((c) => c.id === id);
    if (card && card.status !== status) {
      const next: Board = { todo: [], doing: [], done: [] };
      for (const key of ["todo", "doing", "done"] as const) {
        next[key] = current[key].filter((c) => c.id !== id);
      }
      next[status] = [{ ...card, status }, ...next[status]];
      board.value = next;
    }
  }
  try {
    await api.patchTask(id, { status });
  } catch (error) {
    fail(error);
  }
  void refreshBoard();
  void refreshTask();
  void refreshNotifications();
}

/** Save changes to a task; the drawer shows the server's version afterwards. */
export async function saveTask(id: number, patch: TaskPatch): Promise<void> {
  try {
    const updated = await api.patchTask(id, patch);
    if (openTaskId.value === id) task.value = updated;
  } catch (error) {
    fail(error);
    void refreshTask(); // put the fields back to what the server has
  }
  void refreshBoard();
}

export async function postUpdate(id: number, body: string): Promise<boolean> {
  try {
    const updated = await api.addUpdate(id, body);
    if (openTaskId.value === id) task.value = updated;
    void refreshBoard();
    return true;
  } catch (error) {
    fail(error);
    return false;
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

export const markRead = (id: number) => notificationAction(() => api.markRead(id));
export const markUnread = (id: number) => notificationAction(() => api.markUnread(id));
export const dismissNotification = (id: number) => notificationAction(() => api.dismiss(id));
export const markAllRead = () => notificationAction(() => api.readAll());
export const clearReadNotifications = () => notificationAction(() => api.clearRead());

/** Open a notification's task and mark it read. */
export function openNotification(taskId: number | null, id: number | null): void {
  if (id !== null) void markRead(id);
  if (taskId !== null) openTask(taskId);
}

export async function saveNotificationSetting(kind: string, mode: Mode): Promise<void> {
  settings.value = await api.saveSettings({ [kind]: mode });
}

// ---- people (admin) ------------------------------------------------------------------------
export async function afterPeopleChange(): Promise<void> {
  await Promise.all([refreshPeople(), refreshBoard()]);
}
