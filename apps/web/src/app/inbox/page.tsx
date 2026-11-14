import { useState } from "react";
import { Link } from "react-router-dom";
import { api, unwrap, type JobRow } from "../../lib/api/client";
import { money, useLoad, useSSE } from "../../lib/hooks";
import { ActionBadge, Empty, ErrorBox, Loading, Meter, RiskBadges } from "../../components/ui";

const FILTERS = [
  ["", "All"], ["awaiting_approval", "Awaiting approval"], ["bid", "Recommended bids"], ["watch", "Watch"],
  ["skipped", "Skipped"], ["submitted", "Submitted"], ["needs_attention", "Needs attention"],
] as const;

export default function InboxPage() {
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const [minFit, setMinFit] = useState(0);
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/jobs", {
    params: { query: { status: ["", "bid"].includes(filter) ? undefined : filter, decision: filter === "bid" ? "bid" : undefined, min_fit: minFit, q } },
  })), [filter, q, minFit]);
  useSSE("/api/stream/inbox", () => void reload(true), ["update"]);
  const [note, setNote] = useState<string | null>(null);
  const scout = async () => {
    const r = unwrap(await api.POST("/api/scout/run"));
    setNote(r.detail);
  };
  const skip = async (id: string) => {
    await api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: id } } });
    void reload(true);
  };
  const jobs = data?.jobs ?? [];
  return (
    <section>
      <div className="row between wrap">
        <h1>Job inbox</h1>
        <div className="row gap">
          <button className="primary" onClick={scout}>Run saved searches now</button>
        </div>
      </div>
      {note && <p className="muted small" role="status">{note}</p>}
      <div className="filters row wrap gap" role="group" aria-label="Filters">
        {FILTERS.map(([v, l]) => (
          <button key={v} className={`chip ${filter === v ? "on" : ""}`} aria-pressed={filter === v} onClick={() => setFilter(v)}>
            {l} {data?.counts && v && data.counts[v] ? <span className="pill">{data.counts[v]}</span> : null}
          </button>
        ))}
        <label className="inline small">Min fit <input type="range" min={0} max={1} step={0.05} value={minFit} onChange={(e) => setMinFit(+e.target.value)} aria-valuetext={`${Math.round(minFit * 100)}%`} /></label>
        <input type="search" placeholder="Search titles" aria-label="Search jobs" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error && <ErrorBox error={error} retry={() => reload()} />}
      {loading && !data ? <Loading what="Loading jobs" /> : jobs.length === 0 ? (
        <Empty title="No jobs here yet">
          <p>GigBid checks your saved searches on a schedule. Run them now, or adjust searches in Settings.</p>
        </Empty>
      ) : (
        <ul className="jobs" data-testid="job-list">
          {jobs.map((j: JobRow) => (
            <li key={j.job_id} className="card job">
              <div className="row between wrap">
                <Link to={j.status === "awaiting_approval" ? `/jobs/${j.job_id}?studio=1` : `/jobs/${j.job_id}`} className="title">{j.title}</Link>
                <ActionBadge action={j.decision} status={j.status} />
              </div>
              <div className="row wrap gap small">
                <span className="muted">{j.category}</span>
                <span>Fit <Meter value={j.fit_score} label="fit score" /></span>
                <RiskBadges flags={j.risk_flags} score={j.risk_score} />
                <span>Price {money(j.price, j.price_unit)}</span>
                <span>{j.connects_cost ?? "?"} Connects</span>
                {j.pipeline && <span className="badge">{j.pipeline}</span>}
              </div>
              {j.reason && <p className="small muted reason">{j.reason}</p>}
              <div className="row gap">
                <Link className="ghost btn" to={`/jobs/${j.job_id}`}>Open</Link>
                {!["skipped", "submitted", "rejected"].includes(j.status) && <button className="ghost" onClick={() => skip(j.job_id)}>Skip</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
