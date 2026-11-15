import { useId, useState } from "react";

export type Claim = {
  claim: string;
  label: string;
  score: number;
  evidence_ids: string[];
  reasons: string[];
  evidence?: { evidence_id: string; title?: string | null; snippet?: string }[];
};

/** A claim sentence that reveals the evidence behind it on hover AND keyboard focus. */
export default function EvidenceHover({ claim }: { claim: Claim }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className={`claim ${claim.label}`}
      tabIndex={0}
      aria-describedby={id}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      data-testid="claim"
    >
      {claim.claim}{" "}
      <span id={id} role="tooltip" className={`tip ${open ? "show" : ""}`}>
        <strong>{claim.label.replace("_", " ")}</strong> (similarity {claim.score.toFixed(2)})
        {(claim.evidence ?? claim.evidence_ids.map((e) => ({ evidence_id: e, title: null, snippet: "" }))).map((e) => (
          <span key={e.evidence_id} className="ev">
            <code>{e.evidence_id}</code> {e.title ? `· ${e.title}` : ""}
            {e.snippet ? <q>{e.snippet.slice(0, 260)}…</q> : null}
          </span>
        ))}
        {claim.reasons.length ? <em>{claim.reasons.join("; ")}</em> : null}
      </span>
    </span>
  );
}
