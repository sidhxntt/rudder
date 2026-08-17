import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/dashboard",
}));

import { RedirectToLanding } from "./providers";

it("returns an unauthenticated workspace visitor to the public landing page", () => {
  render(<RedirectToLanding />);

  expect(replace).toHaveBeenCalledWith("/");
});
