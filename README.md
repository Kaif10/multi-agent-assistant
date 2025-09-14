<<<<<<< HEAD
Agent API (Gmail, Calendly, Router)

Production-ready FastAPI app that wraps your helpers for Gmail read/send, Calendly events + scheduling links, and an LLM-powered natural-language router.

Features
- REST API via FastAPI (`app/main.py`)
- Dockerized runtime (`Dockerfile`, `.dockerignore`)
- CI: tests + Docker build with GitHub Actions (`.github/workflows/ci.yml`)
- Kubernetes manifests (`k8s/`), with Secrets/ConfigMap examples
- Safe testing: Gmail sender honors `DRY_RUN=1`

Quickstart (Local)
1) Python deps
  python -m venv .venv && . .venv/bin/activate
  pip install -r requirements.txt

2) Env
- Copy your Google OAuth client to `credentials.json` (see `credentials.example.json`).
- Ensure tokens exist in `tokens/` or be ready to complete OAuth once locally.
- Set `OPENAI_API_KEY`, `CALENDLY_TOKEN`, and `DEFAULT_ACCOUNT_EMAIL` in `.env` or environment.

3) Run API
  uvicorn app.main:app --reload

4) Test
  pytest -q

Docker
Build and run:
  docker build -t agent-api .
  # mount tokens + credentials (read-only) and expose 8000
  mkdir -p tokens downloads
  # Place your tokens under ./tokens and credentials.json at ./credentials
  docker run --rm -p 8000:8000 \
    -e OPENAI_API_KEY=$OPENAI_API_KEY \
    -e CALENDLY_TOKEN=$CALENDLY_TOKEN \
    -e DEFAULT_ACCOUNT_EMAIL=$DEFAULT_ACCOUNT_EMAIL \
    -e GOOGLE_CREDENTIALS_PATH=/app/credentials/credentials.json \
    -e GOOGLE_TOKENS_DIR=/app/tokens \
    -v $(pwd)/tokens:/app/tokens:ro \
    -v $(pwd)/credentials.json:/app/credentials/credentials.json:ro \
    agent-api

Kubernetes
- Edit `k8s/deployment.yaml` image to your registry (`ghcr.io/OWNER/REPO:latest`).
- Create Secrets / ConfigMap from examples:
  kubectl apply -f k8s/secret-example.yaml
  kubectl apply -f k8s/configmap-example.yaml
  kubectl apply -f k8s/deployment.yaml
  kubectl apply -f k8s/service.yaml
  # optional ingress
  kubectl apply -f k8s/ingress.yaml

Mount Gmail user tokens into the `agent-gmail-tokens` Secret (keys named like `gmail-you_example_com.json`). Mount your OAuth client JSON under `agent-google-credentials` Secret as `credentials.json`.

API Endpoints
- GET /health
- POST /gmail/list { account_email?, max_results }
- POST /gmail/search { query, account_email?, max_results }
- POST /gmail/get { message_id, account_email?, download_attachments? }
- POST /gmail/send { to[], subject?, body_text?, cc?, bcc?, account_email?, in_reply_to_message_id? }
- POST /calendly/events { date, window?, tz?, account_key? }
- POST /calendly/link { account_key?, event_type?, max_count?, owner_type? }
- POST /route { text, account_email?, calendly_key? }

Notes & Constraints
- Gmail OAuth in container/cluster is non-interactive. Pre-provision the `tokens/` folder locally and mount via Secret in Kubernetes.
- For enterprise Gmail, consider domain-wide delegation with a service account instead of per-user OAuth.
- Voice features aren’t included in the container by default (audio deps are heavy). Use locally if needed.

Changelog (scoped to this PR)
- Added FastAPI app and tests
- Docker + CI (GitHub Actions)
- Kubernetes manifests
- `agent_email_send.py` respects `DRY_RUN`
- Calendly scheduling uses provided `owner_type`
=======
# 🧑‍💻 Multi-Agent Assistant (Gmail + Calendly + Voice)

A natural-language agent system that can:

* **Send emails** (“send an email to [alice@example.com](mailto:alice@example.com) saying I’ll be late”)
* **Summarize Gmail** (“summarize my emails from yesterday”)
* **Look up Calendly meetings** (“who did I meet on Monday afternoon?”)
* **Send Calendly booking links** (“send my Calendly link to [andrew@example.com](mailto:andrew@example.com)”)
* (Optional) **Voice control**: push-to-talk interface using Whisper + TTS

Built with: **Python, OpenAI, Gmail API, Calendly API**.

---

## ✨ Features

* Multi-user ready (tokens stored in `tokens/` per account).
* Uses **OAuth** for Gmail (no passwords).
* Calendly integration: list events + generate live scheduling links.
* `DRY_RUN` mode for safe demos (no real emails sent).
* Voice router for hands-free interaction.
* Self-test script to validate everything end-to-end.

---

## ⚙️ Requirements

* Python **3.10+**
* A Google Cloud OAuth **Desktop client** JSON (download from [Google Cloud Console](https://console.cloud.google.com/apis/credentials))
* A **Calendly PAT** (personal access token) — for now, used instead of OAuth

---

## 🛠️ Setup

Clone & install:

```bash
git clone https://github.com/Kaif10/multi-agent-assistant.git
cd multi-agent-assistant
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 🔧 Environment

Copy `.env.example` → `.env` and fill in your own keys.

### Example `.env.example`

```ini
# ===============================
# Multi-Agent Assistant Example .env
# ===============================

# --- OpenAI ---
# Your OpenAI API key (from https://platform.openai.com/account/api-keys)
OPENAI_API_KEY=your-openai-key
# Default model used for intent classification & summarization
OPENAI_MODEL=gpt-4o-mini

# --- Gmail OAuth ---
# Path to your Google OAuth Desktop client JSON
# When you download it, Google names it something like:
#   client_secret_xxxxx.apps.googleusercontent.com.json
# Option A: rename it to credentials.json and put it in repo root
# Option B: keep original name and update this path accordingly
GOOGLE_CREDENTIALS_PATH=credentials.json

# Optional default account email (used if you omit --account)
# Leave blank for public use; each user should set their own
DEFAULT_ACCOUNT_EMAIL=

# --- Calendly ---
# Personal Access Token (PAT) from https://calendly.com/integrations/api_webhooks
# For now we use PAT; in production you'd switch to OAuth per user
CALENDLY_TOKEN=

# Local timezone for interpreting "yesterday", "Monday afternoon", etc.
LOCAL_TZ=Europe/London

# --- Router / Safety ---
# DRY_RUN=1 means emails are simulated (not actually sent)
# DRY_RUN=0 means real emails are sent via Gmail API
DRY_RUN=1

# Directory for saving attachments (from Gmail read)
DOWNLOAD_DIR=downloads
```

---

### 📌 Important — Google `credentials.json`

When you download your OAuth client from Google Cloud Console, the file is named like:

```
client_secret_1234567890-abc123def.apps.googleusercontent.com.json
```

You have two options:

1. Rename it to `credentials.json` and place it in the repo root.
2. Keep the weird name, but update `.env`:

   ```ini
   GOOGLE_CREDENTIALS_PATH=client_secret_1234567890-abc123def.apps.googleusercontent.com.json
   ```

### Example `credentials.example.json`

```json
{
  "installed": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "project_id": "your-project-id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uris": ["http://localhost"]
  }
}
```

> ⚠️ Do **not** commit your real `credentials.json` or `token.json`. Only keep them locally.

First run will trigger OAuth in the browser; a token is cached under `tokens/`.

---

## ▶️ Usage

### Summarize emails

```bash
python agent_router.py "summarize my emails from yesterday" --account you@example.com
```

### Send an email

```bash
python agent_router.py "send an email to bob@example.com saying I received the parcel" --account you@example.com
```

### Calendly meetings

```bash
python agent_router.py "who did I meet on Monday afternoon?"
python agent_router.py "did I have any Calendly meetings in the past 2 weeks?"
```

### Send a Calendly link

```bash
python agent_router.py "send my calendly link to alice@example.com"
```

---

## 🎙️ Voice Router (optional)

Run:

```bash
python voice_router.py
```

Press **Enter**, speak your request, pause → it will transcribe, route, and respond.

---

## 🧪 Self-test

Validate integrations without sending real mail:

```bash
# Ensure DRY_RUN=1 in .env
python self_test.py
```

You’ll see a PASS/FAIL summary for Gmail read, Gmail send, and Calendly.

---

## 📁 Repo structure

```
agent_router.py       # NL router → Gmail/Calendly agents
agent_gmail_read.py   # Gmail read/search
agent_email_send.py   # Gmail send (DRY_RUN aware)
agent_calendly.py     # Calendly list events + links
voice_router.py       # Voice interface
self_test.py          # Health check / eval script
requirements.txt
.env.example
credentials.example.json
.gitignore
```

---

## 🔒 Security Notes

* Never commit `.env`, `credentials.json`, `token.json`, or `tokens/`.
* This repo’s `.gitignore` already covers those.
* If secrets were accidentally committed, revoke them immediately in Google Cloud / Calendly and generate new ones.

---

## 📜 License

MIT 
>>>>>>> 60417c5fc843c3f6f35d7c0045bf8d8b51853e01

