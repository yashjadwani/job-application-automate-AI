# CV Tailor — Comprehensive Application Review

_Full end-to-end audit. Opinionated and constructive. No prior assumptions._
_Scope: 58 source files, ~2,440 LOC backend (Python/FastAPI), ~1,640 LOC
frontend (Next.js/TypeScript), Supabase Postgres._

Severity legend: **🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · 🔵 Nice-to-have**

---

## Part 1 — Comprehensive Audit

### 1.1 The overriding finding

> **🔴 Critical — The application has never run end-to-end against live
> services.**
> **Problem:** At review time the Supabase project was unreachable (DNS did not
> resolve), and no full request has traversed browser → API → Postgres → back.
> Live auth (ES256/JWKS), RLS enforcement, Storage upload/download, quota, the
> rewriter/cover-letter on the production model, PDF export, and the Telegram
> webhook are all **unverified in reality**.
> **Why it matters:** Everything below is reasoning about code that compiles and
> passes mocked tests. The gap between "mocked-green" and "works" is exactly
> where projects like this stall. This is the single biggest risk.
> **Solution:** Restore Supabase, then run one real vertical slice (sign up →
> upload CV → analyse → approve → download). Budget a debugging session; expect
> 3–6 integration bugs. Nothing else should be prioritised above this.

### 1.2 Backend

- **🔴 Background jobs are fire-and-forget.** `POST /analyse` schedules a
  `BackgroundTask` in the same container. If Modal scales the container down or
  it crashes mid-run, the `analyses` row is stranded in `researching`/`writing`
  forever, and the frontend polls it indefinitely. *Why:* an analysis takes
  minutes and spans many LLM calls — the most likely time to be interrupted.
  *Solution:* (a) a sweeper that marks non-terminal rows older than ~10 min as
  `failed`; (b) a frontend poll timeout (below); (c) longer term, move to
  `modal.Function.spawn` or a real queue.
- **🟠 No idempotency / retry on stages.** A transient LLM 500 fails the whole
  run. *Solution:* per-stage retry with backoff; the state machine already makes
  resume-from-stage feasible.
- **🟡 Quota counts failed analyses.** `/analyse` counts all rows this month,
  including `failed` — users pay quota for the app's bugs. *Solution:* exclude
  `status = 'failed'` from the count.
- **🟡 Unbounded inputs.** `company_name`, `jd_title`, `user_notes` have no
  server-side length cap (JD is capped; notes capped in worker, not at the API
  boundary). *Solution:* Pydantic `max_length` on the request models.
- **🟢 Magic numbers** (`MAX_ITERATIONS=8`, `CALL_BUDGET=25`, `MAX_SEARCHES=6`)
  are literals across modules. *Solution:* hoist to `config.py` so they're tunable
  without code edits.
- **Strengths:** the LLM-call chokepoint (`_chat`/`_respond`), contextvar-based
  telemetry/budget, gateway auto-degradation, and deterministic ATS scoring are
  genuinely well done and above the norm for a project this size.

### 1.3 Frontend

- **🟠 Polling never times out.** The analyser and history-detail intervals poll
  every 2.5 s with no ceiling. Combined with the stuck-job issue, a user can
  watch "Researching…" forever. *Solution:* stop after N minutes and show
  "This is taking longer than expected — check History or retry."
- **🟠 Frontend has zero tests and no CI.** *Why:* every refactor (e.g. the
  Next 16 / React 19 bump that caused a hydration crash) ships unguarded.
  *Solution:* Playwright smoke test of the public pages + the auth redirect;
  wire `npm run build` + `pytest` into CI.
- **🟡 `Analysis` type duplicated** in `AnalysisResults.tsx` with no shared
  contract with the backend Pydantic models. They will drift. *Solution:*
  generate types from an OpenAPI schema (`openapi-typescript`) or a shared
  package.
- **🟡 Loading states are text-only** ("Loading…" + `animate-pulse`). *Solution:*
  lightweight skeleton rows for the dashboard/history lists.
- **🟢 Transient poll errors are swallowed silently** (`catch {}` inside the
  interval). Correct for blips, but a *persistent* failure gives the user no
  signal. *Solution:* count consecutive failures; surface after ~3.
- **🟢 No error boundary / custom `not-found` / `error.tsx`.** An unexpected
  throw shows the default Next overlay in dev and a blank state in prod.
- **Strengths:** consistent `PageHeader`, one design language, active-route nav,
  optimistic status updates with revert, clean fetch wrapper.

### 1.4 Database

- **🟢 No pagination.** `GET /analyses` returns every row; History renders all
  of them. Fine at tens of rows, sloppy as a pattern. *Solution:* `range()` +
  cursor, or at least `limit`.
- **Strengths:** RLS on every table, per-user Storage path policies, sensible
  `jsonb` use, check constraints on `status`/`app_status`, a covering index on
  `(user_id, created_at)`. The data model is the strongest layer.

### 1.5 Authentication

- **🟠 Cross-tenant isolation is declared P0 but never verified.** RLS policies
  exist; no automated test proves User A cannot read User B's rows/files, and
  there's no CI to run one. *Solution:* the isolation test (two users, A's token
  requesting B's resources → 404/empty) — write it and gate CI on it.
- **🟢 Dependent on Supabase issuing ES256.** If the project is on the legacy
  HS256 secret, every login fails (HS256 is rejected by design). *Solution:*
  the JWKS-endpoint check documented in TECHNICAL_DOCUMENTATION §6.
- **Strengths:** ES256-only, issuer+audience+expiry+required-claims, alg-pinning,
  no secret on the API, JWKS caching with rotation. Auth is the most hardened
  part of the app and is unit-tested with a real EC keypair.

### 1.6 Performance

- **🟡 Analysis latency is high by design.** The agentic pipeline makes ~8–15
  LLM calls (research loop, tool loop, critic rounds, editor). Expect
  60–150 s/run. *Why it matters:* it's the core interaction. *Solution:* it's an
  acceptable trade for quality *if* the live UX (trace + HITL) keeps it feeling
  responsive; measure with telemetry and consider `MAX_REVISIONS=1` if a run
  drags.
- **🟡 No caching of employer research.** Two analyses for the same company
  re-run the whole search. *Solution:* short-TTL cache keyed by company.
- **🟢 Frontend bundle is healthy** (~87 kB shared, per-route 1–3 kB). No action.

### 1.7 Security

- **🟠 Telegram webhook has no rate limiting**, and **link codes never expire**.
  Single-user risk is low, but a leaked code is valid forever. *Solution:* TTL on
  codes; basic per-chat throttle.
- **🟡 Service-role key** is correctly confined to the Telegram module, but its
  safety rests on discipline (every query must filter by resolved `user_id`).
  *Solution:* a thin wrapper that requires `user_id`, so it can't be forgotten.
- **🟢 Secrets hygiene is good** — `.env` gitignored, no keys in code, JWT
  pass-through avoids service-role on request paths.

### 1.8 Accessibility — **the weakest area**

- **🟠 Inputs use placeholders instead of `<label>`s.** Placeholders vanish on
  input and are poorly announced by screen readers. *Solution:* real labels
  (visually-hidden if the design wants placeholder-only look).
- **🟡 Contrast.** `#86868B` subtle text on white is ~3.5:1 — below WCAG AA
  (4.5:1) for body text. *Solution:* darken to ~`#6E6E73` for anything
  informational.
- **🟡 No focus-visible styling / focus management** on route changes or after
  the HITL approval. *Solution:* `:focus-visible` rings; move focus to the
  results heading when an analysis completes.
- **🟢 No `aria-live` on the live trace / status** — screen-reader users don't
  hear progress. *Solution:* `aria-live="polite"` on the status region.

### 1.9 Mobile responsiveness

- **🟢 Generally solid** — `PageHeader` wraps, nav scrolls, stats use flex-wrap.
- **🟡 The dashboard stat strip** uses `divide-x` dividers that can look
  cramped/awkward when they wrap to two lines on narrow screens. *Solution:*
  drop the dividers below `sm`.
- **🟢 The bullet-edit `<textarea>`s** on CV/approval are comfortable on mobile;
  good.

### 1.10 UI/UX consistency

- **🟢 Strong.** One accent, hairline dividers over boxes, consistent header,
  monograms, `ScoreBadge` reused. The Apple-style system is coherent.
- **🟡 Empty states are plain sentences.** Functional but not inviting
  (see Part 2).
- **🟢 Button press states and field-focus halos** were added — good micro-detail.

### 1.11 Error handling

- **🟡 Inconsistent surfaces.** Some errors render inline red text, some only
  `console`, polling errors are swallowed. *Solution:* a small shared
  toast/inline-error convention.
- **🟠 No global handling for the "job silently died" case** (ties to §1.2/§1.3).

### 1.12 Code quality, structure, naming

- **🟢 Above average.** Small focused modules, clear names, docstrings on the
  hard parts, comment density matched to complexity. Folder structure is logical
  and discoverable.
- **🟡 One naming wrinkle:** `worker._finish` (HITL-off inline path) vs the
  `finish` tool vs `awaiting_approval` — three "finish" concepts. *Solution:*
  rename the inline path to `_run_phase_two`.
- **🟢 `probe_gateway.py`, `debug.ipynb`, `evals/`** are excellent developer
  ergonomics — rare and valuable.

### 1.13 Technical debt (consolidated)

Fire-and-forget jobs · no frontend tests/CI · type-contract drift · no
pagination · unverified live path · unproven model quality · a11y gaps ·
Telegram TTL/rate-limit · multi-run-bullet formatting flattening (mid-bullet
bold is lost on export — a real risk to the "formatting preserved" promise).

### 1.14 Reusability / Scalability / Maintainability

- **Reusability:** good on the frontend (shared components) and the LLM layer
  (one chokepoint, generic tool loop). The **backend routers repeat** the
  `user_client(user.token)` + fetch pattern; a dependency that yields the client
  would DRY it.
- **Scalability:** RLS/data model scale fine; **background execution does not** —
  it's the first thing to break past one active user. Otherwise stateless and
  horizontally deployable.
- **Maintainability:** strong after this documentation pass; the main risks are
  the untested frontend and the FE/BE type drift.

---

## Part 2 — Feature & UX Suggestions

Thinking as Product Designer + Frontend Eng + PM.

### Missing features
- **CV diff view** — side-by-side original vs rewritten bullets with
  change highlighting. The data already exists; it's the single highest-value
  addition for user trust.
- **"Add a real number" prompt** in the approval step — when a rewritten bullet
  would be stronger with a metric, ask the user rather than inventing one. Ethical
  answer to the quantify-everything advice; fits HITL perfectly.
- **ATS-friendliness check on upload** — the parser already detects tables;
  warn when a CV layout will confuse scanners.
- **Interview-prep pack** — reuse employer research + gaps to generate likely
  questions and suggested answers.
- **Re-run / duplicate analysis** — one click from a failed or stale run.

### UX & flow
- **Onboarding.** First login lands on an empty dashboard. Add a 3-step
  checklist ("① Upload your CV ② Fill your profile ③ Run your first analysis")
  with progress, so the empty state teaches the flow.
- **Guided first analysis** — a sample JD to try before the user has one.
- **Navigation** — the Analyser is the core action; consider making "New
  Analysis" a persistent primary button in the nav, not just on the dashboard.
- **Empty states** — replace plain sentences with a small illustration/icon, a
  one-line value prop, and the primary CTA. Every empty state is a chance to
  onboard.
- **Loading experiences** — skeleton rows for lists; keep the live agent trace
  (it's a differentiator — lean into it as the "loading" experience for
  analyses).
- **Error messages** — humanise: "We couldn't reach the AI service — retry?"
  instead of a raw status code; always offer the next action.
- **Visual hierarchy** — the results page is long; add a sticky in-page nav
  (Scores · Insights · Bullets · Letter) for quick jumping.
- **Responsiveness** — a bottom tab bar on mobile would beat the horizontally
  scrolling top nav.
- **Animation (tasteful)** — you have `fade-in`; add: score-ring count-up,
  stagger the results sections in, a subtle checkmark when an analysis completes,
  smooth height on the collapsible trace/API-calls panels.
- **Polish** — a favicon + OG image, a proper `/loading` and `not-found`, a
  toast system, and a keyboard shortcut (⌘/Ctrl+Enter to run an analysis).

---

## Part 6 — Final Report

### Ratings

| Dimension | Score | One-line rationale |
|-----------|:-----:|--------------------|
| **Overall** | **6.5 / 10** | Excellent engineering; unrun, unverified, undeployed |
| UI/UX | 7.5 / 10 | Coherent, tasteful, consistent; thin on empty-state/onboarding depth |
| Performance | 7 / 10 | Light frontend; backend slow-by-design (agentic), no caching |
| Accessibility | 4.5 / 10 | Placeholder-labels, contrast, no focus/aria — the weak spot |
| Code quality | 8 / 10 | Clean, factored, documented, backend-tested; above norm |
| Maintainability | 7.5 / 10 | Good structure + docs; hurt by FE/BE type drift, no CI |
| Scalability | 6 / 10 | Data/RLS scale; background execution does not |
| **Production readiness** | **4 / 10** | Never run live, no CI, stuck-job risk, security unverified |

### Top 10 highest-priority improvements
1. 🔴 Run the app **end-to-end against live services** once (unblocks everything).
2. 🔴 Fix **stuck jobs**: sweeper for stale non-terminal rows.
3. 🟠 Add a **frontend poll timeout** with a clear message.
4. 🟠 Write + CI the **cross-tenant isolation test**.
5. 🟠 Stand up **CI** (build + pytest + a Playwright smoke test).
6. 🟠 Run the **eval harness** and judge real rewriter/cover-letter quality;
   pick the model deliberately.
7. 🟡 Exclude **failed runs from quota**.
8. 🟡 Establish a **shared FE/BE type contract** (OpenAPI → TS).
9. 🟡 **Accessibility pass**: labels, contrast, focus-visible, aria-live.
10. 🟡 Add **pagination** to `/analyses`.

### Quick wins (< 30 min each)
- Exclude `failed` from the quota count.
- Poll timeout + persistent-error surfacing.
- Darken subtle text to pass contrast; add `:focus-visible` rings.
- `max_length` on request models.
- Custom `not-found.tsx` + a favicon.
- Hoist magic numbers to config.
- Link-code TTL for Telegram.

### Medium-effort improvements
- Stuck-job sweeper + per-stage retry.
- Onboarding checklist + richer empty states.
- Skeleton loaders + toast system.
- CV diff view.
- OpenAPI-generated shared types.
- Playwright smoke suite + CI.

### Large architectural improvements
- Move background execution to a durable queue (`modal.Function.spawn` or
  Redis/RQ) with resumable, idempotent stages.
- Streaming cover-letter generation (SSE).
- Employer-research cache layer.
- Job-discovery service (poll public ATS boards → auto-analyse matches).

### Suggested roadmap
- **Now (unblock):** live E2E → stuck-job fix → poll timeout → isolation test → CI.
- **Next (trust & polish):** eval-driven model choice → CV diff → onboarding +
  empty states → a11y pass → skeletons/toasts.
- **Later (scale & product):** durable queue → streaming → research cache →
  interview-prep → job discovery.

### Verdict
This is a **genuinely impressive engineering artifact** — agentic pipeline,
four-layer guardrails, telemetry, gateway-agnostic fallbacks, hardened auth, and
excellent dev ergonomics — that is **not yet a running product**. The distance
to production is not more features; it is **proving the existing system live,
adding the operational safety net (stuck-job handling, CI, isolation test), and
one accessibility pass.** Close those and this jumps from ~6.5 to ~8.5.
