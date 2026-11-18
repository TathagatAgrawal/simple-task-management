import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// alerts.ts looks at the browser once, when it loads, so each test sets the browser up and then
// imports a fresh copy.
const INFO = { enabled: true, public_key: "BAUD", details: true, devices: 0, this_device: false };
type Fake = { subscribe: ReturnType<typeof vi.fn>; existing: unknown };

function browser(opts: { push?: boolean; permission?: string; sub?: unknown; apple?: boolean; standalone?: boolean }): Fake {
  const sub = opts.sub ?? null;
  const fake: Fake = { subscribe: vi.fn(), existing: sub };
  const pushManager = {
    getSubscription: vi.fn(async () => fake.existing),
    subscribe: vi.fn(async () => {
      fake.existing = { endpoint: "https://push.example/new", toJSON: () => ({ keys: { p256dh: "k", auth: "a" } }), unsubscribe: vi.fn() };
      return fake.existing;
    }),
  };
  fake.subscribe = pushManager.subscribe;
  vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: opts.permission ?? "default", requestPermission: vi.fn(async () => "granted") }));
  if (opts.push !== false) {
    Object.defineProperty(window, "PushManager", { value: class {}, configurable: true });
  } else {
    Reflect.deleteProperty(window, "PushManager");
  }
  vi.stubGlobal("matchMedia", () => ({ matches: !!opts.standalone }));
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: vi.fn(async () => ({ pushManager })),
      register: vi.fn(async () => ({ pushManager })),
      ready: Promise.resolve({}),
    },
  });
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: opts.apple ? "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)" : "Mozilla/5.0 (Macintosh)" });
  Object.defineProperty(navigator, "standalone", { configurable: true, value: !!opts.standalone });
  return fake;
}

function server(info: object = INFO) {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ method: init.method ?? "GET", path: url, body: init.body ? JSON.parse(init.body as string) : undefined });
      const json = url.startsWith("/api/push") && init.method === "GET" ? info : {};
      return new Response(init.method === "GET" ? JSON.stringify(json) : null, { status: init.method === "GET" ? 200 : 204 });
    }),
  );
  return calls;
}

const load = async () => {
  vi.resetModules();
  return import("./alerts");
};

describe("push state", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());

  it("is unsupported where the browser has no push", async () => {
    browser({ push: false });
    server();
    const a = await load();
    await a.refreshPush();
    expect(a.pushState.value).toBe("unsupported");
  });

  it("asks an iPhone to add the page to the Home Screen first", async () => {
    browser({ push: false, apple: true });
    server();
    const a = await load();
    await a.refreshPush();
    expect(a.pushState.value).toBe("install");
  });

  it("is off when the server has push switched off", async () => {
    browser({});
    server({ ...INFO, enabled: false });
    const a = await load();
    await a.refreshPush();
    expect(a.pushState.value).toBe("server-off");
    expect(a.systemAlerts()).toBe(false);
  });

  it("offers to turn on when nothing is subscribed, and reports blocked", async () => {
    browser({});
    server();
    let a = await load();
    await a.refreshPush();
    expect(a.pushState.value).toBe("ask");
    browser({ permission: "denied" });
    a = await load();
    await a.refreshPush();
    expect(a.pushState.value).toBe("blocked");
  });

  it("is on, with system alerts, when this device is subscribed and re-saves it if the server forgot", async () => {
    browser({ permission: "granted", sub: { endpoint: "https://push.example/me", toJSON: () => ({ keys: { p256dh: "k", auth: "a" } }) } });
    const calls = server();
    const a = await load();
    await a.refreshPush();
    expect(a.pushState.value).toBe("on");
    expect(a.systemAlerts()).toBe(true);
    expect(calls.some((c) => c.method === "PUT" && c.path === "/api/push/subscription")).toBe(true);
  });

  it("turning on subscribes with the server's key and saves the device", async () => {
    const fake = browser({});
    const calls = server();
    const a = await load();
    await a.enablePush();
    const [options] = fake.subscribe.mock.calls[0] as [{ userVisibleOnly: boolean; applicationServerKey: Uint8Array }];
    expect(options.userVisibleOnly).toBe(true);
    expect(Array.from(options.applicationServerKey)).toEqual([4, 5, 3]); // "BAUD" decoded
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toEqual({ endpoint: "https://push.example/new", keys: { p256dh: "k", auth: "a" } });
  });

  it("forgetting the device removes it from the server", async () => {
    const unsubscribe = vi.fn();
    browser({ permission: "granted", sub: { endpoint: "https://push.example/me", unsubscribe, toJSON: () => ({}) } });
    const calls = server();
    const a = await load();
    await a.forgetDevice();
    expect(calls.find((c) => c.path === "/api/push/unsubscribe")?.body).toEqual({ endpoint: "https://push.example/me" });
    expect(unsubscribe).toHaveBeenCalled();
  });
});
