import { NextResponse } from "next/server";

import {
  ensureLocalKubernetesRuntime,
  isLocalKubernetesAutoBootstrapEnabled,
} from "@/lib/local-kubernetes-server";

export const runtime = "nodejs";

/** Local-development bridge: starts/reuses Kind before the first UI release. */
export async function POST(): Promise<NextResponse> {
  if (!isLocalKubernetesAutoBootstrapEnabled()) {
    return NextResponse.json({ status: "skipped" });
  }

  try {
    await ensureLocalKubernetesRuntime();
    return NextResponse.json({ status: "ready" });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Could not prepare local Kubernetes.";
    return NextResponse.json({ detail }, { status: 503 });
  }
}
