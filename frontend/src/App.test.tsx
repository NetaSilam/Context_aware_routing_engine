import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("App", () => {
  it("switches between the registered application pages", async () => {
    const user = userEvent.setup();
    render(
      <App
        initialPage="canonical-network"
        pages={{
          "canonical-network": <div>Canonical network page</div>,
          "accident-attribution": <div>Accident attribution page</div>,
        }}
      />,
    );

    expect(screen.getByText("Canonical network page")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Accident Attribution" }));
    expect(screen.getByText("Accident attribution page")).toBeTruthy();
  });

  it("defaults to the Plan a Route page", () => {
    render(<App pages={{ "plan-route": <div>Plan a route page</div> }} />);
    expect(screen.getByText("Plan a route page")).toBeTruthy();
  });
});
