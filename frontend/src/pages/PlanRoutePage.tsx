import { useState } from "react";

import { updatePreferences } from "../api/auth";
import RouteJobShell from "../components/route-jobs/RouteJobShell";
import type { DrivingExperience, UserProfile, VehicleType } from "../types/auth";

interface PlanRoutePageProps {
  user: UserProfile;
  onProfileUpdated: (user: UserProfile) => void;
}

export default function PlanRoutePage(props: PlanRoutePageProps): JSX.Element {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drivingExperience, setDrivingExperience] = useState(props.user.driving_experience);
  const [vehicleType, setVehicleType] = useState(props.user.vehicle_type);
  const [avoidTolls, setAvoidTolls] = useState(props.user.avoid_tolls);
  const [avoidHighways, setAvoidHighways] = useState(props.user.avoid_highways);

  async function savePreferences(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePreferences({
        driving_experience: drivingExperience,
        vehicle_type: vehicleType,
        avoid_tolls: avoidTolls,
        avoid_highways: avoidHighways,
      });
      props.onProfileUpdated(updated);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update preferences.");
    } finally {
      setSaving(false);
    }
  }

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

      <section className="filters-panel" aria-label="Current profile">
        <p>
          Signed in as <strong>{props.user.email}</strong> — {props.user.driving_experience},{" "}
          {props.user.vehicle_type}
          {props.user.avoid_highways ? ", avoids highways" : ""}
          {props.user.avoid_tolls ? ", avoids tolls" : ""}.
        </p>
        <button type="button" className="ghost-button" onClick={() => setEditing(!editing)}>
          Edit route preferences
        </button>
        {editing ? (
          <form onSubmit={savePreferences} aria-label="Route preferences">
            {error ? <p className="error-banner">{error}</p> : null}
            <label>
              Driving experience
              <select value={drivingExperience} onChange={(event) => setDrivingExperience(event.target.value as DrivingExperience)}>
                <option value="experienced">Experienced</option>
                <option value="novice">Novice</option>
              </select>
            </label>
            <label>
              Vehicle type
              <select value={vehicleType} onChange={(event) => setVehicleType(event.target.value as VehicleType)}>
                <option value="car">Car</option>
                <option value="motorcycle">Motorcycle</option>
                <option value="truck">Truck</option>
              </select>
            </label>
            <label><input type="checkbox" checked={avoidHighways} onChange={(event) => setAvoidHighways(event.target.checked)} /> Avoid highways</label>
            <label><input type="checkbox" checked={avoidTolls} onChange={(event) => setAvoidTolls(event.target.checked)} /> Avoid tolls</label>
            <button type="submit" className="primary-button" disabled={saving}>Save preferences</button>
          </form>
        ) : null}
      </section>
      <RouteJobShell status="empty" />
    </main>
  );
}
