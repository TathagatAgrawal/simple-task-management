import { describe, expect, it } from "vitest";
import { avatarTone, badgeText, groupNotifications, initials, isBefore, splitTaskRefs } from "./util";

describe("initials", () => {
  it("takes the first letters of up to two words", () => {
    expect(initials("Asha Iyer")).toBe("AI");
    expect(initials("meera")).toBe("M");
    expect(initials("A B C")).toBe("AB");
    expect(initials("   ")).toBe("?");
  });
});

describe("avatarTone", () => {
  it("cycles through three tones", () => {
    expect([1, 2, 3, 4].map(avatarTone)).toEqual(["b", "c", "a", "b"]);
  });
});

describe("splitTaskRefs", () => {
  it("turns #42 into a task reference and keeps the text around it", () => {
    expect(splitTaskRefs("Continued from #7 (due Mon)")).toEqual([
      { text: "Continued from " },
      { taskId: 7, text: "#7" },
      { text: " (due Mon)" },
    ]);
  });
  it("leaves apostrophes and plain text alone", () => {
    expect(splitTaskRefs("I'll file it")).toEqual([{ text: "I'll file it" }]);
    expect(splitTaskRefs("")).toEqual([]);
  });
});

const n = (id: number, task: number | null, read = false) => ({
  id,
  task_id: task,
  title: `Task ${task}`,
  read,
  due_label: null,
  due_tone: "",
});

describe("groupNotifications", () => {
  it("folds consecutive changes to one task into one row, newest first", () => {
    const groups = groupNotifications([n(9, 1), n(8, 1), n(7, 2), n(6, 1)]);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([[9, 8], [7], [6]]);
    expect(groups[0]!.title).toBe("Task 1");
  });
  it("keeps read and unread apart", () => {
    const groups = groupNotifications([n(9, 1), n(8, 1, true), n(7, 1, true)]);
    expect(groups.map((g) => [g.read, g.items.length])).toEqual([
      [false, 1],
      [true, 2],
    ]);
  });
  it("never folds notifications about deleted tasks together", () => {
    expect(groupNotifications([n(3, null), n(2, null)])).toHaveLength(2);
  });
});

describe("badgeText", () => {
  it("never grows past 99+", () => {
    expect([0, 9, 10, 99, 100, 5000].map(badgeText)).toEqual(["0", "9", "10", "99", "99+", "99+"]);
  });
});

describe("isBefore", () => {
  it("compares ISO dates", () => {
    expect(isBefore("2026-11-13", "2026-11-14")).toBe(true);
    expect(isBefore("2026-11-14", "2026-11-14")).toBe(false);
    expect(isBefore("2027-01-01", "2026-11-14")).toBe(false);
  });
});
