# Self-Optimising Automation

A FastAPI-based cold-outreach platform that learns which message angles and channels work best for each persona. A multi-armed bandit allocates traffic between proven and exploratory variants, an LLM drafts the messages, and webhook events from the sender feed reward signals back into the policy.

## What it does

- **Lead intake** — JSON ingest or bulk CSV upload, with per-row validation and idempotent upsert by email.
- **Policy selection** — for each lead a Thompson-sampling bandit ([app/services/bandit.py](app/services/bandit.py)) picks a `(channel, angle)` pair from `["email", "linkedin"]` × `["pain", "growth", "compliance", "cost", "speed", "credibility"]`. A configurable share of decisions are random exploration.
- **Message generation** — [app/services/message_gen.py](app/services/message_gen.py) drafts subject/body via the OpenAI API using the chosen template family.
- **Safety checks** — bounce/spam-rate caps and per-domain suppression block sends before they go out ([app/services/safety.py](app/services/safety.py)).
- **Optional human approval** — when `REQUIRE_APPROVAL` is on, drafts land in a pending queue for review/edit/approve from the dashboard before sending.
- **Sending** — pluggable backend (`stub`, `gmail`, or `instantly`) selected from app settings.
- **Reply classification** — inbound replies are classified (positive, objection, OOO, unsubscribe, wrong contact) and reward-credited back to the bandit.
- **Scheduler** — APScheduler tick that finds eligible leads, respects per-persona pacing and a configurable send window, and queues the next touch.
- **Dashboard** — static HTML/JS frontend at `/dashboard/*` for overview stats, leads, policy stats, activity log, approvals, and settings.

## Project layout

- [app/main.py](app/main.py) — FastAPI app, router wiring, dashboard page routes
- [app/models.py](app/models.py) — SQLAlchemy models: `Lead`, `Signal`, `Touch`, `Event`, `Outcome`, `PolicyStat`, `RuleVersion`, `User`, `Setting`, `AccountSuppression`
- [app/database.py](app/database.py) — async engine + session factory
- [app/config.py](app/config.py) — env-driven settings via pydantic-settings
- [app/routers/](app/routers/) — `auth`, `leads`, `webhooks`, `dashboard`, `settings`
- [app/services/](app/services/) — bandit, policy engine, message generation, classifier, safety, sender backends, scheduler, encryption, app settings, auth helpers
- [frontend/](frontend/) — static dashboard pages and shared JS
- [tests/](tests/) — pytest suite (pure-logic tests + a couple of integration tests)

## Setup

Requires Python 3.11+ and a PostgreSQL database (uses `asyncpg` and JSONB columns).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` in the project root:

```ini
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/outreach
OPENAI_API_KEY=sk-...
APP_ENV=development

# Auth (set AUTH_REQUIRED=true to enforce on protected routes)
AUTH_REQUIRED=false
JWT_SECRET=change-me
JWT_EXPIRES_HOURS=24

# Encryption key for stored secrets (e.g. sender credentials)
ENCRYPTION_KEY=change-me

# Bandit / safety
EXPLORATION_RATE=0.12
MIN_BANDIT_TRIALS=50
MAX_BOUNCE_RATE=0.03
MAX_SPAM_RATE=0.001

# Scheduler (off by default — enable once a sender is configured)
SCHEDULER_ENABLED=false
SCHEDULER_INTERVAL_MINUTES=10
SCHEDULER_BATCH_SIZE=10

# Sender — one of: stub | gmail | instantly
SENDER_BACKEND=stub
GMAIL_USERNAME=
GMAIL_APP_PASSWORD=
GMAIL_FROM_ADDRESS=
GMAIL_FROM_NAME=
INSTANTLY_API_KEY=
INSTANTLY_API_BASE_URL=https://api.instantly.ai/api/v2
INSTANTLY_DEFAULT_CAMPAIGN_ID=
```

### Initialize the database

Tables auto-create on app startup, but for a clean slate or to run on an existing DB:

```powershell
python reset_db.py                    # DROP + CREATE all tables (destructive)
python migrate_add_touch_approval.py  # idempotent migration for the approval columns
```

### Create a user

```powershell
python create_user.py admin@example.com
```

### Run the app

```powershell
uvicorn app.main:app --reload
```

Then open:

- API docs: http://localhost:8000/docs
- Dashboard: http://localhost:8000/dashboard
- Login: http://localhost:8000/login

## Key endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/login` | Get a JWT |
| GET  | `/auth/me` | Verify the current token |
| POST | `/leads/ingest` | Upsert a single lead |
| POST | `/leads/import-csv` | Bulk-upsert from CSV |
| GET  | `/leads/import-csv/template` | Download the CSV template |
| PATCH | `/leads/{id}` | Update lead fields |
| POST | `/leads/{id}/generate` | Run policy + draft a message (and send, unless approval is required) |
| GET  | `/leads/touches/pending` | List drafts awaiting approval |
| PATCH | `/leads/touches/{id}` | Edit a pending draft |
| POST | `/leads/touches/{id}/approve` | Approve and send |
| POST | `/leads/touches/{id}/reject` | Reject a draft |
| POST | `/webhooks/instantly` | Ingest delivery / engagement / reply events |
| GET  | `/api/dashboard/stats` | Aggregate stats for the overview page |

## How the bandit learns

Each `(persona, channel, angle)` segment has a `PolicyStat` row holding `alpha`/`beta_param` for a Beta distribution. `decide_policy` samples once per arm and picks the highest sample (Thompson sampling), with a fixed `EXPLORATION_RATE` chance of a uniformly random pick instead.

When a webhook fires, [`_credit_bandit`](app/routers/webhooks.py) maps the event to a reward (positive reply = +10, bounce = -5, unsubscribe = -10, etc.) and `record_reward` updates the segment's Beta parameters. Once a segment crosses `MIN_BANDIT_TRIALS`, every 10 trials a `RuleVersion` snapshot is written for audit. The same event flow is also idempotent against webhook retries.

## Tests

```powershell
pytest
```

The suite is split between pure-logic tests (no DB) and a couple of integration tests for webhook idempotency and reward recording.

## Notes

- The scheduler is **off by default**. Turn it on only after configuring a real sender, otherwise it will keep generating drafts that nothing ships.
- `SENDER_BACKEND=stub` is safe for local development — it writes touches but doesn't actually send.
- Sender credentials and other secrets stored in `app_settings` are encrypted at rest using `ENCRYPTION_KEY`.
