import React from "react";

import { getMe, logout } from "./api/auth";
import AuthPanel from "./components/auth/AuthPanel";
import Logo from "./components/Logo";
import PageSwitcher, { type AppPageId } from "./components/navigation/PageSwitcher";
import NotificationIndicator from "./components/notifications/NotificationIndicator";
import AccidentAttributionPage from "./pages/AccidentAttributionPage";
import CanonicalNetworkPage from "./pages/CanonicalNetworkPage";
import ForumPage from "./pages/ForumPage";
import InboxPage from "./pages/InboxPage";
import NavigatePage from "./pages/NavigatePage";
import PlanRoutePage from "./pages/PlanRoutePage";
import type { UserProfile } from "./types/auth";
import type { NavigationHandoff } from "./types/navigation";
import { clearNavigationSession, loadNavigationSession, saveNavigationSession } from "./lib/navigationSession";

export interface AppProps {
  initialPage?: AppPageId;
  pages?: Partial<Record<AppPageId, JSX.Element>>;
}

export default function App(props: AppProps): JSX.Element {
  // A refresh, crash, or backgrounded tab mid-drive shouldn't force restarting route
  // planning from scratch, so an in-progress navigation session resumes from sessionStorage.
  const [activePage, setActivePage] = React.useState<AppPageId>(
    () => props.initialPage ?? (loadNavigationSession() ? "navigate" : "plan-route"),
  );
  const [user, setUser] = React.useState<UserProfile | null | undefined>(undefined);
  const [navigationHandoff, setNavigationHandoff] = React.useState<NavigationHandoff | null>(
    () => loadNavigationSession()?.handoff ?? null,
  );

  function startNavigation(handoff: NavigationHandoff) {
    setNavigationHandoff(handoff);
    saveNavigationSession({ handoff, candidate: handoff.candidate, stepIndex: 0 });
    setActivePage("navigate");
  }

  function exitNavigation() {
    setNavigationHandoff(null);
    clearNavigationSession();
    setActivePage("plan-route");
  }

  React.useEffect(() => {
    let cancelled = false;
    void getMe()
      .then((profile) => { if (!cancelled) setUser(profile); })
      .catch(() => { if (!cancelled) setUser(null); });
    return () => { cancelled = true; };
  }, []);

  if (user === undefined) {
    return (
      <main className="page-shell">
        <div className="auth-gate">
          <Logo variant="light" height={84} />
        </div>
        <p>Loading account…</p>
      </main>
    );
  }
  if (user === null) {
    return (
      <main className="page-shell">
        <div className="auth-gate">
          <Logo variant="light" height={84} />
        </div>
        <AuthPanel onAuthenticated={setUser} />
      </main>
    );
  }

  const pages: Record<AppPageId, JSX.Element> = {
    "plan-route": props.pages?.["plan-route"] ?? (
      <PlanRoutePage user={user} onProfileUpdated={setUser} onStartNavigation={startNavigation} />
    ),
    forum: props.pages?.forum ?? <ForumPage />,
    inbox: props.pages?.inbox ?? <InboxPage user={user} />,
    "canonical-network": props.pages?.["canonical-network"] ?? <CanonicalNetworkPage />,
    "accident-attribution": props.pages?.["accident-attribution"] ?? <AccidentAttributionPage />,
    navigate: props.pages?.navigate ?? (
      navigationHandoff ? (
        <NavigatePage handoff={navigationHandoff} onExit={exitNavigation} />
      ) : (
        <PlanRoutePage user={user} onProfileUpdated={setUser} onStartNavigation={startNavigation} />
      )
    ),
  };

  return (
    <>
      <header className="site-header">
        <Logo variant="light" height={150} />
        <div className="site-header__session">
          <NotificationIndicator />
          <span className="site-header__user">{user.email}</span>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void logout().then(() => setUser(null))}
          >
            Sign out
          </button>
        </div>
      </header>
      <PageSwitcher activePage={activePage} onPageChange={setActivePage} />
      {pages[activePage]}
      <footer className="site-footer">
        <Logo variant="dark" />
        <p className="site-footer__copy">Context-aware safe routing, built on real historical accident data.</p>
      </footer>
    </>
  );
}
