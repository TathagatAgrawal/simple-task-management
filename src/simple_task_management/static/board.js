// Small client-side helpers: filter memory, drag-and-drop, the task panel, dialogs, theme, errors,
// and the phone layout (tabs, swipe gestures, back navigation, sheets).
// Everything else is htmx attributes in the templates.
(function () {
  "use strict";

  const body = document.body;

  // ---- error banner -------------------------------------------------------
  function banner(message) {
    const el = document.getElementById("banner");
    if (!el) return;
    el.textContent = message;
    // A popover sits in the top layer, so the banner shows above an open task drawer.
    if (el.matches(":popover-open")) el.hidePopover();
    el.showPopover();
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.hidePopover(), 6000);
  }
  body.addEventListener("htmx:responseError", (e) => {
    const xhr = e.detail.xhr;
    const message = xhr.status >= 500 ? "Something went wrong on the server. Please try again."
                                      : (xhr.responseText || "That didn't work. Please try again.");
    // Forms with their own error slot (dialogs, set-password) show it next to the fields;
    // the page banner would be hidden behind a dialog's backdrop.
    const form = e.detail.elt.closest && e.detail.elt.closest("form");
    const slot = form && form.querySelector(".form-error");
    if (slot) slot.textContent = message;
    else banner(message);
    htmx.trigger(body, "tasks-changed"); // re-sync, e.g. snap a dragged card back
  });
  // Clear a form's error once it submits successfully.
  body.addEventListener("htmx:afterRequest", (e) => {
    if (!e.detail.successful) return;
    const slot = e.detail.elt.closest && e.detail.elt.closest("form")?.querySelector(".form-error");
    if (slot) slot.textContent = "";
  });
  body.addEventListener("htmx:sendError", () => banner("Can't reach the server. Is Tailscale connected?"));

  // ---- "Showing" filter (remembered per browser) --------------------------
  const who = document.getElementById("who");
  if (who) {
    try {
      const saved = localStorage.getItem("tb-who");
      if (saved && [...who.options].some((o) => o.value === saved)) who.value = saved;
    } catch (_) { /* storage unavailable: fall back to "My tasks" */ }
    who.addEventListener("change", () => {
      try { localStorage.setItem("tb-who", who.value); } catch (_) { /* ignore */ }
      htmx.trigger(body, "filters-changed");
    });
  }
  // "Show N more" in the summary strip; remembered across the strip's background refreshes.
  const expandedGroups = new Set();
  window.tbToggleSummary = (button) => {
    const card = button.closest(".sumcard");
    card.classList.toggle("expanded");
    if (card.classList.contains("expanded")) expandedGroups.add(card.dataset.group);
    else expandedGroups.delete(card.dataset.group);
  };
  body.addEventListener("htmx:afterSettle", () => {
    expandedGroups.forEach((g) => {
      const card = document.querySelector('.sumcard[data-group="' + g + '"]');
      if (card) card.classList.add("expanded");
    });
  });
  window.tbShowOlder = () => {
    document.getElementById("done-days").value = "3650";
    htmx.trigger(body, "filters-changed");
  };

  // ---- task drawer -------------------------------------------------------------
  // The task view is fetched into #panel, which lives in a modal <dialog> drawer over the board.
  const drawer = document.getElementById("task-dialog");
  function markSelected() {
    const panel = document.querySelector("#panel .panel");
    const id = panel ? panel.dataset.taskId : null;
    document.querySelectorAll(".card").forEach((c) => c.classList.toggle("selected", c.dataset.taskId === id));
    if (panel) history.replaceState(history.state, "", "#task-" + id);
  }
  window.tbOpenTask = (id) => htmx.ajax("GET", "/tasks/" + id, { target: "#panel", swap: "innerHTML" });
  window.tbClosePanel = () => { if (drawer && drawer.open) drawer.close(); };
  // Refresh the open task in the background only when nobody is typing in it.
  window.tbPanelIdle = () => {
    const panel = document.querySelector("#panel .panel");
    if (!panel || isTyping(document.activeElement)) return false;
    const draft = panel.querySelector("textarea[name=body]");
    return !draft || !draft.value.trim();
  };
  function isTyping(el) {
    return !!(el && el.matches && el.matches("input:not([type=checkbox]), textarea, select"));
  }
  if (drawer) {
    // Show the drawer when a task loads into it; close it if the task vanished (deleted).
    body.addEventListener("htmx:afterSettle", () => {
      const hasTask = !!drawer.querySelector(".panel");
      if (hasTask && !drawer.open) {
        drawer.showModal();
        // One history entry per open task, so the phone's Back button or gesture closes it.
        if (!(history.state && history.state.tbTask)) history.pushState({ tbTask: true }, "", location.hash || location.pathname);
      }
      if (!hasTask && drawer.open) drawer.close();
    });
    drawer.addEventListener("close", () => {
      document.getElementById("panel").innerHTML = "";
      drawer.style.transform = drawer.style.transition = "";
      if (history.state && history.state.tbTask) history.back(); // the popstate that follows finds it closed
      else history.replaceState(null, "", location.pathname + location.search);
      markSelected();
    });
    window.addEventListener("popstate", () => { if (drawer.open) drawer.close(); });
    // Clicking the dimmed board (the dialog's backdrop) closes the drawer.
    drawer.addEventListener("click", (e) => { if (e.target === drawer) drawer.close(); });
    // Esc first leaves a text field (which saves it), and only then closes the drawer.
    drawer.addEventListener("cancel", (e) => {
      if (isTyping(document.activeElement)) {
        e.preventDefault();
        document.activeElement.blur();
      }
    });
  }
  body.addEventListener("htmx:afterSettle", markSelected);
  body.addEventListener("task-created", (e) => tbOpenTask(e.detail.id));

  // The panel re-renders after every change. Carry over what the server doesn't know about
  // (an unsent comment, keyboard focus, expanded sections) when it's the same task.
  const FOCUSABLE = "input, select, textarea, button, a[href], summary";
  let carried = null;
  let justPosted = false;
  body.addEventListener("htmx:afterRequest", (e) => {
    if (e.detail.successful && e.detail.elt.matches && e.detail.elt.matches(".composer")) justPosted = true;
  });
  // Named fields are found again by name (+ value for checkboxes); other controls by position.
  function focusKey(panel, el) {
    if (!el || !panel.contains(el)) return null;
    if (el.name) return { name: el.name, value: el.type === "checkbox" ? el.value : null };
    return { index: [...panel.querySelectorAll(FOCUSABLE)].indexOf(el) };
  }
  function findByKey(panel, key) {
    if (!key) return null;
    if (key.name) {
      return [...panel.querySelectorAll("[name]")].find(
        (el) => el.name === key.name && (key.value === null || el.value === key.value));
    }
    return panel.querySelectorAll(FOCUSABLE)[key.index];
  }
  body.addEventListener("htmx:beforeSwap", (e) => {
    const panel = document.querySelector("#panel .panel");
    if (!panel || !(e.detail.target === panel || e.detail.target.id === "panel")) return;
    const draft = panel.querySelector("textarea[name=body]");
    const thread = panel.querySelector(".thread-scroll");
    const page = panel.querySelector(".panel-body");
    carried = {
      pageScroll: page ? page.scrollTop : 0,
      posted: justPosted,
      id: panel.dataset.taskId,
      draft: draft ? draft.value : "",
      focus: focusKey(panel, document.activeElement),
      open: [...panel.querySelectorAll("details")].map((d) => d.open),
      scrollTop: thread ? thread.scrollTop : 0,
      atBottom: !thread || thread.scrollHeight - thread.scrollTop - thread.clientHeight < 24,
    };
  });
  // Runs after every swap; acts only when a freshly rendered task view is in the drawer.
  let seenPanel = null;
  body.addEventListener("htmx:afterSettle", () => {
    const panel = document.querySelector("#panel .panel");
    if (!panel || panel === seenPanel) return;
    seenPanel = panel;
    const state = carried && carried.id === panel.dataset.taskId ? carried : null;
    carried = null;
    const thread = panel.querySelector(".thread-scroll");
    // Newest updates are at the bottom: start there, unless the reader had scrolled up.
    if (thread) thread.scrollTop = state && !state.atBottom ? state.scrollTop : thread.scrollHeight;
    // On a phone the whole panel scrolls (not the thread): keep the reader's place, or go to
    // the end after posting an update.
    const page = panel.querySelector(".panel-body");
    if (page && isPhone() && state) page.scrollTop = state.posted ? page.scrollHeight : state.pageScroll;
    justPosted = false;
    if (!state) return;
    const draft = panel.querySelector("textarea[name=body]");
    if (draft && state.draft && !draft.value) draft.value = state.draft;
    panel.querySelectorAll("details").forEach((d, i) => { if (state.open[i]) d.open = true; });
    const target = findByKey(panel, state.focus);
    if (target && !panel.contains(document.activeElement)) target.focus({ preventScroll: true });
  });
  document.addEventListener("DOMContentLoaded", () => {
    const m = location.hash.match(/^#task-(\d+)$/);
    if (m && document.getElementById("panel")) tbOpenTask(m[1]);
  });

  // ---- drag and drop between columns ---------------------------------------
  window.tbDragging = false;
  function clearDrop() {
    document.querySelectorAll(".col.drop").forEach((c) => c.classList.remove("drop"));
  }
  document.addEventListener("dragstart", (e) => {
    const card = e.target.closest && e.target.closest(".card[draggable]");
    if (!card) return;
    if (isPhone()) { e.preventDefault(); return; } // phones use swipe instead
    window.tbDragging = true;
    e.dataTransfer.setData("text/plain", card.dataset.taskId);
    e.dataTransfer.effectAllowed = "move";
    requestAnimationFrame(() => card.classList.add("dragging"));
  });
  document.addEventListener("dragend", (e) => {
    const card = e.target.closest && e.target.closest(".card");
    if (card) card.classList.remove("dragging");
    window.tbDragging = false;
    clearDrop();
  });
  document.addEventListener("dragover", (e) => {
    const col = e.target.closest && e.target.closest(".col[data-status]");
    if (!col || !window.tbDragging) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (!col.classList.contains("drop")) { clearDrop(); col.classList.add("drop"); }
  });
  document.addEventListener("dragleave", (e) => {
    const col = e.target.closest && e.target.closest(".col");
    if (col && !col.contains(e.relatedTarget)) col.classList.remove("drop");
  });
  document.addEventListener("drop", (e) => {
    const col = e.target.closest && e.target.closest(".col[data-status]");
    if (!col) return;
    e.preventDefault();
    clearDrop();
    const id = e.dataTransfer.getData("text/plain");
    const card = document.querySelector('.card[data-task-id="' + id + '"]');
    if (!id || !card || card.closest(".col") === col) return;
    col.querySelector(".cards").prepend(card.closest(".card-wrap") || card); // optimistic; the refresh re-sorts by date
    htmx.ajax("POST", "/tasks/" + id + "/move", { source: col, swap: "none", values: { status: col.dataset.status } });
  });

  // ---- dialogs and menus ------------------------------------------------------
  window.tbOpenDialog = (id) => {
    const dialog = document.getElementById(id);
    document.querySelectorAll("details.usermenu[open]").forEach((d) => d.removeAttribute("open"));
    dialog.showModal();
    if (id === "people-dialog") htmx.trigger(body, "people-open");
  };
  body.addEventListener("people-changed", () => {
    const dialog = document.getElementById("people-dialog");
    if (dialog) dialog.dataset.changed = "1";
  });
  const peopleDialog = document.getElementById("people-dialog");
  if (peopleDialog) {
    // New or removed people change the filter and assignee lists, so reload once on close.
    peopleDialog.addEventListener("close", () => { if (peopleDialog.dataset.changed) location.reload(); });
  }
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.usermenu[open]").forEach((d) => {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });


  // ---- phone layout -------------------------------------------------------------
  // Tabs, the segmented status control, swipe gestures, back navigation and sheets. All of it is
  // inert on a desktop-sized window; the CSS (max-width: 640px) decides what's visible.
  const phone = window.matchMedia("(max-width: 640px)");
  function isPhone() { return phone.matches; }
  const remember = (key, value) => { try { localStorage.setItem(key, value); } catch (_) { /* ignore */ } };
  const recall = (key, allowed) => {
    try { const v = localStorage.getItem(key); return allowed.includes(v) ? v : null; } catch (_) { return null; }
  };
  if (body.dataset.tab !== undefined) {
    body.dataset.tab = recall("tb-tab", ["board", "soon", "me"]) || "board";
    body.dataset.seg = recall("tb-seg", ["todo", "doing", "done"]) || "todo";
  }
  window.tbSetTab = (tab) => { body.dataset.tab = tab; remember("tb-tab", tab); window.scrollTo(0, 0); };
  window.tbSetSeg = (seg) => { body.dataset.seg = seg; remember("tb-seg", seg); };
  // The red badge on "Coming up" shows how many tasks are overdue.
  body.addEventListener("htmx:afterSettle", () => {
    if (isPhone()) document.querySelectorAll(".card[draggable]").forEach((c) => c.removeAttribute("draggable"));
    const badge = document.getElementById("overdue-badge"), strip = document.querySelector("#summary .summary");
    if (!badge || !strip) return;
    const n = Number(strip.dataset.overdue) || 0;
    badge.textContent = n;
    badge.hidden = n === 0;
  });

  // Keep sheets and the task page above the on-screen keyboard (--kb is the keyboard's height).
  const vv = window.visualViewport;
  function syncKeyboard() {
    const kb = vv && isPhone() && isTyping(document.activeElement) ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
    document.documentElement.style.setProperty("--kb", Math.round(kb) + "px");
  }
  if (vv) { vv.addEventListener("resize", syncKeyboard); vv.addEventListener("scroll", syncKeyboard); }
  document.addEventListener("focusout", () => setTimeout(syncKeyboard, 50));

  // Swipe a card right to move it on (To do → Doing → Done → To do); swipe left or press and hold
  // for a menu with Open, Move to… and Delete.
  const STATUS_LABELS = { todo: "To do", doing: "Doing", done: "Done" };
  const NEXT_STATUS = { todo: "doing", doing: "done", done: "todo" };
  const NEXT_VERB = { todo: "Start", doing: "Done", done: "Reopen" };
  const actions = document.getElementById("card-actions");
  let suppressClick = false;
  function swallowNextClick() { suppressClick = true; setTimeout(() => { suppressClick = false; }, 120); }
  document.addEventListener("click", (e) => {
    if (suppressClick) { e.stopPropagation(); e.preventDefault(); }
  }, true);
  document.addEventListener("contextmenu", (e) => { if (isPhone() && e.target.closest && e.target.closest(".card")) e.preventDefault(); });
  function moveTask(id, status, source) {
    htmx.ajax("POST", "/tasks/" + id + "/move", { source: source || body, swap: "none", values: { status } });
  }
  function openActions(card) {
    if (!actions) return;
    const id = card.dataset.taskId, status = card.closest(".col").dataset.status;
    const box = document.createElement("div");
    box.className = "box";
    const msg = document.createElement("div");
    msg.className = "msg";
    msg.textContent = card.querySelector(".card-title").textContent;
    box.append(msg);
    const add = (label, fn, cls) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; if (cls) b.className = cls;
      b.addEventListener("click", () => { actions.close(); fn(); });
      box.append(b);
    };
    add("Open", () => tbOpenTask(id));
    Object.keys(STATUS_LABELS).filter((k) => k !== status).forEach((k) => add("Move to " + STATUS_LABELS[k], () => moveTask(id, k, card)));
    add("Delete…", () => {
      if (confirm("Delete this task and all its updates? This can't be undone.")) {
        htmx.ajax("POST", "/tasks/" + id + "/delete", { source: card, swap: "none" });
      }
    }, "danger");
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.className = "cancel"; cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => actions.close());
    actions.replaceChildren(box, cancel);
    actions.showModal();
  }
  if (actions) actions.addEventListener("click", (e) => { if (e.target === actions) actions.close(); });

  let swipe = null;
  const SWIPE_COMMIT = 96;
  document.addEventListener("pointerdown", (e) => {
    if (!isPhone() || !e.isPrimary) return;
    const card = e.target.closest && e.target.closest(".card-wrap .card");
    if (!card) return;
    swipe = { card, x: e.clientX, y: e.clientY, dx: 0, active: false, long: false, id: e.pointerId,
              status: card.closest(".col").dataset.status, hint: card.parentNode.querySelector(".swipe-hint") };
    swipe.timer = setTimeout(() => {
      if (!swipe || swipe.active) return;
      swipe.long = true;
      if (navigator.vibrate) navigator.vibrate(8);
      openActions(swipe.card);
    }, 500);
  });
  document.addEventListener("pointermove", (e) => {
    if (!swipe || swipe.long || e.pointerId !== swipe.id) return;
    const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y;
    if (!swipe.active) {
      if (Math.abs(dy) > 10) { clearTimeout(swipe.timer); swipe = null; return; } // it's a scroll
      if (Math.abs(dx) < 10) return;
      swipe.active = true;
      clearTimeout(swipe.timer);
      window.tbDragging = true; // pause background refreshes while a finger is down
      swipe.card.classList.add("swiping");
      try { swipe.card.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    }
    swipe.dx = Math.max(-160, Math.min(window.innerWidth, dx));
    swipe.card.style.transform = "translateX(" + swipe.dx + "px)";
    const right = swipe.dx > 0, h = swipe.hint;
    h.className = "swipe-hint " + (right ? "right" : "left");
    h.textContent = right ? NEXT_VERB[swipe.status] + " →" : "← More";
    h.style.opacity = String(Math.min(1, Math.abs(swipe.dx) / SWIPE_COMMIT));
  });
  function endSwipe(cancelled) {
    if (!swipe) return;
    const s = swipe;
    swipe = null;
    clearTimeout(s.timer);
    if (s.long) { swallowNextClick(); return; }
    if (!s.active) return;
    swallowNextClick();
    window.tbDragging = false;
    s.card.classList.remove("swiping");
    s.card.classList.add("snapback");
    const commit = !cancelled && Math.abs(s.dx) >= SWIPE_COMMIT;
    if (commit && s.dx > 0) {
      s.card.style.transform = "translateX(100%)";
      moveTask(s.card.dataset.taskId, NEXT_STATUS[s.status], s.card);
    } else {
      s.card.style.transform = "";
      s.hint.style.opacity = "0";
      if (commit) openActions(s.card);
    }
    setTimeout(() => s.card.classList.remove("snapback"), 260);
  }
  document.addEventListener("pointerup", () => endSwipe(false));
  document.addEventListener("pointercancel", () => endSwipe(true));

  // Drag a sheet down, or the task page right from the left edge, to dismiss it (like iOS).
  function dismissGesture(el, axis, startsOk) {
    let g = null;
    const reset = () => { el.style.transition = "transform .2s ease-out"; el.style.transform = ""; setTimeout(() => { el.style.transition = ""; }, 220); };
    el.addEventListener("pointerdown", (e) => {
      if (!isPhone() || !e.isPrimary || !startsOk(e, el)) return;
      g = { x: e.clientX, y: e.clientY, d: 0, active: false, id: e.pointerId };
    });
    el.addEventListener("pointermove", (e) => {
      if (!g || e.pointerId !== g.id) return;
      const dx = e.clientX - g.x, dy = e.clientY - g.y, d = axis === "x" ? dx : dy, cross = axis === "x" ? dy : dx;
      if (!g.active) {
        if (Math.abs(cross) > 12 && Math.abs(cross) > Math.abs(d)) { g = null; return; }
        if (d < 10) return;
        g.active = true;
        try { el.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
        if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      }
      g.d = Math.max(0, d);
      el.style.transform = axis === "x" ? "translateX(" + g.d + "px)" : "translateY(" + g.d + "px)";
    });
    const end = (cancelled) => {
      if (!g) return;
      const was = g;
      g = null;
      if (!was.active) return;
      if (!cancelled && was.d > 100) {
        el.style.transition = "transform .18s ease-in";
        el.style.transform = axis === "x" ? "translateX(100vw)" : "translateY(100vh)";
        setTimeout(() => { el.close(); el.style.transform = el.style.transition = ""; }, 180);
      } else reset();
    };
    el.addEventListener("pointerup", () => end(false));
    el.addEventListener("pointercancel", () => end(true));
  }
  // Task page: swipe right starting near the left edge (the phone's own back gesture, if it has
  // one, takes over from the very edge and the history handling above closes the page).
  if (drawer) dismissGesture(drawer, "x", (e) => e.clientX > 8 && e.clientX < 40);
  // Sheets: drag down from the grab handle at the top.
  document.querySelectorAll("dialog.modal").forEach((d) => dismissGesture(d, "y", (e) => !!e.target.closest(".sheet-grab, h2")));
  // Tapping the dimmed area above a sheet closes it (a click on the dialog's own padding doesn't).
  document.querySelectorAll("dialog.modal").forEach((d) => d.addEventListener("click", (e) => {
    const r = d.getBoundingClientRect();
    if (isPhone() && e.target === d && e.clientY < r.top) d.close();
  }));

  // ---- theme ----------------------------------------------------------------
  window.tbSetTheme = (theme) => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-choice]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.themeChoice === theme));
    });
  };
})();
