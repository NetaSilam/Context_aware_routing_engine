import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import PlanRoutePage from "./PlanRoutePage";

afterEach(() => {
  localStorage.clear();
  cleanup();
});

describe("PlanRoutePage", () => {
  it("keeps authentication UI in the route page shell", () => {
    render(<PlanRoutePage />);

    expect(screen.getByRole("main")).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "Sign in or create an account" }),
    ).toBeTruthy();
  });
});
