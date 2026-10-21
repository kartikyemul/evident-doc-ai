import { useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL ?? ""; // empty = same origin (dev proxy)

function Highlight({ text, terms }) {
  const safe = terms.filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!safe.length) return text;
  const parts = text.split(new RegExp(`(${safe.join("|")})`, "gi"));
  return parts.map((p, i) =>
    i % 2 ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>
  );
}

export default function App() {
  const [doc, setDoc] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState(null); // { terms, results }
  const inputRef = useRef(null);

  async function upload(file) {
    if (!file) return;
    setError("");
    setBusy(true);
    setFound(null);
    setQuery("");
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(`${API}/api/upload`, { method: "POST", body });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed.");
      setDoc(data);
    } catch (e) {
      setDoc(null);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function search(e) {
    e.preventDefault();
    if (!query.trim() || !doc) return;
    setError("");
    try {
      const url = `${API}/api/search?doc_id=${doc.doc_id}&q=${encodeURIComponent(query)}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Search failed.");
      setFound(data);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="shell">
      <header className="top">
        <h1>Evident</h1>
        <p>Ask your documents. See where the answer came from.</p>
      </header>

      {error && <div className="error" role="alert">{error}</div>}

      {!doc ? (
        <div
          className={`drop ${drag ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]); }}
        >
          <p className="drop-title">{busy ? "Reading your PDF…" : "Drop a PDF here"}</p>
          <p className="drop-sub">Text-based PDFs up to 20 MB. Scanned pages aren’t supported yet.</p>
          <button onClick={() => inputRef.current.click()} disabled={busy}>Choose a file</button>
          <input ref={inputRef} type="file" accept="application/pdf" hidden
                 onChange={(e) => upload(e.target.files[0])} />
        </div>
      ) : (
        <main className="grid">
          <section className="panel">
            <div className="doc-head">
              <div>
                <h2>{doc.name}</h2>
                <p className="meta">{doc.readable_pages} readable pages, {doc.characters.toLocaleString()} characters</p>
              </div>
              <button className="ghost" onClick={() => { setDoc(null); setFound(null); }}>Use another PDF</button>
            </div>
            <h3>Summary</h3>
            <ol className="summary">
              {doc.summary.map((s, i) => (
                <li key={i}>
                  <p>{s.text}</p>
                  <span className="page">p. {s.page}</span>
                </li>
              ))}
            </ol>
          </section>

          <section className="panel">
            <form onSubmit={search} className="ask">
              <label htmlFor="q">Find evidence</label>
              <div className="row">
                <input id="q" value={query} onChange={(e) => setQuery(e.target.value)}
                       placeholder="A word or phrase from your document" />
                <button type="submit">Search</button>
              </div>
            </form>

            {found && found.results.length === 0 && (
              <p className="empty">No passage matches “{query}”. Try a different word.</p>
            )}
            {found && found.results.map((r, i) => (
              <article className="hit" key={i}>
                <div className="hit-head">
                  <span className="page">p. {r.page}</span>
                  <span className="kind">{r.match}</span>
                </div>
                <p><Highlight text={r.text} terms={found.terms} /></p>
              </article>
            ))}
            {!found && <p className="empty">Search results show the exact passage and its page.</p>}
          </section>
        </main>
      )}
    </div>
  );
}
