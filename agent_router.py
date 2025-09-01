#!/usr/bin/env python3
"""
Natural-language router for multi-user Gmail + Calendly.
- Classifies intent with OpenAI
- Calls local helpers to do the action
- Multi-user via --account (Gmail) and --calendly-key (Calendly)

Examples:
  python agent_router.py "send an email to john@example.com saying I won't be in tomorrow" --account you@example.com
  python agent_router.py "summarize my important emails from yesterday" --account you@example.com
  python agent_router.py "who did I meet on Calendly on Monday afternoon?" --calendly-key you@example.com
"""
from __future__ import annotations
import os, sys, json, re, datetime as dt
from typing import Any, Dict, List, Optional, Literal, Tuple
from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from openai import OpenAI

import agent_gmail_read as gmail_read
import agent_email_send as gmail_send
import agent_calendly as cal

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ---------- Schemas ---------
class Intent(BaseModel):
    kind: Literal["send_email", "summarize_emails", "calendly_lookup", "send_scheduling_link", "other"]
    # Common slots
    account_email: Optional[str] = None

    # send_email
    to: Optional[List[str]] = None
    subject: Optional[str] = None
    message: Optional[str] = None
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    in_reply_to_hint: Optional[str] = None  # subject/thread hint

    # summarize_emails
    time_window: Optional[str] = None  # e.g., "yesterday", "last 3 days"
    query: Optional[str] = None        # gmail search query if user specified
    focus: Optional[str] = None        # e.g., "important", "from my manager"

    # calendly_lookup
    calendly_key: Optional[str] = None
    date_ref: Optional[str] = None  # e.g., "monday", "yesterday"
    daypart: Optional[str] = None   # morning/afternoon/evening

def _ensure_list(x):
    """Normalize input into a list of strings."""
    if x is None:
        return None
    if isinstance(x, list):
        return [s.strip() for s in x if s and isinstance(s, str)]
    if isinstance(x, str):
        # split only on commas/semicolons so "Name <email@x.com>" stays intact
        return [s for s in re.split(r'[;,]+', x.strip()) if s]
    return [str(x)]

SYSTEM = """You are a routing assistant. Extract structured intent JSON ONLY.
- If the user asks to send an email, set kind=send_email and fill to, subject (short), message (first-draft), cc/bcc if present.
- If it's about summarizing/reading emails, set kind=summarize_emails and infer a time_window like "yesterday" or "last 3 days" and include any filters or search query if the user stated them.
- If the user asks about Calendly meetings, set kind=calendly_lookup and infer date_ref (like "monday") and daypart if given.
- If the user asks to send/share a Calendly scheduling link, set kind=send_scheduling_link and set "to" and optionally a short "message".
- Otherwise kind=other.
Return MINIMAL valid JSON, no commentary.
"""

def call_llm_for_intent(nl: str, account_email: Optional[str], calendly_key: Optional[str]) -> Intent:
    client = OpenAI()
    prompt = f"{SYSTEM}\nUser: {nl}\nRemember account_email={account_email or ''} calendly_key={calendly_key or ''}."
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role":"user","content":prompt}],
        temperature=0.2,
        response_format={"type":"json_object"},
    )
    raw = resp.choices[0].message.content
    try:
        data = json.loads(raw)
    except Exception:
        data = {"kind": "other"}

    # Normalize list-like fields so Pydantic doesn’t choke
    for fld in ("to", "cc", "bcc"):
        if fld in data:
            data[fld] = _ensure_list(data[fld])

    if account_email and not data.get("account_email"):
        data["account_email"] = account_email
    if calendly_key and not data.get("calendly_key"):
        data["calendly_key"] = calendly_key

    return Intent(**data)

def _resolve_date_ref(date_ref: Optional[str]) -> str:
    if not date_ref:
        return dt.date.today().isoformat()
    today = dt.date.today()
    ref = date_ref.strip().lower()
    if ref in ("today",):
        return today.isoformat()
    if ref in ("yesterday","yday"):
        return (today - dt.timedelta(days=1)).isoformat()
    weekdays = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    if ref in weekdays:
        i = weekdays.index(ref)
        delta = (today.weekday() - i) % 7
        if delta == 0:
            return today.isoformat()
        return (today - dt.timedelta(days=delta)).isoformat()
    try:
        return dt.date.fromisoformat(ref).isoformat()
    except Exception:
        return today.isoformat()

def handle(nl: str, account_email: Optional[str] = None, calendly_key: Optional[str] = None) -> str:
    intent = call_llm_for_intent(nl, account_email, calendly_key)

    if intent.kind == "send_email":
        if not intent.to:
            return "I couldn't find a recipient. Please include an email address."
        res = gmail_send.send_email(
            to=intent.to,
            subject=intent.subject or "",
            body_text=intent.message or "",
            cc=intent.cc, bcc=intent.bcc,
            account_email=intent.account_email or account_email,
        )
        return f"Sent! id={res.get('id')} thread={res.get('threadId')}"

    if intent.kind == "summarize_emails":
        messages = gmail_read.list_recent_compact(max_results=50, account_email=intent.account_email or account_email)
        client = OpenAI()
        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system","content":"You are a helpful assistant that summarizes emails. Focus on the user's request. Be concise."},
                {"role":"user","content": nl},
                {"role":"user","content": "Here are recent emails (JSON array):"},
                {"role":"user","content": json.dumps(messages)[:120000]},
            ],
            temperature=0.3,
        )
        return chat.choices[0].message.content

    if intent.kind == "send_scheduling_link":
        # Create a one-time scheduling link and email it (or just return it if no recipient).
        link = cal.create_scheduling_link(account_key=intent.calendly_key or calendly_key)
        if not link or not link.get("url"):
            return "I couldn't generate a Calendly scheduling link."
        if not intent.to:
            return f"Scheduling link: {link['url']}"
        body = intent.message or f"Here is my Calendly link to book a time: {link['url']}"
        res = gmail_send.send_email(
            to=intent.to,
            subject=intent.subject or "Schedule a time",
            body_text=body,
            account_email=intent.account_email or account_email,
        )
        return f"Sent scheduling link ({link['url']}) to {', '.join(intent.to)}. id={res.get('id')}"

    if intent.kind == "calendly_lookup":
        date_iso = _resolve_date_ref(intent.date_ref)
        window = intent.daypart or "day"
        events = cal.list_events_on(date_iso, window=window, tz="Europe/London", account_key=intent.calendly_key or calendly_key)
        if not events:
            return f"No hosted Calendly events found on {date_iso} ({window})."
        client = OpenAI()
        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system","content":"Extract who the user met with (names, emails) and summarize any Q&A notes in 3-5 bullets."},
                {"role":"user","content": json.dumps(events)[:120000]},
            ],
            temperature=0.2,
        )
        return chat.choices[0].message.content

    client = OpenAI()
    chat = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role":"user","content": nl}],
    )
    return chat.choices[0].message.content

# CLI
def _usage():
    print('Usage: python agent_router.py "your request here" [--account EMAIL] [--calendly-key KEY]')

def main():
    if len(sys.argv) < 2:
        _usage(); sys.exit(1)
    nl = sys.argv[1]
    args = sys.argv[2:]
    def get_opt(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i+1 < len(args): return args[i+1]
        return default
    account = get_opt("--account", os.getenv("DEFAULT_ACCOUNT_EMAIL"))
    calkey = get_opt("--calendly-key")
    print(handle(nl, account_email=account, calendly_key=calkey))

if __name__ == "__main__":
    main()
