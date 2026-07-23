"use client";

import { STATUS_BG, STATUS_LABEL, STATUS_TEXT } from "@/lib/status";
import type { ServiceStatus } from "@/lib/types";

export function StatusDot({ status }: { status: ServiceStatus }) {
  return (
    <span className="flex items-center gap-xs">
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_BG[status]}`}
        aria-hidden
      />
      <span className={`text-micro ${STATUS_TEXT[status]}`}>{STATUS_LABEL[status]}</span>
    </span>
  );
}
