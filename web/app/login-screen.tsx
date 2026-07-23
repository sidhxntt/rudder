"use client";

import { useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

/**
 * The whole app when there is no session. Not a route — there is exactly one
 * screen behind the gate and no reason for a URL that renders it.
 *
 * There is no signup (Phase 1 step 3: the single user is seeded from `.env`)
 * and no "remember me": the cookie's own `Max-Age` is the session length.
 */
export function LoginScreen() {
  const { signIn } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "could not reach the control plane",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-surface">
      <form
        onSubmit={onSubmit}
        className="w-80 rounded-md border border-hairline bg-surface-raised p-xl shadow-elev-2"
      >
        <div className="flex items-center gap-sm">
          <span className="h-2 w-2 rounded-full bg-accent" aria-hidden />
          <h1 className="text-heading-md text-ink">rudder</h1>
        </div>
        <p className="pt-xs text-micro text-ink-faint">Sign in to the control plane.</p>

        <label className="mt-lg block text-micro text-ink-mute" htmlFor="login-email">
          Email
        </label>
        <input
          id="login-email"
          name="email"
          type="email"
          autoComplete="username"
          autoFocus
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mt-xs w-full rounded-sm border border-hairline-strong bg-surface-inset px-sm py-xs text-caption text-ink placeholder:text-ink-faint"
        />

        <label className="mt-md block text-micro text-ink-mute" htmlFor="login-password">
          Password
        </label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-xs w-full rounded-sm border border-hairline-strong bg-surface-inset px-sm py-xs text-caption text-ink placeholder:text-ink-faint"
        />

        {error ? (
          <p role="alert" className="pt-md text-micro text-status-failed">
            {error}
          </p>
        ) : null}

        {/* The one filled green action on this screen. Near-black on green. */}
        <button
          type="submit"
          disabled={busy}
          className="mt-lg w-full rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
