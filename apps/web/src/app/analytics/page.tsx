import { Empty, ErrorBox, Loading } from "../../components/ui";
import { api, unwrap } from "../../lib/api/client";
import { pct, useLoad } from "../../lib/hooks";

function Bars({ rows, value, label, fmt = (v: number) => String(v) }: { rows: any[]; value: string; label: string; fmt?: (v: number) => string }) {
  const max = Math.max(1e-9, ...rows.map((r) => r[value] ?? 0));
  return (
    <ul className="bars">
      {rows.map((r) => (
        <li key={r[label]}>
          <span className="lbl">{r[label]}</span>
          <span className="bar" role="img" aria-label={`${r[label]}: ${fmt(r[value] ?? 0)}`}><span style={{ width: `${((r[value] ?? 0) / max) * 100}%` }} /></span>
          <span className="val">{fmt(r[value] ?? 0)}</span>
        </li>
      ))}
    </ul>
  );
}

export default function AnalyticsPage() {
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/analytics")));
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (loading || !data) return <Loading what="Loading analytics" />;
  const cl = data.cost_latency as Record<string, number | null>;
  const b = data.budgets as Record<string, number>;
  const funnel = Object.entries(data.funnel).map(([k, v]) => ({ stage: k.replace(/_/g, " "), n: v }));
  const within = (v: number | null, lim: number) => (v == null ? "-" : v <= lim ? "within budget" : "OVER budget");
  return (
    <section>
      <h1>Analytics</h1>
      <div className="grid2">
        <article className="card">
          <h2>Funnel</h2>
          <Bars rows={funnel} value="n" label="stage" />
        </article>
        <article className="card">
          <h2>Reply and hire rate by category</h2>
          {data.by_category.length ? (
            <>
              <Bars rows={data.by_category} value="reply_rate" label="category" fmt={pct} />
              <table className="small"><thead><tr><th>Category</th><th>Sent</th><th>Replied</th><th>Hired</th><th>Connects</th></tr></thead>
                <tbody>{data.by_category.map((c: any) => <tr key={c.category}><td>{c.category}</td><td>{c.sent}</td><td>{c.replied}</td><td>{c.hired}</td><td>{c.connects}</td></tr>)}</tbody></table>
            </>
          ) : <Empty title="No proposals sent yet" />}
        </article>
        <article className="card">
          <h2>Connects spent vs outcomes</h2>
          <p>{data.connects.spent as number} Connects spent · {data.connects.replies as number} replies · {String(data.connects.connects_per_reply ?? "-")} Connects per reply</p>
          <Bars rows={Object.entries(data.connects.by_outcome as Record<string, number>).map(([k, v]) => ({ k, v }))} value="v" label="k" />
        </article>
        <article className="card">
          <h2>Cost and latency vs declared budgets</h2>
          <table className="small">
            <thead><tr><th>Metric</th><th>Measured</th><th>Budget</th><th /></tr></thead>
            <tbody>
              <tr><td>p95 latency per job analysed</td><td>{cl.p95_latency_s_per_job ?? "-"}s</td><td>{b.p95_latency_s_per_job}s</td><td>{within(cl.p95_latency_s_per_job, b.p95_latency_s_per_job)}</td></tr>
              <tr><td>p95 latency per proposal</td><td>{cl.p95_latency_s_per_proposal ?? "-"}s</td><td>{b.p95_latency_s_per_proposal}s</td><td>{within(cl.p95_latency_s_per_proposal, b.p95_latency_s_per_proposal)}</td></tr>
              <tr><td>USD per job analysed (mean)</td><td>{cl.usd_per_job_mean ?? "-"}</td><td>{b.usd_per_job}</td><td>{within(cl.usd_per_job_mean, b.usd_per_job)}</td></tr>
              <tr><td>USD per proposal (mean)</td><td>{cl.usd_per_proposal_mean ?? "-"}</td><td>{b.usd_per_proposal}</td><td>{within(cl.usd_per_proposal_mean, b.usd_per_proposal)}</td></tr>
            </tbody>
          </table>
          <p className="small muted">{cl.jobs_analysed} jobs analysed · p50 {cl.p50_latency_s_per_job ?? "-"}s · {cl.tokens_total} tokens total</p>
        </article>
        <article className="card">
          <h2>Top rejection reasons</h2>
          {data.rejection_reasons.length ? <Bars rows={data.rejection_reasons} value="count" label="reason" /> : <p className="muted small">You haven't rejected any drafts yet.</p>}
        </article>
      </div>
    </section>
  );
}
