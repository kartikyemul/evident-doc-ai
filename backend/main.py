"""Evident API — v0.1: upload a PDF, get a summary, search for evidence."""
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
    "she that the their them they this to was we were what when where which who will with you your".split()
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
    DOCS[doc_id] = {"name": file.filename, "pages": pages}
    return {
        "doc_id": doc_id,
        "name": file.filename,
        "readable_pages": len(pages),
        "characters": sum(len(p["text"]) for p in pages),
        "summary": summarize(pages),
    }


def find_passages(doc: dict, q: str, limit: int):
    terms = list(dict.fromkeys(words(q))) or [q.lower()]
    results = []
    for p in doc["pages"]:
        for chunk in chunks(p["text"]):
            low = chunk.lower()
            hits = sum(1 for t in terms if t in low)
            exact = q.lower() in low
            if hits or exact:
                results.append(
                    {
                        "page": p["page"],
                        "text": chunk[:700],
                        "match": "Exact phrase" if exact else "Keyword match",
                        "score": hits + (10 if exact else 0),
                    }
                )
    results.sort(key=lambda r: r["score"], reverse=True)
    return terms, results[:limit]


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

    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise HTTPException(500, "GROQ_API_KEY is missing. Add it to backend/.env and restart the server.")

    context = "\n\n".join(
        f"[Passage {i} | page {r['page']}]\n{r['text']}" for i, r in enumerate(passages, 1)
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {q}"},
    ]

    client = Groq(api_key=key)
    last_error = None
    for model in model_chain():
        extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
        try:
            reply = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_completion_tokens=1500,
                **extra,
            )
            text = (reply.choices[0].message.content or "").strip()
            if text:
                return {"answer": text, "sources": passages, "terms": terms, "model": model}
            last_error = "empty answer"
        except Exception as error:
            last_error = error
    raise HTTPException(502, f"The AI service failed on every model. Last error: {last_error}")
