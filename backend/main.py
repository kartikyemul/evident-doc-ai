"""Evident API — v0.1: upload a PDF, get a summary, search for evidence."""
import re
import uuid
from collections import Counter

import fitz  # PyMuPDF
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Evident API")
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


@app.get("/api/search")
def search(doc_id: str, q: str, limit: int = 8):
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found. Upload it again.")
    q = q.strip()
    if not q:
        return {"terms": [], "results": []}
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
    return {"terms": terms + ([q] if len(terms) > 1 else []), "results": results[:limit]}
