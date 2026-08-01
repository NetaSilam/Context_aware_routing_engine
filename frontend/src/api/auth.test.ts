import { afterEach, describe, expect, it, vi } from "vitest";

import { getMe, login, updatePreferences } from "./auth";

const profile = {
  id: 1,
  email: "driver@example.com",
  driving_experience: "experienced" as const,
  vehicle_type: "car" as const,
  avoid_tolls: false,
  avoid_highways: false,
};

afterEach(() => vi.unstubAllGlobals());

describe("authentication API", () => {
  it("uses HttpOnly-cookie credentials and never browser token storage", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(profile), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await login({ email: "driver@example.com", password: "correct-password" });
    await getMe();
    await updatePreferences({
      driving_experience: "novice",
      vehicle_type: "truck",
      avoid_tolls: true,
      avoid_highways: true,
    });

    for (const call of fetchMock.mock.calls) {
      expect(call[1]).toEqual(expect.objectContaining({ credentials: "include" }));
      expect(call[1]?.headers ?? {}).not.toHaveProperty("Authorization");
    }
  });
});
