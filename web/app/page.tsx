"use client";

import { LandingPage } from "./landing-page";
import { useSession } from "@/lib/session";

/** Public product homepage. The operator workspace lives at `/dashboard`. */
export default function LandingRoute() {
  const session = useSession();
  return <LandingPage authenticated={session.state.status === "authenticated"} />;
}
