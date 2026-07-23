"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useProjects } from "@/lib/queries";

/** Land on the first project. Selection itself lives in the sidebar. */
export default function IndexPage() {
  const router = useRouter();
  const projects = useProjects();
  const first = projects.data?.[0];

  useEffect(() => {
    if (first) router.replace(`/projects/${first.id}`);
  }, [first, router]);

  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-caption text-ink-faint">
        {projects.isError ? "could not reach the control plane" : "loading projects…"}
      </p>
    </div>
  );
}
