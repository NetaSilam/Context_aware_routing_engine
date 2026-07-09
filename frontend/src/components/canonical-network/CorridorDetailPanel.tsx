import type { CorridorDetail } from "../../types/canonicalNetwork";

interface CorridorDetailPanelProps {
  detail: CorridorDetail | null;
  loading: boolean;
  error: string | null;
}

function renderOfficialLinkNote(detail: CorridorDetail): string {
  if (!detail.official_link_summary) {
    return "No official segment linkage is attached to this corridor.";
  }
  return `${detail.official_link_summary.official_segment_count.toLocaleString()} official segment links are attached to this corridor.`;
}

export default function CorridorDetailPanel(
  props: CorridorDetailPanelProps,
): JSX.Element {
  if (props.loading) {
    return (
      <aside className="detail-panel" aria-label="Corridor detail">
        <p className="detail-panel__empty">Loading corridor detail…</p>
      </aside>
    );
  }

  if (props.error) {
    return (
      <aside className="detail-panel" aria-label="Corridor detail">
        <p className="detail-panel__error">{props.error}</p>
      </aside>
    );
  }

  if (!props.detail) {
    return (
      <aside className="detail-panel" aria-label="Corridor detail">
        <p className="detail-panel__empty">
          Select a corridor from the map or visible corridor list to inspect its build lineage.
        </p>
      </aside>
    );
  }

  const { detail } = props;
  return (
    <aside className="detail-panel" aria-label="Corridor detail">
      <p className="eyebrow">Selected Corridor</p>
      <h2>{detail.primary_name ?? detail.primary_ref ?? detail.corridor_id}</h2>
      <p className="detail-panel__description">{detail.build_description}</p>

      <dl className="detail-grid">
        <div>
          <dt>Corridor ID</dt>
          <dd>{detail.corridor_id}</dd>
        </div>
        <div>
          <dt>Family</dt>
          <dd>{detail.corridor_family}</dd>
        </div>
        <div>
          <dt>Length</dt>
          <dd>{detail.length_m.toLocaleString()} m</dd>
        </div>
        <div>
          <dt>Atoms</dt>
          <dd>{detail.atom_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Build basis</dt>
          <dd>{detail.build_basis}</dd>
        </div>
        <div>
          <dt>Split reason</dt>
          <dd>{detail.split_from_reason}</dd>
        </div>
        <div>
          <dt>Road identity</dt>
          <dd>{detail.road?.road_id ?? "No linked road identity"}</dd>
        </div>
        <div>
          <dt>Official linkage</dt>
          <dd>{renderOfficialLinkNote(detail)}</dd>
        </div>
      </dl>
    </aside>
  );
}
