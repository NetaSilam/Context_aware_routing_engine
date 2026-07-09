import React from "react";
import PageSwitcher, { type AppPageId } from "./components/navigation/PageSwitcher";
import AccidentAttributionPage from "./pages/AccidentAttributionPage";
import CanonicalNetworkPage from "./pages/CanonicalNetworkPage";
import PlanRoutePage from "./pages/PlanRoutePage";

export interface AppProps {
  initialPage?: AppPageId;
  pages?: Partial<Record<AppPageId, JSX.Element>>;
}

export default function App(props: AppProps): JSX.Element {
  const [activePage, setActivePage] = React.useState<AppPageId>(
    props.initialPage ?? "plan-route",
  );

  const pages: Record<AppPageId, JSX.Element> = {
    "plan-route": props.pages?.["plan-route"] ?? <PlanRoutePage />,
    "canonical-network": props.pages?.["canonical-network"] ?? <CanonicalNetworkPage />,
    "accident-attribution":
      props.pages?.["accident-attribution"] ?? <AccidentAttributionPage />,
  };

  return (
    <>
      <PageSwitcher activePage={activePage} onPageChange={setActivePage} />
      {pages[activePage]}
    </>
  );
}
