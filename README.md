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

