import { useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL ?? ""; // empty = same origin (dev proxy)
const IDEAS = ["What is this document about?", "What are the key points?", "Any important numbers or dates?"];

function Highlight({ text, terms = [] }) {
  const safe = terms.filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!safe.length) return text;
  return text.split(new RegExp(`(${safe.join("|")})`, "gi")).map((p, i) =>
    i % 2 ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>
  );
}

async function api(path, options) {
  const res = await fetch(`${API}${path}`, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
}

export default function App() {
  const [doc, setDoc] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [tab, setTab] = useState("ask");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [history, setHistory] = useState([]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState(null);
  const inputRef = useRef(null);

  function reset() {
    setDoc(null); setFound(null); setHistory([]); setQuestion(""); setQuery(""); setError("");
  }

  async function upload(file) {
    if (!file) return;
    reset();
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      setDoc(await api("/api/upload", { method: "POST", body }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function ask(text) {
    const q = text.trim();
    if (!q || !doc || asking) return;
    setError("");
    setAsking(true);
    try {
      const data = await api(`/api/ask?doc_id=${doc.doc_id}&q=${encodeURIComponent(q)}`);
      setHistory((h) => [{ q, ...data }, ...h]);
      setQuestion("");
    } catch (e) {
      setError(e.message);
    } finally {
      setAsking(false);
    }
  }

  async function search(e) {
    e.preventDefault();
    if (!query.trim() || !doc) return;
    setError("");
    try {
      setFound(await api(`/api/search?doc_id=${doc.doc_id}&q=${encodeURIComponent(query)}`));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="shell">
      <header className="top">
        <span className="logo">Evident</span>
        <p>Ask your PDFs. <b>See the proof.</b></p>
      </header>

      {error && <div className="error" role="alert">⚠ {error}</div>}

      {!doc ? (
        <div
          className={`drop ${drag ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]); }}
        >
          <div className="drop-icon" aria-hidden="true">PDF</div>
          <h2>{busy ? "Reading your PDF…" : "Drop a PDF here"}</h2>
          <p>Text-based PDFs up to 20 MB. Scanned pages aren’t supported yet.</p>
          <button className="btn pink" onClick={() => inputRef.current.click()} disabled={busy}>Choose a file</button>
          <input ref={inputRef} type="file" accept="application/pdf" hidden onChange={(e) => upload(e.target.files[0])} />
        </div>
      ) : (
        <main className="grid">
          <section className="card">
            <div className="tag blue">Your document</div>
            <h2 className="doc-name">{doc.name}</h2>
            <div className="stats">
              <span className="stat">{doc.readable_pages} pages</span>
              <span className="stat">{doc.characters.toLocaleString()} characters</span>
            </div>
            <button className="btn ghost small" onClick={reset}>Use another PDF</button>

            <h3>Summary</h3>
            <ol className="summary">
              {doc.summary.map((s, i) => (
                <li key={i}>
                  <span className="num">{i + 1}</span>
                  <div>
                    <p>{s.text}</p>
                    <span className="chip">p. {s.page}</span>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section className="card">
            <div className="tabs" role="tablist">
              <button role="tab" aria-selected={tab === "ask"} className={tab === "ask" ? "on" : ""} onClick={() => setTab("ask")}>Ask AI</button>
              <button role="tab" aria-selected={tab === "search"} className={tab === "search" ? "on" : ""} onClick={() => setTab("search")}>Find text</button>
            </div>

            {tab === "ask" ? (
              <>
                <form className="row" onSubmit={(e) => { e.preventDefault(); ask(question); }}>
                  <input value={question} onChange={(e) => setQuestion(e.target.value)}
                         placeholder="Ask anything about this PDF…" aria-label="Question" />
                  <button className="btn yellow" type="submit" disabled={asking}>{asking ? "Thinking…" : "Ask"}</button>
                </form>
                <div className="ideas">
                  {IDEAS.map((i) => (
                    <button key={i} className="idea" onClick={() => ask(i)} disabled={asking}>{i}</button>
                  ))}
                </div>

                {asking && <div className="skeleton" aria-label="Loading answer"><i /><i /><i /></div>}

                {history.map((h, n) => (
                  <article className="qa" key={n}>
                    <p className="q">{h.q}</p>
                    <div className="answer">
                      <p>{h.answer}</p>
                      <span className="badge">{h.model}</span>
                    </div>
                    {h.sources.length > 0 && (
                      <details>
                        <summary>Evidence ({h.sources.length} passages)</summary>
                        {h.sources.map((r, i) => (
                          <div className="src" key={i}>
                            <span className="chip">p. {r.page}</span>
                            <p><Highlight text={r.text} terms={h.terms} /></p>
                          </div>
                        ))}
                      </details>
                    )}
                  </article>
                ))}
                {!asking && history.length === 0 && <p className="empty">Answers appear here with the pages they came from.</p>}
              </>
            ) : (
              <>
                <form className="row" onSubmit={search}>
                  <input value={query} onChange={(e) => setQuery(e.target.value)}
                         placeholder="A word or phrase from your PDF" aria-label="Search text" />
                  <button className="btn mint" type="submit">Search</button>
                </form>
                {found && found.results.length === 0 && <p className="empty">No passage matches “{query}”.</p>}
                {found && found.results.map((r, i) => (
                  <div className="src boxed" key={i}>
                    <div className="src-head">
                      <span className="chip">p. {r.page}</span>
                      <span className="kind">{r.match}</span>
                    </div>
                    <p><Highlight text={r.text} terms={found.terms} /></p>
                  </div>
                ))}
                {!found && <p className="empty">Search shows the exact passage and its page.</p>}
              </>
            )}
          </section>
        </main>
      )}
      <footer className="foot">Evident v0.2 · React + FastAPI + Groq</footer>
    </div>
  );
}
