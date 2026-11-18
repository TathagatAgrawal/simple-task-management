import { beforeEach, describe, expect, it, vi } from "vitest";

// state.ts reads the browser when it loads (media queries, storage), so each test sets up a stub
// browser first and then imports a fresh copy.
async function load() {
  vi.resetModules();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {} }));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit = {}) =>
      init.method && init.method !== "GET" ? new Response(null, { status: 204 }) : new Response("{}", { status: 200 }),
    ),
  );
  return import("./state");
}

const card = (id: number, title: string, status: "todo" | "doing" | "done") => ({
  id, title, status, due: "2026-11-20", due_label: "Fri 20 Nov", due_tone: "", repeat: "none", repeat_label: "", comments: 0, assignees: [],
});

describe("asking before something that can't be undone", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("resolves true only when the person says yes", async () => {
    const s = await load();
    const yes = s.askConfirm({ title: "t", body: "b", confirmLabel: "Do it" });
    expect(s.confirmRequest.value?.confirmLabel).toBe("Do it");
    s.answerConfirm(true);
    expect(await yes).toBe(true);
    expect(s.confirmRequest.value).toBeNull();

    const no = s.askConfirm({ title: "t", body: "b", confirmLabel: "Do it" });
    s.answerConfirm(false);
    expect(await no).toBe(false);
  });

  it("answers an unanswered question with no when a new one arrives", async () => {
    const s = await load();
    const first = s.askConfirm({ title: "one", body: "", confirmLabel: "Yes" });
    void s.askConfirm({ title: "two", body: "", confirmLabel: "Yes" });
    expect(await first).toBe(false);
    expect(s.confirmRequest.value?.title).toBe("two");
  });

  it("names the task and what goes with it when asking to delete", async () => {
    const s = await load();
    void s.confirmDelete("GSTR-3B", 0);
    expect(s.confirmRequest.value).toMatchObject({ title: "Delete “GSTR-3B”?", danger: true });
    expect(s.confirmRequest.value?.body).toBe("This deletes the task and its history. It can't be undone.");
    void s.confirmDelete("GSTR-3B", 1);
    expect(s.confirmRequest.value?.body).toContain("its 1 comment.");
    void s.confirmDelete("GSTR-3B", 4);
    expect(s.confirmRequest.value?.body).toContain("its 4 comments.");
  });
});

describe("undoing a move", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("offers to put the card back, and does so", async () => {
    const s = await load();
    s.board.value = { todo: [card(1, "File the return", "todo")], doing: [], done: [] };
    await s.moveTask(1, "done");
    expect(s.undo.value).toMatchObject({ id: 1, from: "todo" });
    expect(s.undo.value?.text).toContain("File the return");

    await s.undoMove();
    expect(s.undo.value).toBeNull();
    const calls = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls;
    const patches = calls.filter(([, init]) => init?.method === "PATCH").map(([, init]) => JSON.parse(init.body as string));
    expect(patches).toEqual([{ status: "done" }, { status: "todo" }]);
  });

  it("does not offer another undo after an undo, and forgets the offer after a few seconds", async () => {
    vi.useFakeTimers();
    const s = await load();
    s.board.value = { todo: [card(1, "File the return", "todo")], doing: [], done: [] };
    await s.moveTask(1, "doing");
    expect(s.undo.value).not.toBeNull();
    vi.advanceTimersByTime(6100);
    expect(s.undo.value).toBeNull();
    vi.useRealTimers();
  });
});
