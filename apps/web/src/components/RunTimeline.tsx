import { useEffect, useState } from "react";
import { useSSE } from "../lib/hooks";

type Ev = { id?: number; node: string; kind: string; payload: Record<string, unknown>; ts?: string };

/** Live node-by-node progress streamed from the LangGraph run (SSE). */
export default function RunTimeline({ runId, initial, live }: { runId: number; initial: Ev[]; live: boolean }) {
  const [events, setEvents] = useState<Ev[]>(initial);
  useEffect(() => setEvents(initial), [initial]);
  useSSE(live ? `/api/stream/runs/${runId}` : null, (_type, d) => {
    const e = d as Ev;
    setEvents((xs) => (xs.some((x) => x.ts === e.ts && x.node === e.node && x.kind === e.kind) ? xs : [...xs, e]));
  }, ["node_start", "node_end", "interrupt", "done", "start", "custom"]);
  const ends = events.filter((e) => e.kind === "node_end" || e.kind === "interrupt" || e.kind === "done" || e.kind === "start");
  const running = events.filter((e) => e.kind === "node_start" && !events.some((x) => x.kind === "node_end" && x.node === e.node));
  return (
    <ol className="timeline" aria-live="polite" data-testid="timeline">
      {ends.map((e, i) => (
        <li key={i} className={`k-${e.kind}`}>
          <strong>{e.node}</strong>{" "}
          {e.kind === "node_end" ? (
            <span className="muted small">
              {String(e.payload.latency_s ?? "")}s · {String(e.payload.tokens ?? 0)} tokens
              {Array.isArray(e.payload.tool_calls) && e.payload.tool_calls.length
                ? ` · tools: ${(e.payload.tool_calls as { tool: string }[]).map((t) => t.tool).join(", ")}`
                : ""}
            </span>
          ) : (
            <span className="badge">{e.kind === "interrupt" ? "waiting for your approval" : e.kind}</span>
          )}
          {e.payload.summary ? <pre className="small">{JSON.stringify(e.payload.summary)}</pre> : null}
          {e.kind === "done" && e.payload.error ? <p className="bad">{String(e.payload.error)}</p> : null}
        </li>
      ))}
      {running.map((e, i) => (
        <li key={`r${i}`} className="k-running"><strong>{e.node}</strong> <span className="muted">running…</span></li>
      ))}
    </ol>
  );
}
