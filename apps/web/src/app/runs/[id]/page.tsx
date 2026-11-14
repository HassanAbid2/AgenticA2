import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import RunTimeline from "../../../components/RunTimeline";
import { ErrorBox, Loading } from "../../../components/ui";
import { api, unwrap } from "../../../lib/api/client";
import { useLoad } from "../../../lib/hooks";

export default function RunPage() {
  const { id = "" } = useParams();
  const rid = Number(id);
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/runs/{run_id}", { params: { path: { run_id: rid } } })), [rid]);
  const [hist, setHist] = useState<any[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (loading || !data) return <Loading what="Loading run" />;
  const r = data.run;
  const live = r.status === "running";
  const loadHistory = async () => setHist(unwrap(await api.GET("/api/runs/{run_id}/history", { params: { path: { run_id: rid } } })) as any[]);
  const replay = async (cp: string) => setNote(unwrap(await api.POST("/api/runs/{run_id}/replay/{checkpoint_id}", { params: { path: { run_id: rid, checkpoint_id: cp } } })).detail);
  return (
    <section>
      <p><Link to="/runs">← Runs</Link> {r.job_id && <>· <Link to={`/jobs/${r.job_id}`}>job {r.job_id}</Link></>}</p>
      <h1>Run #{r.id} <span className="badge">{r.status}</span></h1>
      <p className="small">
        {r.graph} graph · thread <code>{r.thread_id}</code> · trace <code>{r.trace_id}</code>{" "}
        {r.trace_url ? <a href={r.trace_url} target="_blank" rel="noreferrer">open full trace in Phoenix</a> : <span className="muted">(trace stored in run events + audit log below)</span>}
      </p>
      <p className="small">{r.latency_s.toFixed(2)}s · {r.tokens} tokens · ${r.cost_usd.toFixed(5)} · {r.steps} steps</p>
      {r.error && <p className="bad">{r.error}</p>}
      <div className="grid2">
        <article className="card">
          <h2>Node by node {live && <span className="muted small">(live)</span>}</h2>
          <RunTimeline runId={rid} initial={data.events as any} live={live} />
        </article>
        <div className="stack">
          <article className="card">
            <h2>Tokens and cost per node</h2>
            <table className="small">
              <thead><tr><th>Node</th><th>In</th><th>Out</th><th>USD</th><th>LLM s</th></tr></thead>
              <tbody>
                {Object.entries(r.per_node as Record<string, any>).map(([n, v]) => (
                  <tr key={n}><td>{n}</td><td>{v.input_tokens}</td><td>{v.output_tokens}</td><td>{v.cost_usd.toFixed(5)}</td><td>{v.llm_s.toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
            {!Object.keys(r.per_node).length && <p className="small muted">No LLM calls (deterministic nodes or offline profile).</p>}
          </article>
          <article className="card">
            <h2>Audit log (MCP tool calls, same trace id)</h2>
            <ol className="small audit">
              {data.audit.map((a: any) => <li key={a.id}><code>{a.server}.{a.tool}</code> <span className={a.status === "ok" ? "good" : "bad"}>{a.status}</span> <span className="muted">{JSON.stringify(a.args).slice(0, 120)}</span></li>)}
            </ol>
          </article>
          <article className="card">
            <h2>Checkpoints</h2>
            <button className="ghost" onClick={loadHistory}>Load checkpoint history</button>
            {note && <p className="small" role="status">{note}</p>}
            {hist && (
              <ol className="small">
                {hist.map((h) => (
                  <li key={h.checkpoint_id}>step {h.step} · next: {h.next.join(", ") || "(end)"} · {h.writes.join(", ")}
                    {" "}<button className="link" onClick={() => replay(h.checkpoint_id)}>replay from here</button></li>
                ))}
              </ol>
            )}
          </article>
        </div>
      </div>
    </section>
  );
}
