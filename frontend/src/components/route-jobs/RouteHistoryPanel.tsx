import { useEffect, useState } from "react";

import {
  clearRouteHistory,
  deleteRouteHistoryEntry,
  listRouteHistory,
} from "../../api/routeJobs";
import type { RouteHistorySummary } from "../../types/routeJobs";

const PAGE_SIZE = 10;

interface RouteHistoryPanelProps {
  refreshKey: string | null;
  onOpen: (jobId: string) => Promise<void>;
  onRunAgain: (jobId: string) => Promise<void>;
}

export default function RouteHistoryPanel({ refreshKey, onOpen, onRunAgain }: RouteHistoryPanelProps): JSX.Element {
  const [items, setItems] = useState<RouteHistorySummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void listRouteHistory(offset, PAGE_SIZE)
      .then((page) => {
        if (!cancelled) { setItems(page.items); setHasMore(page.has_more); setError(null); }
      })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Could not load route history."); });
    return () => { cancelled = true; };
  }, [offset, refreshKey]);

  async function deleteEntry(item: RouteHistorySummary) {
    if (!window.confirm(`Delete route from ${displayOrigin(item)}?`)) return;
    try {
      await deleteRouteHistoryEntry(item.id);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete route history.");
    }
  }

  async function clearAll() {
    if (!window.confirm("Clear all completed route history?")) return;
    try {
      await clearRouteHistory();
      setItems([]); setHasMore(false); setOffset(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not clear route history.");
    }
  }

  return (
    <section className="filters-panel" aria-label="Route history">
      <div className="filters-panel__heading">
        <p className="eyebrow">Saved Routes</p>
        <h2>Route history</h2>
        <p>Completed calculations are saved exactly as they originally ran.</p>
      </div>
      {error ? <p role="alert" className="error-banner">{error}</p> : null}
      {items.length === 0 && !error ? <p>No completed routes yet.</p> : null}
      {items.map((item) => (
        <article className="summary-card" key={item.id}>
          <h3>{displayOrigin(item)} → {displayDestination(item)}</h3>
          <p>{new Date(item.completed_at).toLocaleString()} · {(item.distance_m / 1000).toFixed(1)} km · {Math.round(item.duration_seconds / 60)} min</p>
          <p>Risk density {item.historical_accident_density_per_km.toFixed(2)} · Coverage {(item.coverage * 100).toFixed(1)}% · Cost {item.final_cost.toFixed(3)}</p>
          <button type="button" onClick={() => void onOpen(item.id)}>Open saved result</button>{" "}
          <button type="button" onClick={() => void onRunAgain(item.id)}>Run again</button>{" "}
          <button type="button" onClick={() => void deleteEntry(item)}>Delete</button>
        </article>
      ))}
      <div>
        <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>{" "}
        <button type="button" disabled={!hasMore} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>{" "}
        <button type="button" disabled={items.length === 0} onClick={() => void clearAll()}>Clear history</button>
      </div>
    </section>
  );
}

function displayOrigin(item: RouteHistorySummary): string {
  return item.origin_label ?? `${item.origin_latitude.toFixed(5)}, ${item.origin_longitude.toFixed(5)}`;
}

function displayDestination(item: RouteHistorySummary): string {
  return item.destination_label ?? `${item.destination_latitude.toFixed(5)}, ${item.destination_longitude.toFixed(5)}`;
}
