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
