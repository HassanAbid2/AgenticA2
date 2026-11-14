import { useState } from "react";
import ApprovalPanel from "../../components/ApprovalPanel";
import { Empty, ErrorBox, Loading } from "../../components/ui";
import { api, unwrap, type ThreadOut } from "../../lib/api/client";
import { useLoad, useSSE } from "../../lib/hooks";

export default function MessagesPage() {
  const { data, error, loading, reload } = useLoad(async () => unwrap(await api.GET("/api/threads")));
  useSSE("/api/stream/inbox", () => void reload(true), ["update"]);
  const [sel, setSel] = useState<number | null>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [note, setNote] = useState<string | null>(null);
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (loading || !data) return <Loading what="Loading conversations" />;
  if (!data.length) return <section><h1>Messages</h1><Empty title="No client conversations yet"><p>When a client replies to a proposal, GigBid drafts a response here for you to approve.</p></Empty></section>;
  const t: ThreadOut = data.find((x) => x.id === sel) ?? data[0];
  const ap = t.approval;
  const pay = (ap?.payload ?? {}) as Record<string, any>;
  const draft = async () => {
    const r = unwrap(await api.POST("/api/threads/{marketplace_thread_id}/draft", { params: { path: { marketplace_thread_id: t.marketplace_thread_id } } }));
    setNote(r.detail);
  };
  return (
    <section>
      <h1>Messages</h1>
      <div className="msgs">
        <nav aria-label="Conversations" className="threads">
          {data.map((x) => (
            <button key={x.id} className={`thread ${x.id === t.id ? "on" : ""}`} onClick={() => setSel(x.id)} aria-current={x.id === t.id}>
              <strong>{x.title}</strong>
              <span className="small muted">{x.intent ?? x.status}{x.approval ? " · reply ready" : ""}</span>
            </button>
          ))}
        </nav>
        <div className="stack">
          <article className="card">
            <h2>{t.title}</h2>
            <ol className="chat">
              {t.messages.map((m: any) => (
                <li key={m.message_id} className={m.sender}><span className="small muted">{m.sender}</span><p>{m.text}</p></li>
              ))}
            </ol>
            {!ap && <button className="ghost" onClick={draft}>Draft a reply</button>}
            {note && <p className="small muted" role="status">{note}</p>}
          </article>
          {ap && (
            <article className="card">
              <h3>Suggested reply <span className="badge">{pay.intent?.intent}</span></h3>
              {pay.intent?.intent === "scam_signal" && <p className="banner warn small">This message looks like a scam signal (off-platform contact or payment). The suggested reply keeps things on the platform.</p>}
              {pay.intent?.intent === "injection" && <p className="banner warn small">The client message contained instructions aimed at AI tools; they were ignored.</p>}
              <label htmlFor={`reply-${ap.id}`} className="small">Reply (edit freely)</label>
              <textarea id={`reply-${ap.id}`} rows={5} value={edits[ap.id] ?? pay.reply?.text ?? ""} onChange={(e) => setEdits({ ...edits, [ap.id]: e.target.value })} />
              {pay.slots?.length ? <p className="small">Proposed interview slots: {pay.slots.map((s: any) => s.label).join(" · ")} (tentative holds are placed on approval)</p> : null}
              <ApprovalPanel approvalId={ap.id} preview={pay.preview} kind="message"
                editedText={edits[ap.id] && edits[ap.id] !== pay.reply?.text ? edits[ap.id] : null} onDone={(m) => { setNote(m); void reload(true); }} />
            </article>
          )}
        </div>
      </div>
    </section>
  );
}
