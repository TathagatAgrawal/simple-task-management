// The sign-in and choose-a-password screens.
import { useState } from "preact/hooks";
import { ApiError } from "../api/client";
import { changeOwnPassword, signIn, signOut } from "../state";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function Login() {
  const [error, setError] = useState("");
  return (
    <main class="center-card">
      <h1 class="brand">Tasks</h1>
      <form
        class="stack-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          try {
            await signIn(String(data.get("username")), String(data.get("password")));
          } catch (err) {
            setError(message(err));
          }
        }}
      >
        <label>
          Username <input name="username" autocomplete="username" required autofocus />
        </label>
        <label>
          Password <input name="password" type="password" autocomplete="current-password" required />
        </label>
        <p id="login-error" class="error" aria-live="polite">
          {error}
        </p>
        <button class="btn primary" type="submit">
          Sign in
        </button>
        <p class="muted small">
          Stays signed in for 30 days on this computer.
          <br />
          <a href="/help" target="_blank" rel="noopener">
            How to use this app
          </a>
        </p>
      </form>
    </main>
  );
}

export function SetPassword({ name }: { name: string }) {
  const [error, setError] = useState("");
  return (
    <main class="center-card">
      <h1 class="brand">Welcome, {name}</h1>
      <p class="muted">Please choose your own password to finish signing in.</p>
      <form
        class="stack-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          try {
            await changeOwnPassword("", String(data.get("new_password")), String(data.get("confirm_password")));
          } catch (err) {
            setError(message(err));
          }
        }}
      >
        <label>
          New password <input name="new_password" type="password" autocomplete="new-password" minLength={8} required autofocus />
        </label>
        <label>
          Type it again <input name="confirm_password" type="password" autocomplete="new-password" minLength={8} required />
        </label>
        <p class="error form-error" aria-live="polite">
          {error}
        </p>
        <button class="btn primary" type="submit">
          Save and continue
        </button>
      </form>
      <button class="btn link small" type="button" onClick={signOut}>
        Sign out
      </button>
    </main>
  );
}
