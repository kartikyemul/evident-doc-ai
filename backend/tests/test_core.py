import time

import fitz
import pytest
from fastapi.testclient import TestClient

import main

SAMPLE = [
    "Refund Policy. Customers may request a refund within thirty days of purchase. "
    "Policies differ by region and product.",
    "Shipping takes five business days. Contact support for any shipping problems with your order.",
]


def make_pdf(pages):
    pdf = fitz.open()
    for text in pages:
        page = pdf.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 780), text, fontsize=11)
    data = pdf.tobytes()
    pdf.close()
    return data


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    main.DOCS.clear()
    main.HITS.clear()
    main.USAGE.update(day="", tokens=0, calls=0, cooldown_until=0.0)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")


@pytest.fixture
def client():
    return TestClient(main.app)


def upload(client, pages=SAMPLE, name="sample.pdf", data=None):
    data = data if data is not None else make_pdf(pages)
    return client.post("/api/upload", files={"file": (name, data, "application/pdf")})


# ---- pure logic ----
def test_stemmer_matches_word_forms():
    assert main.stem("policies") == main.stem("policy")
    assert main.stem("required") == main.stem("require")


def test_summary_keeps_reading_order():
    pages = [{"page": i, "text": f"Sentence number {i} talks about budgets and research funding today."} for i in range(1, 6)]
    out = main.summarize(pages, 3)
    assert len(out) == 3
    assert [s["page"] for s in out] == sorted(s["page"] for s in out)


def test_rare_words_rank_first():
    pages = [{"page": 1, "text": "Refund rules apply to every purchase made online."},
             {"page": 2, "text": "Shipping rules apply to every order sent abroad."}]
    items, idf = main.index_doc(pages)
    _, results = main.find_passages({"items": items, "idf": idf}, "refund rules", 5)
    assert results[0]["page"] == 1


# ---- API ----
def test_upload_search_and_page(client):
    r = upload(client)
    assert r.status_code == 200
    body = r.json()
    assert body["readable_pages"] == 2
    found = client.get("/api/search", params={"doc_id": body["doc_id"], "q": "refund"}).json()
    assert found["results"][0]["page"] == 1
    page = client.get("/api/page", params={"doc_id": body["doc_id"], "n": 2}).json()
    assert "Shipping" in page["text"]


def test_rejects_wrong_files(client):
    assert upload(client, name="notes.txt", data=b"hello").status_code == 400
    assert upload(client, name="fake.pdf", data=b"hello world").status_code == 400


def test_blank_pdf_gives_clear_error(client):
    r = upload(client, pages=[""])
    assert r.status_code == 422
    assert "scanned" in r.json()["detail"].lower()


def test_unknown_document_is_404(client):
    assert client.get("/api/search", params={"doc_id": "nope", "q": "x"}).status_code == 404


def test_ask_is_cached(client, monkeypatch):
    calls = []

    def fake_llm(messages, max_tokens=1500, temperature=0.2):
        calls.append(1)
        return "Refunds take thirty days. [p. 1]", "test-model"

    monkeypatch.setattr(main, "call_llm", fake_llm)
    doc_id = upload(client).json()["doc_id"]
    for _ in range(2):
        r = client.get("/api/ask", params={"doc_id": doc_id, "q": "How long do refunds take?"})
        assert r.status_code == 200
    assert len(calls) == 1


def test_ask_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "call_llm", lambda *a, **k: ("ok", "test-model"))
    monkeypatch.setattr(main, "ASKS_PER_HOUR", 2)
    doc_id = upload(client).json()["doc_id"]
    codes = [client.get("/api/ask", params={"doc_id": doc_id, "q": f"question {i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_daily_budget_blocks_ai_but_not_search(client):
    doc_id = upload(client).json()["doc_id"]
    main.USAGE.update(day=time.strftime("%Y-%m-%d", time.gmtime()), tokens=main.DAILY_TOKEN_BUDGET)
    assert client.get("/api/usage").json()["level"] == "blocked"
    assert client.get("/api/ask", params={"doc_id": doc_id, "q": "refund"}).status_code == 429
    assert client.get("/api/search", params={"doc_id": doc_id, "q": "refund"}).status_code == 200


def test_missing_key_is_reported(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    doc_id = upload(client).json()["doc_id"]
    r = client.get("/api/ask", params={"doc_id": doc_id, "q": "refund"})
    assert r.status_code == 500 and "GROQ_API_KEY" in r.json()["detail"]
