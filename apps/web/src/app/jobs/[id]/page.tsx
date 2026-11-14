import { useEffect } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, unwrap } from "../../../lib/api/client";
import { money, pct, useLoad, useSSE } from "../../../lib/hooks";
import { ActionBadge, ErrorBox, Loading, Meter, RiskBadges } from "../../../components/ui";

type Matrix = { requirement: string; evidence_ids: string[]; titles: string[]; best_score: number; strength: string }[];

export default function JobPage() {
  const { id = "" } = useParams();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })), [id]);
  useSSE("/api/stream/inbox", () => void reload(true), ["update"]);
  useEffect(() => {
    if (sp.get("studio") && data?.approval_id) nav(`/studio/${data.approval_id}`, { replace: true });
  }, [sp, data, nav]);
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (loading || !data) return <Loading what="Loading job" />;
  const a = data.analysis as Record<string, any>;
  const spec = a.job_spec ?? {};
  const risk = a.risk_report ?? {};
  const fit = a.fit_report ?? {};
  const price = a.price ?? {};
  const dec = a.decision ?? {};
  const job = data.job as Record<string, any>;
  const analyse = async (force: boolean) => {
    await api.POST("/api/jobs/{job_id}/analyse", { params: { path: { job_id: id } }, body: { force_bid: force } });
    void reload(true);
  };
  return (
    <section>
      <p><Link to="/inbox">← Inbox</Link></p>
      <div className="row between wrap">
        <h1>{job.title}</h1>
        <ActionBadge action={data.row.decision} status={data.row.status} />
      </div>
      <div className="row gap wrap">
        {data.approval_id && <Link className="btn primary" to={`/studio/${data.approval_id}`}>Open proposal studio</Link>}
        {data.run_id && <Link className="btn ghost" to={`/runs/${data.run_id}`}>Watch agent run</Link>}
        <button className="ghost" onClick={() => analyse(false)}>Re-analyse</button>
        {data.row.decision !== "bid" && <button className="ghost" onClick={() => analyse(true)}>Bid anyway</button>}
      </div>
      <div className="grid2">
        <article className="card">
          <h2>Bid or skip</h2>
          <p><strong>{dec.action ?? "pending"}</strong> {dec.confidence != null && <span className="muted">(confidence {pct(dec.confidence)})</span>}</p>
          <ul>{(dec.reasons ?? [a.status_reason].filter(Boolean)).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          <h3>Price</h3>
          <p>{money(price.amount, price.unit)} <span className="muted small">band {money(price.band_low, price.unit)}–{money(price.band_high, price.unit)} · {price.connects_cost ?? job.connects_cost} Connects</span></p>
          <ul className="small">{(price.rationale ?? []).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
        </article>
        <article className="card">
          <h2>Risk report <RiskBadges flags={risk.flags ?? []} score={risk.score} /></h2>
          <p className="small">{risk.explanation}</p>
          <p className="small">Client quality <Meter value={risk.client_quality} label="client quality" /></p>
          {risk.injection_detected && (
            <div className="banner warn small">
              Instructions aimed at AI tools were found in this post and removed before any agent read it:
              <ul>{(risk.injected_spans ?? []).map((s: string, i: number) => <li key={i}><code>{s}</code></li>)}</ul>
            </div>
          )}
        </article>
      </div>
      <article className="card">
        <h2>Requirement → evidence <span className="muted small">fit {pct(fit.score)}</span></h2>
        <div className="tablewrap">
          <table data-testid="matrix">
            <thead><tr><th>Requirement</th><th>Strength</th><th>Portfolio evidence</th><th>Similarity</th></tr></thead>
            <tbody>
              {((fit.matrix ?? []) as Matrix).map((m, i) => (
                <tr key={i}>
                  <td>{m.requirement}</td>
                  <td><span className={`badge s-${m.strength}`}>{m.strength}</span></td>
                  <td>{m.titles.length ? m.titles.map((t, k) => <div key={k}>{t} <code className="small">{m.evidence_ids[k]}</code></div>) : <em className="muted">none</em>}</td>
                  <td>{m.best_score?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {fit.missing_skills?.length ? <p className="small">No evidence for: {fit.missing_skills.join(", ")}</p> : null}
      </article>
      <div className="grid2">
        <article className="card">
          <h2>JobSpec</h2>
          <dl className="spec">
            <dt>Requirements</dt><dd>{(spec.requirements ?? []).join(" · ")}</dd>
            <dt>Skills</dt><dd>{(spec.required_skills ?? []).join(", ")}</dd>
            <dt>Deliverables</dt><dd>{(spec.deliverables ?? []).join(" · ") || "-"}</dd>
            <dt>Hidden needs</dt><dd>{(spec.hidden_needs ?? []).join(" · ") || "-"}</dd>
            <dt>Budget</dt><dd>{money(job.budget?.min)}–{money(job.budget?.max)} ({job.budget?.type})</dd>
            <dt>Screening</dt><dd>{(spec.screening_questions ?? []).join(" / ") || "-"}</dd>
            <dt>Extracted by</dt><dd>{spec.source ?? "-"}</dd>
          </dl>
        </article>
        <article className="card">
          <h2>Original post <span className="badge flag">untrusted</span></h2>
          <pre className="post">{job.description}</pre>
        </article>
      </div>
    </section>
  );
}
