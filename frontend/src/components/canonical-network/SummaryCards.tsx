import type { CanonicalNetworkSummary } from "../../types/canonicalNetwork";

interface SummaryCardsProps {
  summary: CanonicalNetworkSummary;
}

function topBreakdownEntry(breakdown: Record<string, number>): string {
  const [label, count] =
    Object.entries(breakdown).sort((left, right) => right[1] - left[1])[0] ?? [];
  if (!label || typeof count !== "number") {
    return "No data";
  }
  return `${label.split("_").join(" ")} (${count.toLocaleString()})`;
}

export default function SummaryCards({ summary }: SummaryCardsProps): JSX.Element {
  const cards = [
    {
      label: "Network Atoms",
      value: summary.atom_count.toLocaleString(),
      note: `${summary.atoms_with_road_identity.toLocaleString()} atoms retain strong road identity`,
    },
    {
      label: "Canonical Roads",
      value: summary.road_count.toLocaleString(),
      note: `Top identity mode: ${topBreakdownEntry(summary.road_identity_type_breakdown)}`,
    },
    {
      label: "Canonical Corridors",
      value: summary.corridor_count.toLocaleString(),
      note: `Dominant family: ${topBreakdownEntry(summary.corridor_family_breakdown)}`,
    },
    {
      label: "Official Links",
      value: summary.official_linked_segment_count.toLocaleString(),
      note: `${summary.official_unlinked_segment_count.toLocaleString()} official segments remain unlinked`,
    },
  ];

  return (
    <section className="summary-cards" aria-label="Canonical network summary">
      {cards.map((card) => (
        <article key={card.label} className="summary-card">
          <p className="summary-card__label">{card.label}</p>
          <p className="summary-card__value">{card.value}</p>
          <p className="summary-card__note">{card.note}</p>
        </article>
      ))}
    </section>
  );
}
