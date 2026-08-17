"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { sendAssistantMessage } from "@/lib/api";
import type { AssistantTurn } from "@/lib/types";

const PROMPTS = [
  "What is the current release state?",
  "Which services need attention?",
  "Summarize the latest runtime signals.",
];
const MAX_PRIOR_TURNS = 6;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Rudder could not answer that question.";
}

/**
 * A session-only, read-only assistant. It deliberately overlays the canvas
 * instead of replacing it, so operators keep their topology and inspector in
 * view while asking for factual project context.
 */
export function AssistantDock({ environmentId }: { environmentId: string }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = question.trim();
    if (!message || pending) return;

    const userTurn: AssistantTurn = { role: "user", content: message };
    const priorTurns = turns.slice(-MAX_PRIOR_TURNS).map(({ role, content }) => ({ role, content }));
    setQuestion("");
    setError(null);
    setPending(true);
    setTurns((current) => [...current, userTurn]);

    try {
      const response = await sendAssistantMessage(environmentId, message, priorTurns);
      setModel(response.model);
      setTurns((current) => [...current, response.message]);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setPending(false);
    }
  }

  function onPanelKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") setOpen(false);
  }

  return (
    <div className="absolute bottom-5 right-5 z-20 flex flex-col items-end gap-sm">
      {open ? (
        <section
          role="dialog"
          aria-modal="false"
          aria-label="Ask Rudder"
          onKeyDown={onPanelKeyDown}
          className="flex h-[min(34rem,calc(100vh-8rem))] w-[min(25rem,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-md border border-hairline-strong bg-surface-raised/92 shadow-elev-2 backdrop-blur-md"
        >
          <header className="flex items-start justify-between gap-sm border-b border-hairline px-md py-sm">
            <div>
              <h2 className="text-heading-md text-ink">Ask Rudder</h2>
              <p className="mt-xxs font-mono text-micro uppercase tracking-[0.1em] text-accent">Read-only project context</p>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close Ask Rudder">
              <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4 fill-none stroke-current stroke-[1.8]">
                <path d="m6 6 12 12M18 6 6 18" strokeLinecap="round" />
              </svg>
            </Button>
          </header>

          <div className="rd-scroll min-h-0 flex-1 overflow-y-auto px-md py-sm" aria-live="polite">
            {turns.length === 0 ? (
              <div className="space-y-sm">
                <p className="text-caption leading-relaxed text-ink-mute">Ask for a factual summary of this environment. Rudder will not make changes.</p>
                <div className="flex flex-wrap gap-xs" aria-label="Suggested questions">
                  {PROMPTS.map((prompt) => (
                    <Button key={prompt} variant="outline" size="sm" onClick={() => setQuestion(prompt)} disabled={pending}>
                      {prompt}
                    </Button>
                  ))}
                </div>
              </div>
            ) : (
              <ol className="space-y-sm" aria-label="Assistant conversation">
                {turns.map((turn, index) => (
                  <li key={`${turn.role}-${index}`} className={turn.role === "user" ? "ml-lg border-l border-accent/60 pl-sm" : "mr-lg border-l border-hairline-strong pl-sm"}>
                    <p className="font-mono text-micro uppercase tracking-[0.1em] text-ink-faint">{turn.role === "user" ? "You" : model ?? "Rudder"}</p>
                    <p className="mt-xxs whitespace-pre-wrap text-caption leading-relaxed text-ink">{turn.content}</p>
                    {turn.sources?.length ? (
                      <ul className="mt-xs flex flex-wrap gap-x-sm gap-y-xxs" aria-label="Sources">
                        {turn.sources.map((source) => <li key={`${source.label}-${source.href}`}><a href={source.href} className="text-micro text-accent underline underline-offset-2 hover:text-accent-deep">{source.label}</a></li>)}
                      </ul>
                    ) : null}
                  </li>
                ))}
                {pending ? <li className="text-micro text-ink-faint">Rudder is reading project context…</li> : null}
              </ol>
            )}
            {error ? <p role="alert" className="mt-sm text-micro text-status-failed">{error}</p> : null}
          </div>

          <form aria-label="Ask Rudder" onSubmit={submit} className="flex gap-xs border-t border-hairline p-sm">
            <Input
              aria-label="Ask a question about this project"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about this environment"
              disabled={pending}
            />
            <Button type="submit" size="sm" disabled={pending || !question.trim()}>
              {pending ? "Reading…" : "Ask"}
            </Button>
          </form>
          <footer className="border-t border-hairline px-md py-xxs text-micro text-ink-faint">
            {model ? <>Model · {model}</> : "Session-only conversation"}
          </footer>
        </section>
      ) : null}

      <Button onClick={() => setOpen(true)} className="bottom-5 right-5 border-hairline-strong bg-surface-raised/90 text-ink shadow-elev-2 backdrop-blur-md hover:bg-surface-soft hover:text-accent">
        <svg viewBox="0 0 24 24" aria-hidden="true" className="mr-xs h-4 w-4 fill-none stroke-current stroke-[1.7]">
          <path d="M5 5.75A2.75 2.75 0 0 1 7.75 3h8.5A2.75 2.75 0 0 1 19 5.75v6.5A2.75 2.75 0 0 1 16.25 15H11l-4.2 3.15c-.66.5-1.6.03-1.6-.8V15.4A2.74 2.74 0 0 1 5 14.25v-8.5Z" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Ask Rudder
      </Button>
    </div>
  );
}
