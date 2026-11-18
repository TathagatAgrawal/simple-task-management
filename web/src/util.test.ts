import { describe, expect, it } from "vitest";
import { avatarTone, initials, splitTaskRefs } from "./util";

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
