"use client";

/**
 * Who is logged in.
 *
 * There is no token here and no token anywhere else in this app. `POST
 * /auth/token` sets an httpOnly `rudder_token` cookie; the browser sends it on
 * every same-origin request without being asked, and JavaScript cannot read
 * it. All this module holds is the answer to "did `GET /auth/me` work" — which
 * is why the only way to end up back at the login screen is a real 401 from
 * the control plane, not a client-side clock.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as api from "./api";
import type { User } from "./types";

/**
 * The Next development proxy can be unavailable briefly while it recompiles.
 * A session check must never turn that into a permanently blank application.
 */
export const SESSION_CHECK_TIMEOUT_MS = 8_000;

export type SessionState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; user: User };

interface SessionValue {
  state: SessionState;
  signOut: () => Promise<void>;
  /** Called when any request comes back 401. Drops straight to the login screen. */
  expire: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const timeout = window.setTimeout(() => {
      if (!cancelled) setState({ status: "anonymous" });
    }, SESSION_CHECK_TIMEOUT_MS);

    api
      .me()
      .then((user) => {
        if (!cancelled) {
          window.clearTimeout(timeout);
          setState({ status: "authenticated", user });
        }
      })
      .catch(() => {
        // 401 is the ordinary case (no cookie yet). A network failure lands
        // here too, and showing the login screen is the right thing then as
        // well — nothing can be done until the control plane answers.
        if (!cancelled) {
          window.clearTimeout(timeout);
          setState({ status: "anonymous" });
        }
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setState({ status: "anonymous" });
    }
  }, []);

  const expire = useCallback(() => {
    setState((current) => (current.status === "anonymous" ? current : { status: "anonymous" }));
  }, []);

  const value = useMemo<SessionValue>(
    () => ({ state, signOut, expire }),
    [state, signOut, expire],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}
