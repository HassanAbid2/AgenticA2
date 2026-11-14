import { useState } from "react";
import { api, unwrap } from "../lib/api/client";

type Preview = {
  dry_run?: boolean;
  connects_cost?: number | null;
  balance_before?: number | null;
  balance_after?: number | null;
  policy_issues?: string[];
  would_send?: Record<string, unknown>;
};

/** Approve / edit / reject an interrupted agent action. Decisions are persisted server-side before
 * the graph resumes, so a page refresh never loses them. */
export default function ApprovalPanel({ approvalId, preview, editedText, kind, onDone }: {
  approvalId: number;
  preview?: Preview | null;
  editedText?: string | null;
  kind: "proposal" | "message";
  onDone: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const decide = async (action: "approve" | "edit" | "reject") => {
    setBusy(true);
    setErr(null);
    try {
      const body = { action, reason: action === "reject" ? reason : null, edited_text: action === "edit" ? editedText : null };
      const r = unwrap(await api.POST("/api/approvals/{aid}/decide", { params: { path: { aid: approvalId } }, body }));
      onDone(r.detail);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const issues = preview?.policy_issues ?? [];
  return (
    <section className="card approval" aria-label="Approval">
      <h3>{kind === "proposal" ? "Send this proposal?" : "Send this reply?"}</h3>
      {preview && (
        <div className="preview" data-testid="dry-run">
          <h4>Dry run: exactly what would be sent</h4>
          <dl>
            <dt>Connects</dt>
            <dd>{preview.connects_cost ?? 0} (balance {preview.balance_before ?? "?"} → {preview.balance_after ?? "?"})</dd>
            <dt>Platform rules</dt>
            <dd>{issues.length ? <span className="bad">{issues.join("; ")}</span> : <span className="good">no violations</span>}</dd>
          </dl>
          <details>
            <summary>Payload</summary>
            <pre>{JSON.stringify(preview.would_send, null, 1)}</pre>
          </details>
        </div>
      )}
      {err && <p className="bad" role="alert">{err}</p>}
      <div className="row gap">
        <button className="primary" disabled={busy} onClick={() => decide(editedText ? "edit" : "approve")} data-testid="approve">
          {editedText ? "Approve with my edits" : "Approve"}
        </button>
        <button className="ghost" disabled={busy} onClick={() => setRejecting((x) => !x)} aria-expanded={rejecting}>Reject…</button>
      </div>
      {rejecting && (
        <div className="reject">
          <label htmlFor={`reason-${approvalId}`}>Why reject? (teaches GigBid what you don't want)</label>
          <textarea id={`reason-${approvalId}`} value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
          <button className="danger" disabled={busy || !reason.trim()} onClick={() => decide("reject")} data-testid="confirm-reject">
            Reject with reason
          </button>
        </div>
      )}
      <p className="small muted">Nothing is sent until you approve. {kind === "proposal" && "Approving submits and spends the Connects shown."}</p>
    </section>
  );
}
