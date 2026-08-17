"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useRenameService } from "@/lib/queries";
import type { Service } from "@/lib/types";

/** Service-scoped configuration, kept distinct from the project-wide settings panel. */
export function ServiceSettings({ service }: { service: Service }) {
  const rename = useRenameService(service.environment_id);
  const [name, setName] = useState(service.name);

  useEffect(() => setName(service.name), [service.name]);

  async function saveName() {
    if (!name.trim() || name.trim() === service.name) return;
    await rename.mutateAsync({ serviceId: service.id, name: name.trim() });
  }

  const runtime = [
    ["Service type", service.kind],
    ["Container port", String(service.container_port)],
    ["CPU limit", `${service.cpu_limit} core${service.cpu_limit === 1 ? "" : "s"}`],
    ["Memory limit", `${service.memory_limit_mb} MB`],
    ["Replicas", String(service.replica_count)],
  ] as const;

  return (
    <div className="rd-scroll min-h-0 flex-1 overflow-auto">
      <section className="border-b border-hairline px-lg py-lg">
        <h3 className="text-caption font-medium text-ink">General</h3>
        <p className="pt-xxs text-micro text-ink-mute">Identity for this service. Renaming does not redeploy it.</p>
        <label className="mt-lg block">
          <span className="text-micro text-ink-secondary">Service name</span>
          <div className="mt-xs flex gap-sm">
            <Input value={name} onChange={(event) => setName(event.target.value)} aria-label="Service name" />
            <Button size="sm" onClick={() => void saveName()} disabled={rename.isPending || !name.trim() || name.trim() === service.name}>
              {rename.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </label>
      </section>

      <section className="px-lg py-lg">
        <h3 className="text-caption font-medium text-ink">Runtime profile</h3>
        <p className="pt-xxs text-micro text-ink-mute">Current deployment defaults for this service.</p>
        <dl className="mt-lg divide-y divide-hairline border-y border-hairline">
          {runtime.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-lg py-sm">
              <dt className="text-micro text-ink-mute">{label}</dt>
              <dd className="font-mono text-micro text-ink-secondary">{value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
