# Agent Console

Natural‑language agent that can fetch/summarize Gmail, send email, and create Calendly scheduling links. It exposes a FastAPI service with a tiny web UI and a router that turns plain text into actions.

## Features
- Gmail read (search, list compact, fetch bodies/attachments)
- Gmail send (reply threading preserved when possible)
- Calendly (list hosted events + create one‑off scheduling links)
- OpenAI‑driven intent router with structured JSON output

## Prerequisites
- Python 3.10+ (tested on 3.12)
- An OpenAI API key
- A Google Cloud project with a Desktop OAuth client (for Gmail)
- Optional: Calendly personal access token

## Setup
1) Create and activate a virtualenv, then install deps
```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -r requirements.txt
```

2) Add secrets and config
- Copy your Google OAuth Desktop client JSON to `credentials.json` (format like `credentials.example.json`).
- Create a `.env` file with at least:
  - `OPENAI_API_KEY=sk-...`
  - `DEFAULT_ACCOUNT_EMAIL=you@gmail.com`  (optional but recommended)
  - `CALENDLY_TOKEN=...`  (optional; only for Calendly features)
  - Optional overrides: `GOOGLE_CREDENTIALS_PATH=credentials.json`, `GOOGLE_TOKENS_DIR=tokens`, `LOCAL_TZ=Europe/London`, `DRY_RUN=0|1`.

3) Configure Google consent (only on first run / new project)
- In Google Cloud Console → APIs & Services → OAuth consent screen: set User Type to External, fill app details, and add yourself under Test users.
- Enable “Gmail API” in Library.

4) Run the API
```powershell
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Open http://localhost:8000/ to load the UI, or http://localhost:8000/docs for Swagger.
- On your first Gmail action, a browser login appears; the token is saved to `tokens/gmail-<email>.json`.

## Using the Agent
You can talk to it via the UI or the REST API (`/route`). Examples:
- “Fetch all important mails from last week”
- “Summarize July 14 emails about invoices”
- “Send an email to josh@gmail.com telling him the report is ready”
- “Send my Calendly link to andrew@yahoo.com”

The router returns both a plain `text` response and the original Markdown in `text_markdown`, plus `details` describing what it did. For Gmail summarization, date phrases are parsed and enforced within a 40‑day lookback window.

## Date Windows (Gmail)
Natural phrases supported and clamped to the last 40 days:
- `today`, `yesterday`
- `last week`, `this week`, `past 2 weeks`
- `last month`, `past 2 months` (limited by 40‑day cap)
- Specific days like `July 14`, `2025-07-14`, or ranges like `July 1 to July 7`
The app composes a Gmail query and also filters results by internalDate to make the window accurate.

## Multi‑user
- Gmail tokens are stored per account at `tokens/gmail-<email>.json`.
- Pass `account_email` in the request body (or set `DEFAULT_ACCOUNT_EMAIL` in `.env`).
- Calendly can use `CALENDLY_TOKEN` globally or per‑user tokens in `tokens/calendly-<key>.txt`.

## CLI (optional)
```powershell
# Structured router output
python agent_router.py "fetch emails from last week" --account you@gmail.com --json

# Gmail list/search/get
python agent_gmail_read.py list --account you@gmail.com --max 5
python agent_gmail_read.py search "newer_than:7d" --account you@gmail.com
python agent_gmail_read.py get <message_id> --account you@gmail.com --download

# Gmail send
python agent_email_send.py --account you@gmail.com --to "a@b.com" --subject "Hi" --body "Quick check-in"
```

## Environment Variables
- `OPENAI_API_KEY` – required
- `DEFAULT_ACCOUNT_EMAIL` – default Gmail identity
- `CALENDLY_TOKEN` – PAT for Calendly (optional)
- `GOOGLE_CREDENTIALS_PATH` – defaults to `credentials.json`
- `GOOGLE_TOKENS_DIR` – defaults to `tokens`
- `LOCAL_TZ` – for summaries; defaults to `Europe/London`
- `DRY_RUN` – set to `1` to suppress actual sends in development

## Troubleshooting
- Access blocked during Google OAuth: add your Gmail under Consent Screen → Test users, ensure “Gmail API” is enabled, and delete stale tokens under `tokens/` before retrying.
- Wrong account picked: set `DEFAULT_ACCOUNT_EMAIL` or pass `account_email` in the request.
- `uvicorn` not found: `pip install -r requirements.txt`.
- “Only last 40 days”: the router enforces a 40‑day cap by design.

## Security & Git Hygiene
- `.gitignore` excludes tokens and real credentials; commit only `credentials.example.json`.
- Do not commit `.env` or any `tokens/` files.

## Project Layout
```
app/        FastAPI app (REST + static assets)
web/        Minimal UI assets served at /
agent_*.py  Helper modules for Gmail, Calendly, and routing
tests/      Basic health check
```

## License
No license provided; consult the repository owner before redistribution.

