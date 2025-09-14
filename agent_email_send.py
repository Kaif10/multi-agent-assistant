
"""
Gmail SEND (multi-user). Uses the same token store as agent_gmail_read.py.

Scope: gmail.modify (by design)
- We intentionally request gmail.modify so one consent covers both read and send
  flows across the app. For stricter least-privilege you can split to separate
  credentials/flows using gmail.readonly and gmail.send.

send_email(
    to: list[str] | str,
    subject: str,
    body_text: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    account_email: str | None = None,
    in_reply_to_message_id: str | None = None
) -> dict
"""
from __future__ import annotations
import os, sys, base64, json, re
from typing import List, Optional, Tuple
from email.message import EmailMessage
from dotenv import load_dotenv
load_dotenv()

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
TOKENS_DIR = os.getenv("GOOGLE_TOKENS_DIR", "tokens")
DEFAULT_ACCOUNT_EMAIL = os.getenv("DEFAULT_ACCOUNT_EMAIL")

def _token_path_for(email_addr: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9_.+-]+', '_', email_addr.strip())
    return os.path.join(TOKENS_DIR, f"gmail-{slug}.json")

def _load_credentials(token_path: str) -> Optional[Credentials]:
    if os.path.exists(token_path):
        try:
            return Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            return None
    return None

def _save_credentials(creds: Credentials, token_path: str) -> None:
    with open(token_path, "w") as f:
        f.write(creds.to_json())

def _interactive_login(token_path: str) -> Credentials:
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        raise FileNotFoundError(f"Missing GOOGLE_CREDENTIALS_PATH at {GOOGLE_CREDENTIALS_PATH}")
    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_credentials(creds, token_path)
    return creds

def get_credentials(account_email: Optional[str] = None) -> Tuple[Credentials, str]:
    if account_email:
        token_path = _token_path_for(account_email)
        creds = _load_credentials(token_path)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request()); _save_credentials(creds, token_path)
        if not creds or not creds.valid:
            creds = _interactive_login(token_path)
        return creds, account_email
    if DEFAULT_ACCOUNT_EMAIL:
        return get_credentials(DEFAULT_ACCOUNT_EMAIL)
    raise RuntimeError("No account_email provided and DEFAULT_ACCOUNT_EMAIL is not set.")

def _gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

def _as_list(x) -> List[str]:
    if not x: return []
    if isinstance(x, str): return [x]
    return list(x)

def send_email(
    to, subject: str, body_text: str,
    cc=None, bcc=None,
    account_email: Optional[str] = None,
    in_reply_to_message_id: Optional[str] = None
) -> dict:
    # Respect DRY_RUN for safe testing environments
    if os.getenv("DRY_RUN", "0").lower() in {"1", "true", "yes", "on"}:
        return {"id": "dry-run", "threadId": None}

    creds, acct = get_credentials(account_email)
    svc = _gmail_service(creds)

    # Build the RFC822 message
    msg = EmailMessage()
    msg["To"] = ", ".join(_as_list(to))
    if cc: msg["Cc"] = ", ".join(_as_list(cc))
    if bcc: msg["Bcc"] = ", ".join(_as_list(bcc))
    msg["Subject"] = subject or ""
    msg.set_content(body_text or "")

    thread_id = None
    if in_reply_to_message_id:
        # Fetch original to stitch thread + set headers (preserve chain)
        orig = svc.users().messages().get(
            userId="me",
            id=in_reply_to_message_id,
            format="metadata",
            metadataHeaders=["Message-Id", "References"],
        ).execute()
        hdrs = {h["name"].lower(): h["value"] for h in orig.get("payload", {}).get("headers", [])}
        orig_mid = hdrs.get("message-id")
        orig_refs = hdrs.get("references")
        if orig_mid:
            msg["In-Reply-To"] = orig_mid
            msg["References"] = f"{orig_refs} {orig_mid}".strip() if orig_refs else orig_mid
        thread_id = orig.get("threadId")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id

    sent = svc.users().messages().send(userId="me", body=body).execute()
    return {"id": sent.get("id"), "threadId": sent.get("threadId")}

# ------------- CLI ----------------
def _usage():
    print("Usage:")
    print('  python agent_email_send.py --account you@example.com --to "a@b.com,c@d.com" --subject "Hi" --body "Hello"')
    print("Options: --cc --bcc --reply MID")

def main():
    args = sys.argv[1:]
    def get_opt(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i+1 < len(args): return args[i+1]
        return default
    account = get_opt("--account", os.getenv("DEFAULT_ACCOUNT_EMAIL"))
    to = get_opt("--to", "")
    subj = get_opt("--subject", "")
    body = get_opt("--body", "")
    cc = get_opt("--cc")
    bcc = get_opt("--bcc")
    reply = get_opt("--reply")
    if not to:
        _usage(); sys.exit(2)
    res = send_email(to.split(","), subj, body, cc.split(",") if cc else None, bcc.split(",") if bcc else None, account_email=account, in_reply_to_message_id=reply)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
