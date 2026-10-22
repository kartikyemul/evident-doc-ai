# Evident

Ask your PDFs. See the proof.

**v0.2** — upload a PDF, get a summary, search the text, and ask questions. Answers come from the most relevant passages and show the pages they came from.

## Stack
React + Vite · FastAPI · PyMuPDF · Groq API (OpenAI GPT-OSS models, with automatic fallback)

## Run locally
**Backend** (Python 3.10+)
```
cd backend
pip install -r requirements.txt
copy .env.example .env        # then paste your Groq key into .env
python -m uvicorn main:app --reload
```
**Frontend** (Node 18+), second terminal
```
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

## How Q&A works
1. PDF text is kept per page.
2. A question finds the best-matching passages (keyword scoring).
3. Only those passages go to the model, which must answer from them and cite pages.
4. The UI shows the answer plus the evidence passages.

## Roadmap
- Semantic search (embeddings)
- Tests and evaluation set
- Deployment
