# CV Tailoring Platform

Paste a job description → the app researches the employer, scores your match,
rewrites your CV bullets (formatting preserved), and drafts a cover letter —
downloadable as DOCX. Multi-tenant, invite-only. Spec: `CV_Tailoring_Platform_PRD_v1.1.docx`.

## Structure

```
apps/api    FastAPI backend (deploys to Modal)
apps/web    Next.js 14 frontend (deploys to Vercel)
supabase/   schema.sql — tables, RLS policies, storage buckets
spikes/     de-risk scripts (DOCX round-trip)
```

## Setup

### 1. Supabase
1. Create a project at supabase.com
2. Run `supabase/schema.sql` in the SQL editor (tables + RLS + buckets)
3. Auth → disable public signups (invite-only); invite users from the dashboard
4. Copy the URL, anon key, and JWT secret

### 2. Backend (local)
```bash
cd apps/api
py -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # fill in values
uvicorn app.main:app --reload
```

### 3. Frontend (local)
```bash
cd apps/web
npm install
copy .env.local.example .env.local   # fill in values
npm run dev
```

## Deploy

### Backend → Modal
```bash
pip install modal && modal setup
modal secret create cv-tailor-secrets SUPABASE_URL=... SUPABASE_ANON_KEY=... \
  OPENAI_API_KEY=... CORS_ORIGINS=https://<app>.vercel.app
cd apps/api && modal deploy modal_app.py    # prints the public URL
```

### Frontend → Vercel
Import the repo in Vercel, set root directory to `apps/web`, add the three
`NEXT_PUBLIC_*` env vars (point `NEXT_PUBLIC_API_URL` at the Modal URL).

## Telegram bot (optional)

1. Create a bot with **@BotFather** → copy the token
2. Add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` (any random string), and
   `TELEGRAM_BOT_USERNAME` to the Modal secret / `.env`
3. Register the webhook (after deploying):
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<API_URL>/telegram/webhook&secret_token=<WEBHOOK_SECRET>"
   ```
4. In the web app: Profile → **Connect Telegram** → send the code to the bot

Then: paste a JD to the bot (first line `Company: <name>` enables employer
research) → it runs the full pipeline and replies with scores, gaps, insights,
and your tailored CV as a DOCX. Web-run analyses also ping the linked chat.

## Pipeline (async)

`POST /analyse` → `{analysis_id, status: pending}` → background worker advances
`researching → analysing → writing → done`; the UI polls `GET /analyses/{id}`.

Stages: employer research (web search, cited) → match & gaps → ATS keyword
scoring → bullet rewrite (strict JSON schema, counts preserved) → cover letter.

## Security model

- RLS on every table (`user_id = auth.uid()`); storage policies per-user prefix
- The API passes the caller's Supabase JWT through to Postgres — the
  service-role key is never used on request paths
