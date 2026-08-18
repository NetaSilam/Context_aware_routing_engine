import type { RerouteResult, RerouteScoringContext } from "../types/routeJobs";

export interface RerouteRequest {
  current_longitude: number;
  current_latitude: number;
  destination_longitude: number;
  destination_latitude: number;
  scoring_context: RerouteScoringContext;
}

export class RerouteError extends Error {
  retryable: boolean;

  constructor(message: string, retryable: boolean) {
    super(message);
    this.name = "RerouteError";
    this.retryable = retryable;
  }
}

async function parseRerouteError(response: Response): Promise<RerouteError> {
  const body = (await response.json().catch(() => ({}))) as {
    detail?: string | { message?: string; retryable?: boolean };
  };
  if (typeof body.detail === "object" && body.detail !== null) {
    return new RerouteError(
      body.detail.message ?? `Reroute request failed (${response.status}).`,
      body.detail.retryable ?? response.status === 503,
    );
  }
  return new RerouteError(
    typeof body.detail === "string" ? body.detail : `Reroute request failed (${response.status}).`,
    response.status === 503,
  );
}

export async function reroute(payload: RerouteRequest): Promise<RerouteResult> {
  const response = await fetch("/api/routing/reroute", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Origin: window.location.origin },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await parseRerouteError(response);
  return response.json() as Promise<RerouteResult>;
}
