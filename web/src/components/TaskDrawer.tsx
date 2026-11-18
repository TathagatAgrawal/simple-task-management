// The task view, shown in a drawer over the board. Each field saves itself when you leave it.
import { useEffect, useRef, useState } from "preact/hooks";
import type { Task, Update } from "../api/types";
import { dismissGesture, isPhone } from "../gestures";
import {
  closeTask, deleteTask, meta, moveTask, openTask, openTaskId, people, postUpdate, saveTask, task,
} from "../state";
import { isTyping } from "../util";
import { Avatar, Linked } from "./bits";
import { Icon } from "./Icon";

/** A value that follows the server's copy, except while the person is editing the field. */
function useFieldValue<T extends HTMLElement>(server: string) {
  const ref = useRef<T>(null);
  const [value, setValue] = useState(server);
  useEffect(() => {
    if (document.activeElement !== ref.current) setValue(server);
  }, [server]);
  return { ref, value, setValue };
}

function Title({ t }: { t: Task }) {
  const { ref, value, setValue } = useFieldValue<HTMLTextAreaElement>(t.title);
  return (
    <textarea
      ref={ref}
      class="title-input"
      rows={1}
      maxLength={200}
      required
      aria-label="Title"
      value={value}
      onInput={(e) => setValue(e.currentTarget.value)}
      onChange={() => value !== t.title && saveTask(t.id, { title: value })}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          e.currentTarget.blur();
        }
      }}
    />
  );
}

function Notes({ t }: { t: Task }) {
  const { ref, value, setValue } = useFieldValue<HTMLTextAreaElement>(t.notes);
  return (
    <textarea
      ref={ref}
      class="notes-input"
      rows={2}
      maxLength={5000}
      placeholder="Add notes…"
      value={value}
      onInput={(e) => setValue(e.currentTarget.value)}
      onChange={() => value !== t.notes && saveTask(t.id, { notes: value })}
    />
  );
}

function Thread({ updates, justPosted }: { updates: Update[]; justPosted: { current: boolean } }) {
  const scroller = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    // Newest updates are at the bottom: start there, unless the reader had scrolled up.
    if (atBottom.current) el.scrollTop = el.scrollHeight;
    if (justPosted.current && isPhone()) {
      // On a phone the whole panel scrolls, not the thread: go to the end after posting.
      const page = el.closest<HTMLElement>(".panel-body");
      if (page) page.scrollTop = page.scrollHeight;
    }
    justPosted.current = false;
  }, [updates.length, justPosted]);
  return (
    <div
      class="thread-scroll"
      ref={scroller}
      onScroll={(e) => {
        const el = e.currentTarget;
        atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
    >
      <ul class="thread">
        {updates.map((u) =>
          u.kind === "comment" ? (
            <li class="comment" key={u.id}>
              <Avatar id={u.author?.id ?? 0} name={u.author?.name ?? "?"} />
              <div>
                <span class="who">{u.author?.name}</span> <span class="when">{u.when}</span>
                <div class="body">
                  <Linked text={u.body} />
                </div>
              </div>
            </li>
          ) : (
            <li class="event" key={u.id}>
              {u.author ? `${u.author.name} ` : ""}
              <Linked text={u.body} /> · {u.when}
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

function Composer({ id, justPosted }: { id: number; justPosted: { current: boolean } }) {
  const [body, setBody] = useState("");
  const submit = async (e?: Event) => {
    e?.preventDefault();
    if (!body.trim()) return;
    justPosted.current = true;
    if (await postUpdate(id, body)) setBody("");
    else justPosted.current = false;
  };
  return (
    <form class="composer" onSubmit={submit}>
      <textarea
        name="body"
        rows={3}
        maxLength={5000}
        placeholder="Write an update… (Ctrl/⌘ + Enter to post)"
        required
        value={body}
        onInput={(e) => setBody(e.currentTarget.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void submit();
        }}
      />
      <div class="row end">
        <button class="btn primary" type="submit">
          Post update
        </button>
      </div>
    </form>
  );
}

function Assignees({ t }: { t: Task }) {
  const serverIds = t.assignees.map((a) => a.id).sort((a, b) => a - b).join(",");
  const [chosen, setChosen] = useState<number[] | null>(null);
  useEffect(() => setChosen(null), [serverIds]);
  const current = chosen ?? t.assignees.map((a) => a.id);
  return (
    <form class="side-section" onSubmit={(e) => e.preventDefault()}>
      <div class="side-label">Assignees</div>
      <div class="chips">
        {people.value.map((p) => (
          <label class="chip-toggle" key={p.id}>
            <input
              type="checkbox"
              name="assignee_ids"
              value={p.id}
              checked={current.includes(p.id)}
              onChange={(e) => {
                const next = e.currentTarget.checked ? [...current, p.id] : current.filter((i) => i !== p.id);
                setChosen(next);
                void saveTask(t.id, { assignee_ids: next });
              }}
            />
            {p.name}
          </label>
        ))}
      </div>
    </form>
  );
}

function Panel({ t }: { t: Task }) {
  const justPosted = useRef(false);
  const statuses = meta.value?.statuses ?? [];
  const repeats = meta.value?.repeats ?? [];
  return (
    <div class="panel" data-task-id={t.id}>
      <header class="panel-head">
        <button type="button" class="btn icon back-btn" onClick={closeTask} aria-label="Back to the board">
          <Icon name="chevron-left" size={22} />
        </button>
        <Title t={t} />
        <span class="muted task-number">#{t.id}</span>
        <button type="button" class="btn icon" onClick={closeTask} aria-label="Close" autofocus>
          <Icon name="close" size={18} />
        </button>
      </header>

      <div class="panel-body">
        <section class="panel-main">
          <h3 class="section-title">Notes</h3>
          <Notes t={t} />
          <h3 class="section-title">Updates</h3>
          <Thread updates={t.updates} justPosted={justPosted} />
          <Composer id={t.id} justPosted={justPosted} />
        </section>

        <aside class="panel-side">
          <div class="side-section">
            <div class="side-label">Status</div>
            <div class="seg status-seg" role="group" aria-label="Status">
              {statuses.map((s) => (
                <button key={s.value} type="button" aria-pressed={t.status === s.value} onClick={() => moveTask(t.id, s.value as Task["status"])}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <Assignees t={t} />

          <div class="side-section">
            <label class="side-label" for={`due-${t.id}`}>
              Due
            </label>
            <div class="row tight">
              <input
                type="date"
                id={`due-${t.id}`}
                name="due"
                required
                defaultValue={t.due}
                key={t.due}
                onChange={(e) => e.currentTarget.value && e.currentTarget.value !== t.due && saveTask(t.id, { due: e.currentTarget.value })}
              />
              {t.due_label && t.status !== "done" && <span class={`chip ${t.due_tone}`}>{t.due_label}</span>}
            </div>
          </div>

          <div class="side-section">
            <label class="side-label" for={`repeat-${t.id}`}>
              Repeats
            </label>
            <select id={`repeat-${t.id}`} name="repeat" value={t.repeat} onChange={(e) => saveTask(t.id, { repeat: e.currentTarget.value })}>
              {repeats.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
            {t.series.length > 0 && (
              <details class="series">
                <summary class="muted small">Other occurrences ({t.series.length})</summary>
                <ul>
                  {t.series.map((s) => (
                    <li key={s.id}>
                      <a
                        href={`#task-${s.id}`}
                        onClick={(e) => {
                          e.preventDefault();
                          openTask(s.id);
                        }}
                      >
                        {s.due_short}
                      </a>{" "}
                      <span class="muted small">· {statuses.find((x) => x.value === s.status)?.label}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>

          <div class="side-section">
            <button
              type="button"
              class="btn link danger small"
              onClick={() => confirm("Delete this task and all its updates? This can't be undone.") && deleteTask(t.id)}
            >
              Delete task
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

export function TaskDrawer() {
  const ref = useRef<HTMLDialogElement>(null);
  const id = openTaskId.value;
  const t = task.value;
  const shown = id !== null && t !== null && t.id === id;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (shown && !dialog.open) {
      dialog.showModal();
      // One history entry per open task, so the phone's Back button or gesture closes it.
      if (!(history.state && history.state.tbTask)) history.pushState({ tbTask: true }, "", location.hash || location.pathname);
    }
    if (id === null && dialog.open) dialog.close();
    if (shown) history.replaceState(history.state, "", `#task-${id}`);
  }, [shown, id]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const onClose = () => {
      dialog.style.transform = dialog.style.transition = "";
      closeTask();
      if (history.state && history.state.tbTask) history.back(); // the popstate that follows finds it closed
      else history.replaceState(null, "", location.pathname + location.search);
    };
    const onPop = () => dialog.open && dialog.close();
    // Clicking the dimmed board (the dialog's backdrop) closes the drawer.
    const onClick = (e: MouseEvent) => e.target === dialog && dialog.close();
    // Esc first leaves a text field (which saves it), and only then closes the drawer.
    const onCancel = (e: Event) => {
      if (isTyping(document.activeElement)) {
        e.preventDefault();
        (document.activeElement as HTMLElement).blur();
      }
    };
    dialog.addEventListener("close", onClose);
    dialog.addEventListener("click", onClick);
    dialog.addEventListener("cancel", onCancel);
    window.addEventListener("popstate", onPop);
    // Task page: swipe right starting near the left edge dismisses it, as on iOS.
    const stop = dismissGesture(dialog, "x", (e) => e.clientX > 8 && e.clientX < 40);
    return () => {
      dialog.removeEventListener("close", onClose);
      dialog.removeEventListener("click", onClick);
      dialog.removeEventListener("cancel", onCancel);
      window.removeEventListener("popstate", onPop);
      stop();
    };
  }, []);

  return (
    <dialog ref={ref} id="task-dialog" class="drawer" aria-label="Task">
      <div id="panel">{shown && t && <Panel key={t.id} t={t} />}</div>
    </dialog>
  );
}
