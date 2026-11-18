// Starts the app: finds out who is signed in, wires up live updates, and renders the page.
import { effect } from "@preact/signals";
import { render } from "preact";
import { registerWorker } from "./alerts";
import { api, setSignedOutHandler } from "./api/client";
import { App } from "./App";
import { initGestures } from "./gestures";
import { startLive, stopLive } from "./live";
import { endSession, me, modal, openNotification, openTask, startSession } from "./state";
import { isTyping } from "./util";

setSignedOutHandler(() => {
  stopLive();
  endSession();
});

// Live updates run exactly while someone is signed in and past the set-password screen.
effect(() => {
  const user = me.value;
  if (user && !user.must_change_password) startLive();
  else stopLive();
});

// A clicked desktop alert asks an already-open page to show its task.
navigator.serviceWorker?.addEventListener("message", (event: MessageEvent) => {
  const data = event.data as { type?: string; taskId?: number | null; id?: number | string } | null;
  if (data?.type === "open-task") {
    openNotification(data.taskId ?? null, typeof data.id === "number" ? data.id : null);
  }
});

// Single-key shortcuts for people who live in the board: n = new task, / = search.
document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || !me.value || me.value.must_change_password) return;
  if (isTyping(document.activeElement) || document.querySelector("dialog[open]")) return;
  if (e.key === "n") {
    e.preventDefault();
    modal.value = "new-task";
  } else if (e.key === "/") {
    e.preventDefault();
    document.getElementById("q")?.focus();
  }
});

async function boot(): Promise<void> {
  registerWorker();
  initGestures();
  render(<App />, document.getElementById("root")!);
  try {
    startSession(await api.me());
    const match = location.hash.match(/^#task-(\d+)$/);
    if (match) openTask(Number(match[1]));
  } catch {
    me.value = null; // not signed in (or the server is unreachable): show the sign-in form
  }
}

void boot();
