import type { RouteJob } from "../types/routeJobs";

export interface SubmitRouteJobRequest {
  origin_longitude: number;
  origin_latitude: number;
  destination_longitude: number;
  destination_latitude: number;
  origin_label?: string;
  destination_label?: string;
}

async function parseError(response: Response): Promise<string> {
  const body = await response.json().catch(() => ({})) as { detail?: string };
  return body.detail ?? `Route request failed (${response.status}).`;
}

export async function submitRouteJob(
  payload: SubmitRouteJobRequest,
  idempotencyKey: string,
): Promise<{ id: string; status: "queued" }> {
  const request = () => fetch("/api/route-jobs", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Origin: window.location.origin,
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(payload),
    });
  let response: Response;
  try {
    response = await request();
  } catch {
    // The server may have persisted the first request before the connection
    // failed. Retry the transport once with the same key.
    response = await request();
  }
  if (!response.ok) throw new Error(await parseError(response));
  return response.json() as Promise<{ id: string; status: "queued" }>;
}

export async function getRouteJob(jobId: string): Promise<RouteJob> {
  const response = await fetch(`/api/route-jobs/${encodeURIComponent(jobId)}`, { credentials: "include" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json() as Promise<RouteJob>;
}
