import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../App";
import { api, unwrap, type UserOut } from "../../lib/api/client";

export default function LoginPage() {
  const { setUser } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const u: UserOut = mode === "login"
        ? unwrap(await api.POST("/api/auth/login", { body: { email, password } }))
        : unwrap(await api.POST("/api/auth/signup", { body: { email, password, name } }));
      setUser(u);
      nav(u.onboarded ? "/inbox" : "/onboarding");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="auth">
      <section className="card narrow">
        <h1 className="brand big">GigBid</h1>
        <p className="muted">Your freelancing copilot: finds jobs, flags scams, drafts proposals backed by your real portfolio. You approve every send.</p>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={mode === "login"} onClick={() => setMode("login")}>Sign in</button>
          <button role="tab" aria-selected={mode === "signup"} onClick={() => setMode("signup")}>Create account</button>
        </div>
        <form onSubmit={submit} className="stack">
          {mode === "signup" && (
            <label>Name<input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
          )}
          <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
          <label>Password<input type="password" required minLength={mode === "signup" ? 8 : 1} value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
          {err && <p className="bad" role="alert">{err}</p>}
          <button className="primary" disabled={busy} type="submit">{mode === "login" ? "Sign in" : "Create account"}</button>
        </form>
      </section>
    </div>
  );
}
