"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useEnvironments } from "@/lib/queries";

/** A project has no view of its own — it resolves to its production env. */
export default function ProjectPage() {
  const params = useParams();
  const projectId = typeof params?.projectId === "string" ? params.projectId : undefined;
  const router = useRouter();
  const environments = useEnvironments(projectId);

  const target =
    environments.data?.find((environment) => environment.is_production) ??
    environments.data?.[0];

  useEffect(() => {
    if (target && projectId) {
      router.replace(`/projects/${projectId}/environments/${target.id}`);
    }
  }, [target, projectId, router]);

  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-caption text-ink-faint">
        {environments.isSuccess && !target
          ? "this project has no environments"
          : "loading environments…"}
      </p>
    </div>
  );
}
