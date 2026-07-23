import type { Metadata } from "next";
import type { ReactNode } from "react";

// tokens.css first — it is the source of truth the Tailwind theme points at.
import "../styles/tokens.css";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "./sidebar";
import { TopBar } from "./top-bar";

export const metadata: Metadata = {
  title: "Rudder",
  description: "Self-hosted PaaS — canvas console",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-surface text-ink antialiased">
        <Providers>
          <div className="flex h-screen w-screen overflow-hidden">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <TopBar />
              <main className="min-h-0 flex-1">{children}</main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
