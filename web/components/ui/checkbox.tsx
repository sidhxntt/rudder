import * as React from "react";

/**
 * Shared checkbox primitive with a native control for form semantics and a
 * shadcn-style visual indicator for consistent keyboard and checked states.
 */
export const Checkbox = React.forwardRef<
  HTMLInputElement,
  Omit<React.ComponentProps<"input">, "type">
>(({ className = "", ...props }, ref) => (
  <span className="relative inline-flex h-4 w-4 shrink-0 align-[-0.15em]">
    <input
      ref={ref}
      type="checkbox"
      className={`peer sr-only ${className}`}
      {...props}
    />
    <span
      aria-hidden="true"
      className="flex h-4 w-4 items-center justify-center rounded-[3px] border border-hairline-strong bg-surface-inset text-on-accent transition-[background-color,border-color,box-shadow] duration-150 peer-checked:border-accent peer-checked:bg-accent peer-focus-visible:ring-1 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-1 peer-focus-visible:ring-offset-surface peer-disabled:cursor-not-allowed peer-disabled:opacity-50"
    />
    <svg viewBox="0 0 12 12" className="pointer-events-none absolute left-0.5 top-0.5 hidden h-3 w-3 text-on-accent peer-checked:block" fill="none" aria-hidden="true">
      <path d="m2.25 6.1 2.2 2.2 5.1-5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </span>
));

Checkbox.displayName = "Checkbox";
