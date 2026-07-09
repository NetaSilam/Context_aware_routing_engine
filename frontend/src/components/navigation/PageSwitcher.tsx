export type AppPageId = "plan-route" | "canonical-network" | "accident-attribution";

interface PageSwitcherProps {
  activePage: AppPageId;
  onPageChange: (pageId: AppPageId) => void;
}

const PAGES: Array<{ id: AppPageId; label: string }> = [
  { id: "plan-route", label: "Plan a Route" },
  { id: "canonical-network", label: "Canonical Network" },
  { id: "accident-attribution", label: "Accident Attribution" },
];

export default function PageSwitcher(props: PageSwitcherProps): JSX.Element {
  return (
    <nav className="page-switcher" aria-label="Top-level pages">
      {PAGES.map((page) => (
        <button
          key={page.id}
          type="button"
          className={
            page.id === props.activePage
              ? "page-switcher__button page-switcher__button--active"
              : "page-switcher__button"
          }
          onClick={() => props.onPageChange(page.id)}
        >
          {page.label}
        </button>
      ))}
    </nav>
  );
}
