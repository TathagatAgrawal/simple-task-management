// Phone gestures, ported as they were: swipe a card right to move it on, swipe left or press and
// hold for its menu, drag a sheet or the task page to dismiss it, and keep sheets above the
// on-screen keyboard. All of it does nothing on a desktop-sized window (the CSS decides what shows).
import { cardActions, moveTask, setDragging } from "./state";
import { isTyping } from "./util";

const phone = window.matchMedia("(max-width: 640px)");
export const isPhone = (): boolean => phone.matches;

const NEXT_STATUS = { todo: "doing", doing: "done", done: "todo" } as const;
const NEXT_VERB = { todo: "Start", doing: "Done", done: "Reopen" } as const;
type Status = keyof typeof NEXT_STATUS;

const SWIPE_COMMIT = 96;

type Swipe = {
  card: HTMLElement;
  x: number;
  y: number;
  dx: number;
  active: boolean;
  long: boolean;
  id: number;
  status: Status;
  hint: HTMLElement;
  timer?: ReturnType<typeof setTimeout>;
};

/** Open the card's actions sheet (Open, Move to…, Delete…). */
function openActions(card: HTMLElement): void {
  const status = card.closest<HTMLElement>(".col")?.dataset.status as Status | undefined;
  const id = Number(card.dataset.taskId);
  const title = card.querySelector(".card-title")?.textContent ?? "";
  if (status && id) cardActions.value = { id, title, status };
}

/** Wire up card swipes, long-press, context-menu suppression and keyboard tracking. Call once. */
export function initGestures(): void {
  let swipe: Swipe | null = null;
  let suppressClick = false;
  const swallowNextClick = () => {
    suppressClick = true;
    setTimeout(() => (suppressClick = false), 120);
  };

  document.addEventListener(
    "click",
    (e) => {
      if (suppressClick) {
        e.stopPropagation();
        e.preventDefault();
      }
    },
    true,
  );
  document.addEventListener("contextmenu", (e) => {
    if (isPhone() && (e.target as Element).closest?.(".card")) e.preventDefault();
  });

  document.addEventListener("pointerdown", (e) => {
    if (!isPhone() || !e.isPrimary) return;
    const card = (e.target as Element).closest?.<HTMLElement>(".card-wrap .card");
    const hint = card?.parentElement?.querySelector<HTMLElement>(".swipe-hint");
    const status = card?.closest<HTMLElement>(".col")?.dataset.status as Status | undefined;
    if (!card || !hint || !status) return;
    const s: Swipe = { card, x: e.clientX, y: e.clientY, dx: 0, active: false, long: false, id: e.pointerId, status, hint };
    swipe = s;
    s.timer = setTimeout(() => {
      if (swipe !== s || s.active) return;
      s.long = true;
      navigator.vibrate?.(8);
      openActions(s.card);
    }, 500);
  });

  document.addEventListener("pointermove", (e) => {
    const s = swipe;
    if (!s || s.long || e.pointerId !== s.id) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (!s.active) {
      if (Math.abs(dy) > 10) {
        clearTimeout(s.timer); // it's a scroll
        swipe = null;
        return;
      }
      if (Math.abs(dx) < 10) return;
      s.active = true;
      clearTimeout(s.timer);
      setDragging(true); // pause background refreshes while a finger is down
      s.card.classList.add("swiping");
      try {
        s.card.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    }
    s.dx = Math.max(-160, Math.min(window.innerWidth, dx));
    s.card.style.transform = `translateX(${s.dx}px)`;
    const right = s.dx > 0;
    s.hint.className = "swipe-hint " + (right ? "right" : "left");
    s.hint.textContent = right ? `${NEXT_VERB[s.status]} →` : "← More";
    s.hint.style.opacity = String(Math.min(1, Math.abs(s.dx) / SWIPE_COMMIT));
  });

  function endSwipe(cancelled: boolean): void {
    const s = swipe;
    if (!s) return;
    swipe = null;
    clearTimeout(s.timer);
    if (s.long) {
      swallowNextClick();
      return;
    }
    if (!s.active) return;
    swallowNextClick();
    setDragging(false);
    s.card.classList.remove("swiping");
    s.card.classList.add("snapback");
    const commit = !cancelled && Math.abs(s.dx) >= SWIPE_COMMIT;
    if (commit && s.dx > 0) {
      s.card.style.transform = "translateX(100%)";
      void moveTask(Number(s.card.dataset.taskId), NEXT_STATUS[s.status]);
    } else {
      s.card.style.transform = "";
      s.hint.style.opacity = "0";
      if (commit) openActions(s.card);
    }
    setTimeout(() => s.card.classList.remove("snapback"), 260);
  }
  document.addEventListener("pointerup", () => endSwipe(false));
  document.addEventListener("pointercancel", () => endSwipe(true));

  // Keep sheets and the task page above the on-screen keyboard (--kb is the keyboard's height).
  const vv = window.visualViewport;
  const syncKeyboard = () => {
    const kb =
      vv && isPhone() && isTyping(document.activeElement)
        ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop)
        : 0;
    document.documentElement.style.setProperty("--kb", Math.round(kb) + "px");
  };
  vv?.addEventListener("resize", syncKeyboard);
  vv?.addEventListener("scroll", syncKeyboard);
  document.addEventListener("focusout", () => setTimeout(syncKeyboard, 50));
}

/**
 * Drag a sheet down, or the task page right from the left edge, to dismiss it (like iOS).
 * Returns a function that removes the listeners.
 */
export function dismissGesture(
  el: HTMLDialogElement,
  axis: "x" | "y",
  startsOk: (e: PointerEvent, el: HTMLElement) => boolean,
): () => void {
  let g: { x: number; y: number; d: number; active: boolean; id: number } | null = null;
  const reset = () => {
    el.style.transition = "transform .2s ease-out";
    el.style.transform = "";
    setTimeout(() => (el.style.transition = ""), 220);
  };
  const down = (e: PointerEvent) => {
    if (!isPhone() || !e.isPrimary || !startsOk(e, el)) return;
    g = { x: e.clientX, y: e.clientY, d: 0, active: false, id: e.pointerId };
  };
  const move = (e: PointerEvent) => {
    if (!g || e.pointerId !== g.id) return;
    const dx = e.clientX - g.x;
    const dy = e.clientY - g.y;
    const d = axis === "x" ? dx : dy;
    const cross = axis === "x" ? dy : dx;
    if (!g.active) {
      if (Math.abs(cross) > 12 && Math.abs(cross) > Math.abs(d)) {
        g = null;
        return;
      }
      if (d < 10) return;
      g.active = true;
      try {
        el.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      (document.activeElement as HTMLElement | null)?.blur?.();
    }
    g.d = Math.max(0, d);
    el.style.transform = axis === "x" ? `translateX(${g.d}px)` : `translateY(${g.d}px)`;
  };
  const end = (cancelled: boolean) => {
    const was = g;
    g = null;
    if (!was || !was.active) return;
    if (!cancelled && was.d > 100) {
      el.style.transition = "transform .18s ease-in";
      el.style.transform = axis === "x" ? "translateX(100vw)" : "translateY(100vh)";
      setTimeout(() => {
        el.close();
        el.style.transform = el.style.transition = "";
      }, 180);
    } else reset();
  };
  const up = () => end(false);
  const cancel = () => end(true);
  el.addEventListener("pointerdown", down);
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", cancel);
  return () => {
    el.removeEventListener("pointerdown", down);
    el.removeEventListener("pointermove", move);
    el.removeEventListener("pointerup", up);
    el.removeEventListener("pointercancel", cancel);
  };
}
