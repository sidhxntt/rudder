import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  me: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("./api", () => api);

import { SessionProvider, useSession } from "./session";

function SessionStatus() {
  const { state } = useSession();
  return <output>{state.status}</output>;
}

describe("SessionProvider", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("stops loading when the initial session request never resolves", async () => {
    vi.useFakeTimers();
    api.me.mockReturnValue(new Promise(() => undefined));

    render(
      <SessionProvider>
        <SessionStatus />
      </SessionProvider>,
    );

    expect(screen.getByText("loading")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_000);
    });
    expect(screen.getByText("anonymous")).toBeTruthy();
  });
});
