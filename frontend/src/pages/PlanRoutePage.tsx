import { useEffect, useRef, useState } from "react";

import { updatePreferences } from "../api/auth";
import { getRouteHistoryEntry, getRouteJob, runRouteHistoryAgain, submitRouteJob } from "../api/routeJobs";
import type { SubmitRouteJobRequest } from "../api/routeJobs";
import CoordinateAcquisition from "../components/route-jobs/CoordinateAcquisition";
import RouteJobShell from "../components/route-jobs/RouteJobShell";
import RouteHistoryPanel from "../components/route-jobs/RouteHistoryPanel";
import { createIdempotencyKey } from "../lib/idempotencyKey";
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

  async function submitRoute(payload: SubmitRouteJobRequest) {
    if (routeStatus === "submitting" || routeStatus === "polling") return;
    setRouteStatus("submitting");
    setRouteError(null);
    try {
      const submissionKey = createIdempotencyKey();
      const accepted = await submitRouteJob(payload, submissionKey);
      activateJob(accepted.id);
    } catch (err) {
      setRouteStatus("failed");
      setRouteError(err instanceof Error ? err.message : "Could not submit route job.");
    }
  }

  function activateJob(id: string) {
    pollAttempt.current = 0;
    const url = new URL(window.location.href);
    url.searchParams.set("routeJob", id);
    window.history.replaceState({}, "", url);
    setJobId(id);
    setRouteStatus("polling");
  }

  async function openHistory(jobIdToOpen: string) {
    try {
      const saved = await getRouteHistoryEntry(jobIdToOpen);
      setJob(saved);
      setJobId(null);
      setRouteStatus("completed");
      const url = new URL(window.location.href);
      url.searchParams.set("routeJob", saved.id);
      window.history.replaceState({}, "", url);
    } catch (err) {
      setRouteStatus("failed");
      setRouteError(err instanceof Error ? err.message : "Could not open route history.");
    }
  }

  async function runAgain(historyJobId: string) {
    if (routeStatus === "submitting" || routeStatus === "polling") return;
    setRouteStatus("submitting");
    try {
      const accepted = await runRouteHistoryAgain(historyJobId, createIdempotencyKey());
      activateJob(accepted.id);
    } catch (err) {
      setRouteStatus("failed");
      setRouteError(err instanceof Error ? err.message : "Could not run saved route again.");
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
      <CoordinateAcquisition
        disabled={routeStatus === "submitting" || routeStatus === "polling"}
        onSubmit={submitRoute}
      />
      <RouteJobShell
        status={routeStatus}
        error={routeError ?? undefined}
        result={job?.result}
        llmExplanation={job?.llm_explanation}
      />
      <RouteHistoryPanel refreshKey={routeStatus === "completed" ? job?.id ?? null : null} onOpen={openHistory} onRunAgain={runAgain} />
    </main>
  );
}
