// The only place that talks to the server: one typed function per API endpoint.
import type {
  Board, Me, Meta, Mode, Notification, Person, PersonCreated, Session, Settings, Summary, Task,
  TaskIn, TaskPatch, TaskPatched, TemporaryPassword, Theme, Unread,
} from "./types";

/** A failed request. ``message`` is already written for the person to read. */
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let csrfToken = "";
let onSignedOut: () => void = () => {};
let onSuccess: () => void = () => {};

/** Called after every successful change (not a read), so stale error messages can clear. */
export function setSuccessHandler(handler: () => void): void {
  onSuccess = handler;
}

/** Remember the CSRF token that unsafe requests must carry (from ``GET /api/me``). */
export function setCsrf(token: string): void {
  csrfToken = token;
}

/** Called whenever the server says the session is over, so the page can show the sign-in form. */
export function setSignedOutHandler(handler: () => void): void {
  onSignedOut = handler;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch("/api" + path, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach the server. Is Tailscale connected?", 0);
  }
  if (res.status === 401 && path !== "/session") onSignedOut();
  if (!res.ok) {
    let message = "That didn't work. Please try again.";
    if (res.status >= 500) message = "Something went wrong on the server. Please try again.";
    else {
      try {
        const data = (await res.json()) as { error?: string };
        if (data.error) message = data.error;
      } catch {
        /* keep the generic message */
      }
    }
    throw new ApiError(message, res.status);
  }
  if (method !== "GET") onSuccess();
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const q = (params: Record<string, string | number | boolean | undefined>): string => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== false);
  return entries.length ? "?" + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])) : "";
};

export const api = {
  signIn: (username: string, password: string) =>
    request<Session>("POST", "/session", { username, password }),
  signOut: () => request<void>("DELETE", "/session"),
  me: () => request<Me>("GET", "/me"),
  meta: () => request<Meta>("GET", "/meta"),
  setTheme: (theme: Theme) => request<Me>("PATCH", "/me", { theme }),
  changePassword: (current_password: string, new_password: string, confirm_password: string) =>
    request<void>("POST", "/me/password", { current_password, new_password, confirm_password }),

  summary: (who: string) => request<Summary>("GET", "/summary" + q({ who })),
  board: (who: string, done_days: number) =>
    request<Board>("GET", "/board" + q({ who, done_days })),
  task: (id: number) => request<Task>("GET", `/tasks/${id}`),
  createTask: (body: TaskIn) => request<Task>("POST", "/tasks", body),
  patchTask: (id: number, patch: TaskPatch) => request<TaskPatched>("PATCH", `/tasks/${id}`, patch),
  deleteTask: (id: number) => request<void>("DELETE", `/tasks/${id}`),
  addUpdate: (id: number, body: string) => request<Task>("POST", `/tasks/${id}/updates`, { body }),

  people: () => request<Person[]>("GET", "/people"),
  addPerson: (name: string, username: string) =>
    request<PersonCreated>("POST", "/people", { name, username }),
  setAdmin: (id: number, is_admin: boolean) => request<Person>("PATCH", `/people/${id}`, { is_admin }),
  resetPassword: (id: number) =>
    request<TemporaryPassword>("POST", `/people/${id}/reset-password`),
  removePerson: (id: number) => request<void>("DELETE", `/people/${id}`),

  notifications: (opts: { after?: number; unread?: boolean; announce?: boolean } = {}) =>
    request<Notification[]>("GET", "/notifications" + q(opts)),
  unread: () => request<Unread>("GET", "/notifications/unread"),
  markRead: (id: number) => request<void>("POST", `/notifications/${id}/read`),
  markUnread: (id: number) => request<void>("POST", `/notifications/${id}/unread`),
  readAll: () => request<void>("POST", "/notifications/read-all"),
  dismiss: (id: number) => request<void>("DELETE", `/notifications/${id}`),
  clearRead: () => request<void>("DELETE", "/notifications"),
  settings: () => request<Settings>("GET", "/me/notification-settings"),
  saveSettings: (changes: Record<string, Mode>) =>
    request<Settings>("PATCH", "/me/notification-settings", changes),
};
