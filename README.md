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

