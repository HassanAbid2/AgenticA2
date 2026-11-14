import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../App";
import { api, unwrap } from "../../lib/api/client";

const PERSONAS = [
  { id: "ai_ml", label: "AI/ML engineer", hint: "LLM apps, RAG, computer vision, tabular ML", rate: 45, floor: 30, min: 300 },
  { id: "fullstack", label: "Full-stack web developer", hint: "React/Next.js, Node, Django, payments", rate: 38, floor: 25, min: 250 },
  { id: "data_analyst", label: "Data analyst", hint: "SQL, dbt, BI dashboards, experiments", rate: 30, floor: 20, min: 150 },
  { id: "own", label: "My own profile", hint: "Upload your CV, case studies and code below", rate: 30, floor: 20, min: 150 },
] as const;

export default function OnboardingPage() {
  const { refresh } = useAuth();
  const nav = useNavigate();
  const [persona, setPersona] = useState<(typeof PERSONAS)[number]["id"]>("ai_ml");
  const p = PERSONAS.find((x) => x.id === persona)!;
  const [market, setMarket] = useState<"gigsim" | "upwork">("gigsim");
  const [rate, setRate] = useState<number>(p.rate);
  const [floor, setFloor] = useState<number>(p.floor);
  const [min, setMin] = useState<number>(p.min);
  const [budget, setBudget] = useState(120);
  const [keywords, setKeywords] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pick = (id: typeof persona) => {
    const q = PERSONAS.find((x) => x.id === id)!;
    setPersona(id);
    setRate(q.rate);
    setFloor(q.floor);
    setMin(q.min);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      unwrap(await api.POST("/api/onboarding", { body: { persona, marketplace: market, hourly_rate: rate, floor_hourly: floor, min_fixed: min,
        weekly_connects_budget: budget, keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean), categories: [], headline: "" } }));
      for (const f of Array.from(files ?? [])) {
        const fd = new FormData();
        fd.append("file", f);
        fd.append("meta", JSON.stringify({}));
        const r = await fetch("/api/portfolio/upload", { method: "POST", body: fd, credentials: "include" });
        if (!r.ok) throw new Error(`upload ${f.name}: ${(await r.json()).detail}`);
      }
      if (market === "upwork") {
        const r = await api.GET("/api/accounts/upwork/start");
        if (r.response.ok) {
          window.location.href = (r.data as { authorize_url: string }).authorize_url;
          return;
        }
        setMsg("Upwork's authorization server could not be reached; you can connect it later in Settings. Using GigSim for now.");
      }
      await api.POST("/api/scout/run");
      await refresh();
      nav("/inbox");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="auth">
      <form className="card wide stack" onSubmit={submit} aria-labelledby="ob-title">
        <h1 id="ob-title">Set up GigBid</h1>
        <fieldset>
          <legend>1. Whose portfolio should GigBid use?</legend>
          <div className="grid4">
            {PERSONAS.map((x) => (
              <label key={x.id} className={`choice ${persona === x.id ? "on" : ""}`}>
                <input type="radio" name="persona" value={x.id} checked={persona === x.id} onChange={() => pick(x.id)} />
                <strong>{x.label}</strong>
                <span className="small muted">{x.hint}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>2. Connect a marketplace</legend>
          <label className="inline"><input type="radio" name="m" checked={market === "gigsim"} onChange={() => setMarket("gigsim")} /> GigSim (simulator, safe for testing)</label>
          <label className="inline"><input type="radio" name="m" checked={market === "upwork"} onChange={() => setMarket("upwork")} /> Upwork (official MCP server, OAuth; drafts only)</label>
        </fieldset>
        <fieldset>
          <legend>3. Portfolio (optional)</legend>
          <label>CV, case studies (Markdown/PDF) or code files
            <input type="file" multiple accept=".pdf,.md,.txt,.py,.ts,.tsx,.js,.sql" onChange={(e) => setFiles(e.target.files)} />
          </label>
        </fieldset>
        <fieldset className="grid4">
          <legend>4. Rates, filters and budget</legend>
          <label>Hourly rate ($)<input type="number" min={1} value={rate} onChange={(e) => setRate(+e.target.value)} /></label>
          <label>Hourly floor ($)<input type="number" min={1} value={floor} onChange={(e) => setFloor(+e.target.value)} /></label>
          <label>Minimum fixed job ($)<input type="number" min={0} value={min} onChange={(e) => setMin(+e.target.value)} /></label>
          <label>Weekly Connects budget<input type="number" min={0} value={budget} onChange={(e) => setBudget(+e.target.value)} /></label>
          <label className="span2">Extra search keywords (comma separated)<input value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="e.g. RAG, churn model" /></label>
        </fieldset>
        {msg && <p className="banner warn">{msg}</p>}
        {err && <p className="bad" role="alert">{err}</p>}
        <button className="primary" disabled={busy} type="submit" data-testid="finish-onboarding">{busy ? "Setting up…" : "Finish and find jobs"}</button>
      </form>
    </div>
  );
}
