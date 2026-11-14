import type { ReactNode } from "react";

export const Loading = ({ what = "Loading" }: { what?: string }) => (
  <p className="muted" role="status" aria-live="polite">{what}…</p>
);

export const ErrorBox = ({ error, retry }: { error: string; retry?: () => void }) => (
  <div className="banner error" role="alert">
    {error} {retry && <button className="ghost" onClick={retry}>Retry</button>}
  </div>
);

export const Empty = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="empty">
    <h3>{title}</h3>
    {children}
  </div>
);

const RISK_LABEL: Record<string, string> = {
  scam: "Scam", unpaid_work: "Unpaid work", off_platform_contact: "Off-platform contact", off_platform_payment: "Off-platform pay",
  personal_info_request: "Asks personal data", overpayment_scheme: "Overpayment scheme", prompt_injection: "Injected instructions",
  low_budget: "Low budget", unverified_payment: "Unverified payment", new_client: "New client", poor_client_history: "Poor history",
  duplicate: "Duplicate",
};

export function RiskBadges({ flags, score }: { flags: string[]; score?: number | null }) {
  const level = score == null ? "na" : score >= 0.6 ? "high" : score >= 0.3 ? "mid" : "low";
  return (
    <span className="badges">
      <span className={`badge risk-${level}`} title="Risk score">{score == null ? "risk ?" : `risk ${Math.round(score * 100)}`}</span>
      {flags.slice(0, 4).map((f) => (
        <span key={f} className={`badge ${f === "scam" || f === "prompt_injection" ? "risk-high" : "flag"}`}>{RISK_LABEL[f] ?? f}</span>
      ))}
    </span>
  );
}

export function ActionBadge({ action, status }: { action?: string | null; status: string }) {
  const s = status === "awaiting_approval" ? "Awaiting your approval" : status === "marketplace_unavailable" ? "Queued (marketplace down)"
    : status === "needs_attention" ? "Needs attention" : status === "dead_letter" ? "Failed" : action ? `Recommend: ${action}` : status;
  const cls = status === "awaiting_approval" ? "act-approve" : action === "bid" ? "act-bid" : action === "skip" ? "act-skip" : "act-other";
  return <span className={`badge ${cls}`}>{s}</span>;
}

export function Meter({ value, label }: { value?: number | null; label: string }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  return (
    <span className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)} aria-label={label}>
      <span style={{ width: `${v * 100}%` }} />
      <em>{value == null ? "-" : Math.round(v * 100)}</em>
    </span>
  );
}
