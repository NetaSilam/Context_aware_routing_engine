import { useEffect, useRef, useState } from "react";

import { updatePreferences } from "../api/auth";
import { getRouteJob, submitRouteJob } from "../api/routeJobs";
import RouteJobShell from "../components/route-jobs/RouteJobShell";
import type { DrivingExperience, UserProfile, VehicleType } from "../types/auth";
import type { RouteJob } from "../types/routeJobs";

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
  const [originLongitude, setOriginLongitude] = useState("34.7800");
  const [originLatitude, setOriginLatitude] = useState("32.0700");
  const [destinationLongitude, setDestinationLongitude] = useState("34.7900");
  const [destinationLatitude, setDestinationLatitude] = useState("32.0800");
  const [originLabel, setOriginLabel] = useState("");
  const [destinationLabel, setDestinationLabel] = useState("");
  const initialJobId = new URLSearchParams(window.location.search).get("routeJob");
  const [jobId, setJobId] = useState<string | null>(initialJobId);
  const [job, setJob] = useState<RouteJob | null>(null);
  const [routeStatus, setRouteStatus] = useState<"empty" | "submitting" | "polling" | "completed" | "failed">(initialJobId ? "polling" : "empty");
  const [routeError, setRouteError] = useState<string | null>(null);
  const pollAttempt = useRef(0);

  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timeoutId: number | undefined;
    async function poll() {
      try {
        const loaded = await getRouteJob(jobId as string);
        if (stopped) return;
        setJob(loaded);
        if (loaded.status === "completed") { setRouteStatus("completed"); return; }
        if (loaded.status === "failed") { setRouteStatus("failed"); setRouteError(loaded.error_message ?? "Route processing failed."); return; }
        setRouteStatus("polling");
        const delays = [500, 1000, 2000];
        const delay = delays[Math.min(pollAttempt.current, delays.length - 1)];
        pollAttempt.current += 1;
        timeoutId = window.setTimeout(() => void poll(), delay);
      } catch (err) {
        if (!stopped) { setRouteStatus("failed"); setRouteError(err instanceof Error ? err.message : "Could not load route job."); }
      }
    }
    void poll();
    return () => { stopped = true; if (timeoutId !== undefined) window.clearTimeout(timeoutId); };
  }, [jobId]);

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

  async function submitRoute(event: React.FormEvent) {
    event.preventDefault();
    if (routeStatus === "submitting" || routeStatus === "polling") return;
    setRouteStatus("submitting");
    setRouteError(null);
    try {
      const submissionKey = window.crypto.randomUUID();
      const accepted = await submitRouteJob({
        origin_longitude: Number(originLongitude), origin_latitude: Number(originLatitude),
        destination_longitude: Number(destinationLongitude), destination_latitude: Number(destinationLatitude),
        ...(originLabel ? { origin_label: originLabel } : {}),
        ...(destinationLabel ? { destination_label: destinationLabel } : {}),
      }, submissionKey);
      pollAttempt.current = 0;
      const url = new URL(window.location.href);
      url.searchParams.set("routeJob", accepted.id);
      window.history.replaceState({}, "", url);
      setJobId(accepted.id);
      setRouteStatus("polling");
    } catch (err) {
      setRouteStatus("failed");
      setRouteError(err instanceof Error ? err.message : "Could not submit route job.");
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
      <section className="filters-panel" aria-label="Route coordinates">
        <h2>Choose route coordinates</h2>
        <form onSubmit={submitRoute} className="filters-grid">
          <label className="filter-field">Origin longitude<input required type="number" step="any" value={originLongitude} onChange={(event) => setOriginLongitude(event.target.value)} /></label>
          <label className="filter-field">Origin latitude<input required type="number" step="any" value={originLatitude} onChange={(event) => setOriginLatitude(event.target.value)} /></label>
          <label className="filter-field">Origin label (optional)<input maxLength={200} value={originLabel} onChange={(event) => setOriginLabel(event.target.value)} /></label>
          <label className="filter-field">Destination longitude<input required type="number" step="any" value={destinationLongitude} onChange={(event) => setDestinationLongitude(event.target.value)} /></label>
          <label className="filter-field">Destination latitude<input required type="number" step="any" value={destinationLatitude} onChange={(event) => setDestinationLatitude(event.target.value)} /></label>
          <label className="filter-field">Destination label (optional)<input maxLength={200} value={destinationLabel} onChange={(event) => setDestinationLabel(event.target.value)} /></label>
          <button className="primary-button" type="submit" disabled={routeStatus === "submitting" || routeStatus === "polling"}>Compare routes</button>
        </form>
      </section>
      <RouteJobShell status={routeStatus} error={routeError ?? undefined} result={job?.result} />
    </main>
  );
}
