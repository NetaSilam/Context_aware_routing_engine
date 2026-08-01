import { afterEach, describe, expect, it, vi } from "vitest";

import { submitRouteJob } from "./routeJobs";

const payload = {
  origin_longitude: 34.78,
  origin_latitude: 32.07,
  destination_longitude: 34.79,
  destination_latitude: 32.08,
};

afterEach(() => vi.unstubAllGlobals());

describe("route job submission", () => {
  it("reuses the deliberate submission key for a transport retry", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError("connection reset"))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ id: "job-1", status: "queued" }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(submitRouteJob(payload, "submission-key-1")).resolves.toEqual({
      id: "job-1",
      status: "queued",
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      "Idempotency-Key": "submission-key-1",
    });
    expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({
      "Idempotency-Key": "submission-key-1",
    });
  });

  it("does not retry a controlled HTTP failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "Queue unavailable" }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(submitRouteJob(payload, "submission-key-2")).rejects.toThrow(
      "Queue unavailable",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
