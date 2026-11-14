import { Link } from "react-router-dom";
import { Empty, ErrorBox, Loading } from "../../components/ui";
import { api, unwrap } from "../../lib/api/client";
import { useLoad, useSSE } from "../../lib/hooks";

export default function RunsPage() {
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/runs", { params: { query: { limit: 100 } } })));
  useSSE("/api/stream/inbox", () => void reload(true), ["update"]);
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (loading || !data) return <Loading what="Loading runs" />;
  return (
    <section>
      <h1>Agent runs</h1>
      {!data.length ? <Empty title="No runs yet" /> : (
        <div className="tablewrap">
          <table>
            <thead><tr><th>Run</th><th>Graph</th><th>Job</th><th>Status</th><th>Latency</th><th>Tokens</th><th>Cost</th></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/runs/${r.id}`}>#{r.id}</Link></td>
                  <td>{r.graph}</td>
                  <td>{r.job_id}</td>
                  <td><span className="badge">{r.status}</span></td>
                  <td>{r.latency_s.toFixed(1)}s</td>
                  <td>{r.tokens}</td>
                  <td>${r.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
