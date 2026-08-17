"use client";

import { useEffect, useRef } from "react";

import type { RuntimeMetric } from "@/lib/types";

export function MetricSparkline({ metrics }: { metrics: RuntimeMetric[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    if (!element || metrics.length < 2) return;
    const context = element.getContext("2d");
    if (!context) return;
    const width = element.width;
    const height = element.height;
    context.clearRect(0, 0, width, height);
    const max = Math.max(1, ...metrics.map((metric) => metric.cpu_percent));
    context.strokeStyle = "#4f8cff";
    context.lineWidth = 1.5;
    context.beginPath();
    metrics.forEach((metric, index) => {
      const x = (index / (metrics.length - 1)) * width;
      const y = height - (metric.cpu_percent / max) * (height - 2) - 1;
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
  }, [metrics]);
  const latest = metrics.at(-1);
  return (
    <div className="mt-sm flex items-center justify-between gap-sm" aria-label="CPU usage over the last hour">
      <canvas ref={canvas} width={112} height={28} className="h-7 flex-1" />
      <span className="font-mono text-micro text-ink-mute">
        {latest ? `${latest.cpu_percent.toFixed(1)}%` : "no CPU data"}
      </span>
    </div>
  );
}
