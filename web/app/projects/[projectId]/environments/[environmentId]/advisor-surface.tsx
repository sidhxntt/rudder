"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { acceptAdvisorItem, scanAdvisor } from "@/lib/api";
import type { AdvisorProposal } from "@/lib/types";

/** Proposal surface: ghost cards are never services until an individual click. */
export function AdvisorSurface({ environmentId }: { environmentId: string }) {
  const [path, setPath] = useState("");
  const [proposal, setProposal] = useState<AdvisorProposal | null>(null);
  const [message, setMessage] = useState("");

  async function scan() {
    setMessage("");
    try { setProposal(await scanAdvisor(environmentId, path)); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Advisor scan failed"); }
  }
  async function accept(item: AdvisorProposal["items"][number]) {
    try {
      await acceptAdvisorItem(environmentId, item);
      setProposal((current) => current && { ...current, items: current.items.filter((candidate) => candidate.id !== item.id) });
      setMessage(`${item.id} accepted through the normal resource API.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not accept proposal"); }
  }

  return <div className="rd-scroll min-h-0 flex-1 overflow-auto p-lg">
    <section className="border border-dashed border-accent/50 bg-accent/5 p-md">
      <p className="font-mono text-micro uppercase tracking-wide text-accent">Advisor · propose only</p>
      <p className="mt-xs text-caption text-ink-secondary">Ghost nodes are suggestions, not deployed resources. Each acceptance is separate.</p>
      <div className="mt-md flex gap-sm">
        <Input
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder="checkout path relative to advisor root"
          className="min-w-0 flex-1"
        />
        <Button type="button" variant="outline" size="sm" onClick={() => void scan()} disabled={!path}>
          Scan
        </Button>
      </div>
      <div className="mt-sm border-t border-hairline pt-sm text-micro leading-relaxed text-ink-mute">
        <span className="font-medium text-ink-secondary">Example:</span>{" "}
        for this local Rudder checkout, enter <code className="font-mono text-ink">.</code> to scan it. For a checkout at{" "}
        <code className="font-mono text-ink">&lt;advisor-root&gt;/my-api</code>, enter <code className="font-mono text-ink">my-api</code>. Then select{" "}
        <span className="text-ink-secondary">Scan</span> and review the ghost suggestions before accepting any one of them.
      </div>
    </section>
    {message ? <p className="mt-md text-micro text-ink-mute">{message}</p> : null}
    <div className="mt-md grid gap-sm sm:grid-cols-2">
      {proposal?.items.map((item) => <article key={item.id} className="border border-dashed border-ink-faint/50 bg-surface-soft p-md opacity-80"><p className="font-mono text-micro text-ink-faint">ghost · {item.kind}</p><p className="mt-xs text-caption text-ink">{item.id.replace(/^[^:]+:/, "")}</p><pre className="mt-xs overflow-auto text-micro text-ink-mute">{JSON.stringify(item.payload, null, 2)}</pre><button type="button" onClick={() => void accept(item)} className="mt-sm text-micro text-accent underline">Accept this item</button></article>)}
    </div>
  </div>;
}
