import { useEffect, useState } from "react";

import { clearToken, getMe, getToken } from "../api/auth";
import AuthPanel from "../components/auth/AuthPanel";
import RouteJobShell from "../components/route-jobs/RouteJobShell";
import type { UserProfile } from "../types/auth";

export default function PlanRoutePage(): JSX.Element {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<UserProfile | null>(null);

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

  return (
    <main className="page-shell">
      <section className="hero-panel">
        <p className="eyebrow">Context-Aware Safe Routing</p>
        <h1>Risk-aware route planning</h1>
        <p className="hero-panel__copy">
          Route requests will run as background jobs so progress and completed results can be
          recovered without keeping one browser request open.
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
                  }}
                >
                  Sign out
                </button>
              </div>
            </section>
          ) : null}
          <RouteJobShell status="empty" />
        </>
      )}
    </main>
  );
}
