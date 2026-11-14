import { useState } from "react";
import { useAuth } from "../../App";
import { ErrorBox, Loading } from "../../components/ui";
import { api, unwrap } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const s = (user?.settings ?? {}) as Record<string, any>;
  const [autonomy, setAutonomy] = useState<string>(s.autonomy ?? "suggest");
  const [budget, setBudget] = useState<number>(s.weekly_connects_budget ?? 120);
  const [rate, setRate] = useState<number>(s.hourly_rate ?? 30);
  const [floor, setFloor] = useState<number>(s.floor_hourly ?? 20);
  const [min, setMin] = useState<number>(s.min_fixed ?? 150);
  const [msg, setMsg] = useState<string | null>(null);
  const searches = useLoad(async () => unwrap(await api.GET("/api/searches")));
  const accounts = useLoad(async () => unwrap(await api.GET("/api/accounts")));
  const memory = useLoad(async () => unwrap(await api.GET("/api/memory")));
  const portfolio = useLoad(async () => unwrap(await api.GET("/api/portfolio")));
  const [ns, setNs] = useState({ name: "", query: "", interval_minutes: 180 });
  const [pf, setPf] = useState("");
  const save = async () => {
    const u = unwrap(await api.PUT("/api/settings", { body: { autonomy: autonomy as "suggest" | "auto_skip_low_fit", weekly_connects_budget: budget, hourly_rate: rate, floor_hourly: floor, min_fixed: min } }));
    setUser(u);
    setMsg("Saved.");
  };
  const addSearch = async () => {
    if (!ns.name.trim()) return;
    unwrap(await api.POST("/api/searches", { body: { ...ns, skills: [], category: "", min_budget: 0, enabled: true } }));
    setNs({ name: "", query: "", interval_minutes: 180 });
    void searches.reload(true);
  };
  const forget = async (namespace: string, key: string) => {
    await api.DELETE("/api/memory/{namespace}/{key}", { params: { path: { namespace, key } } });
    void memory.reload(true);
  };
  const toggle = async (id: string, excluded: boolean) => {
    setUser(unwrap(await api.POST("/api/portfolio/{evidence_id}/exclude", { params: { path: { evidence_id: id }, query: { excluded } } })));
    void portfolio.reload(true);
  };
  const upload = async (f: File | undefined) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("meta", "{}");
    const r = await fetch("/api/portfolio/upload", { method: "POST", body: fd, credentials: "include" });
    setMsg(r.ok ? `Indexed ${f.name} (incremental re-index).` : `Upload failed: ${(await r.json()).detail}`);
    void portfolio.reload(true);
  };
  const connectUpwork = async () => {
    const r = await api.GET("/api/accounts/upwork/start");
    if (r.response.ok) window.location.href = (r.data as { authorize_url: string }).authorize_url;
    else setMsg("Upwork authorization server unreachable from this deployment.");
  };
  const items = (portfolio.data ?? []).filter((e) => !pf || (e.title + e.evidence_id + (e.project ?? "")).toLowerCase().includes(pf.toLowerCase()));
  return (
    <section className="stack">
      <h1>Settings</h1>
      {msg && <p className="banner ok" role="status">{msg}</p>}
      <article className="card">
        <h2>Autonomy and budgets</h2>
        <fieldset>
          <legend>Autonomy</legend>
          <label className="inline"><input type="radio" checked={autonomy === "suggest"} onChange={() => setAutonomy("suggest")} /> Suggest only (default)</label>
          <label className="inline"><input type="radio" checked={autonomy === "auto_skip_low_fit"} onChange={() => setAutonomy("auto_skip_low_fit")} /> Auto-skip low-fit jobs</label>
          <p className="small muted">GigBid never sends anything without your approval, whatever this setting.</p>
        </fieldset>
        <div className="grid4">
          <label>Weekly Connects budget<input type="number" value={budget} onChange={(e) => setBudget(+e.target.value)} /></label>
          <label>Hourly rate<input type="number" value={rate} onChange={(e) => setRate(+e.target.value)} /></label>
          <label>Hourly floor<input type="number" value={floor} onChange={(e) => setFloor(+e.target.value)} /></label>
          <label>Minimum fixed job<input type="number" value={min} onChange={(e) => setMin(+e.target.value)} /></label>
        </div>
        <button className="primary" onClick={save}>Save</button>
      </article>
      <article className="card">
        <h2>Saved searches</h2>
        {searches.error && <ErrorBox error={searches.error} />}
        <ul>{(searches.data ?? []).map((x) => (
          <li key={x.id} className="row between">
            <span>{x.name} <span className="muted small">{x.query || x.category} · every {x.interval_minutes} min · last {x.last_run_at ? new Date(x.last_run_at).toLocaleString() : "never"}</span></span>
            <button className="ghost" onClick={async () => { await api.DELETE("/api/searches/{sid}", { params: { path: { sid: x.id } } }); void searches.reload(true); }}>Remove</button>
          </li>))}
        </ul>
        <div className="row gap wrap">
          <input aria-label="Search name" placeholder="Name" value={ns.name} onChange={(e) => setNs({ ...ns, name: e.target.value })} />
          <input aria-label="Keywords" placeholder="Keywords" value={ns.query} onChange={(e) => setNs({ ...ns, query: e.target.value })} />
          <label className="inline small">every <input type="number" min={15} value={ns.interval_minutes} onChange={(e) => setNs({ ...ns, interval_minutes: +e.target.value })} /> min</label>
          <button className="ghost" onClick={addSearch}>Add search</button>
        </div>
      </article>
      <article className="card">
        <h2>Connected accounts</h2>
        <ul>{(accounts.data ?? []).map((a) => (
          <li key={a.provider} className="row between">
            <span>{a.provider === "gigsim" ? "GigSim (simulator)" : "Upwork (official MCP, drafts only)"}: {a.connected ? <span className="good">connected</span> : <span className="muted">not connected</span>}</span>
            {a.provider === "upwork" && !a.connected && <button className="ghost" onClick={connectUpwork}>Connect Upwork</button>}
            {a.connected && <button className="ghost" onClick={async () => { await api.DELETE("/api/accounts/{provider}", { params: { path: { provider: a.provider } } }); void accounts.reload(true); }}>Disconnect</button>}
          </li>))}
        </ul>
        <p className="small muted">Tokens are stored encrypted and never shown or logged.</p>
      </article>
      <article className="card" data-testid="memory">
        <h2>What GigBid has learned</h2>
        {memory.loading && !memory.data ? <Loading /> : (
          <>
            <h3>Style memory <span className="muted small">(from {memory.data?.edits_logged ?? 0} edits; a rule is promoted only after it shows up in 3 different edits)</span></h3>
            {memory.data?.style.length ? <ul>{memory.data.style.map((m) => (
              <li key={m.key} className="row between"><span>{String(m.value.rule)} <span className="muted small">support {String(m.value.support)}</span></span>
                <button className="ghost" onClick={() => forget("style", m.key)}>Forget</button></li>))}</ul> : <p className="muted small">Nothing learned yet.</p>}
            <h3>Outcome memory</h3>
            {memory.data?.outcome.length ? <ul>{memory.data.outcome.map((m) => (
              <li key={m.key} className="row between"><span>{m.key}: reply rate {String(m.value.reply_rate)} over {String(m.value.n)} proposals; best strategy {String(m.value.best_strategy)}</span>
                <button className="ghost" onClick={() => forget("outcome", m.key)}>Forget</button></li>))}</ul> : <p className="muted small">Needs 5 outcomes in a category first.</p>}
          </>
        )}
      </article>
      <article className="card">
        <h2>Portfolio evidence</h2>
        <div className="row gap wrap">
          <label className="inline">Add work <input type="file" accept=".pdf,.md,.txt,.py,.ts,.tsx,.js,.sql" onChange={(e) => upload(e.target.files?.[0])} /></label>
          <input type="search" aria-label="Filter evidence" placeholder="Filter" value={pf} onChange={(e) => setPf(e.target.value)} />
        </div>
        <div className="tablewrap">
          <table className="small">
            <thead><tr><th>Evidence</th><th>Type</th><th>Project</th><th>Use in proposals</th></tr></thead>
            <tbody>{items.slice(0, 200).map((e) => (
              <tr key={e.evidence_id} className={e.excluded ? "muted" : ""}>
                <td><code>{e.evidence_id}</code> {e.title}</td><td>{e.type}</td><td>{e.project ?? "-"}</td>
                <td><label className="inline"><input type="checkbox" checked={!e.excluded} onChange={(ev) => toggle(e.evidence_id, !ev.target.checked)} /> {e.excluded ? "hidden" : "used"}</label></td>
              </tr>))}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}
