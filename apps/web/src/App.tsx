import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, type UserOut } from "./lib/api/client";
import Layout from "./components/Layout";
import LoginPage from "./app/login/page";
import OnboardingPage from "./app/onboarding/page";
import InboxPage from "./app/inbox/page";
import JobPage from "./app/jobs/[id]/page";
import StudioPage from "./app/studio/[id]/page";
import PipelinePage from "./app/pipeline/page";
import MessagesPage from "./app/messages/page";
import RunsPage from "./app/runs/page";
import RunPage from "./app/runs/[id]/page";
import AnalyticsPage from "./app/analytics/page";
import SettingsPage from "./app/settings/page";

type AuthCtx = { user: UserOut | null; setUser: (u: UserOut | null) => void; refresh: () => Promise<void> };
const Ctx = createContext<AuthCtx>({ user: null, setUser: () => {}, refresh: async () => {} });
export const useAuth = () => useContext(Ctx);

export default function App() {
  const [user, setUser] = useState<UserOut | null>(null);
  const [ready, setReady] = useState(false);
  const loc = useLocation();
  const refresh = async () => {
    const r = await api.GET("/api/auth/me");
    setUser(r.response.ok ? (r.data as UserOut) : null);
  };
  useEffect(() => {
    void refresh().finally(() => setReady(true));
  }, []);
  if (!ready) return <p className="center muted" role="status">Loading GigBid…</p>;
  const guard = (el: JSX.Element) =>
    !user ? <Navigate to="/login" state={{ from: loc.pathname }} replace /> : !user.onboarded ? <Navigate to="/onboarding" replace /> : el;
  return (
    <Ctx.Provider value={{ user, setUser, refresh }}>
      <Routes>
        <Route path="/login" element={user ? <Navigate to={user.onboarded ? "/inbox" : "/onboarding"} replace /> : <LoginPage />} />
        <Route path="/onboarding" element={user ? <OnboardingPage /> : <Navigate to="/login" replace />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/inbox" replace />} />
          <Route path="/inbox" element={guard(<InboxPage />)} />
          <Route path="/jobs/:id" element={guard(<JobPage />)} />
          <Route path="/studio/:id" element={guard(<StudioPage />)} />
          <Route path="/pipeline" element={guard(<PipelinePage />)} />
          <Route path="/messages" element={guard(<MessagesPage />)} />
          <Route path="/runs" element={guard(<RunsPage />)} />
          <Route path="/runs/:id" element={guard(<RunPage />)} />
          <Route path="/analytics" element={guard(<AnalyticsPage />)} />
          <Route path="/settings" element={guard(<SettingsPage />)} />
          <Route path="*" element={<p className="center">Page not found.</p>} />
        </Route>
      </Routes>
    </Ctx.Provider>
  );
}
