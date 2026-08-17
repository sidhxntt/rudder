"use client";

import { useServiceMetrics } from "@/lib/queries";
import type { RuntimeMetric } from "@/lib/types";

function memoryLabel(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function CpuTrend({ samples }: { samples: RuntimeMetric[] }) {
  const values = samples.slice(-36).map((sample) => sample.cpu_percent);
  const highest = Math.max(1, ...values);
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 50 : (index / (values.length - 1)) * 100;
    const y = 92 - (value / highest) * 76;
    return `${x},${y}`;
  }).join(" ");

  return (
    <section aria-labelledby="cpu-trend-heading" className="border-b border-hairline pb-md">
      <div className="flex items-baseline justify-between gap-md">
        <h3 id="cpu-trend-heading" className="text-caption font-medium text-ink">CPU trend</h3>
        <span className="font-mono text-micro text-ink-mute">peak {highest.toFixed(1)}%</span>
      </div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="CPU utilisation trend" className="mt-sm h-24 w-full overflow-visible">
        <path d="M0 92 H100 M0 54 H100 M0 16 H100" stroke="var(--rd-hairline)" strokeWidth="0.65" vectorEffect="non-scaling-stroke" />
        {values.length > 1 ? <polyline points={points} fill="none" stroke="var(--rd-accent)" strokeWidth="1.8" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" /> : null}
        {values.length === 1 ? <circle cx="50" cy="16" r="2" fill="var(--rd-accent)" vectorEffect="non-scaling-stroke" /> : null}
      </svg>
    </section>
  );
}

function MemoryBars({ samples }: { samples: RuntimeMetric[] }) {
  const values = samples.slice(-24).map((sample) => sample.memory_bytes);
  const highest = Math.max(1, ...values);

  return (
    <section aria-labelledby="memory-bars-heading" className="border-b border-hairline py-md">
      <div className="flex items-baseline justify-between gap-md">
        <h3 id="memory-bars-heading" className="text-caption font-medium text-ink">Memory footprint</h3>
        <span className="font-mono text-micro text-ink-mute">peak {memoryLabel(highest)}</span>
      </div>
      <div role="img" aria-label="Memory usage over recent samples" className="mt-sm flex h-24 items-end gap-px border-b border-hairline px-px">
        {values.map((value, index) => (
          <span
            key={`${samples[index]?.captured_at ?? index}-${value}`}
            title={`${memoryLabel(value)} at ${new Date(samples[index]?.captured_at ?? "").toLocaleTimeString()}`}
            className="min-w-0 flex-1 rounded-t-xs transition-opacity hover:opacity-100"
            style={{
              height: `${Math.max(4, (value / highest) * 100)}%`,
              backgroundColor: "var(--rd-status-live)",
              opacity: 0.72,
            }}
          />
        ))}
      </div>
    </section>
  );
}

function CpuDistribution({ samples }: { samples: RuntimeMetric[] }) {
  const buckets = [0, 5, 15, 35, 65, 100].map((floor, index, all) => ({
    label: index === all.length - 1 ? `${floor}%+` : `${floor}–${all[index + 1]}%`,
    count: 0,
    floor,
    ceiling: all[index + 1] ?? Infinity,
  }));
  samples.forEach((sample) => {
    const bucket = buckets.find((item) => sample.cpu_percent >= item.floor && sample.cpu_percent < item.ceiling) ?? buckets.at(-1);
    if (bucket) bucket.count += 1;
  });
  const largest = Math.max(1, ...buckets.map((bucket) => bucket.count));

  return (
    <section aria-labelledby="cpu-distribution-heading" className="border-b border-hairline py-md">
      <div className="flex items-baseline justify-between gap-md">
        <h3 id="cpu-distribution-heading" className="text-caption font-medium text-ink">CPU distribution</h3>
        <span className="text-micro text-ink-mute">sample frequency</span>
      </div>
      <div role="img" aria-label="CPU utilization distribution" className="mt-md grid grid-cols-6 items-end gap-xs">
        {buckets.map((bucket) => (
          <div key={bucket.label} className="min-w-0">
            <div className="flex h-20 items-end border-b border-hairline">
              <span
                title={`${bucket.label}: ${bucket.count} samples`}
                className="w-full rounded-t-xs transition-opacity hover:opacity-100"
                style={{
                  height: `${Math.max(bucket.count ? 8 : 2, (bucket.count / largest) * 100)}%`,
                  backgroundColor: "var(--rd-accent)",
                  opacity: bucket.count ? 0.78 : 0.18,
                }}
              />
            </div>
            <p className="pt-xxs text-center font-mono text-[10px] leading-tight text-ink-faint">{bucket.label}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function average(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function percentile(values: number[], percentileValue: number): number {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * percentileValue))];
}

/** A concise operational view of the telemetry retained for this service. */
export function Analytics({ serviceId }: { serviceId: string }) {
  const metrics = useServiceMetrics(serviceId);
  const samples = metrics.data ?? [];
  const latest = samples.at(-1);
  const peakCpu = samples.length ? Math.max(...samples.map((sample) => sample.cpu_percent)) : null;
  const peakMemory = samples.length ? Math.max(...samples.map((sample) => sample.memory_bytes)) : null;

  if (metrics.isPending) {
    return <p className="px-lg py-md text-micro text-ink-faint">loading analytics…</p>;
  }

  if (metrics.isError) {
    return <p className="px-lg py-md text-micro text-status-failed">could not load analytics</p>;
  }

  if (!latest) {
    return (
      <p className="px-lg py-md text-micro text-ink-faint">
        no telemetry yet — analytics appear after the service reports its first sample
      </p>
    );
  }

  const cpuValues = samples.map((sample) => sample.cpu_percent);
  const memoryValues = samples.map((sample) => sample.memory_bytes);
  const first = samples[0];
  const observedForMinutes = Math.max(0, Math.round((new Date(latest.captured_at).getTime() - new Date(first.captured_at).getTime()) / 60_000));
  const figures = [
    ["CPU now", `${latest.cpu_percent.toFixed(1)}%`],
    ["CPU average", `${average(cpuValues).toFixed(1)}%`],
    ["CPU p95", `${percentile(cpuValues, 0.95).toFixed(1)}%`],
    ["CPU peak", `${peakCpu?.toFixed(1)}%`],
    ["Memory now", memoryLabel(latest.memory_bytes)],
    ["Memory average", memoryLabel(average(memoryValues))],
    ["Memory peak", memoryLabel(peakMemory ?? 0)],
  ] as const;

  return (
    <div className="rd-scroll min-h-0 flex-1 overflow-auto px-lg py-md">
      <CpuTrend samples={samples} />
      <MemoryBars samples={samples} />
      <CpuDistribution samples={samples} />
      <dl className="mt-md divide-y divide-hairline rounded-md border border-hairline bg-surface-inset">
        {figures.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-lg px-md py-sm">
            <dt className="text-micro text-ink-mute">{label}</dt>
            <dd className="font-mono text-caption text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="pt-md text-micro text-ink-faint">
        {samples.length} samples across {observedForMinutes || "<1"} min · {latest.resolution_seconds}s resolution · latest {new Date(latest.captured_at).toLocaleTimeString()}
      </p>
    </div>
  );
}
