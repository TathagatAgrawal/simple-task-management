// Small client-side helpers: filter memory, drag-and-drop, the task panel, dialogs, theme, errors.
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
    if (panel) history.replaceState(null, "", "#task-" + id);
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
      if (hasTask && !drawer.open) drawer.showModal();
      if (!hasTask && drawer.open) drawer.close();
    });
    drawer.addEventListener("close", () => {
      document.getElementById("panel").innerHTML = "";
      history.replaceState(null, "", location.pathname + location.search);
      markSelected();
    });
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
    carried = {
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
    col.querySelector(".cards").prepend(card); // optimistic; the refresh re-sorts by date
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

  // ---- theme ----------------------------------------------------------------
  window.tbSetTheme = (theme) => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-choice]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.themeChoice === theme));
    });
  };
})();
