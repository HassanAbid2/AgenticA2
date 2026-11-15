import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ApprovalPanel from "../../../components/ApprovalPanel";
import EvidenceHover, { type Claim } from "../../../components/EvidenceHover";
import { ErrorBox, Loading, RiskBadges } from "../../../components/ui";
import { api, unwrap } from "../../../lib/api/client";
import { money, pct, useLoad } from "../../../lib/hooks";

const norm = (s: string) => s.replace(/[   ]/g, " ").replace(/[‐-—]/g, "-").replace(/\s*\[\d+\]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
const sentences = (t: string) => t.split(/(?<=[.!?])\s+/).filter(Boolean);

export default function StudioPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const aid = Number(id);
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/approvals/{aid}", { params: { path: { aid } } })), [aid]);
  const p = (data?.payload ?? {}) as Record<string, any>;
  const [text, setText] = useState("");
  const [para, setPara] = useState(0);
  const [instr, setInstr] = useState("");
  const [regen, setRegen] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => {
    if (p.final_text) setText(p.final_text);
  }, [p.final_text]);
  const claims = useMemo(() => {
    const m = new Map<string, Claim>();
    (p.claims ?? []).forEach((c: Claim) => m.set(norm(c.claim), c));
    return m;
  }, [p.claims]);
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (loading || !data) return <Loading what="Loading draft" />;
  const edited = text.trim() !== (p.final_text ?? "").trim() ? text : null;
  const critique = (p.critiques ?? []).slice(-1)[0] ?? {};
  const violations = p.compliance?.violations ?? [];
  const paragraphs = text.split(/\n\s*\n/).filter((x) => x.trim());
  const regenerate = async () => {
    setRegen("Rewriting paragraph…");
    try {
      const r = unwrap(await api.POST("/api/approvals/{aid}/regenerate", { params: { path: { aid } }, body: { paragraph_index: para, text, instruction: instr } }));
      setText(r.text);
      setRegen(r.violations.length ? `Rewritten; compliance fixed ${r.violations.length} issue(s).` : "Rewritten and re-verified.");
    } catch (e) {
      setRegen((e as Error).message);
    }
  };
  if (data.status !== "pending" || done) {
    return (
      <section>
        <p><Link to="/inbox">← Inbox</Link></p>
        <div className="card" role="status" data-testid="decision-done">
          <h2>Decision recorded</h2>
          <p>{done ? `${done}.` : `This approval is ${data.status}.`} Track it in the <Link to="/pipeline">pipeline</Link>.</p>
          <button className="ghost" onClick={() => nav("/inbox")}>Back to inbox</button>
        </div>
      </section>
    );
  }
  return (
    <section>
      <p><Link to={`/jobs/${p.job?.job_id}`}>← {p.job?.title}</Link></p>
      <h1>Proposal studio</h1>
      <div className="row wrap gap small">
        <span>Bid {money(p.price?.amount, p.price?.unit)}</span>
        <span>{p.preview?.connects_cost ?? p.job?.connects_cost} Connects</span>
        <RiskBadges flags={p.risk_report?.flags ?? []} score={p.risk_report?.score} />
        <span>Fit {pct(p.fit_report?.score)}</span>
        <span className="badge">strategy: {p.strategy}</span>
        <span className="muted">unsupported claims {pct(p.unsupported_rate_before)} → {pct(p.unsupported_rate_after)}</span>
      </div>
      <div className="studio">
        <div className="stack">
          <article className="card">
            <h2>Grounded draft <span className="muted small">(hover or focus a highlighted sentence to see its evidence)</span></h2>
            <p className="letter" data-testid="letter">
              {sentences(p.final_text ?? "").map((s: string, i: number) => {
                const c = claims.get(norm(s));
                return c ? <EvidenceHover key={i} claim={c} /> : <span key={i}>{s} </span>;
              })}
            </p>
            {p.removed_claims?.length ? (
              <details>
                <summary>{p.removed_claims.length} unsupported claim(s) removed by verification</summary>
                <ul className="small">{p.removed_claims.map((r: string, i: number) => <li key={i}><s>{r}</s></li>)}</ul>
              </details>
            ) : null}
          </article>
          <article className="card">
            <h2><label htmlFor="editor">Edit before sending</label></h2>
            <textarea id="editor" value={text} onChange={(e) => setText(e.target.value)} rows={12} data-testid="editor" />
            <div className="row gap wrap small">
              <label className="inline">Paragraph
                <select value={para} onChange={(e) => setPara(+e.target.value)}>
                  {paragraphs.map((_, i) => <option key={i} value={i}>{i + 1}</option>)}
                </select>
              </label>
              <input aria-label="Instruction for the rewrite" placeholder="e.g. mention the timeline" value={instr} onChange={(e) => setInstr(e.target.value)} />
              <button className="ghost" onClick={regenerate}>Regenerate paragraph</button>
              {regen && <span role="status">{regen}</span>}
            </div>
            {edited && <p className="small muted">Your edits will be diffed, re-checked by the Compliance Guard and used to learn your style.</p>}
            {(p.screening_questions ?? []).length > 0 && (
              <>
                <h3>Screening answers</h3>
                {(p.screening_questions as string[]).map((q, i) => (
                  <div key={i} className="qa"><strong>{q}</strong><p>{p.screening_answers?.[i] || <em className="muted">(no answer)</em>}</p></div>
                ))}
              </>
            )}
          </article>
        </div>
        <aside className="stack">
          <ApprovalPanel approvalId={aid} preview={p.preview} editedText={edited} kind="proposal" onDone={setDone} />
          <section className="card">
            <h3>Critic {critique.score != null && <span className="muted small">score {critique.score}/10</span>}</h3>
            {(critique.issues ?? []).length ? <ul className="small">{critique.issues.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul> : <p className="small good">No open issues.</p>}
            <p className="small muted">{(p.critiques ?? []).length - 1 > 0 ? `${(p.critiques ?? []).length - 1} revision(s) requested` : "Approved on first pass"}</p>
          </section>
          <section className="card">
            <h3>Compliance <span className="badge">{p.compliance?.status}</span></h3>
            {violations.length ? (
              <ul className="small">{violations.map((v: any, i: number) => <li key={i}><code>{v.rule_id}</code> {v.message} {v.excerpt && <q>{v.excerpt}</q>}</li>)}</ul>
            ) : <p className="small good">No policy issues.</p>}
          </section>
          <section className="card">
            <h3>Price rationale</h3>
            <ul className="small">{(p.price?.rationale ?? []).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          </section>
        </aside>
      </div>
    </section>
  );
}
