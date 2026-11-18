// The New task, Change password and Manage people dialogs.
import { useSignal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api, ApiError } from "../api/client";
import { afterPeopleChange, checkForUpdate, chooseAutoUpdate, createTask, me, meta, modal, people, refreshUpdate, updateInfo } from "../state";
import { Avatar } from "./bits";
import { CloseButton } from "./Modal";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function NewTaskForm() {
  const user = me.value!;
  const [error, setError] = useState("");
  return (
    <form
      class="stack-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const data = new FormData(e.currentTarget);
        try {
          await createTask({
            title: String(data.get("title")),
            due: String(data.get("due")),
            notes: String(data.get("notes") ?? ""),
            repeat: String(data.get("repeat")),
            assignee_ids: data.getAll("assignee_ids").map(Number),
          });
          modal.value = null;
        } catch (err) {
          setError(message(err));
        }
      }}
    >
      <h2 id="new-task-title">New task</h2>
      <label>
        Title <input name="title" maxLength={200} required placeholder="e.g. GSTR-3B – Patel Traders" />
      </label>
      <fieldset>
        <legend>Assign to (pick any)</legend>
        <div class="chips">
          {people.value.map((p) => (
            <label class="chip-toggle" key={p.id}>
              <input type="checkbox" name="assignee_ids" value={p.id} defaultChecked={p.id === user.id} /> {p.name}
            </label>
          ))}
        </div>
      </fieldset>
      <div class="row">
        <label>
          Due <input type="date" name="due" defaultValue={meta.value?.today} required />
        </label>
        <label>
          Repeats
          <select name="repeat">
            {(meta.value?.repeats ?? []).map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Notes (optional) <textarea name="notes" rows={3} maxLength={5000} />
      </label>
      <p class="error form-error" aria-live="polite">
        {error}
      </p>
      <div class="row end">
        <button class="btn" type="button" onClick={() => (modal.value = null)}>
          Cancel
        </button>
        <button class="btn primary" type="submit">
          Create
        </button>
      </div>
    </form>
  );
}

export function PasswordForm() {
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  return (
    <form
      class="stack-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const data = new FormData(form);
        try {
          await api.changePassword(String(data.get("current_password")), String(data.get("new_password")), String(data.get("confirm_password")));
          form.reset();
          setError("");
          setDone(true);
        } catch (err) {
          setDone(false);
          setError(message(err));
        }
      }}
    >
      <h2 id="password-title">Change password</h2>
      <label>
        Current password <input name="current_password" type="password" autocomplete="current-password" required />
      </label>
      <label>
        New password <input name="new_password" type="password" autocomplete="new-password" minLength={8} required />
      </label>
      <label>
        Type it again <input name="confirm_password" type="password" autocomplete="new-password" minLength={8} required />
      </label>
      <div id="password-result">{done && <p class="ok">Password changed.</p>}</div>
      <p class="error form-error" aria-live="polite">
        {error}
      </p>
      <div class="row end">
        <button class="btn" type="button" onClick={() => (modal.value = null)}>
          Close
        </button>
        <button class="btn primary" type="submit">
          Change
        </button>
      </div>
    </form>
  );
}

export function PeopleDialog() {
  const user = me.value!;
  const flash = useSignal<ComponentChildren>(null);
  const [error, setError] = useState("");

  const run = async (action: () => Promise<ComponentChildren>) => {
    try {
      flash.value = await action();
      setError("");
    } catch (err) {
      setError(message(err));
    }
    await afterPeopleChange();
  };

  return (
    <div id="people">
      <h2 id="people-title">People</h2>
      {flash.value && <p class="flash">{flash.value}</p>}
      <ul class="people">
        {people.value.map((p) => (
          <li key={p.id}>
            <Avatar id={p.id} name={p.name} />
            <span class="grow">
              {p.name} <span class="muted small">@{p.username}</span> {p.is_admin && <span class="chip">admin</span>}
            </span>
            <button
              type="button"
              class="btn small"
              onClick={() =>
                confirm(`Give ${p.name} a new temporary password? They'll be signed out.`) &&
                run(async () => {
                  const r = await api.resetPassword(p.id);
                  return (
                    <>
                      New temporary password for {p.name}: <code>{r.temporary_password}</code>. They'll choose their own when they next sign in.
                    </>
                  );
                })
              }
            >
              Reset password
            </button>
            {p.id !== user.id && (
              <>
                <button
                  type="button"
                  class="btn small"
                  onClick={() =>
                    run(async () => {
                      await api.setAdmin(p.id, !p.is_admin);
                      return `${p.name} ${p.is_admin ? "is no longer an admin" : "is now an admin"}.`;
                    })
                  }
                >
                  {p.is_admin ? "Remove admin" : "Make admin"}
                </button>
                <button
                  type="button"
                  class="btn small danger"
                  onClick={() =>
                    confirm(`Remove ${p.name}? They won't be able to sign in, and they'll be taken off their open tasks. Their past updates stay.`) &&
                    run(async () => {
                      await api.removePerson(p.id);
                      return `Removed ${p.name}.`;
                    })
                  }
                >
                  Remove
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      <form
        class="row"
        onSubmit={async (e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const data = new FormData(form);
          await run(async () => {
            const r = await api.addPerson(String(data.get("name")), String(data.get("username")));
            form.reset();
            return (
              <>
                Added {r.person.name}. Username: <b>{r.person.username}</b> · temporary password: <code>{r.temporary_password}</code>. Share it
                with them now; it won't be shown again.
              </>
            );
          });
        }}
      >
        <input name="name" placeholder="Full name" required maxLength={60} />
        <input name="username" placeholder="Username, e.g. meera" required maxLength={32} pattern="[a-zA-Z0-9._\-]{2,32}" />
        <button class="btn primary" type="submit">
          Add person
        </button>
        <p class="error form-error" aria-live="polite">
          {error}
        </p>
      </form>
      <CloseButton label="Done" />
    </div>
  );
}

/** Admins only: is a newer version waiting, and should the PC install new versions by itself at night? */
export function UpdatesDialog() {
  const info = updateInfo.value;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    void refreshUpdate();
  }, []);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setProblem("");
    try {
      await action();
    } catch (err) {
      setProblem(message(err));
    }
    setBusy(false);
  };

  return (
    <div id="updates">
      <h2 id="updates-title">Updates</h2>
      {!info && <p class="muted">Loading…</p>}
      {info && (
        <>
          {info.error && <p class={info.supported ? "error" : "muted"}>{info.error}</p>}
          {!info.error && info.available && (
            <>
              <p>
                <strong>A newer version is available</strong> ({info.behind} change{info.behind === 1 ? "" : "s"}):
              </p>
              <ul class="update-list">
                {info.commits.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </>
          )}
          {!info.error && !info.available && info.checked_when && <p>You have the latest version.</p>}
          {!info.error && !info.checked_when && <p class="muted">Not checked yet.</p>}
          <p class="muted small">
            {info.current && <>This PC is on version {info.current}. </>}
            {info.checked_when && <>Last checked {info.checked_when}.</>}
          </p>
          <div class="row">
            <button class="btn" type="button" disabled={busy || !info.supported} onClick={() => run(checkForUpdate)}>
              {busy ? "Checking…" : "Check now"}
            </button>
          </div>
          <p class="muted small">
            A new version is installed on the PC with <code>update.ps1</code>, or by itself at night when the choice below is on. Nothing
            changes until then.
          </p>
          <h3 class="nset-section">Update automatically at night</h3>
          <label class="chip-toggle">
            <input type="checkbox" checked={info.auto_update} disabled={busy} onChange={(e) => run(() => chooseAutoUpdate(e.currentTarget.checked))} />
            {info.auto_update ? "On" : "Off"}
          </label>
          <p class="muted small">
            When on, the PC looks for a new version at about 3 am. If there is one, it takes a backup, installs it and restarts the app
            (unavailable for a minute or two), then checks that all your data is still there. If the new version won't start, the old one is
            put back. This needs the nightly task set up once on the PC by running <code>update.ps1 -EnableAutoUpdate</code>.
          </p>
          {info.last_run ? (
            <p class="small">
              <strong>Last automatic run:</strong> {info.last_run.when}. {info.last_run.result === "updated" && "Updated. "}
              {info.last_run.result === "failed" && "It failed. "}
              {info.last_run.result === "up-to-date" && "Nothing new. "}
              {info.last_run.result === "available" && "A new version was waiting, and automatic updates are off. "}
              {info.last_run.detail}
            </p>
          ) : (
            <p class="muted small">No automatic run yet.</p>
          )}
        </>
      )}
      <p class="error form-error" aria-live="polite">
        {problem}
      </p>
      <CloseButton label="Done" />
    </div>
  );
}
