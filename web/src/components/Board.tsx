// The "coming up" strip and the three columns of cards.
import { useSignal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { isPhone } from "../gestures";
import type { Card as CardData, OtherOverdue, Status, SummaryItem } from "../api/types";
import {
  board, doneDays, focusCardId, meta, moveTask, openTask, openTaskId, search, setDragging, setSeg,
  setTab, setWho, showOlder, summary, who,
} from "../state";
import { Avatar } from "./bits";
import { Icon } from "./Icon";
import { recall, remember } from "../util";

const SUMMARY_LIMIT = 3;

/** True when a title matches what is typed in the search box (always true when it is empty). */
const matches = (title: string): boolean => title.toLowerCase().includes(search.value.trim().toLowerCase());

/** The icon that backs up a late or due-today chip, so the urgency isn't carried by colour alone. */
const toneIcon = (tone: string) => (tone === "red" ? "alert" : tone === "amber" ? "clock" : null);

function SummaryGroup({
  keyName,
  label,
  items,
  others = [],
  hidden = 0,
}: {
  keyName: "overdue" | "today" | "soon";
  label: string;
  items: SummaryItem[];
  /** The first few overdue tasks that belong to other people and are hidden by "Showing". */
  others?: OtherOverdue[];
  /** How many overdue tasks "Showing" hides in all (more than ``others`` when there are many). */
  hidden?: number;
}) {
  const expanded = useSignal(false);
  // Anything overdue, anywhere in the firm, makes the card loud: that is what the board is for.
  const alarm = keyName === "overdue" && items.length + hidden > 0;
  const count = keyName === "overdue" ? items.length + hidden : items.length;
  return (
    <div class={`sumcard ${keyName}${alarm ? " alarm" : ""}${expanded.value ? " expanded" : ""}`} data-group={keyName}>
      <h3>
        <span>{label}</span>
        <span class="sum-count">{count}</span>
      </h3>
      {items.length ? (
        <>
          <div class="sum-list">
            {items.map((t, i) => (
              <button
                key={t.id}
                type="button"
                class={`sum-item${i >= SUMMARY_LIMIT ? " extra" : ""}`}
                title={`Open: ${t.title}`}
                onClick={() => openTask(t.id)}
              >
                <span class="sum-title">{t.title}</span>
                <span class="sum-meta">
                  {t.repeat !== "none" && <Icon name="repeat" size={11} label={`Repeats ${t.repeat}`} />}
                  {keyName !== "today" && <span>{t.due_label}</span>}
                </span>
                <span class="sum-go">
                  <Icon name="chevron-right" size={14} />
                </span>
              </button>
            ))}
          </div>
          {items.length > SUMMARY_LIMIT && (
            <button type="button" class="btn link small sum-toggle" onClick={() => (expanded.value = !expanded.value)}>
              <span class="when-collapsed">Show {items.length - SUMMARY_LIMIT} more</span>
              <span class="when-expanded">Show less</span>
            </button>
          )}
        </>
      ) : (
        <p class="muted small">
          {keyName === "overdue"
            ? hidden > 0
              ? "Nothing overdue for you."
              : "Nothing overdue."
            : keyName === "today"
              ? "Nothing due today."
              : "Nothing due soon."}
        </p>
      )}
      {others.length > 0 && (
        <>
          <p class="sum-sub">Overdue for others</p>
          <div class="sum-list">
            {others.map((t) => (
              <button key={t.id} type="button" class="sum-item" title={`Open: ${t.title}`} onClick={() => openTask(t.id)}>
                <span class="sum-title">{t.title}</span>
                <span class="sum-meta">
                  {t.people} · {t.due_label}
                </span>
                <span class="sum-go">
                  <Icon name="chevron-right" size={14} />
                </span>
              </button>
            ))}
          </div>
        </>
      )}
      {hidden > 0 && (
        <button type="button" class="btn link small sum-more" onClick={() => setWho("all")}>
          {hidden > others.length ? `${hidden - others.length} more overdue · ` : ""}Show everyone
        </button>
      )}
    </div>
  );
}

export function Summary() {
  const data = summary.value;
  if (!data) return <section id="summary" />;
  const keep = (items: SummaryItem[]) => items.filter((t) => matches(t.title));
  const overdue = keep(data.overdue);
  const today = keep(data.today);
  const soon = keep(data.soon);
  const hiddenOverdue = who.value !== "all" ? data.firm_overdue - data.overdue.length : 0;
  const allClear = !data.overdue.length && !data.today.length && !data.soon.length && hiddenOverdue <= 0;
  return (
    <section id="summary">
      {allClear ? (
        <div class="summary" data-overdue="0">
          <p class="summary-clear">All clear for the next 3 days. Nothing overdue, nothing due.</p>
        </div>
      ) : (
        <div class="summary" data-overdue={data.overdue.length}>
          <SummaryGroup
            keyName="overdue"
            label="Overdue"
            items={overdue}
            others={who.value !== "all" ? data.others_overdue : []}
            hidden={hiddenOverdue > 0 ? hiddenOverdue : 0}
          />
          <SummaryGroup keyName="today" label="Due today" items={today} />
          <SummaryGroup keyName="soon" label="Next 3 days" items={soon} />
        </div>
      )}
    </section>
  );
}

/** On a phone, one line of what is due, so the deadlines are in sight without leaving the Board tab. */
function DeadlineLine() {
  const data = summary.value;
  if (!data) return null;
  const hidden = who.value !== "all" ? Math.max(0, data.firm_overdue - data.overdue.length) : 0;
  const parts: string[] = [];
  if (data.overdue.length) parts.push(`${data.overdue.length} overdue`);
  if (hidden) parts.push(`${hidden} overdue for others`);
  if (data.today.length) parts.push(`${data.today.length} due today`);
  if (data.soon.length) parts.push(`${data.soon.length} in 3 days`);
  const late = data.overdue.length + hidden > 0;
  return (
    <button type="button" class={`deadline-line${late ? " late" : ""}`} onClick={() => setTab("soon")}>
      <span>{parts.length ? parts.join(" · ") : "Nothing due in the next 3 days"}</span>
      <Icon name="chevron-right" size={16} />
    </button>
  );
}

/** A one-time reminder that cards respond to a swipe or a long press (invisible otherwise). */
function SwipeTip() {
  const key = "tb-swipe-tip";
  const gone = useSignal(recall(key) === "1");
  if (gone.value) return null;
  return (
    <p class="swipe-tip">
      Swipe a card right to move it on, or left (or press and hold) for more.{" "}
      <button
        type="button"
        class="linkbtn"
        onClick={() => {
          remember(key, "1");
          gone.value = true;
        }}
      >
        Got it
      </button>
    </p>
  );
}

const ORDER: Status[] = ["todo", "doing", "done"];

function CardView({ card }: { card: CardData }) {
  const ref = useRef<HTMLElement>(null);
  const label = (n: number) => `${n} comment${n === 1 ? "" : "s"}`;
  const urgent = card.status !== "done" && (card.due_tone === "red" || card.due_tone === "amber");
  const icon = card.status !== "done" ? toneIcon(card.due_tone) : null;

  // After a keyboard move the card is drawn again in its new column: give it focus back there.
  useEffect(() => {
    if (focusCardId.value === card.id) {
      ref.current?.focus();
      focusCardId.value = null;
    }
  });

  return (
    <div class="card-wrap">
      <div class="swipe-hint" aria-hidden="true" />
      <article
        ref={ref}
        class={`card${urgent ? ` tone-${card.due_tone}` : ""}${openTaskId.value === card.id ? " selected" : ""}`}
        draggable={!isPhone()}
        data-task-id={card.id}
        tabIndex={0}
        aria-keyshortcuts="[ ]"
        title="Press Enter to open, [ or ] to move it to the previous or next column"
        onClick={() => openTask(card.id)}
        onKeyUp={(e) => e.key === "Enter" && openTask(card.id)}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget || e.metaKey || e.ctrlKey || e.altKey) return;
          const step = e.key === "[" ? -1 : e.key === "]" ? 1 : 0;
          const to = ORDER[ORDER.indexOf(card.status) + step];
          if (step && to) {
            e.preventDefault();
            void moveTask(card.id, to, { keepFocus: true });
          }
        }}
        onDragStart={(e) => {
          if (isPhone()) return e.preventDefault();
          setDragging(true);
          e.dataTransfer?.setData("text/plain", String(card.id));
          if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
          const el = e.currentTarget as HTMLElement;
          requestAnimationFrame(() => el.classList.add("dragging"));
        }}
        onDragEnd={(e) => {
          (e.currentTarget as HTMLElement).classList.remove("dragging");
          setDragging(false);
        }}
      >
        <div class="card-meta">
          <span class="chips">
            <span class={`chip due-chip ${card.due_tone}`}>
              {icon && <Icon name={icon} size={12} />}
              {icon ? " " : ""}
              {card.due_label}
            </span>
            {card.repeat !== "none" && (
              <span class="chip blue">
                <Icon name="repeat" size={11} /> {card.repeat_label}
              </span>
            )}
          </span>
          <span class="card-right">
            {card.comments > 0 && (
              <span class="muted small comments" title={label(card.comments)}>
                <Icon name="comment" size={12} /> {card.comments}
              </span>
            )}
            <span class="avatars">
              {card.assignees.map((p) => (
                <Avatar key={p.id} id={p.id} name={p.name} />
              ))}
              {!card.assignees.length && <span class="muted small">Unassigned</span>}
            </span>
          </span>
        </div>
        <div class="card-title">{card.title}</div>
      </article>
    </div>
  );
}

function Column({ status, label, cards, total }: { status: Status; label: string; cards: CardData[]; total: number }) {
  const over = useSignal(false);
  const showAll = status === "done" && doneDays.value < 1000;
  const searching = search.value.trim() !== "";
  return (
    <section
      class={`col${over.value ? " drop" : ""}`}
      data-status={status}
      aria-label={label}
      onDragOver={(e) => {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
        over.value = true;
      }}
      onDragLeave={(e) => {
        if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) over.value = false;
      }}
      onDrop={(e) => {
        e.preventDefault();
        over.value = false;
        const id = Number(e.dataTransfer?.getData("text/plain"));
        if (id && !cards.some((c) => c.id === id)) void moveTask(id, status);
      }}
    >
      <h3>
        <span>
          {label}
          {showAll ? ` (last ${doneDays.value} days)` : ""}
        </span>
        <span>{cards.length}</span>
      </h3>
      <div class="cards">
        {cards.map((c) => (
          <CardView key={c.id} card={c} />
        ))}
        {!cards.length && (
          <p class="empty">
            {searching ? "No matching tasks here." : "Nothing here yet."} {!searching && status !== "done" && total ? "Drag a card here to move it." : ""}
          </p>
        )}
      </div>
      {showAll && (
        <button type="button" class="btn link small" onClick={showOlder}>
          Show older
        </button>
      )}
    </section>
  );
}

export function BoardView() {
  const data = board.value;
  const statuses = meta.value?.statuses ?? [];
  if (!data) return <section id="board" />;
  const everything = data.todo.length + data.doing.length + data.done.length;
  const shown = (s: Status) => data[s].filter((c) => matches(c.title));
  const total = shown("todo").length + shown("doing").length + shown("done").length;
  const query = search.value.trim();
  return (
    <section id="board">
      {everything === 0 && who.value === "me" && (
        <p class="board-hint">
          Nothing is assigned to you yet. Choose <strong>Everyone</strong> under “Showing” to see all the firm's tasks, or click{" "}
          <strong>+ New task</strong>.
        </p>
      )}
      {query && total === 0 && everything > 0 && (
        <p class="board-hint">
          No task title contains “{query}”. Searching covers the tasks in “Showing”: try <strong>Everyone</strong>.
        </p>
      )}
      <DeadlineLine />
      <div class="col-tabs" role="tablist" aria-label="Status">
        {statuses.map((s) => (
          <button key={s.value} type="button" role="tab" data-seg={s.value} onClick={() => setSeg(s.value as Status)}>
            {s.label} <span class="n">{shown(s.value as Status).length}</span>
          </button>
        ))}
      </div>
      {everything > 0 && <SwipeTip />}
      <div class="board">
        {statuses.map((s) => (
          <Column key={s.value} status={s.value as Status} label={s.label} cards={shown(s.value as Status)} total={total} />
        ))}
      </div>
    </section>
  );
}
