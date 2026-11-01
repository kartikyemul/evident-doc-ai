# Deploying Evident

Frontend on **Vercel**, backend on **Render** (both free). Your Groq key lives only in Render's settings.

## 1. Backend on Render
1. Push the repo to GitHub.
2. render.com → **New → Blueprint** → pick this repo. Render reads `render.yaml`.
3. When asked, set `GROQ_API_KEY` (your key). Leave `ALLOWED_ORIGINS` blank for now.
4. Deploy. Open `https://YOUR-SERVICE.onrender.com/api/health`. You should see `{"ok": true}`.

## 2. Frontend on Vercel
1. vercel.com → **Add New → Project** → import this repo.
2. **Root Directory:** `frontend`. Framework: Vite (auto-detected).
3. **Environment Variable:** `VITE_API_URL` = your Render URL, no trailing slash.
4. Deploy. You get a URL like `https://evident-doc-ai.vercel.app`.

## 3. Connect them
In Render → your service → Environment, set `ALLOWED_ORIGINS` to your Vercel URL
(comma-separate more than one). Save; Render redeploys. Open the Vercel site and upload a PDF.

## Usage safety (Groq)
The backend caps usage so a free key lasts:
- Daily token budget (`DAILY_TOKEN_BUDGET`); at 80% the site warns, at 100% AI pauses (search still works).
- Per-visitor hourly limits for uploads, summaries and questions.
- Small prompts, cached answers, at most two model attempts per request, 60 s cooldown on provider rate limits.
Tune these in Render's Environment tab. Also set a spend/usage limit in the Groq console.

## Good to know
- Render's free tier sleeps after ~15 min idle; the first request takes up to a minute.
- Uploaded PDFs live in server memory only and are deleted after `DOC_TTL_MIN` minutes or on restart.
- Never commit `.env`. If a key leaks, delete it in the Groq console and make a new one.
