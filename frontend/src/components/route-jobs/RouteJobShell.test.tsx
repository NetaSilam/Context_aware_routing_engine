import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import RouteJobShell, { type RouteJobShellStatus } from "./RouteJobShell";

afterEach(cleanup);

describe("RouteJobShell", () => {
  it.each<[RouteJobShellStatus, string]>([
    ["empty", "No route job yet"],
    ["submitting", "Submitting route job"],
    ["polling", "Route job in progress"],
    ["completed", "Route job completed"],
    ["failed", "Route job failed"],
  ])("renders the %s state boundary", (status, heading) => {
    render(<RouteJobShell status={status} error="Upstream routing unavailable." />);

    const shell = screen.getByRole("region", { name: "Route job" });
    expect(shell.getAttribute("data-route-job-state")).toBe(status);
    expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
  });

  it("renders a controlled failure message", () => {
    render(<RouteJobShell status="failed" error="Upstream routing unavailable." />);

    expect(screen.getByText("Upstream routing unavailable.")).toBeTruthy();
  });
});
