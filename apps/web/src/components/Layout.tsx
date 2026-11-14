import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../App";
import { api, type HealthOut } from "../lib/api/client";
import { useSSE } from "../lib/hooks";

const LINKS = [
  ["/inbox", "Inbox"],
  ["/pipeline", "Pipeline"],
  ["/messages", "Messages"],
  ["/runs", "Agent runs"],
  ["/analytics", "Analytics"],
  ["/settings", "Settings"],
] as const;

export function DegradedBanner() {
  const [h, setH] = useState<HealthOut | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await api.GET("/api/health");
      if (alive && r.response.ok) setH(r.data as HealthOut);
      if (alive && !r.response.ok && r.response.status >= 500)
        setH({ api: "down", marketplace_ok: false, mode: "?", detail: "API unreachable", model_profile: "?", llm: false });
    };
    void tick();
    const t = setInterval(tick, 8000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  if (!h || h.marketplace_ok) return null;
  return (
    <div className="banner warn" role="alert" data-testid="degraded-banner">
      <strong>Marketplace unavailable.</strong> GigBid can't reach the {h.mode === "upwork_live" ? "Upwork" : "GigSim"} marketplace right now
      ({h.detail}). New analyses and approved sends are queued and will resume automatically when it's back. Nothing is lost.
    </div>
  );
}

export default function Layout() {
  const { user, setUser } = useAuth();
  const nav = useNavigate();
  const [pending, setPending] = useState<number | null>(null);
  const [live, setLive] = useState("");
  useSSE(user ? "/api/stream/inbox" : null, (_t, d) => {
    const data = d as { pending_approvals: number; events: { node: string; kind: string }[] };
    setPending(data.pending_approvals);
    const last = data.events[data.events.length - 1];
    if (last) setLive(`${last.node}: ${last.kind.replace("_", " ")}`);
  }, ["update"]);
  useEffect(() => {
    if (user) void api.GET("/api/approvals").then((r) => r.response.ok && setPending((r.data ?? []).length));
  }, [user]);
  const logout = async () => {
    await api.POST("/api/auth/logout");
    setUser(null);
    nav("/login");
  };
  return (
    <div className="shell">
      <a href="#main" className="skip">Skip to content</a>
      <header className="top">
        <span className="brand" aria-label="GigBid">GigBid</span>
        <nav aria-label="Main">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
              {to === "/inbox" && pending ? <span className="pill" aria-label={`${pending} awaiting approval`}>{pending}</span> : null}
            </NavLink>
          ))}
        </nav>
        <div className="who">
          <span className="muted small" aria-live="polite">{live}</span>
          <span className="small">{user?.name || user?.email}</span>
          <button className="ghost" onClick={logout}>Sign out</button>
        </div>
      </header>
      <DegradedBanner />
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
