# CV Tailor

**Tailor your CV and cover letter to every job — in minutes, not hours.**

CV Tailor is a personal web app that takes a job description, researches the
employer, and rewrites your CV to match the role — while keeping your original
document's formatting exactly as it was. It also drafts a matching cover letter
and tracks where each of your applications stands.

---

## Why it exists

Applying for jobs well is repetitive and slow. Every role wants slightly
different wording, and a generic CV gets lost. Doing it properly by hand takes
45–90 minutes per application. CV Tailor gets that down to a few minutes of
*review* — the writing is done for you, and you stay in control of every word.

## What it does

- **Reads the job description** and scores how well you match, with an honest
  list of gaps.
- **Researches the employer** on the web and surfaces non-obvious things worth
  knowing — recent news, culture signals, interview process — with sources.
- **Rewrites your CV bullets** to fit the role, using only facts from your real
  CV, and preserving your document's exact formatting.
- **Keeps your links** — pulls the hyperlinks out of your CV (LinkedIn, GitHub,
  portfolio, project demos) and re-embeds them as clickable links in the tailored
  CV, so a bullet rewrite can never drop them. Contact links can be imported into
  your profile in one click.
- **Checks ATS keywords** — the terms an applicant-tracking system scans for —
  and works the missing ones in naturally.
- **Drafts a cover letter** tailored to the company and the role.
- **Lets you review and edit** the rewritten bullets before anything is
  finalised — nothing is submitted without your approval.
- **Exports** ready-to-send DOCX and PDF files.
- **Tracks your applications** — applied, interviewing, offer, rejected.
- **Works from Telegram too** — send a job description to a bot and get your
  tailored CV back in chat.

## How it works (the short version)

```
You  →  paste a job description
          │
          ▼
   A team of AI "agents" runs in order:
     1. Research the company (with web search)
     2. Score your match + find gaps
     3. Check ATS keywords
     4. Rewrite your bullets  →  you review & approve
     5. Write the cover letter
          │
          ▼
You  →  download your tailored CV + cover letter
```

Every step is shown live while it runs, and every AI call is logged so you can
see exactly what happened (and what it cost).

## Built with

- **Web app:** Next.js, React, TypeScript, Tailwind CSS
- **Backend:** Python, FastAPI
- **Database & login:** Supabase
- **AI:** OpenAI-compatible models, with live web search
- **Documents:** python-docx, WeasyPrint, LibreOffice
- **Hosting:** Vercel (web), Modal (backend)

## Screenshots

> _Placeholder — add screenshots here._

| Dashboard | Analyser | Review |
|-----------|----------|--------|
| _(coming soon)_ | _(coming soon)_ | _(coming soon)_ |

## Run it locally

You'll need a Supabase project, an OpenAI-compatible API key, and (optionally) a
Tavily key for employer research.

**1. Backend**
```bash
cd apps/api
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env                               # fill in your keys
uvicorn app.main:app --reload
```

**2. Frontend**
```bash
cd apps/web
npm install
copy .env.local.example .env.local                   # fill in your keys
npm run dev
```

Then open http://localhost:3000.

Full setup and architecture details are in
[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md).

## Deployment

- **Frontend** deploys to **Vercel** (import the repo, set the web environment
  variables).
- **Backend** deploys to **Modal** (`modal deploy modal_app.py`).
- **Database, login, and file storage** are hosted on **Supabase**.

## Roadmap

- Side-by-side diff of original vs rewritten bullets
- Interview-prep pack generated from the employer research
- ATS-friendliness warnings when a CV uses formats that scanners struggle with
- Automatic job discovery from public job boards
- Streaming cover-letter generation

## License

Personal project — not currently licensed for redistribution. See the repository
owner for terms.
