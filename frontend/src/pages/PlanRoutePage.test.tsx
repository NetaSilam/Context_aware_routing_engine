import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import PlanRoutePage from "./PlanRoutePage";

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

const profile = { id: 1, email: "driver@example.com", driving_experience: "experienced" as const, vehicle_type: "car" as const, avoid_tolls: false, avoid_highways: false };

describe("PlanRoutePage", () => {
  it("renders the authenticated profile and asynchronous route shell", () => {
    render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getByText(/driver@example.com/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Route job" })).toBeTruthy();
  });

  it("updates the allowed route preferences through the authenticated API", async () => {
    const user = userEvent.setup();
    const updated = { ...profile, driving_experience: "novice" as const, vehicle_type: "truck" as const, avoid_tolls: true, avoid_highways: true };
    const onProfileUpdated = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(updated), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<PlanRoutePage user={profile} onProfileUpdated={onProfileUpdated} />);

    await user.click(screen.getByRole("button", { name: "Edit route preferences" }));
    await user.selectOptions(screen.getByLabelText("Driving experience"), "novice");
    await user.selectOptions(screen.getByLabelText("Vehicle type"), "truck");
    await user.click(screen.getByLabelText("Avoid highways"));
    await user.click(screen.getByLabelText("Avoid tolls"));
    await user.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => expect(onProfileUpdated).toHaveBeenCalledWith(updated));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ method: "PATCH", credentials: "include" }),
    );
  });
});
