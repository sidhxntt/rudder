import * as React from "react";

type ButtonVariant = "default" | "outline" | "ghost" | "destructive";
type ButtonSize = "default" | "sm" | "icon";

const variants: Record<ButtonVariant, string> = {
  default: "border border-accent bg-accent text-on-accent hover:bg-accent-deep hover:border-accent-deep",
  outline: "border border-hairline-strong bg-transparent text-ink hover:border-accent hover:text-accent",
  ghost: "border border-transparent bg-transparent text-ink-mute hover:bg-surface-soft hover:text-ink",
  destructive: "border border-status-failed/60 bg-transparent text-status-failed hover:bg-status-failed/10",
};

const sizes: Record<ButtonSize, string> = {
  default: "h-9 px-lg py-sm text-button",
  sm: "h-7 px-sm py-xxs text-micro",
  icon: "h-7 w-7 p-0 text-micro",
};

/** Shared shadcn-style action control for workspace actions. */
export const Button = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> & { variant?: ButtonVariant; size?: ButtonSize }
>(({ className = "", variant = "default", size = "default", type = "button", ...props }, ref) => (
  <button
    ref={ref}
    type={type}
    className={`inline-flex shrink-0 items-center justify-center rounded-sm font-medium outline-none transition-[background-color,border-color,color,box-shadow,transform] duration-150 focus-visible:ring-1 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 ${variants[variant]} ${sizes[size]} ${className}`}
    {...props}
  />
));

Button.displayName = "Button";
