// The top bar, the phone's tab bar and Me / Alerts pages, the card actions sheet and the banner.
import { useEffect, useRef } from "preact/hooks";
import type { Theme } from "../api/types";
import {
  banner, cardActions, chooseTheme, deleteTask, dismissBanner, liveMessage, me, modal, moveTask, openTask,
  people, search, setSearch, setTab, setWho, signOut, summary, tab, unread, updateInfo, who,
} from "../state";
import { Avatar } from "./bits";
import { Icon } from "./Icon";
import { AlertsOptin, Bell, CountBadge, NotificationList } from "./Notifications";

const THEMES: Theme[] = ["system", "light", "dark"];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function ThemeChoice({ class: cls }: { class?: string }) {
  const current = me.value?.theme;
  return (
    <div class={`seg${cls ? " " + cls : ""}`} role="group" aria-label="Theme">
      {THEMES.map((t) => (
        <button key={t} type="button" data-theme-choice={t} aria-pressed={current === t} onClick={() => chooseTheme(t)}>
          {cap(t)}
        </button>
      ))}
    </div>
  );
}

function UserMenu() {
  const user = me.value!;
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) ref.current.open = false;
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  const choose = (name: "notif-settings" | "password" | "people" | "updates") => {
    if (ref.current) ref.current.open = false;
    modal.value = name;
  };
  return (
    <details class="usermenu" ref={ref}>
      <summary>
        <Avatar id={user.id} name={user.name} /> {user.name.split(" ")[0]} <Icon name="chevron" size={14} />
      </summary>
      <div class="menu">
        <div class="menu-item strong">
          {user.name} {user.is_admin && <span class="chip">admin</span>}
        </div>
        <div class="menu-item">
          <div class="muted small">Theme</div>
          <ThemeChoice />
        </div>
        <button type="button" class="menu-item" onClick={() => choose("notif-settings")}>
          Notification settings
        </button>
        <button type="button" class="menu-item" onClick={() => choose("password")}>
          Change password
        </button>
        {user.is_admin && (
          <button type="button" class="menu-item" onClick={() => choose("people")}>
            Manage people
          </button>
        )}
        {user.is_admin && (
          <button type="button" class="menu-item" onClick={() => choose("updates")}>
            Updates{updateInfo.value?.available ? " · new version" : ""}
          </button>
        )}
        <button type="button" class="menu-item sep" onClick={signOut}>
          Sign out
        </button>
      </div>
    </details>
  );
}

export function TopBar() {
  return (
    <header class="topbar">
      <span class="brand">Tasks</span>
      <label class="muted who-label" for="who">
        Showing
      </label>
      <select id="who" name="who" value={who.value} onChange={(e) => setWho(e.currentTarget.value)}>
        <option value="me">My tasks</option>
        <option value="all">Everyone</option>
        <option value="none">Unassigned</option>
        <optgroup label="Person">
          {people.value.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {p.name}
            </option>
          ))}
        </optgroup>
      </select>
      <input
        id="q"
        class="search"
        type="search"
        placeholder="Search tasks"
        aria-label="Search tasks by title"
        aria-keyshortcuts="/"
        value={search.value}
        onInput={(e) => setSearch(e.currentTarget.value)}
        onKeyDown={(e) => e.key === "Escape" && search.value && (e.preventDefault(), setSearch(""))}
      />
      <span class="spacer" />
      <a class="help-link" href="/help" target="_blank" rel="noopener">
        <Icon name="help" size={16} /> Help
      </a>
      <Bell />
      <button class="btn primary new-btn" type="button" aria-label="New task" aria-keyshortcuts="n" onClick={() => (modal.value = "new-task")}>
        +<span class="lbl"> New task</span>
      </button>
      <UserMenu />
    </header>
  );
}

export function TabBar() {
  const overdue = summary.value?.overdue.length ?? 0;
  const current = (name: string) => (tab.value === name ? "page" : undefined);
  return (
    <nav class="tabbar" aria-label="Sections">
      <button type="button" data-tab="board" aria-current={current("board")} onClick={() => setTab("board")}>
        <Icon name="board" size={22} />
        <span>Board</span>
      </button>
      <button type="button" data-tab="soon" aria-current={current("soon")} onClick={() => setTab("soon")}>
        <Icon name="calendar" size={22} />
        <span>Coming up</span>
        <CountBadge count={overdue} class="badge" />
      </button>
      <button type="button" data-tab="alerts" aria-current={current("alerts")} onClick={() => setTab("alerts")}>
        <Icon name="bell" size={22} />
        <span>Alerts</span>
        <CountBadge count={unread.value} class="badge" />
      </button>
      <button type="button" data-tab="me" aria-current={current("me")} onClick={() => setTab("me")}>
        <Icon name="user" size={22} />
        <span>Me</span>
      </button>
    </nav>
  );
}

export function AlertsView() {
  return (
    <section id="alerts-view" class="alerts-view" aria-label="Alerts">
      <h1 class="me-title">Alerts</h1>
      <AlertsOptin />
      <div id="alerts-list">
        <NotificationList />
      </div>
    </section>
  );
}

export function MeView() {
  const user = me.value!;
  return (
    <section id="me-view" class="me-view" aria-label="Me">
      <h1 class="me-title">Me</h1>
      <div class="me-card">
        <Avatar id={user.id} name={user.name} large />
        <div>
          <strong>{user.name}</strong> {user.is_admin && <span class="chip">admin</span>}
        </div>
      </div>
      <h2 class="me-label">Appearance</h2>
      <ThemeChoice class="me-theme" />
      <h2 class="me-label">Account</h2>
      <div class="me-list">
        <button type="button" onClick={() => (modal.value = "notif-settings")}>
          Notification settings <Icon name="chevron-right" size={16} />
        </button>
        <button type="button" onClick={() => (modal.value = "password")}>
          Change password <Icon name="chevron-right" size={16} />
        </button>
        {user.is_admin && (
          <button type="button" onClick={() => (modal.value = "people")}>
            Manage people <Icon name="chevron-right" size={16} />
          </button>
        )}
        {user.is_admin && (
          <button type="button" onClick={() => (modal.value = "updates")}>
            Updates{updateInfo.value?.available ? " · new version" : ""} <Icon name="chevron-right" size={16} />
          </button>
        )}
        <a href="/help">
          How to use this app <Icon name="chevron-right" size={16} />
        </a>
      </div>
      <div class="me-list">
        <button type="button" class="danger" onClick={signOut}>
          Sign out
        </button>
      </div>
      <p class="muted small me-foot">Stays signed in for 30 days on this phone.</p>
    </section>
  );
}

/** The sheet a phone shows on long-press or swipe-left: Open, Move to…, Delete…. */
export function CardActions() {
  const ref = useRef<HTMLDialogElement>(null);
  const target = cardActions.value;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (target && !dialog.open) dialog.showModal();
    if (!target && dialog.open) dialog.close();
  }, [target]);
  const done = () => (cardActions.value = null);
  const labels = { todo: "To do", doing: "Doing", done: "Done" } as const;
  return (
    <dialog
      ref={ref}
      id="card-actions"
      class="actions"
      aria-label="Task actions"
      onClose={done}
      onClick={(e) => e.target === ref.current && done()}
    >
      {target && (
        <>
          <div class="box">
            <div class="msg">{target.title}</div>
            <button type="button" onClick={() => { done(); openTask(target.id); }}>
              Open
            </button>
            {(Object.keys(labels) as (keyof typeof labels)[])
              .filter((k) => k !== target.status)
              .map((k) => (
                <button key={k} type="button" onClick={() => { done(); void moveTask(target.id, k); }}>
                  Move to {labels[k]}
                </button>
              ))}
            <button
              type="button"
              class="danger"
              onClick={() => {
                done();
                if (confirm("Delete this task and all its updates? This can't be undone.")) void deleteTask(target.id);
              }}
            >
              Delete…
            </button>
          </div>
          <button type="button" class="cancel" onClick={done}>
            Cancel
          </button>
        </>
      )}
    </dialog>
  );
}

/** The red error message at the top of the page (a popover, so it shows above open dialogs). It stays until dismissed. */
export function Banner() {
  const ref = useRef<HTMLDivElement>(null);
  const message = banner.value;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (message) {
      if (el.matches(":popover-open")) el.hidePopover();
      el.showPopover();
    } else if (el.matches(":popover-open")) el.hidePopover();
  }, [message]);
  return (
    <>
      <div id="banner" role="alert" ref={ref} {...{ popover: "manual" }}>
        <span>{message}</span>
        <button type="button" class="iconbtn" aria-label="Dismiss this message" onClick={dismissBanner}>
          <Icon name="close" size={16} />
        </button>
      </div>
      <div class="sr-only" role="status" aria-live="polite">
        {liveMessage.value}
      </div>
    </>
  );
}
