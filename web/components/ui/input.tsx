import * as React from "react";

/**
 * Shared form control following the project's shadcn-style primitive pattern.
 * Keep visual defaults here so controls remain consistent wherever settings are
 * edited, while allowing narrow layout variants through `className`.
 */
export const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className = "", ...props }, ref) => (
    <input
      ref={ref}
      className={`h-8 w-full rounded-sm border border-hairline-strong bg-surface-inset px-sm py-xs font-mono text-micro text-ink outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-ink-faint hover:border-ink-faint focus:border-accent focus:ring-1 focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...props}
    />
  ),
);

Input.displayName = "Input";
