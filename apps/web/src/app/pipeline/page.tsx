import { Link } from "react-router-dom";
import { api, unwrap, type ProposalCard } from "../../lib/api/client";
import { money, useLoad, useSSE } from "../../lib/hooks";
import { Empty, ErrorBox, Loading } from "../../components/ui";

const COLS = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"];

export default function PipelinePage() {
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/pipeline")));
  useSSE("/api/stream/inbox", () => void reload(true), ["update"]);
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (loading || !data) return <Loading what="Loading pipeline" />;
  const total = Object.values(data.columns).reduce((n, c) => n + c.length, 0);
  return (
    <section>
      <h1>Pipeline</h1>
      <p className="muted small">Cards move as marketplace events arrive (viewed, replied, interview, hired).</p>
      {total === 0 ? <Empty title="No proposals yet"><p>Approve a draft in the proposal studio to see it here.</p></Empty> : (
        <div className="kanban" data-testid="kanban">
          {COLS.map((c) => (
            <section key={c} className="col" aria-label={c}>
              <h2>{c} <span className="pill">{data.columns[c]?.length ?? 0}</span></h2>
              {(data.columns[c] ?? []).map((p: ProposalCard) => (
                <article key={p.id} className="card mini">
                  <Link to={p.approval_id ? `/studio/${p.approval_id}` : `/jobs/${p.job_id}`}>{p.title}</Link>
                  <div className="small muted">{p.category} · {money(p.bid_amount, p.bid_unit)} · {p.connects_spent} Connects</div>
                  <div className="small"><span className="badge">{p.status}</span> <span className="muted">{p.strategy}</span></div>
                </article>
              ))}
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
