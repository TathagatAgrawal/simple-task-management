// The "coming up" strip and the three columns of cards.
import { useSignal } from "@preact/signals";
import { isPhone } from "../gestures";
import type { Card as CardData, Status, SummaryItem } from "../api/types";
import {
  board, doneDays, meta, moveTask, openTask, openTaskId, setDragging, setSeg, showOlder,
  summary, who,
} from "../state";
import { Avatar } from "./bits";
import { Icon } from "./Icon";

const SUMMARY_LIMIT = 3;

function SummaryGroup({ keyName, label, items }: { keyName: "overdue" | "today" | "soon"; label: string; items: SummaryItem[] }) {
  const expanded = useSignal(false);
  return (
    <div class={`sumcard ${keyName}${expanded.value ? " expanded" : ""}`} data-group={keyName}>
      <h3>
        <span>{label}</span>
        <span>{items.length}</span>
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
        <p class="muted small">Nothing {keyName === "overdue" ? "overdue" : "due"}.</p>
      )}
    </div>
  );
}

export function Summary() {
  const data = summary.value;
  if (!data) return <section id="summary" />;
  return (
    <section id="summary">
      <div class="summary" data-overdue={data.overdue.length}>
        <SummaryGroup keyName="overdue" label="Overdue" items={data.overdue} />
        <SummaryGroup keyName="today" label="Due today" items={data.today} />
        <SummaryGroup keyName="soon" label="Next 3 days" items={data.soon} />
      </div>
    </section>
  );
}

function CardView({ card }: { card: CardData }) {
  const label = (n: number) => `${n} comment${n === 1 ? "" : "s"}`;
  return (
    <div class="card-wrap">
      <div class="swipe-hint" aria-hidden="true" />
      <article
        class={`card${openTaskId.value === card.id ? " selected" : ""}`}
        draggable={!isPhone()}
        data-task-id={card.id}
        tabIndex={0}
        onClick={() => openTask(card.id)}
        onKeyUp={(e) => e.key === "Enter" && openTask(card.id)}
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
        <div class="card-title">{card.title}</div>
        <div class="card-meta">
          <span class="chips">
            <span class={`chip ${card.due_tone}`}>{card.due_label}</span>
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
      </article>
    </div>
  );
}

function Column({ status, label, cards, total }: { status: Status; label: string; cards: CardData[]; total: number }) {
  const over = useSignal(false);
  const showAll = status === "done" && doneDays.value < 1000;
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
          <p class="empty">Nothing here. {status !== "done" && total ? "Drag a card here to move it." : ""}</p>
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
  const total = data.todo.length + data.doing.length + data.done.length;
  return (
    <section id="board">
      {total === 0 && who.value === "me" && (
        <p class="board-hint">
          Nothing is assigned to you yet. Choose <strong>Everyone</strong> under “Showing” to see all the firm's tasks, or click{" "}
          <strong>+ New task</strong>.
        </p>
      )}
      <div class="col-tabs" role="tablist" aria-label="Status">
        {statuses.map((s) => (
          <button key={s.value} type="button" role="tab" data-seg={s.value} onClick={() => setSeg(s.value as Status)}>
            {s.label} <span class="n">{data[s.value as Status].length}</span>
          </button>
        ))}
      </div>
      <div class="board">
        {statuses.map((s) => (
          <Column key={s.value} status={s.value as Status} label={s.label} cards={data[s.value as Status]} total={total} />
        ))}
      </div>
    </section>
  );
}

