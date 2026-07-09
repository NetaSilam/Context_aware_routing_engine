import { useState } from "react";

import { login, setToken, signup } from "../../api/auth";
import type { DrivingExperience, VehicleType } from "../../types/auth";

interface AuthPanelProps {
  onAuthenticated: (token: string) => void;
}

export default function AuthPanel(props: AuthPanelProps): JSX.Element {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [drivingExperience, setDrivingExperience] = useState<DrivingExperience>("experienced");
  const [vehicleType, setVehicleType] = useState<VehicleType>("car");
  const [avoidTolls, setAvoidTolls] = useState(false);
  const [avoidHighways, setAvoidHighways] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const token =
        mode === "login"
          ? await login({ email, password })
          : await signup({
              email,
              password,
              driving_experience: drivingExperience,
              vehicle_type: vehicleType,
              avoid_tolls: avoidTolls,
              avoid_highways: avoidHighways,
            });
      setToken(token);
      props.onAuthenticated(token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="filters-panel" aria-label="Sign in or create an account">
      <div className="filters-panel__heading">
        <p className="eyebrow">{mode === "login" ? "Sign In" : "Create Account"}</p>
        <h2>Route recommendations are personalized to your driving profile</h2>
        <p>
          Your driving experience, vehicle type, and road preferences change how much weight
          safety gets versus speed when a route is chosen.
        </p>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}

      <form onSubmit={handleSubmit}>
        <div className="filters-grid">
          <label className="filter-field">
            <span>Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="filter-field">
            <span>Password</span>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
        </div>

        {mode === "signup" ? (
          <div className="filters-grid" style={{ marginTop: 14 }}>
            <label className="filter-field">
              <span>Driving experience</span>
              <select
                value={drivingExperience}
                onChange={(event) => setDrivingExperience(event.target.value as DrivingExperience)}
              >
                <option value="experienced">Experienced</option>
                <option value="novice">Novice</option>
              </select>
            </label>
            <label className="filter-field">
              <span>Vehicle type</span>
              <select
                value={vehicleType}
                onChange={(event) => setVehicleType(event.target.value as VehicleType)}
              >
                <option value="car">Car</option>
                <option value="motorcycle">Motorcycle</option>
                <option value="truck">Truck</option>
              </select>
            </label>
            <label className="filter-field">
              <span>Preferences</span>
              <span>
                <label>
                  <input
                    type="checkbox"
                    checked={avoidHighways}
                    onChange={(event) => setAvoidHighways(event.target.checked)}
                  />{" "}
                  Avoid highways
                </label>
                <br />
                <label>
                  <input
                    type="checkbox"
                    checked={avoidTolls}
                    onChange={(event) => setAvoidTolls(event.target.checked)}
                  />{" "}
                  Avoid tolls
                </label>
              </span>
            </label>
          </div>
        ) : null}

        <div className="filters-actions" style={{ display: "flex", gap: 12 }}>
          <button type="submit" className="primary-button" disabled={submitting}>
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => setMode(mode === "login" ? "signup" : "login")}
          >
            {mode === "login" ? "Need an account? Sign up" : "Already have an account? Sign in"}
          </button>
        </div>
      </form>
    </section>
  );
}
