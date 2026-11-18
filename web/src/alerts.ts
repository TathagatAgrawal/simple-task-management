// Announcing new notifications: a message on the page whenever it is visible, plus a desktop (OS)
// alert, through the service worker, when the person has turned those on and isn't looking.
import { signal } from "@preact/signals";
import type { Notification } from "./api/types";

export type AlertState = "ask" | "on" | "blocked" | "unsupported";
export type Toast = {
  id: number;
  text: string;
  detail: string;
  taskId: number | null;
  /** The notification to mark read when the message is opened; null for a summary message. */
  notificationId: number | null;
  /** Deadline and assignment changes stay until dismissed; the rest fade after 15 seconds. */
  sticky: boolean;
  dueLabel: string | null;
  dueTone: string;
  /** More than a few arrived at once: one message that opens the list instead. */
  summary: boolean;
};

const MAX_TOASTS = 3;

export const toasts = signal<Toast[]>([]);
export const alertState = signal<AlertState>(readAlertState());

const supported = "Notification" in window && "serviceWorker" in navigator;

function readAlertState(): AlertState {
  if (!("Notification" in window && "serviceWorker" in navigator)) return "unsupported";
  if (Notification.permission === "granted") return "on";
  if (Notification.permission === "denied") return "blocked";
  return "ask";
}

/** Register the service worker when alerts are already allowed (it must exist to show them). */
export function registerWorker(): void {
  if (supported && alertState.value === "on") {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* alerts stay in-page */
    });
  }
}

/** Ask the browser for permission. Must run from a click, or browsers refuse to ask. */
export async function enableAlerts(): Promise<void> {
  try {
    await navigator.serviceWorker.register("/sw.js");
    await Notification.requestPermission();
  } catch {
    /* blocked or unsupported: the state below says so */
  }
  alertState.value = readAlertState();
}

async function osNotify(n: { id: number | string; text: string; detail: string; taskId: number | null }) {
  const reg = await navigator.serviceWorker.ready;
  await reg.showNotification(n.text, {
    body: n.detail,
    tag: "n-" + n.id,
    icon: "/static/icons/icon-192.png",
    data: { taskId: n.taskId, id: n.id },
  });
}

/** Show a sample desktop alert, so someone can check alerts work on this computer. */
export function testAlert(): void {
  void osNotify({
    id: "test",
    text: "Desktop alerts are working",
    detail: "You'll see this when a task of yours changes.",
    taskId: null,
  });
}

/** Dismiss one on-page message. */
export function removeToast(id: number): void {
  toasts.value = toasts.value.filter((t) => t.id !== id);
}

function push(toast: Toast): void {
  toasts.value = [...toasts.value.filter((t) => t.id !== toast.id), toast].slice(-MAX_TOASTS);
  if (!toast.sticky) setTimeout(() => removeToast(toast.id), 15000);
}

/**
 * Show new notifications as messages on the page, oldest first. When more arrive at once than
 * fit, show one summary message that opens the list, so nothing is hidden behind a pile.
 */
export function showToasts(fresh: Notification[]): void {
  if (fresh.length > MAX_TOASTS) {
    const titles = [...new Set(fresh.map((n) => n.title))];
    push({
      id: -1,
      text: `${fresh.length} changes to your tasks`,
      detail: titles.slice(0, 2).join(", ") + (titles.length > 2 ? ` and ${titles.length - 2} more` : ""),
      taskId: null,
      notificationId: null,
      sticky: fresh.some((n) => n.sticky),
      dueLabel: null,
      dueTone: "",
      summary: true,
    });
    return;
  }
  for (const n of fresh) {
    push({
      id: n.id,
      text: n.text,
      detail: n.detail,
      taskId: n.task_id,
      notificationId: n.id,
      sticky: n.sticky,
      dueLabel: n.due_label,
      dueTone: n.due_tone,
      summary: false,
    });
  }
}

/** Show desktop (OS) alerts for new notifications, when the person has turned them on. */
export function showOsAlerts(fresh: Notification[]): void {
  if (alertState.value !== "on") return;
  for (const n of fresh) {
    void osNotify({ id: n.id, text: n.text, detail: n.detail, taskId: n.task_id });
  }
}
