# Evident

Ask your documents. See where the answer came from.

v0.1: upload a PDF, get an extractive summary, search for evidence with page numbers.

## Run locally
**Backend** (Python 3.10+)
```
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload        # http://localhost:8000/docs
```
**Frontend** (Node 18+), in a second terminal
```
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

## Roadmap
1. PDF reader + summary + keyword search (this)
2. Semantic search (embeddings)
3. Local RAG with an open-source LLM
4. Evaluation set
5. Deployment
