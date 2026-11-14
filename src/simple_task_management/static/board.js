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
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.hidden = true; }, 6000);
  }
  body.addEventListener("htmx:responseError", (e) => {
    const xhr = e.detail.xhr;
    banner(xhr.status >= 500 ? "Something went wrong on the server. Please try again."
                             : (xhr.responseText || "That didn't work. Please try again."));
    htmx.trigger(body, "tasks-changed"); // re-sync, e.g. snap a dragged card back
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
  window.tbShowOlder = () => {
    document.getElementById("done-days").value = "3650";
    htmx.trigger(body, "filters-changed");
  };

  // ---- task panel ----------------------------------------------------------
  function markSelected() {
    const panel = document.querySelector("#panel .panel");
    const id = panel ? panel.dataset.taskId : null;
    document.querySelectorAll(".card").forEach((c) => c.classList.toggle("selected", c.dataset.taskId === id));
    if (panel) history.replaceState(null, "", "#task-" + id);
  }
  window.tbOpenTask = (id) => htmx.ajax("GET", "/tasks/" + id, { target: "#panel", swap: "innerHTML" });
  window.tbClosePanel = () => {
    document.getElementById("panel").innerHTML = "";
    history.replaceState(null, "", location.pathname + location.search);
    markSelected();
  };
  // Refresh the panel in the background only when nobody is typing in it.
  window.tbPanelIdle = () => {
    const panel = document.querySelector("#panel .panel");
    if (!panel || panel.contains(document.activeElement)) return false;
    const draft = panel.querySelector("textarea[name=body]");
    return !draft || !draft.value.trim();
  };
  body.addEventListener("htmx:afterSettle", markSelected);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.querySelector("dialog[open]") && document.querySelector("#panel .panel")) {
      tbClosePanel();
    }
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
