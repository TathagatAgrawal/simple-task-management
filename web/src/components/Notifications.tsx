// The bell, its panel, the phone's Alerts list, on-page messages and the settings form.
import { useSignal } from "@preact/signals";
import { useEffect } from "preact/hooks";
import {
  alertState, disablePush, enableAlerts, enablePush, pushError, pushInfo, pushState, removeToast, setPushDetails,
  testAlert, testPush, toasts,
} from "../alerts";
import type { Mode, Notification } from "../api/types";
import {
  askConfirm, clearReadNotifications, dismissNotifications, markAllRead, markRead, markUnread, meta, modal,
  notifications, openNotification, panelOpen, refreshNotifications, refreshSettings,
  saveAllNotificationSettings, saveNotificationSetting, setTab, settings, unread,
} from "../state";
import { badgeText, groupNotifications, type NotificationGroup } from "../util";
import { Icon } from "./Icon";

const GROUPS_SHOWN = 8;
const LINES_SHOWN = 3;

/** A count in a red badge. Never wider than "99+", and the same on the bell and the tab bar. */
export function CountBadge({ count, class: cls }: { count: number; class?: string }) {
  return (
    <span class={cls ?? "nbadge"} aria-hidden="true" hidden={count === 0}>
      {badgeText(count)}
    </span>
  );
}

/**
 * The alerts setup row. Where the browser can do push, it turns on system alerts for this device
 * (they arrive even with the board closed). Otherwise it offers the older desktop alerts.
 * In the panel it shows only while there is something to do.
 */
export function AlertsOptin({ always }: { always?: boolean }) {
  const push = pushState.value;
  const system = push !== "unsupported" && push !== "server-off";
  const state = system ? push : alertState.value;
  if (!always && state !== "ask" && state !== "blocked" && state !== "install") return null;
  const details = pushInfo.value?.details ?? true;
  return (
    <div class="alerts-optin" data-state={state}>
      <p class="s-ask">
        {system
          ? "Get an alert on this device when someone changes one of your tasks, even when the board is closed."
          : "Get a desktop alert when someone changes one of your tasks."}{" "}
        <button type="button" class="btn small primary" onClick={system ? enablePush : enableAlerts}>
          {system ? "Turn on alerts on this device" : "Turn on desktop alerts"}
        </button>
      </p>
      <p class="s-on">
        {system ? "Alerts are on for this device." : "Desktop alerts are on for this browser."}{" "}
        <button type="button" class="linkbtn" onClick={system ? testPush : testAlert}>
          Send a test
        </button>
        {system && (
          <>
            {" "}
            <button type="button" class="linkbtn" onClick={disablePush}>
              Turn off
            </button>
          </>
        )}
      </p>
      <p class="s-blocked">
        Alerts are blocked in this browser. To get them, allow notifications for this site from the padlock beside the
        address, then reload.
      </p>
      <p class="s-install">
        To get alerts on an iPhone or iPad, add this page to your Home Screen (Share, then Add to Home Screen), open it from
        there, and turn alerts on in the notification settings.
      </p>
      <p class="s-unsupported">
        Alerts aren't available in this browser. You'll still see new changes in the bell and as a message on the page.
      </p>
      {always && system && push === "on" && (
        <label class="alerts-details">
          <input type="checkbox" checked={details} onChange={(e) => void setPushDetails(e.currentTarget.checked)} /> Show the
          task's name in alerts. Turn this off to keep it off a lock screen: alerts then say only "A task changed".
        </label>
      )}
      {pushError.value && (
        <p class="s-error" role="alert">
          {pushError.value}
        </p>
      )}
    </div>
  );
}

function closePanel(): void {
  const panel = document.getElementById("notif-panel");
  if (panel?.matches(":popover-open")) panel.hidePopover();
}

function focusAfter(selector: string | null, fallback: string): void {
  requestAnimationFrame(() => {
    const target = (selector && document.querySelector<HTMLElement>(selector)) || document.querySelector<HTMLElement>(fallback);
    target?.focus();
  });
}

function GroupRow({ g, neighbour }: { g: NotificationGroup<Notification>; neighbour: string | null }) {
  const newest = g.items[0]!;
  const many = g.items.length;
  const ids = g.items.map((n) => n.id);
  const shown = g.items.slice(0, LINES_SHOWN);
  const rest = many - shown.length;
  const label = many > 1 ? `${many} changes to ${g.title}` : g.title;
  const body = (
    <>
      <span class="ntitle">
        {!g.read && <span class="sr-only">Unread. </span>}
        {g.title}
      </span>
      {shown.map((n) => (
        <span class="ntext" key={n.id}>
          <strong>{n.actor}</strong> {n.body}
        </span>
      ))}
      {rest > 0 && <span class="nmore">and {rest} earlier</span>}
      {g.taskId === null && <span class="nmore">This task was deleted.</span>}
      <span class="nmeta">
        {newest.due_label && <span class={`chip ${newest.due_tone}`}>{newest.due_label}</span>}
        <span>{newest.when}</span>
      </span>
    </>
  );
  return (
    <li class={`nrow ${g.read ? "read" : "unread"}`} data-group={g.key}>
      <span class="ndot" aria-hidden="true" />
      {g.taskId !== null ? (
        <button
          type="button"
          class="nmain"
          onClick={() => {
            closePanel();
            // Opening the task marks everything in the row read, not only the newest.
            const unreadIds = g.items.filter((n) => !n.read).map((n) => n.id);
            if (unreadIds.length) void markRead(unreadIds);
            openNotification(g.taskId, null);
          }}
        >
          {body}
        </button>
      ) : (
        <div class="nmain">{body}</div>
      )}
      <div class="nacts">
        {g.read ? (
          <button type="button" class="iconbtn" aria-label={`Mark as unread: ${label}`} title="Mark as unread" onClick={() => markUnread(ids)}>
            <Icon name="dot" size={18} />
          </button>
        ) : (
          <button type="button" class="iconbtn" aria-label={`Mark as read: ${label}`} title="Mark as read" onClick={() => markRead(ids)}>
            <Icon name="check" size={18} />
          </button>
        )}
        <button
          type="button"
          class="iconbtn"
          aria-label={`Dismiss: ${label}`}
          title="Dismiss"
          onClick={async () => {
            await dismissNotifications(ids);
            // The row is gone: give keyboard focus to its neighbour so it isn't lost.
            focusAfter(neighbour ? `[data-group="${neighbour}"] .nmain, [data-group="${neighbour}"] .iconbtn` : null, "#notif-panel .linkbtn");
          }}
        >
          <Icon name="close" size={18} />
        </button>
      </div>
    </li>
  );
}

export function NotificationList() {
  const showAll = useSignal(false);
  const items = notifications.value;
  if (!items.length) {
    return (
      <p class="nempty">
        <strong>You're all caught up.</strong>
        <br />
        When someone changes a task you're on, it shows up here.
      </p>
    );
  }
  const groups = groupNotifications(items);
  const visible = showAll.value ? groups : groups.slice(0, GROUPS_SHOWN);
  const anyUnread = items.some((n) => !n.read);
  const readCount = items.filter((n) => n.read).length;
  return (
    <>
      <div class="nbar">
        <button type="button" class="linkbtn" disabled={!anyUnread} onClick={markAllRead}>
          Mark all read
        </button>
        <button
          type="button"
          class="linkbtn"
          disabled={readCount === 0}
          onClick={async () => {
            const ok = await askConfirm({
              title: `Clear ${readCount} read notification${readCount === 1 ? "" : "s"}?`,
              body: "They leave your list for good. Notifications you haven't read stay.",
              confirmLabel: "Clear",
            });
            if (ok) void clearReadNotifications();
          }}
        >
          Clear read
        </button>
      </div>
      <ul class="nlist">
        {visible.map((g, i) => (
          <GroupRow key={g.key} g={g} neighbour={(visible[i + 1] ?? visible[i - 1])?.key ?? null} />
        ))}
      </ul>
      {groups.length > GROUPS_SHOWN && (
        <button type="button" class="linkbtn nshow" onClick={() => (showAll.value = !showAll.value)}>
          {showAll.value ? "Show fewer" : `Show ${groups.length - GROUPS_SHOWN} older`}
        </button>
      )}
    </>
  );
}

export function Bell() {
  const count = unread.value;
  return (
    <span id="bell-badge" class="bell-wrap">
      <button
        id="bell-btn"
        type="button"
        class="bell"
        {...{ popovertarget: "notif-panel" }}
        aria-expanded={panelOpen.value}
        aria-controls="notif-panel"
        aria-label={`Notifications${count ? `, ${count} unread` : ""}`}
      >
        <Icon name="bell" size={20} />
        <CountBadge count={count} />
      </button>
    </span>
  );
}

export function BellPanel() {
  return (
    <div
      id="notif-panel"
      class="notif-panel"
      {...{ popover: "auto" }}
      aria-label="Notifications"
      onToggle={(e) => {
        const open = (e as ToggleEvent).newState === "open";
        panelOpen.value = open;
        if (open) {
          e.currentTarget.scrollTop = 0; // always start at the top, where the tools are
          void refreshNotifications();
        }
      }}
    >
      <div class="notif-head">
        <h2>Notifications</h2>
        <button
          type="button"
          class="linkbtn"
          onClick={() => {
            closePanel();
            modal.value = "notif-settings";
          }}
        >
          Settings
        </button>
      </div>
      <AlertsOptin />
      <div id="notif-list">
        <NotificationList />
      </div>
    </div>
  );
}

/** Messages on the page: top right under the bell, above everything (even an open panel). */
export function Toasts() {
  const list = toasts.value;
  useEffect(() => {
    const el = document.getElementById("toasts");
    if (!el) return;
    if (list.length && !el.matches(":popover-open")) el.showPopover();
    if (!list.length && el.matches(":popover-open")) el.hidePopover();
  }, [list.length]);
  return (
    <div id="toasts" role="status" aria-live="polite" {...{ popover: "manual" }}>
      {list.map((t) => (
        <div class={`toast${t.sticky ? " sticky" : ""}`} key={t.id}>
          <div class="toast-body">
            <strong>{t.text}</strong>
            <span class="toast-detail">{t.detail}</span>
            {t.dueLabel && <span class={`chip ${t.dueTone}`}>{t.dueLabel}</span>}
          </div>
          <div class="toast-acts">
            <button
              type="button"
              class="btn small primary"
              onClick={() => {
                removeToast(t.id);
                if (t.summary) {
                  const panel = document.getElementById("notif-panel");
                  if (panel && getComputedStyle(panel).display !== "none") panel.showPopover();
                  else setTab("alerts");
                } else openNotification(t.taskId, t.notificationId);
              }}
            >
              {t.summary ? "See all" : t.taskId === null ? "Dismiss" : "View"}
            </button>
            <button type="button" class="iconbtn" aria-label="Dismiss message" onClick={() => removeToast(t.id)}>
              <Icon name="close" size={16} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

const MODE_HELP: Record<string, string> = {
  alert: "A bell entry, and an alert on each device where you've turned alerts on (a message on the page if a device has none).",
  inbox: "A bell entry only, quietly.",
  off: "You aren't told.",
};

/** A short word for whether alerts are on for this device, shown beside the heading. */
function deviceStatus(): { label: string; tone: string } {
  const push = pushState.value;
  const system = push !== "unsupported" && push !== "server-off";
  const state = system ? push : alertState.value;
  if (state === "on") return { label: "On", tone: "green" };
  if (state === "blocked") return { label: "Blocked", tone: "red" };
  if (state === "install") return { label: "Needs Home Screen", tone: "amber" };
  if (state === "unsupported") return { label: "Not available", tone: "" };
  return { label: "Off", tone: "" };
}

export function NotificationSettings() {
  const saved = useSignal<{ kind: string; text: string } | null>(null);
  useEffect(() => {
    void refreshSettings();
  }, []);
  const current = settings.value;
  const kinds = meta.value?.notification_kinds ?? [];
  const modes = meta.value?.notification_modes ?? [];
  const status = deviceStatus();
  // One answer for everything when every kind has the same mode; otherwise it is "customised".
  const values = current ? kinds.map((k) => current[k.kind]) : [];
  const same = values.length > 0 && values.every((v) => v === values[0]) ? values[0] : null;
  const save = async (kind: string, run: () => Promise<void>) => {
    saved.value = null;
    try {
      await run();
      saved.value = { kind, text: "Saved ✓" };
    } catch {
      saved.value = { kind, text: "Couldn't save. Please try again." };
      void refreshSettings();
    }
  };
  return (
    <div id="notif-settings">
      <h2 id="notif-settings-title">Notification settings</h2>
      <p class="muted small">You hear about changes other people make to a task you're on or created. You never hear about your own.</p>

      <h3 class="nset-section">
        Alerts on this device <span class={`chip ${status.tone}`}>{status.label}</span>
      </h3>
      <AlertsOptin always />

      <h3 class="nset-section" id="nset-all">
        How much do you want to hear?
        <span class="saved" aria-live="polite">
          {saved.value?.kind === "all" ? saved.value.text : ""}
        </span>
      </h3>
      {current && (
        <>
          <div class="seg" role="radiogroup" aria-labelledby="nset-all">
            {modes.map((m) => (
              <label class="segopt" key={m.value}>
                <input
                  type="radio"
                  name="mode_all"
                  value={m.value}
                  checked={same === m.value}
                  onChange={() => save("all", () => saveAllNotificationSettings(m.value as Mode))}
                />
                <span>{m.label}</span>
              </label>
            ))}
          </div>
          <p class="muted small nset-help">
            {same ? MODE_HELP[same] : "Customised: you chose differently for some events below. Pick one above to set them all."}
          </p>

          <details class="nset-more" open={same === null}>
            <summary>Customise by event</summary>
            <form class="nset" onSubmit={(e) => e.preventDefault()}>
              {kinds.map((k) => (
                <div class="nset-row" key={k.kind}>
                  <div class="nset-q" id={`nset-${k.kind}`}>
                    {k.label}
                    <span class="saved" aria-live="polite">
                      {saved.value?.kind === k.kind ? saved.value.text : ""}
                    </span>
                  </div>
                  <p class="muted small">{k.help}</p>
                  <div class="seg" role="radiogroup" aria-labelledby={`nset-${k.kind}`}>
                    {modes.map((m) => (
                      <label class="segopt" key={m.value}>
                        <input
                          type="radio"
                          name={`mode_${k.kind}`}
                          value={m.value}
                          checked={current[k.kind] === m.value}
                          onChange={() => save(k.kind, () => saveNotificationSetting(k.kind, m.value as Mode))}
                        />
                        <span>{m.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </form>
          </details>
        </>
      )}
    </div>
  );
}
