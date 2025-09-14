
"""
Gmail (multi-user) helpers + optional CLI.

- Stores OAuth tokens per user at: TOKENS_DIR/gmail-{email}.json
- Uses a single scope set (gmail.modify) so one consent works for read + send.
- Exposes three functions you can import:
    list_recent_compact(max_results=25, account_email=None)
    search_emails(query, max_results=25, account_email=None)
    get_email(message_id, download_attachments=False, account_email=None)

Scope: gmail.modify (by design)
- We intentionally request gmail.modify so one consent covers both read and send
  in this app. For strict least-privilege, split flows into gmail.readonly and
  gmail.send with separate credentials.

If run as a script, you can call these from the CLI, e.g.:
    python agent_gmail_read.py list --account you@example.com --max 20
    python agent_gmail_read.py search "subject:invoice" --account you@example.com
    python agent_gmail_read.py get 18c1a1a0a2f... --download --account you@example.com
"""
from __future__ import annotations
import os, sys, json, base64, pathlib, datetime as dt, email, re
from typing import Dict, Any, List, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()

# ---- Google API setup -------------------------------------------------------
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
TOKENS_DIR = os.getenv("GOOGLE_TOKENS_DIR", "tokens")
DEFAULT_ACCOUNT_EMAIL = os.getenv("DEFAULT_ACCOUNT_EMAIL")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")

pathlib.Path(TOKENS_DIR).mkdir(parents=True, exist_ok=True)
pathlib.Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

def _safe_filename(name: str, default: str = "attachment.bin") -> str:
    name = (name or default).strip()
    # remove path separators and control chars
    name = re.sub(r"[\\/\r\n\t]+", "_", name)
    # keep a conservative charset
    name = re.sub(r"[^A-Za-z0-9._+-]", "_", name)
    # clamp length
    return name[:200] or default

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
    # Local server picks a free port and opens browser for the user
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_credentials(creds, token_path)
    return creds

def get_credentials(account_email: Optional[str] = None) -> Tuple[Credentials, str]:
    """
    Returns (creds, actual_account_email).
    If account_email is None, uses DEFAULT_ACCOUNT_EMAIL if present; otherwise will
    attempt to use the first token found in TOKENS_DIR.
    """
    if account_email:
        token_path = _token_path_for(account_email)
        creds = _load_credentials(token_path)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_credentials(creds, token_path)
        if not creds or not creds.valid:
            creds = _interactive_login(token_path)
        actual_email = account_email
    else:
        # Try default
        if DEFAULT_ACCOUNT_EMAIL:
            return get_credentials(DEFAULT_ACCOUNT_EMAIL)
        # Or any token in the folder
        candidates = [p for p in os.listdir(TOKENS_DIR) if p.startswith("gmail-") and p.endswith(".json")]
        if not candidates:
            # Force interactive login to create first token
            em = input("No tokens found. Enter email to authenticate: ").strip()
            return get_credentials(em)
        token_path = os.path.join(TOKENS_DIR, sorted(candidates)[0])
        creds = _load_credentials(token_path)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_credentials(creds, token_path)
        actual_email = re.sub(r'^gmail-|\.json$', '', os.path.basename(token_path))
    if not creds or not creds.valid:
        raise RuntimeError("Failed to obtain valid Google credentials.")
    return creds, actual_email

def _gmail_service(creds: Credentials):
    # cache_discovery=False avoids disk writes that can fail in some environments
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

def _extract_headers(payload: Dict[str, Any]) -> Dict[str, str]:
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    return {
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "date": headers.get("date", ""),
        "subject": headers.get("subject", ""),
        "message-id": headers.get("message-id", ""),
    }

def list_recent_compact(max_results: int = 25, account_email: Optional[str] = None) -> List[Dict[str, Any]]:
    creds, acct = get_credentials(account_email)
    svc = _gmail_service(creds)
    res = svc.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=max_results).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    out: List[Dict[str, Any]] = []
    for mid in ids:
        m = svc.users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["From","To","Cc","Date","Subject","Message-Id"]).execute()
        payload = m.get("payload", {})
        headers = _extract_headers(payload)
        out.append({
            "id": m["id"],
            "threadId": m.get("threadId"),
            "internalDate": m.get("internalDate"),
            "snippet": m.get("snippet", ""),
            **headers,
        })
    return out

def search_emails(query: str, max_results: int = 25, account_email: Optional[str] = None) -> List[Dict[str, Any]]:
    creds, acct = get_credentials(account_email)
    svc = _gmail_service(creds)
    res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    out: List[Dict[str, Any]] = []
    for mid in ids:
        m = svc.users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["From","To","Cc","Date","Subject","Message-Id"]).execute()
        payload = m.get("payload", {})
        headers = _extract_headers(payload)
        out.append({
            "id": m["id"],
            "threadId": m.get("threadId"), 
            "internalDate": m.get("internalDate"),
            "snippet": m.get("snippet", ""),
            **headers,
        }) 
    return out

def _decode_body(part: Dict[str, Any]) -> bytes:
    body = part.get("body", {})
    data = body.get("data")
    if data:
        return base64.urlsafe_b64decode(data.encode("utf-8"))
    return b""

def _walk_parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    parts = []
    if "parts" in payload:
        for p in payload["parts"]:
            parts.extend(_walk_parts(p))
    else:
        parts.append(payload)
    return parts

def get_email(message_id: str, download_attachments: bool = False, account_email: Optional[str] = None) -> Dict[str, Any]:
    creds, acct = get_credentials(account_email)
    svc = _gmail_service(creds)
    m = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = m.get("payload", {})
    headers = _extract_headers(payload)

    # Build plain/html bodies and optionally download attachments
    text_body = ""
    html_body = ""
    attachments: List[Dict[str, Any]] = []
    parts = _walk_parts(payload) if payload else []
    for p in parts:
        mime = p.get("mimeType", "")
        filename = p.get("filename", "")
        if filename and p.get("body", {}).get("attachmentId"):
            # attachment
            att_id = p["body"]["attachmentId"]
            att = svc.users().messages().attachments().get(userId="me", messageId=message_id, id=att_id).execute()
            data = base64.urlsafe_b64decode(att["data"].encode("utf-8"))
            att_meta = {"filename": filename, "mimeType": mime, "size": len(data)}
            if download_attachments:
                dest_dir = os.path.join(DOWNLOAD_DIR, acct, message_id)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, _safe_filename(filename))
                with open(dest, "wb") as f:
                    f.write(data)
                att_meta["saved_to"] = dest
            attachments.append(att_meta)
        else:
            data = _decode_body(p)
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
            if mime == "text/plain":
                text_body += text + "\n"
            elif mime == "text/html":
                html_body += text + "\n"

    return {
        "id": m.get("id"),
        "threadId": m.get("threadId"),
        "labelIds": m.get("labelIds", []),
        "internalDate": m.get("internalDate"),
        **headers,
        "snippet": m.get("snippet", ""),
        "text_body": text_body.strip(),
        "html_body": html_body.strip(),
        "attachments": attachments,
    }

# ---------------- CLI -----------------
def _usage():
    print("Usage:")
    print("  python agent_gmail_read.py list --account EMAIL [--max N]")
    print('  python agent_gmail_read.py search "QUERY" --account EMAIL [--max N]')
    print("  python agent_gmail_read.py get MESSAGE_ID [--download] --account EMAIL")

def main():
    if len(sys.argv) < 2:
        _usage()
        sys.exit(1)
    cmd = sys.argv[1]
    args = sys.argv[2:]

    def get_opt(flag: str, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i+1]
        return default

    account = get_opt("--account", os.getenv("DEFAULT_ACCOUNT_EMAIL"))
    if cmd == "list":
        maxn = int(get_opt("--max", "25"))
        data = list_recent_compact(max_results=maxn, account_email=account)
        print(json.dumps(data, indent=2))
    elif cmd == "search":
        if not args or args[0].startswith("--"):
            _usage(); sys.exit(2)
        query = args[0]
        maxn = int(get_opt("--max", "25"))
        data = search_emails(query, max_results=maxn, account_email=account)
        print(json.dumps(data, indent=2))
    elif cmd == "get":
        if not args or args[0].startswith("--"):
            _usage(); sys.exit(2)
        mid = args[0]
        dl = "--download" in args
        data = get_email(mid, download_attachments=dl, account_email=account)
        print(json.dumps(data, indent=2))
    else:
        _usage(); sys.exit(2)

if __name__ == "__main__":
    main()
