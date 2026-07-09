import type { AttributedAccidentDetail } from "../../types/accidentAttribution";

interface AttributionDetailPanelProps {
  detail: AttributedAccidentDetail | null;
  loading: boolean;
  error: string | null;
}

function detailLabel(detail: AttributedAccidentDetail): string {
  return (
    detail.attribution.corridor_primary_name ??
    detail.attribution.corridor_primary_ref ??
    detail.attribution.corridor_id ??
    detail.accident.accident_id
  );
}

export default function AttributionDetailPanel(
  props: AttributionDetailPanelProps,
): JSX.Element {
  if (props.loading) {
    return (
      <aside className="detail-panel" aria-label="Attributed accident detail">
        <p className="detail-panel__empty">Loading accident detail...</p>
      </aside>
    );
  }

  if (props.error) {
    return (
      <aside className="detail-panel" aria-label="Attributed accident detail">
        <p className="detail-panel__error">{props.error}</p>
      </aside>
    );
  }

  if (!props.detail) {
    return (
      <aside className="detail-panel" aria-label="Attributed accident detail">
        <p className="detail-panel__empty">
          Select an accident marker or list row to inspect the final corridor assignment.
        </p>
      </aside>
    );
  }

  const { detail } = props;
  return (
    <aside className="detail-panel" aria-label="Attributed accident detail">
      <p className="eyebrow">Selected Accident</p>
      <h2>{detailLabel(detail)}</h2>
      <p className="detail-panel__description">
        Attribution result first, source accident facts second, diagnostics third.
      </p>

      <dl className="detail-grid">
        <div>
          <dt>Status</dt>
          <dd>{detail.attribution.attribution_status}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{detail.attribution.confidence_tier}</dd>
        </div>
        <div>
          <dt>Selected corridor</dt>
          <dd>{detail.attribution.corridor_id ?? "Unresolved"}</dd>
        </div>
        <div>
          <dt>Distance</dt>
          <dd>
            {detail.attribution.distance_to_corridor_m == null
              ? "No distance available"
              : `${detail.attribution.distance_to_corridor_m.toLocaleString()} m`}
          </dd>
        </div>
        <div>
          <dt>Official reference effect</dt>
          <dd>{detail.attribution.official_reference_effect ?? "not_available"}</dd>
        </div>
        <div>
          <dt>Primary reason</dt>
          <dd>{detail.attribution.confidence_reason_code ?? "none"}</dd>
        </div>
        <div>
          <dt>Accident year</dt>
          <dd>{detail.accident.accident_year ?? "unknown"}</dd>
        </div>
        <div>
          <dt>Severity</dt>
          <dd>{detail.accident.severity ?? "unknown"}</dd>
        </div>
        <div>
          <dt>Road number</dt>
          <dd>{detail.accident.road_number ?? "none"}</dd>
        </div>
      </dl>

      <div className="detail-section">
        <h3>Explanation</h3>
        {detail.explanation_snippets.length ? (
          <ul className="detail-list">
            {detail.explanation_snippets.map((snippet) => (
              <li key={snippet}>{snippet}</li>
            ))}
          </ul>
        ) : (
          <p className="detail-panel__description">No extra explanation snippets were generated.</p>
        )}
      </div>

      <div className="detail-section">
        <h3>Diagnostics</h3>
        {detail.diagnostics ? (
          <pre className="detail-json">{JSON.stringify(detail.diagnostics, null, 2)}</pre>
        ) : (
          <p className="detail-panel__description">No diagnostics payload is attached to this row.</p>
        )}
      </div>
    </aside>
  );
}
