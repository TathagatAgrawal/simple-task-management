// Retakes the screenshots in the user manual (src/simple_task_management/static/help/*.jpg).
//
//   node web/scripts/help-screenshots.mjs http://localhost:8000
//
// Start the app on a FRESH demo database first (it creates tasks and a person, and signs in as the
// demo people):  DATA_DIR=/tmp/help-demo uv run simple-task-management seed-demo, then serve it.
// The script drives a private, headless Chrome through its debugging protocol (Node 22 or newer,
// no packages), takes every picture in the light theme at twice the pixel density, and prints, for
// each picture, the numbered pins, boxes and arrows in the picture's own pixels, ready to paste
// into the figure() calls in templates/help.html. Chrome must be installed; set CHROME to its path
// if it isn't in the usual place.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.argv[2] ?? "http://localhost:8000";
const OUT = new URL("../../src/simple_task_management/static/help/", import.meta.url).pathname;
const CHROME =
  process.env.CHROME ??
  ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"].find(existsSync);
const PORT = 9333;
const SCALE = 2;
const PASSWORD = "demo-pass";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- Chrome and the debugging protocol ---------------------------------------------------
const profile = mkdtempSync(join(tmpdir(), "help-shots-"));
const chrome = spawn(
  CHROME,
  ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--no-first-run", "--hide-scrollbars", "about:blank"],
  { stdio: "ignore" },
);
const stop = () => {
  chrome.kill();
  try {
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  } catch {
    /* Chrome may still be writing to its scratch folder; the system clears it later */
  }
};
process.on("exit", stop);

let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    target = list.find((t) => t.type === "page");
  } catch {
    /* Chrome is still starting */
  }
}
if (!target) throw new Error("Chrome did not start");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve) => (socket.onopen = resolve));
let nextId = 0;
const waiting = new Map();
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && waiting.has(message.id)) {
    const { resolve, reject } = waiting.get(message.id);
    waiting.delete(message.id);
    message.error ? reject(new Error(message.error.message)) : resolve(message.result);
  }
};
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++nextId;
    waiting.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });

/** Run JavaScript in the page and return its (JSON) result. */
async function js(expression) {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
  return r.result.value;
}

// ---- page helpers, defined inside the page ----------------------------------------------
const HELPERS = `
window.$h = {
  // A CSS selector, or "text:Label" (starts with) or "text~:Label" (contains) for the first button, link, summary, label, heading or list item with that text.
  find(sel, nth = 0) {
    if (sel.startsWith("text:") || sel.startsWith("text~:")) {
      const contains = sel.startsWith("text~:");
      const want = sel.slice(contains ? 6 : 5);
      const all = [...document.querySelectorAll("button, a, summary, label, h1, h2, h3, li, span, p")];
      const hit = (e) => (contains ? e.textContent.includes(want) : e.textContent.trim().startsWith(want));
      return all.filter((e) => hit(e) && e.getClientRects().length)[nth] ?? null;
    }
    return [...document.querySelectorAll(sel)].filter((e) => e.getClientRects().length)[nth] ?? null;
  },
  rect(sel, nth = 0) {
    const e = this.find(sel, nth);
    if (!e) return null;
    const r = e.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  },
  set(sel, value) {
    const e = this.find(sel);
    const proto = e instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(e, value);
    e.dispatchEvent(new Event("input", { bubbles: true }));
    e.dispatchEvent(new Event("change", { bubbles: true }));
  },
  click(sel, nth = 0) {
    const e = this.find(sel, nth);
    if (!e) throw new Error("nothing to click: " + sel);
    e.click();
  },
};`;

async function waitFor(expression, what, tries = 60) {
  for (let i = 0; i < tries; i++) {
    if (await js(expression)) return;
    await sleep(100);
  }
  throw new Error("timed out waiting for " + what);
}

async function go(path) {
  await send("Page.navigate", { url: BASE + path });
  await sleep(700);
  await js(HELPERS);
  await sleep(300);
}

async function viewport(kind) {
  const phone = kind === "phone";
  await send("Emulation.setDeviceMetricsOverride", {
    width: phone ? 390 : 1512,
    height: phone ? 844 : 900,
    deviceScaleFactor: SCALE,
    mobile: phone,
  });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });
}

async function api(path, method = "GET", body) {
  return js(`(async () => {
    const me = await (await fetch("/api/me")).json().catch(() => null);
    const r = await fetch("/api${path}", { method: "${method}", headers: { "Content-Type": "application/json", "X-CSRF-Token": me?.csrf_token ?? "" }, body: ${JSON.stringify(body === undefined ? null : JSON.stringify(body))} });
    return r.status === 204 ? null : r.json();
  })()`);
}

async function signIn(username, password = PASSWORD) {
  await go("/help"); // any page on the site, so the cookie belongs to it
  await js(`fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "${username}", password: "${password}" }) }).then((r) => r.status)`);
}

// ---- taking one picture ------------------------------------------------------------------
const R = (v) => Math.round(v);

/**
 * Take a picture of an area (a selector, or {x, y, w, h}) and print its figure() arguments.
 * pins:   [[number, selector, anchor, nth?], ...]  anchor: see point() below (c, l, r, t, b, L, R, A, B, tr)
 * boxes:  [[selector, padding, nth?], ...]
 * arrows: [[x1, y1, x2, y2], ...] in CSS pixels of the page
 */
async function shot(name, area, { pad = 0, pins = [], boxes = [], arrows = [], quality = 82 } = {}) {
  await sleep(250);
  const base = typeof area === "string" ? await js(`$h.rect(${JSON.stringify(area)})`) : area;
  if (!base) throw new Error("nothing to photograph: " + JSON.stringify(area));
  const vw = await js("innerWidth");
  const vh = await js("innerHeight");
  const x = Math.max(0, base.x - pad);
  const y = Math.max(0, base.y - pad);
  const w = Math.min(vw - x, base.w + 2 * pad);
  const h = Math.min(vh - y, base.h + 2 * pad);
  const { data } = await send("Page.captureScreenshot", { format: "jpeg", quality, clip: { x, y, width: w, height: h, scale: 1 } });
  writeFileSync(join(OUT, name + ".jpg"), Buffer.from(data, "base64"));

  const point = async (sel, anchor, nth) => {
    const r = await js(`$h.rect(${JSON.stringify(sel)}, ${nth ?? 0})`);
    if (!r) throw new Error(`${name}: no element for ${sel}`);
    const inset = 14;
    const cx = r.x + r.w / 2;
    const cy = r.y + r.h / 2;
    // c: centre; l, r, t, b: just inside that edge; L, R, A, B: just outside it (left, right, above, below);
    // tr: on the top right corner, like a badge.
    const at = {
      c: [cx, cy], l: [r.x + inset, cy], r: [r.x + r.w - inset, cy], t: [cx, r.y + inset], b: [cx, r.y + r.h - inset],
      L: [r.x - 16, cy], R: [r.x + r.w + 16, cy], A: [cx, r.y - 14], B: [cx, r.y + r.h + 14], tr: [r.x + r.w, r.y],
    }[anchor];
    // Keep the pin inside the picture.
    const px = Math.min(Math.max(at[0], x + 12), x + w - 12);
    const py = Math.min(Math.max(at[1], y + 12), y + h - 12);
    return [R((px - x) * SCALE), R((py - y) * SCALE)];
  };
  const out = { size: `${R(w * SCALE)} x ${R(h * SCALE)}`, pins: [], boxes: [], arrows: [] };
  for (const [n, sel, anchor = "c", nth] of pins) out.pins.push([n, ...(await point(sel, anchor, nth))]);
  for (const [sel, p = 6, nth = 0] of boxes) {
    const r = await js(`$h.rect(${JSON.stringify(sel)}, ${nth})`);
    const bx = Math.max(r.x - p, x + 3);
    const by = Math.max(r.y - p, y + 3);
    const bw = Math.min(r.x + r.w + p, x + w - 3) - bx;
    const bh = Math.min(r.y + r.h + p, y + h - 3) - by;
    out.boxes.push([R((bx - x) * SCALE), R((by - y) * SCALE), R(bw * SCALE), R(bh * SCALE)]);
  }
  for (const [x1, y1, x2, y2] of arrows) out.arrows.push([R((x1 - x) * SCALE), R((y1 - y) * SCALE), R((x2 - x) * SCALE), R((y2 - y) * SCALE)]);
  const list = (items) => "[" + items.map((i) => "(" + i.join(", ") + ")").join(", ") + "]";
  console.log(`\n${name}  (${out.size})`);
  console.log(`  figure("${name}", ${R(w * SCALE)}, ${R(h * SCALE)}, "...",`);
  if (out.pins.length) console.log(`     pins=${list(out.pins)}`);
  if (out.boxes.length) console.log(`     boxes=${list(out.boxes)}`);
  if (out.arrows.length) console.log(`     arrows=${list(out.arrows)}`);
}

const closeDialogs = () => js(`document.querySelectorAll("dialog[open]").forEach((d) => d.close()); document.querySelector(".usermenu")?.removeAttribute("open")`);

// ---- the scenes --------------------------------------------------------------------------
await send("Page.enable");
await send("Network.enable");
await send("Browser.grantPermissions", { permissions: ["notifications"], origin: BASE }).catch(() => {});
await viewport("desktop");

// Signing in
await go("/");
await waitFor(`!!document.querySelector("input[name=username]")`, "the sign-in form");
await js(`$h.set("input[name=username]", "ravi")`);
await shot("login", ".center-card", {
  pad: 40,
  pins: [
    [1, "input[name=username]", "r"],
    [2, "input[name=password]", "r"],
    [3, "form button[type=submit]", "r"],
    [4, "a[href='/help']", "R"],
  ],
});

// Some extra work for today, so the "Show more" button and a lively board appear
await signIn("asha");
const today = (await api("/meta")).today;
const asha = (await api("/me")).id;
for (const title of ["File GSTR-1 - Khan Traders", "Reply to GST notice - Shah & Sons", "TDS challan - Patel Traders"]) {
  await api("/tasks", "POST", { title, due: today, repeat: "none", assignee_ids: [asha] });
}
await go("/");
await waitFor(`!!document.querySelector("article.card")`, "the board");

// The board
const dragFrom = await js(`$h.rect("article.card", 1)`);
const doing = await js(`$h.rect(".col[data-status=doing] h3")`);
await shot("board", { x: 0, y: 0, w: 1512, h: 800 }, {
  pins: [
    [1, "#who", "B"],
    [2, ".help-link", "L"],
    [3, ".new-btn", "tr"],
    [4, ".usermenu summary", "B"],
    [5, "#summary .summary", "t"],
    [6, ".sumcard.today .sum-toggle", "R"],
    [7, ".col[data-status=doing] h3", "c"],
    [8, "article.card", "r", 1],
    [9, ".col[data-status=done] .btn.link", "R"],
  ],
  boxes: [["#summary .summary", 8], [".board", 8], ["article.card", 4, 1]],
  arrows: [[dragFrom.x + dragFrom.w - 60, dragFrom.y + dragFrom.h / 2, doing.x + doing.w / 2, doing.y + 150]],
});

// One card (a quarterly one, with comments and two people)
await shot("card", ".col[data-status=doing] article.card", {
  pad: 30,
  pins: [
    [1, ".col[data-status=doing] .card-title", "B"],
    [2, ".col[data-status=doing] .due-chip", "A"],
    [3, ".col[data-status=doing] .chip.blue", "A"],
    [4, ".col[data-status=doing] .comments", "A"],
    [5, ".col[data-status=doing] .avatars", "A"],
  ],
});

// Creating a task
await js(`$h.click(".new-btn")`);
await waitFor(`!!$h.find("dialog[open] input[name=title]")`, "the New task form");
await js(`$h.set("dialog[open] input[name=title]", "GSTR-1 - Patel Traders"); $h.set("dialog[open] textarea[name=notes]", "Sales register is in the shared folder.")`);
await shot("new-task", "dialog.modal[open]", {
  pad: 24,
  pins: [
    [1, "dialog[open] input[name=title]", "r"],
    [2, "dialog[open] fieldset .chips", "R"],
    [3, "dialog[open] input[name=due]", "R"],
    [4, "dialog[open] select[name=repeat]", "R"],
    [5, "dialog[open] textarea[name=notes]", "r"],
    [6, "dialog[open] button[type=submit]", "tr"],
  ],
});
await closeDialogs();

// An open task
await js(`$h.click(".col[data-status=doing] article.card")`);
await waitFor(`!!$h.find("dialog.drawer[open] .thread")`, "the task");
await sleep(600);
await shot("drawer", "dialog.drawer[open]", {
  pins: [
    [1, "dialog.drawer[open] .title-input", "r"],
    [2, "dialog.drawer[open] .panel-head .btn.icon:not(.back-btn)", "B"],
    [3, "dialog.drawer[open] .notes-input", "r"],
    [4, "dialog.drawer[open] .thread", "l"],
    [5, "dialog.drawer[open] .composer textarea", "r"],
    [6, "dialog.drawer[open] .composer button[type=submit]", "L"],
    [7, "dialog.drawer[open] .status-seg", "L"],
    [8, "dialog.drawer[open] .panel-side .chips", "L"],
    [9, "dialog.drawer[open] input[type=date]", "L"],
    [10, "dialog.drawer[open] select[name=repeat]", "L"],
    [11, "text:Delete task", "L"],
  ],
  boxes: [["dialog.drawer[open] .thread-scroll", 6]],
});
const taskId = await js(`$h.find("dialog.drawer[open] .panel").dataset.taskId`);
await closeDialogs();

// A recurring task, just marked Done
await api(`/tasks/${taskId}`, "PATCH", { status: "done" });
await go("/");
await waitFor(`!!$h.find(".col[data-status=done] article.card")`, "the Done column");
await js(`$h.click(".col[data-status=done] article.card")`);
await waitFor(`!!$h.find("dialog.drawer[open] .thread")`, "the task");
await js(`document.querySelector("dialog.drawer[open] details.series").open = true`);
await sleep(500);
await shot("recurring", "dialog.drawer[open]", {
  pins: [
    [1, "dialog.drawer[open] .status-seg", "L"],
    [2, "text~:marked this Done", "L"],
    [3, "text~:Next occurrence created", "L"],
    [4, "dialog.drawer[open] select[name=repeat]", "L"],
    [5, "dialog.drawer[open] details.series summary", "L"],
  ],
  boxes: [["text~:marked this Done", 6], ["text~:Next occurrence created", 6]],
});
await closeDialogs();

// Your menu
await go("/");
await waitFor(`!!$h.find(".usermenu summary")`, "the menu");
await js(`$h.click(".usermenu summary")`);
await sleep(300);
await shot("menu", { x: 1512 - 380, y: 0, w: 380, h: 430 }, {
  pins: [
    [1, ".help-link", "L"],
    [2, ".usermenu .seg", "R"],
    [3, "text:Notification settings", "r"],
    [4, "text:Change password", "r"],
    [5, "text:Manage people", "r"],
    [6, "text:Updates", "r"],
    [7, "text:Sign out", "r"],
  ],
});

// The People window, after adding someone
await js(`$h.click("text:Manage people")`);
await waitFor(`!!$h.find("#people input[name=name]")`, "the People window");
await js(`$h.set("#people input[name=name]", "Neha Rao"); $h.set("#people input[name=username]", "neha")`);
await js(`$h.click("text:Add person")`);
await waitFor(`!!$h.find("#people .flash code")`, "the temporary password");
const temp = await js(`$h.find("#people .flash code").textContent`);
await shot("people", "dialog.modal.wide[open]", {
  pad: 24,
  pins: [
    [1, "#people .flash", "r"],
    [2, "text:Reset password", "tr"],
    [3, "text:Make admin", "tr"],
    [4, "#people .people .btn.danger", "tr"],
    [5, "#people input[name=name]", "r"],
    [6, "text:Add person", "tr"],
  ],
});
await closeDialogs();

// The bell's list
await go("/");
await waitFor(`!!$h.find("#bell-btn")`, "the bell");
await js(`$h.click("#bell-btn")`);
await waitFor(`document.querySelector("#notif-panel").matches(":popover-open")`, "the list");
await sleep(400);
const panel = await js(`$h.rect("#notif-panel")`);
await shot("notifications", { x: panel.x - 16, y: 0, w: panel.w + 32, h: panel.y + panel.h + 16 }, {
  pins: [
    [1, "#bell-btn", "tr"],
    [2, "#notif-panel .nrow .nmain", "b"],
    [3, "#notif-panel .nrow .iconbtn", "tr", 0],
    [4, "#notif-panel .nrow .iconbtn", "tr", 1],
    [5, "text:Mark all read", "R"],
    [6, "text:Settings", "L"],
  ],
});
await js(`document.querySelector("#notif-panel").hidePopover()`);

// Notification settings
await js(`$h.click(".usermenu summary")`);
await sleep(200);
await js(`$h.click("text:Notification settings")`);
await waitFor(`!!$h.find("#notif-settings .seg")`, "the settings");
await sleep(500);
await shot("settings", "dialog.modal[open]", {
  pad: 24,
  pins: [
    [1, "#notif-settings .alerts-optin", "tr"],
    [2, "#notif-settings .seg", "R"],
    [3, "#notif-settings .nset-more summary", "R"],
  ],
});
await closeDialogs();

// The first sign-in of the person just added
await send("Network.clearBrowserCookies");
await signIn("neha", temp);
await go("/");
await waitFor(`!!$h.find("input[name=new_password]")`, "the choose-a-password screen");
await js(`$h.set("input[name=new_password]", "a-good-password"); $h.set("input[name=confirm_password]", "a-good-password")`);
await shot("first-sign-in", ".center-card", {
  pad: 40,
  pins: [
    [1, "input[name=new_password]", "r"],
    [2, "input[name=confirm_password]", "r"],
    [3, "form button[type=submit]", "tr"],
  ],
});
await send("Network.clearBrowserCookies");

// The phone
await signIn("asha");
const lateDay = new Date(Date.parse(today) - 3 * 86400000).toISOString().slice(0, 10);
await api("/tasks", "POST", { title: "Respond to IT notice - Mehta & Co", due: lateDay, repeat: "none", assignee_ids: [asha] });
await viewport("phone");
await go("/");
await waitFor(`!!$h.find("article.card")`, "the board");
const screen = { x: 0, y: 0, w: 390, h: 844 };
await shot("m-board", screen, {
  pins: [
    [1, "#who", "tr"],
    [2, ".search-btn", "tr"],
    [3, ".new-btn", "tr"],
    [4, ".deadline-line", "tr"],
    [5, ".col-tabs", "tr"],
    [6, ".swipe-tip", "tr"],
    [7, "article.card", "tr"],
    [8, ".tabbar [data-tab=soon]", "tr"],
  ],
});
await js(`$h.click(".tabbar [data-tab=soon]")`);
await sleep(300);
await shot("m-soon", screen, {
  pins: [
    [1, ".sumcard.overdue h3", "c"],
    [2, ".sumcard.today .sum-item", "tr"],
    [3, ".sumcard.today .sum-toggle", "R"],
  ],
});
await js(`$h.click(".tabbar [data-tab=board]")`);
await sleep(300);
await js(`$h.click(".col[data-status=todo] article.card")`);
await waitFor(`!!$h.find("dialog.drawer[open] .thread")`, "the task");
await sleep(700);
await shot("m-task", screen, {
  pins: [
    [1, "dialog.drawer[open] .back-btn", "tr"],
    [2, "dialog.drawer[open] .status-seg", "tr"],
    [3, "dialog.drawer[open] .composer textarea", "tr"],
  ],
});
await closeDialogs();
await js(`$h.click(".tabbar [data-tab=alerts]")`);
await sleep(400);
await shot("m-alerts", screen, {
  pins: [
    [1, ".alerts-view .nrow .nmain", "tr"],
    [2, ".alerts-view .nrow .iconbtn", "tr", 0],
    [3, ".tabbar [data-tab=alerts]", "tr"],
  ],
});
await js(`$h.click(".tabbar [data-tab=me]")`);
await sleep(400);
await shot("m-me", screen, {
  pins: [
    [1, ".me-theme", "tr"],
    [2, ".me-list button", "tr", 0],
    [3, ".me-list a[href='/help']", "tr"],
    [4, ".me-list .danger", "tr"],
  ],
});

// The menu a long press opens on a card
await js(`$h.click(".tabbar [data-tab=board]")`);
await sleep(400);
const card = await js(`$h.rect(".col[data-status=todo] article.card")`);
const touch = (type, points) => send("Input.dispatchTouchEvent", { type, touchPoints: points });
const at = [{ x: card.x + card.w / 2, y: card.y + card.h / 2 }];
await touch("touchStart", at);
await sleep(900);
await touch("touchEnd", []);
await sleep(500);
if (await js(`!!document.querySelector("dialog#card-actions[open]")`)) {
  await shot("m-actions", screen, {
    pins: [
      [1, "#card-actions .msg", "tr"],
      [2, "#card-actions button", "tr", 1],
      [3, "#card-actions .danger", "tr"],
    ],
  });
} else {
  console.log("\nm-actions: the long press did not open the menu; no picture taken");
}

socket.close();
stop();
process.exit(0);
