// Live updates. The server pushes "something changed" over one Server-Sent Events connection, and
// the page refetches what it shows. A slow refresh and a refresh when the window regains focus
// remain as a safety net, so a dropped connection can never leave anyone looking at old data.
import {
  me, refreshAll, refreshBoard, refreshNotifications, refreshPeople, refreshTask,
} from "./state";

const SAFETY_NET_MS = 60_000;

let source: EventSource | null = null;
let timer: ReturnType<typeof setInterval> | undefined;

function onTopics(topics: string[]): void {
  if (topics.includes("ready")) void refreshAll(); // (re)connected: catch up on anything missed
  if (topics.includes("tasks")) {
    void refreshBoard();
    void refreshTask();
  }
  if (topics.includes("notifications")) void refreshNotifications();
  if (topics.includes("people")) void refreshPeople();
}

function connect(): void {
  source?.close();
  source = new EventSource("/api/events");
  source.onmessage = (event: MessageEvent<string>) => {
    try {
      onTopics(JSON.parse(event.data) as string[]);
    } catch {
      /* ignore a message we don't understand */
    }
  };
  source.onerror = () => {
    // The browser retries by itself after a dropped connection. If it gave up (for example after
    // a server restart that answered with an error), try again shortly.
    if (source?.readyState === EventSource.CLOSED) setTimeout(() => me.value && connect(), 10_000);
  };
}

function visibleAgain(): void {
  if (document.visibilityState === "visible" && me.value && !me.value.must_change_password) {
    void refreshAll();
  }
}

/** Start listening. Safe to call once; stops by itself when the person signs out. */
export function startLive(): void {
  if (timer) return;
  connect();
  timer = setInterval(() => {
    if (document.visibilityState === "visible" && me.value && !me.value.must_change_password) {
      void refreshAll();
    }
  }, SAFETY_NET_MS);
  window.addEventListener("focus", visibleAgain);
  document.addEventListener("visibilitychange", visibleAgain);
  // The server closes the stream at shutdown and when a session ends; reconnect resumes it.
}

/** Stop the event stream (used when signing out). */
export function stopLive(): void {
  source?.close();
  source = null;
  if (timer) clearInterval(timer);
  timer = undefined;
  window.removeEventListener("focus", visibleAgain);
  document.removeEventListener("visibilitychange", visibleAgain);
}
