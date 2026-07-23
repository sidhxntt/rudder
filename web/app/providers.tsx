"use client";

import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { isUnauthorized } from "@/lib/api";
import { SessionProvider, useSession } from "@/lib/session";

import { LoginScreen } from "./login-screen";
import { Sidebar } from "./sidebar";
import { TopBar } from "./top-bar";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <QueryLayer>
        <Gate>{children}</Gate>
      </QueryLayer>
    </SessionProvider>
  );
}

/**
 * TanStack Query, plus the one place a 401 is handled.
 *
 * Every read and every write in this app goes through a query or a mutation,
 * so these two cache-level handlers are a complete 401 net: an expired cookie
 * on any request drops the whole app back to the login screen instead of
 * leaving a half-rendered console full of failed panels.
 */
function QueryLayer({ children }: { children: ReactNode }) {
  const { expire } = useSession();

  const [client] = useState(() => {
    const onError = (error: Error): void => {
      if (isUnauthorized(error)) expire();
    };

    return new QueryClient({
      queryCache: new QueryCache({ onError }),
      mutationCache: new MutationCache({ onError }),
      defaultOptions: {
        queries: {
          staleTime: 1_000,
          refetchOnWindowFocus: false,
          // Retrying a 401 just burns a request on a cookie that is gone.
          retry: (failureCount, error) => !isUnauthorized(error) && failureCount < 1,
        },
      },
    });
  });

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function Gate({ children }: { children: ReactNode }) {
  const { state } = useSession();
  const client = useQueryClient();

  // One operator's data must never be left in the cache for the next one, and
  // stale panels must not flash back on re-login. Clearing on the way out
  // rather than on the way in means the shell has already unmounted.
  useEffect(() => {
    if (state.status === "anonymous") client.clear();
  }, [state.status, client]);

  if (state.status === "loading") {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-surface">
        <p className="text-caption text-ink-faint">checking session…</p>
      </div>
    );
  }

  if (state.status === "anonymous") return <LoginScreen />;

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
