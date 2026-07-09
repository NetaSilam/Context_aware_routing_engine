import { useEffect, useState } from "react";

import { clearToken, getMe, getToken } from "../api/auth";
import { planRoute } from "../api/routing";
import AuthPanel from "../components/routing/AuthPanel";
import RouteForm from "../components/routing/RouteForm";
import RouteResultPanel from "../components/routing/RouteResultPanel";
import type { UserProfile } from "../types/auth";
import type { Coordinate, RouteResponse } from "../types/routing";

export default function PlanRoutePage(): JSX.Element {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<UserProfile | null>(null);
  const [routeResult, setRouteResult] = useState<RouteResponse | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      setUser(null);
      return;
    }
    let cancelled = false;
    void getMe(token)
      .then((profile) => {
        if (!cancelled) {
          setUser(profile);
        }
      })
      .catch(() => {
        if (!cancelled) {
          clearToken();
          setTokenState(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleRouteSubmit(origin: Coordinate, destination: Coordinate) {
    if (!token) {
      return;
    }
    setRouteLoading(true);
    setRouteError(null);
    setRouteResult(null);
    try {
      const result = await planRoute(token, origin, destination);
      setRouteResult(result);
    } catch (err) {
      setRouteError(err instanceof Error ? err.message : "Failed to compute a route.");
    } finally {
      setRouteLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <section className="hero-panel">
        <p className="eyebrow">Context-Aware Safe Routing</p>
        <h1>Get a route that weighs your safety, not just your time</h1>
        <p className="hero-panel__copy">
          Every recommendation blends travel time with historical accident risk near each
          candidate route, weighted by your driving experience, vehicle type, and the time of day.
        </p>
      </section>

      {!token ? (
        <AuthPanel onAuthenticated={(newToken) => setTokenState(newToken)} />
      ) : (
        <>
          {user ? (
            <section className="filters-panel" aria-label="Current profile">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <p>
                  Signed in as <strong>{user.email}</strong> — {user.driving_experience},{" "}
                  {user.vehicle_type}
                  {user.avoid_highways ? ", avoids highways" : ""}
                  {user.avoid_tolls ? ", avoids tolls" : ""}.
                </p>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => {
                    clearToken();
                    setTokenState(null);
                    setUser(null);
                    setRouteResult(null);
                  }}
                >
                  Sign out
                </button>
              </div>
            </section>
          ) : null}

          <RouteForm onSubmit={(origin, destination) => void handleRouteSubmit(origin, destination)} submitting={routeLoading} />

          <RouteResultPanel result={routeResult} error={routeError} loading={routeLoading} />
        </>
      )}
    </main>
  );
}
