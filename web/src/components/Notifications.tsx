// The bell, its panel, the phone's Alerts list, on-page messages and the settings form.
import { useSignal } from "@preact/signals";
import { alertState, enableAlerts, removeToast, testAlert, toasts } from "../alerts";
import {
  clearReadNotifications, dismissNotification, markAllRead, markRead, markUnread, meta,
  modal, notifications, openNotification, refreshNotifications, refreshSettings,
  saveNotificationSetting, settings, unread,
} from "../state";
import type { Mode } from "../api/types";
import { Icon } from "./Icon";
import { useEffect } from "preact/hooks";

export function AlertsOptin() {
  return (
    <div class="alerts-optin" data-state={alertState.value}>
      <p class="s-ask">
        Get a desktop alert when someone changes one of your tasks.{" "}
        <button type="button" class="btn small primary" onClick={enableAlerts}>
          Turn on desktop alerts
        </button>
      </p>
      <p class="s-on">
        Desktop alerts are on for this browser.{" "}
        <button type="button" class="linkbtn" onClick={testAlert}>
          Send a test
        </button>
      </p>
      <p class="s-blocked">
        Desktop alerts are blocked in this browser. To get them, allow notifications for this site from the padlock beside the
        address, then reload.
      </p>
      <p class="s-unsupported">
        Desktop alerts aren't available in this browser. New notifications still appear here and as a banner while the page is open.
      </p>
    </div>
  );
}

export function NotificationList() {
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
  const anyUnread = items.some((n) => !n.read);
  const allUnread = items.every((n) => !n.read);
  return (
    <>
      <div class="nbar">
        <button type="button" class="linkbtn" disabled={!anyUnread} onClick={markAllRead}>
          Mark all read
        </button>
        <button type="button" class="linkbtn" disabled={allUnread} onClick={clearReadNotifications}>
          Clear read
        </button>
      </div>
      <ul class="nlist">
        {items.map((n) => {
          const body = (
            <>
              <span class="ntext">
                {!n.read && <span class="sr-only">Unread. </span>}
                <strong>{n.actor}</strong> {n.body}
              </span>
              <span class="ntitle">{n.title}</span>
              <span class="nmeta">
                {n.due_label && <span class={`chip ${n.due_tone}`}>{n.due_label}</span>}
                <span>{n.when}</span>
              </span>
            </>
          );
          return (
            <li key={n.id} class={`nrow ${n.read ? "read" : "unread"}`}>
              <span class="ndot" aria-hidden="true" />
              {n.task_id !== null ? (
                <button type="button" class="nmain" onClick={() => {
                  closePanel();
                  openNotification(n.task_id, n.read ? null : n.id);
                }}>
                  {body}
                </button>
              ) : (
                <div class="nmain">{body}</div>
              )}
              <div class="nacts">
                {n.read ? (
                  <button type="button" class="iconbtn" aria-label="Mark as unread" title="Mark as unread" onClick={() => markUnread(n.id)}>
                    <Icon name="dot" size={18} />
                  </button>
                ) : (
                  <button type="button" class="iconbtn" aria-label="Mark as read" title="Mark as read" onClick={() => markRead(n.id)}>
                    <Icon name="check" size={18} />
                  </button>
                )}
                <button type="button" class="iconbtn" aria-label="Dismiss" title="Dismiss" onClick={() => dismissNotification(n.id)}>
                  <Icon name="close" size={18} />
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function closePanel(): void {
  const panel = document.getElementById("notif-panel");
  if (panel?.matches(":popover-open")) panel.hidePopover();
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
        aria-label={`Notifications${count ? `, ${count} unread` : ""}`}
      >
        <Icon name="bell" size={20} />
        {count > 0 && (
          <span class="nbadge" aria-hidden="true">
            {count < 10 ? count : "9+"}
          </span>
        )}
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
      onToggle={(e) => (e as ToggleEvent).newState === "open" && void refreshNotifications()}
    >
      <div class="notif-head">
        <strong>Notifications</strong>
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

export function Toasts() {
  return (
    <div id="toasts" role="status" aria-live="polite">
      {toasts.value.map((t) => (
        <div class="toast" key={t.id}>
          <button
            type="button"
            class="toast-open"
            onClick={() => {
              openNotification(t.taskId, t.id);
              removeToast(t.id);
            }}
          >
            <strong>{t.text}</strong>
            <span>{t.detail}</span>
          </button>
          <button type="button" class="iconbtn" aria-label="Dismiss alert" onClick={() => removeToast(t.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export function NotificationSettings() {
  const saved = useSignal("");
  useEffect(() => {
    void refreshSettings();
  }, []);
  const current = settings.value;
  const kinds = meta.value?.notification_kinds ?? [];
  const modes = meta.value?.notification_modes ?? [];
  return (
    <>
      <AlertsOptin />
      <div id="notif-settings">
        <h2>Notification settings</h2>
        <p class="muted small">
          Choose what you hear about when someone else changes a task you're on. You never hear about your own changes.
        </p>
        {current && (
          <form class="nset" onSubmit={(e) => e.preventDefault()}>
            {kinds.map((k) => (
              <fieldset key={k.kind}>
                <legend>{k.label}</legend>
                <p class="muted small">{k.help}</p>
                <div class="seg" role="radiogroup">
                  {modes.map((m) => (
                    <label class="segopt" key={m.value}>
                      <input
                        type="radio"
                        name={`mode_${k.kind}`}
                        value={m.value}
                        checked={current[k.kind] === m.value}
                        onChange={async () => {
                          saved.value = "";
                          try {
                            await saveNotificationSetting(k.kind, m.value as Mode);
                            saved.value = "Saved ✓";
                          } catch {
                            saved.value = "Couldn't save. Please try again.";
                            void refreshSettings();
                          }
                        }}
                      />
                      <span>{m.label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
            <p class="muted small">
              <strong>Alert me</strong>: in your bell, a message on the page, and a desktop alert if you've turned those on.{" "}
              <strong>Inbox only</strong>: in your bell, quietly. <strong>Off</strong>: not at all.
            </p>
            <p id="notif-saved" class="saved" aria-live="polite">
              {saved.value}
            </p>
          </form>
        )}
      </div>
    </>
  );
}
