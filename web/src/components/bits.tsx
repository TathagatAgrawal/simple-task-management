// Small pieces used in several places: avatars, linked text, and the Saved cue.
import type { ComponentChildren } from "preact";
import { openTask } from "../state";
import { avatarTone, initials, splitTaskRefs } from "../util";

export function Avatar({ id, name, large }: { id: number; name: string; large?: boolean }) {
  return (
    <span class={`avatar${large ? " lg" : ""} tone-${avatarTone(id)}`} title={large ? undefined : name}>
      {initials(name)}
    </span>
  );
}

/** Text in which ``#42`` becomes a link that opens that task. */
export function Linked({ text }: { text: string }) {
  return (
    <>
      {splitTaskRefs(text).map((part, i) =>
        "taskId" in part ? (
          <a
            key={i}
            href={`#task-${part.taskId}`}
            onClick={(e) => {
              e.preventDefault();
              openTask(part.taskId);
            }}
          >
            {part.text}
          </a>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

export function Chip({ tone, children }: { tone?: string; children: ComponentChildren }) {
  return <span class={`chip${tone ? " " + tone : ""}`}>{children}</span>;
}
