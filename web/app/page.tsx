"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { useProjects } from "@/lib/queries";

/** Land on the first project. Selection itself lives in the sidebar. */
export default function IndexPage() {
  const router = useRouter();
  const search = useSearchParams();
  const projects = useProjects();
  const first = projects.data?.[0];

  useEffect(() => {
    const installationId = search.get("installation_id");
    const returnPath = window.sessionStorage.getItem("rudder:github-import-return");
    if (installationId && returnPath) {
      const destination = new URL(returnPath, window.location.origin);
      destination.searchParams.set("installation_id", installationId);
      window.sessionStorage.removeItem("rudder:github-import-return");
      router.replace(`${destination.pathname}?${destination.searchParams.toString()}`);
      return;
    }
    if (first) router.replace(`/projects/${first.id}`);
  }, [first, router, search]);

  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-caption text-ink-faint">
        {projects.isError ? "could not reach the control plane" : "loading projects…"}
      </p>
    </div>
  );
}
