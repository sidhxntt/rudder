"use client";

import { useState } from "react";

import { useGitHubImportStatus } from "@/lib/queries";

export function GitHubImportDialog() {
  const [open, setOpen] = useState(false);
  const status = useGitHubImportStatus();

  return (
    <>
      <button
        className="rounded-md border border-ink-faint/40 bg-surface-raised px-3 py-2 text-caption text-ink hover:border-accent hover:text-accent"
        onClick={() => setOpen(true)}
      >
        Import from GitHub
      </button>
      {open ? (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface/80 p-6 backdrop-blur-sm">
          <section className="w-full max-w-lg rounded-lg border border-hairline bg-surface-raised p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-heading">Import from GitHub</p>
                <p className="mt-1 text-caption text-ink-mute">
                  Connect a repository, review detected private add-ons, then deploy your app.
                </p>
              </div>
              <button className="text-ink-faint hover:text-ink" onClick={() => setOpen(false)} aria-label="Close">
                ×
              </button>
            </div>
            <div className="mt-6 rounded-md border border-hairline bg-surface p-4">
              {status.isLoading ? <p className="text-caption text-ink-mute">Checking GitHub App setup…</p> : null}
              {status.isError ? <p className="text-caption text-status-failed">Could not check GitHub App setup.</p> : null}
              {status.data ? (
                <>
                  <p className="text-caption text-ink">{status.data.message}</p>
                  {status.data.configured && status.data.install_url ? (
                    <a className="mt-4 inline-block rounded-md bg-accent px-3 py-2 text-caption font-medium text-surface" href={status.data.install_url}>
                      Install GitHub App
                    </a>
                  ) : (
                    <p className="mt-3 text-caption text-ink-faint">
                      Set <code>RUDDER_GITHUB_APP_ID</code>, <code>RUDDER_GITHUB_APP_SLUG</code>, and <code>RUDDER_GITHUB_APP_PRIVATE_KEY</code> to enable repository selection.
                    </p>
                  )}
                </>
              ) : null}
            </div>
            <p className="mt-4 text-caption text-ink-faint">PostgreSQL and Redis will remain private; only the app receives a public URL.</p>
          </section>
        </div>
      ) : null}
    </>
  );
}
