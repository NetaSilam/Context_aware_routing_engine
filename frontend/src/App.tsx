import React from "react";

import { getMe, logout } from "./api/auth";
import AuthPanel from "./components/auth/AuthPanel";
import PageSwitcher, { type AppPageId } from "./components/navigation/PageSwitcher";
import AccidentAttributionPage from "./pages/AccidentAttributionPage";
import CanonicalNetworkPage from "./pages/CanonicalNetworkPage";
import PlanRoutePage from "./pages/PlanRoutePage";
import type { UserProfile } from "./types/auth";

export interface AppProps {
  initialPage?: AppPageId;
  pages?: Partial<Record<AppPageId, JSX.Element>>;
}

export default function App(props: AppProps): JSX.Element {
  const [activePage, setActivePage] = React.useState<AppPageId>(props.initialPage ?? "plan-route");
  const [user, setUser] = React.useState<UserProfile | null | undefined>(undefined);

  React.useEffect(() => {
    let cancelled = false;
    void getMe()
      .then((profile) => { if (!cancelled) setUser(profile); })
      .catch(() => { if (!cancelled) setUser(null); });
    return () => { cancelled = true; };
  }, []);

  if (user === undefined) {
    return <main className="page-shell"><p>Loading account…</p></main>;
  }
  if (user === null) {
    return <main className="page-shell"><AuthPanel onAuthenticated={setUser} /></main>;
  }

  const pages: Record<AppPageId, JSX.Element> = {
    "plan-route": props.pages?.["plan-route"] ?? <PlanRoutePage user={user} onProfileUpdated={setUser} />,
    "canonical-network": props.pages?.["canonical-network"] ?? <CanonicalNetworkPage />,
    "accident-attribution": props.pages?.["accident-attribution"] ?? <AccidentAttributionPage />,
  };

  return (
    <>
      <header className="app-session-bar">
        <span>Signed in as {user.email}</span>
        <button type="button" onClick={() => void logout().then(() => setUser(null))}>Sign out</button>
      </header>
      <PageSwitcher activePage={activePage} onPageChange={setActivePage} />
      {pages[activePage]}
    </>
  );
}
