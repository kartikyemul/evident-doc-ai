"""Evident API — v0.1: upload a PDF, get a summary, search for evidence."""
import json
import math
import os
import re
import uuid
from collections import Counter

import fitz  # PyMuPDF
from dotenv import load_dotenv
from groq import Groq
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # reads backend/.env

app = FastAPI(title="Evident")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # add your deployed frontend URL later
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BYTES = 20 * 1024 * 1024
DOCS: dict[str, dict] = {}  # in-memory for now; a database comes later

STOP = set(
    "a an and are as at be but by for from has have he her his i in is it its of on or "
    "she that the their them they this to was we were what when where which who will with you your how does do did can could should would about there these those than then so if not no also".split()
)


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z0-9']+", text.lower()) if w not in STOP]


def extract_pages(data: bytes) -> list[dict]:
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(400, "Could not read this file. Is it a valid PDF?")
    with pdf:
        if pdf.is_encrypted:
            raise HTTPException(400, "This PDF is password-protected.")
        pages = [
            {"page": i, "text": t}
            for i, p in enumerate(pdf, start=1)
            if (t := p.get_text("text").strip())
        ]
    if not pages:
        raise HTTPException(422, "No selectable text found. This may be a scanned PDF (OCR comes later).")
    return pages


def sentences(pages: list[dict]) -> list[dict]:
    out = []
    for p in pages:
        flat = re.sub(r"\s+", " ", p["text"])
        for s in re.split(r"(?<=[.!?])\s+", flat):
            if len(s.split()) >= 6:
                out.append({"page": p["page"], "text": s.strip()})
    return out


def summarize(pages: list[dict], n: int = 5) -> list[dict]:
    sents = sentences(pages)
    if len(sents) <= n:
        return sents
    freq = Counter(w for s in sents for w in words(s["text"]))
    def score(s):
        ws = words(s["text"])
        return sum(freq[w] for w in ws) / (len(ws) ** 0.7 or 1)
    top = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)[:n]
    return [sents[i] for i in sorted(top)]


def chunks(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if len(para) > 800:  # split long blocks into ~4-sentence groups
            sents = re.split(r"(?<=[.!?])\s+", para)
            out += [" ".join(sents[i : i + 4]) for i in range(0, len(sents), 4)]
        elif para:
            out.append(para)
    return out


def stem(w: str) -> str:
    """Very simple stemmer so 'policies', 'policy' and 'policys' match each other."""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    else:
        for suf in ("ing", "ed", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf) and not w.endswith("ss"):
                w = w[: -len(suf)]
                break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def stems(text: str) -> set[str]:
    return {stem(w) for w in words(text)}


def index_doc(pages: list[dict]):
    """Split pages into chunks once, and weight rare words higher (IDF)."""
    items = [
        {"page": p["page"], "text": c, "stems": stems(c)}
        for p in pages
        for c in chunks(p["text"])
    ]
    df = Counter(st for it in items for st in it["stems"])
    idf = {st: math.log(1 + len(items) / n) for st, n in df.items()}
    return items, idf


def highlight_term(st: str) -> str:
    return st[:-1] if len(st) > 4 and st.endswith("y") else st


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "PDF is larger than 20 MB.")
    pages = extract_pages(data)
    doc_id = uuid.uuid4().hex
    items, idf = index_doc(pages)
    DOCS[doc_id] = {"name": file.filename, "pages": pages, "items": items, "idf": idf}
    return {
        "doc_id": doc_id,
        "name": file.filename,
        "readable_pages": len(pages),
        "characters": sum(len(p["text"]) for p in pages),
        "summary": summarize(pages),
    }


def find_passages(doc: dict, q: str, limit: int):
    """Rank chunks: rare query words count more, and an exact phrase gets a bonus."""
    q_words = list(dict.fromkeys(words(q))) or [q.lower()]
    q_stems = list(dict.fromkeys(stem(w) for w in q_words))
    results = []
    for it in doc["items"]:
        hit = [st for st in q_stems if st in it["stems"]]
        exact = q.lower() in it["text"].lower()
        if not hit and not exact:
            continue
        score = sum(doc["idf"].get(st, 0) for st in hit) + (5 if exact else 0)
        results.append(
            {
                "page": it["page"],
                "text": it["text"][:700],
                "match": "Exact phrase" if exact else "Keyword match",
                "score": round(score, 2),
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return [highlight_term(st) for st in q_stems], results[:limit]


@app.get("/api/search")
def search(doc_id: str, q: str, limit: int = 8):
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found. Upload it again.")
    q = q.strip()
    if not q:
        return {"terms": [], "results": []}
    terms, results = find_passages(doc, q, limit)
    return {"terms": terms + ([q] if len(terms) > 1 else []), "results": results}


SYSTEM_PROMPT = (
    "You answer questions about a document using ONLY the numbered passages provided. "
    "Cite the page after each claim, like [p. 3]. "
    "If the passages do not contain the answer, say you could not find it in the document. "
    "Keep the answer short and plain."
)

# If the chosen model is retired or rate-limited, we quietly try the next one.
FALLBACK_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]


def model_chain() -> list[str]:
    first = os.getenv("GROQ_MODEL", "").strip()
    return list(dict.fromkeys(([first] if first else []) + FALLBACK_MODELS))


def call_llm(messages: list[dict], max_tokens: int = 1500, temperature: float = 0.2) -> tuple[str, str]:
    """Ask Groq, trying each model in turn. Returns (text, model_used)."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise HTTPException(500, "GROQ_API_KEY is missing. Add it to backend/.env and restart the server.")
    client = Groq(api_key=key)
    last_error = None
    for model in model_chain():
        extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
        try:
            reply = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                **extra,
            )
            text = (reply.choices[0].message.content or "").strip()
            if text:
                return text, model
            last_error = "empty answer"
        except Exception as error:
            last_error = error
    raise HTTPException(502, f"The AI service failed on every model. Last error: {last_error}")


@app.get("/api/ask")
def ask(doc_id: str, q: str):
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found. Upload it again.")
    q = q.strip()
    if not q:
        raise HTTPException(400, "Type a question first.")

    terms, passages = find_passages(doc, q, limit=5)
    if not passages:
        # Broad questions ("what is this about?") rarely match keywords,
        # so fall back to the document's key sentences.
        passages = [
            {"page": s["page"], "text": s["text"], "match": "Key sentence", "score": 0}
            for s in summarize(doc["pages"], 6)
        ]
    context = "\n\n".join(
        f"[Passage {i} | page {r['page']}]\n{r['text']}" for i, r in enumerate(passages, 1)
    )
    text, model = call_llm(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {q}"},
        ]
    )
    return {"answer": text, "sources": passages, "terms": terms, "model": model}


SUMMARY_PROMPT = (
    "You write accurate, plain-English summaries for a complete beginner. "
    "Rules: use ONLY the excerpts given; never add outside facts; never invent names, numbers or dates; "
    "cover the beginning, middle and end of the document; one idea per point; short everyday words. "
    "Reply with JSON only, no markdown fences, in exactly this shape: "
    '{"tldr": "1-2 simple sentences: what kind of document this is and its main point", '
    '"points": [{"text": "one short, clear sentence", "pages": [1]}]} '
    "Give 4 to 6 points. Each point's pages must come from the [p. N] tags of the excerpts it is based on."
)


def condensed_text(doc: dict, budget: int = 14000) -> str:
    """Take the best sentences from EVERY page, so the summary covers the whole document."""
    pages = doc["pages"]
    if len(pages) > 60:  # very long PDFs: sample 60 pages evenly
        step = len(pages) / 60
        pages = [pages[int(k * step)] for k in range(60)]
    freq = Counter(w for sent in sentences(doc["pages"]) for w in words(sent["text"]))
    per_page = max(250, budget // len(pages))

    def score(sentence: str) -> float:
        ws = words(sentence)
        return sum(freq[w] for w in ws) / (len(ws) ** 0.7 or 1)

    opening = re.sub(r"\s+", " ", pages[0]["text"])[:500]
    lines = [f"[p. {pages[0]['page']}] (opening) {opening}"]
    for p in pages:
        flat = re.sub(r"\s+", " ", p["text"])
        sents = [x for x in re.split(r"(?<=[.!?])\s+", flat) if len(x.split()) >= 6]
        if not sents:
            continue
        picked, used = [], 0
        for x in sorted(sents, key=score, reverse=True):
            if used + len(x) <= per_page:
                picked.append(x)
                used += len(x)
        if not picked:
            picked = [sorted(sents, key=score, reverse=True)[0][:per_page]]
        ordered = [x for x in sents if x in picked]  # back to reading order
        lines.append(f"[p. {p['page']}] " + " ".join(ordered or picked))
    return "\n".join(lines)


def parse_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


@app.get("/api/summary")
def ai_summary(doc_id: str):
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found. Upload it again.")
    if "ai_summary" in doc:
        return doc["ai_summary"]

    text, model = call_llm(
        [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": f"Excerpts:\n{condensed_text(doc)}"},
        ],
        max_tokens=2000,
        temperature=0.1,
    )
    data = parse_json(text)
    points = data.get("points") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("tldr"), str) or not isinstance(points, list):
        raise HTTPException(502, "The AI returned a summary we could not read. Try again.")

    valid = {p["page"] for p in doc["pages"]}
    clean = []
    for pt in points[:6]:
        if isinstance(pt, dict) and isinstance(pt.get("text"), str):
            pages = [n for n in pt.get("pages", []) if isinstance(n, int) and n in valid]
            clean.append({"text": pt["text"], "pages": sorted(set(pages))})
    doc["ai_summary"] = {"tldr": data["tldr"], "points": clean, "model": model}
    return doc["ai_summary"]
