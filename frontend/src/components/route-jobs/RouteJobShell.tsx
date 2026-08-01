import { MapContainer, Polyline, TileLayer } from "react-leaflet";

import type { RouteJobResult } from "../../types/routeJobs";

export type RouteJobShellStatus = "empty" | "submitting" | "polling" | "completed" | "failed";

interface RouteJobShellProps {
  status: RouteJobShellStatus;
  error?: string;
  result?: RouteJobResult | null;
}

const STATE_CONTENT: Record<RouteJobShellStatus, { heading: string; description: string }> = {
  empty: { heading: "No route job yet", description: "Enter two coordinates to compare available routes." },
  submitting: { heading: "Submitting route job", description: "The request is being saved before background processing starts." },
  polling: { heading: "Route job in progress", description: "The route is being calculated and compared with historical accident corridors." },
  completed: { heading: "Route job completed", description: "The saved route result is ready." },
  failed: { heading: "Route job failed", description: "The job reached a controlled failure state." },
};

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function RouteResult({ result }: { result: RouteJobResult }): JSX.Element {
  const chosen = result.candidates.find((candidate) => candidate.candidate_index === result.chosen_index) ?? result.candidates[0];
  const center: [number, number] = chosen
    ? [chosen.geometry.coordinates[0][1], chosen.geometry.coordinates[0][0]]
    : [31.7, 34.9];
  const hasLowCoverage = result.candidates.some((candidate) => candidate.warning);

  return (
    <div className="route-result">
      {hasLowCoverage ? <p role="alert" className="error-banner">Some routes have incomplete historical corridor coverage. Their risk comparison is less reliable.</p> : null}
      {!result.risk_choice_available ? <p><strong>Only one route was available.</strong> No risk-aware choice between alternatives was possible.</p> : null}
      <div className="map-shell" aria-label="Route result map">
        <MapContainer center={center} zoom={12} className="corridor-map">
          <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {result.candidates.map((candidate) => (
            <Polyline
              key={candidate.candidate_index}
              positions={candidate.geometry.coordinates.map(([longitude, latitude]) => [latitude, longitude] as [number, number])}
              pathOptions={{ color: candidate.candidate_index === result.chosen_index ? "#0d7288" : "#777", weight: candidate.candidate_index === result.chosen_index ? 7 : 4 }}
            />
          ))}
        </MapContainer>
      </div>
      <section aria-label="Route comparison" className="route-candidate-grid">
        {result.candidates.map((candidate) => (
          <article key={candidate.candidate_index} className="summary-card">
            <h3>Route {candidate.candidate_index + 1}{candidate.candidate_index === result.chosen_index ? " — recommended" : ""}</h3>
            <dl>
              <dt>Distance</dt><dd>{(candidate.distance_m / 1000).toFixed(1)} km</dd>
              <dt>Duration</dt><dd>{Math.round(candidate.duration_seconds / 60)} min</dd>
              <dt>Historical accident density</dt><dd>{candidate.historical_accident_density_per_km.toFixed(2)} per matched km</dd>
              <dt>Matched length</dt><dd>{(candidate.matched_route_length_m / 1000).toFixed(1)} km</dd>
              <dt>Coverage</dt><dd>{percent(candidate.coverage)}</dd>
              <dt>Accident score</dt><dd>{candidate.accident_score.toFixed(2)}</dd>
              <dt>Normalized risk</dt><dd>{candidate.normalized_risk.toFixed(3)}</dd>
              <dt>Time penalty</dt><dd>{candidate.time_penalty.toFixed(3)}</dd>
              <dt>Safety contribution</dt><dd>{candidate.safety_contribution.toFixed(3)}</dd>
              <dt>Time contribution</dt><dd>{candidate.time_contribution.toFixed(3)}</dd>
              <dt>Final cost</dt><dd>{candidate.final_cost.toFixed(3)}</dd>
            </dl>
            {candidate.warning ? <p className="error-banner">{candidate.warning}</p> : null}
          </article>
        ))}
      </section>
      <p>{result.risk_metric_description}</p>
      <dl className="route-version-details">
        <dt>Safety/time weights</dt><dd>{result.safety_weight.toFixed(2)} / {result.time_weight.toFixed(2)}</dd>
        <dt>Safety factors</dt><dd>{Object.entries(result.safety_factor_contributions).map(([name, value]) => `${name} ${value.toFixed(2)}`).join(", ")}</dd>
        <dt>Reference risk p95</dt><dd>{result.reference_risk_p95.toFixed(3)}</dd>
        <dt>Accident years</dt><dd>{result.included_year_start}–{result.included_year_end}</dd>
        <dt>Formula / data / matcher / graph</dt><dd>{result.formula_version} / {result.risk_data_version} / {result.matcher_version} / {result.graph_version}</dd>
      </dl>
    </div>
  );
}

export default function RouteJobShell({ status, error, result }: RouteJobShellProps): JSX.Element {
  const content = STATE_CONTENT[status];
  return (
    <section className="filters-panel" aria-label="Route job" data-route-job-state={status}>
      <div className="filters-panel__heading">
        <p className="eyebrow">Route Job</p>
        <h2>{content.heading}</h2>
        <p>{status === "failed" && error ? error : content.description}</p>
      </div>
      {status === "completed" && result ? <RouteResult result={result} /> : null}
    </section>
  );
}
