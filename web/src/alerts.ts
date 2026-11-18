// Announcing new notifications: a message on the page whenever it is visible, plus a desktop (OS)
// alert, through the service worker, when the person has turned those on and isn't looking.
import { signal } from "@preact/signals";
import { api } from "./api/client";
import type { Notification, PushInfo } from "./api/types";

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

// ---- alerts that arrive even when the board is closed (Web Push) -------------------------------
// "on": this device is subscribed. The system then does all the alerting (phone banner, Windows or
// macOS notification) and the page shows only the bell number, so nothing appears twice.
// "install": an iPhone or iPad that must first add the page to the Home Screen.
// "unsupported" / "server-off": push isn't available, so the older on-page alerts above stay.
export type PushState = "unsupported" | "server-off" | "install" | "ask" | "on" | "blocked";

export const pushState = signal<PushState>("unsupported");
export const pushInfo = signal<PushInfo | null>(null);
export const pushError = signal<string>("");

const isApple = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isInstalled = (navigator as Navigator & { standalone?: boolean }).standalone === true || matchMedia("(display-mode: standalone)").matches;

/** The browser's own subscription for this device, if it has one. */
async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration("/sw.js");
  return reg ? reg.pushManager.getSubscription() : null;
}

/** Decode the server's URL-safe public key into the bytes the browser wants. */
function keyBytes(key: string): Uint8Array<ArrayBuffer> {
  const raw = atob(key.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(key.length / 4) * 4, "="));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

function keysOf(sub: PushSubscription): { endpoint: string; keys: { p256dh: string; auth: string } } {
  const json = sub.toJSON();
  return { endpoint: sub.endpoint, keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" } };
}

/** Work out this device's push state, and re-save its subscription if the server lost it. */
export async function refreshPush(): Promise<void> {
  try {
    if (!("serviceWorker" in navigator && "PushManager" in window && "Notification" in window)) {
      pushState.value = isApple && !isInstalled ? "install" : "unsupported";
      return;
    }
    const sub = await currentSubscription();
    const info = await api.push(sub?.endpoint);
    pushInfo.value = info;
    if (!info.enabled) pushState.value = "server-off";
    else if (Notification.permission === "denied") pushState.value = "blocked";
    else if (Notification.permission === "granted" && sub) {
      pushState.value = "on";
      if (!info.this_device) {
        const { endpoint, keys } = keysOf(sub);
        await api.savePush(endpoint, keys);
      }
    } else pushState.value = "ask";
  } catch {
    /* offline or signed out: leave the state as it was */
  }
}

/** Turn alerts on for this device. Must run from a click, or browsers refuse to ask. */
export async function enablePush(): Promise<void> {
  pushError.value = "";
  try {
    const info = pushInfo.value ?? (await api.push());
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    if ((await Notification.requestPermission()) !== "granted") {
      pushState.value = Notification.permission === "denied" ? "blocked" : "ask";
      return;
    }
    const old = await reg.pushManager.getSubscription();
    if (old) await old.unsubscribe(); // made with another key, or stale: start clean
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(info.public_key) });
    const { endpoint, keys } = keysOf(sub);
    await api.savePush(endpoint, keys);
    alertState.value = readAlertState();
    await refreshPush();
  } catch {
    pushError.value = "Couldn't turn alerts on. Check that you're online, then try again.";
  }
}

/** Turn alerts off for this device (the browser's permission stays; turning on again is one tap). */
export async function disablePush(): Promise<void> {
  pushError.value = "";
  try {
    const sub = await currentSubscription();
    if (sub) {
      await api.removePush(sub.endpoint);
      await sub.unsubscribe();
    }
    await refreshPush();
  } catch {
    pushError.value = "Couldn't turn alerts off. Please try again.";
  }
}

/** Forget this device before signing out, so the next person on it isn't sent the last one's alerts. */
export async function forgetDevice(): Promise<void> {
  try {
    const sub = await currentSubscription();
    if (sub) {
      await api.removePush(sub.endpoint);
      await sub.unsubscribe();
    }
  } catch {
    /* signing out matters more */
  }
  pushState.value = "ask";
}

/** Ask the server to send a sample alert to all of my devices. */
export async function testPush(): Promise<void> {
  pushError.value = "";
  try {
    const { sent } = await api.testPush();
    if (!sent) pushError.value = "The test couldn't be delivered. Try turning alerts off and on again.";
  } catch (e) {
    pushError.value = e instanceof Error ? e.message : "The test didn't work.";
  }
}

/** Choose whether banners show the task's name. */
export async function setPushDetails(details: boolean): Promise<void> {
  pushInfo.value = await api.setPushDetails(details);
}

/** True when the system does the alerting on this device, so the page shows none of its own. */
export function systemAlerts(): boolean {
  return pushState.value === "on";
}

/** Show the unread count on the app icon (iPhone Home Screen, installed desktop app), where allowed. */
export function setIconBadge(count: number): void {
  const nav = navigator as Navigator & { setAppBadge?: (n: number) => Promise<void>; clearAppBadge?: () => Promise<void> };
  try {
    void (count > 0 ? nav.setAppBadge?.(count) : nav.clearAppBadge?.())?.catch(() => {});
  } catch {
    /* not supported here */
  }
}
