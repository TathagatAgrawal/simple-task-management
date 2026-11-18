// Announcing new notifications: a message on the page whenever it is visible, plus a desktop (OS)
// alert, through the service worker, when the person has turned those on and isn't looking.
import { signal } from "@preact/signals";
import type { Notification } from "./api/types";

export type AlertState = "ask" | "on" | "blocked" | "unsupported";
export type Toast = { id: number; text: string; detail: string; taskId: number | null };

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

function addToast(n: Notification): void {
  const toast: Toast = { id: n.id, text: n.text, detail: n.detail, taskId: n.task_id };
  toasts.value = [...toasts.value.filter((t) => t.id !== n.id), toast].slice(-3);
  setTimeout(() => removeToast(n.id), 15000);
}

/** Announce notifications that just arrived (oldest first). */
export function announce(fresh: Notification[]): void {
  const looking = document.visibilityState === "visible";
  const focused = looking && document.hasFocus();
  for (const n of fresh) {
    if (looking) addToast(n);
    if (alertState.value === "on" && !focused) {
      void osNotify({ id: n.id, text: n.text, detail: n.detail, taskId: n.task_id });
    }
  }
}
