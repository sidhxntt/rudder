import type { Metadata } from "next";
import type { ReactNode } from "react";

// tokens.css first — it is the source of truth the Tailwind theme points at.
import "../styles/tokens.css";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Rudder",
  description: "Self-hosted PaaS — canvas console",
};

/**
 * The app shell lives in `Providers`, not here: it must not render at all
 * without a session, and the gate that decides that is a client component.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-surface text-ink antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
