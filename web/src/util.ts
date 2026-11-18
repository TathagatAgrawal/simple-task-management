// Small pure helpers shared by the components.

/** Up to two initials for an avatar, e.g. "Asha Sharma" -> "AS". */
export function initials(name: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!)
    .join("")
    .toUpperCase();
  return letters || "?";
}

/** Stable colour class for a person's avatar. */
export function avatarTone(userId: number): string {
  return "abc"[userId % 3]!;
}

export type TextPart = { text: string } | { taskId: number; text: string };

/** Split text into plain pieces and ``#42`` task references, so the references can become links. */
export function splitTaskRefs(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;
  for (const match of text.matchAll(/#(\d+)\b/g)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start) });
    parts.push({ taskId: Number(match[1]), text: match[0] });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

/** True when the element is a field someone may be typing into. */
export function isTyping(el: Element | null): boolean {
  return !!el && el.matches("input:not([type=checkbox]), textarea, select");
}

/** Read a value from localStorage, or null when storage is unavailable. */
export function recall(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Save a value to localStorage; silently does nothing when storage is unavailable. */
export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export type NotificationLike = {
  id: number;
  task_id: number | null;
  title: string;
  read: boolean;
  due_label: string | null;
  due_tone: string;
};

export type NotificationGroup<T extends NotificationLike> = {
  key: string;
  taskId: number | null;
  title: string;
  read: boolean;
  items: T[]; // newest first
};

/**
 * Fold consecutive notifications about the same task (with the same read state) into one row, so
 * five changes to one filing read as one entry instead of five. Notifications about a deleted task
 * stay on their own. The list is newest first and keeps that order.
 */
export function groupNotifications<T extends NotificationLike>(items: T[]): NotificationGroup<T>[] {
  const groups: NotificationGroup<T>[] = [];
  for (const n of items) {
    const last = groups[groups.length - 1];
    if (last && n.task_id !== null && last.taskId === n.task_id && last.read === n.read) {
      last.items.push(n);
    } else {
      groups.push({ key: String(n.id), taskId: n.task_id, title: n.title, read: n.read, items: [n] });
    }
  }
  return groups;
}

/** The unread count as it should be written on a badge, never wider than three characters. */
export function badgeText(count: number): string {
  return count > 99 ? "99+" : String(count);
}

/** True when an ISO date (YYYY-MM-DD) is before today's ISO date. */
export function isBefore(date: string, today: string): boolean {
  return date < today;
}
