# Agent Console

FastAPI service with a minimal web UI for natural-language control of three helpers:
- Gmail read/send (via OAuth tokens saved in `tokens/`)
- Calendly availability and one-off scheduling links
- An OpenAI-powered router that decides which helper to call

## Quickstart
1. **Install dependencies**
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Configure secrets**
   - Copy your Google OAuth *desktop* client to `credentials.json` (the format matches `credentials.example.json`).
   - Ensure `.env` contains `OPENAI_API_KEY`, `DEFAULT_ACCOUNT_EMAIL`, `CALENDLY_TOKEN`, and any SMTP settings you plan to use.
3. **First-run Gmail consent**
   - Start the API (`python -m uvicorn app.main:app --reload --port 8501`).
   - Ask the app for a Gmail action (e.g. “summarise my latest emails”). A browser window will pop up the first time so you can approve access; the resulting token is stored under `tokens/`.
4. **Use the UI**
   - Open <http://localhost:8501/>. Type a request such as “Send Leo a note confirming Thursday works and cc Maya” and press **Run**. The response card shows the natural-language reply plus structured details (intent, recipients, events, etc.).

## CLI snippets
All helper scripts still work for quick testing:
```bash
# Structured router output
python agent_router.py "summarise everything from yesterday" --json

# Gmail list/search/send
python agent_gmail_read.py list --account you@example.com --max 5
python agent_email_send.py --account you@example.com --to "a@b.com" --subject "Hi" --body "Quick check-in"
```
The router CLI defaults to plain text; add `--json` to see the same metadata the UI uses.

## Environment variables
Key values consumed across the helpers:
- `OPENAI_API_KEY`: OpenAI project key used by the router and summarisation steps
- `DEFAULT_ACCOUNT_EMAIL`: Gmail account used when none is specified in a request
- `CALENDLY_TOKEN`: Personal access token for Calendly API calls
- `GOOGLE_CREDENTIALS_PATH` and `GOOGLE_TOKENS_DIR`: override paths if you relocate the OAuth client or token cache (defaults are `credentials.json` and `tokens/`)
- `DRY_RUN=1`: prevents the Gmail sender from actually dispatching emails

## Project layout
```
app/        FastAPI app (REST + static assets)
web/        Minimal UI assets served at /
agent_*.py  Helper modules for Gmail, Calendly, and routing
```

## Testing
```bash
pytest -q
```

The API endpoints are documented at `/docs`. The router endpoint returns structured JSON:
```json
{
  "ok": true,
  "query": "summarise yesterday's invoices",
  "text": "…",
  "kind": "summarize_emails",
  "intent": { "kind": "summarize_emails", "time_window": "yesterday" },
  "details": { "messages_considered": 8, "query": "label:inbox after:2024-09-18" },
  "timestamp": "2025-09-26T16:54:12.203Z"
}
```
Use that structure if you want to build alternative front-ends or integrate with other systems.
