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
LOCAL_TZ = os.getenv("LOCAL_TZ", "Europe/London")
DEFAULT_SIGNATURE = os.getenv("DEFAULT_SIGNATURE", "")

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

SYSTEM = """You convert user requests into a STRICT JSON intent.
Rules:
- Allowed kinds: send_email | summarize_emails | calendly_lookup | send_scheduling_link | other
- Never invent email addresses or names. If a field is unknown, set it to null (or [] for list fields).
- Keep subject short and neutral. Use the user's wording for message when provided; otherwise draft a brief, professional first version.
- For summarize_emails, infer time_window (e.g., "yesterday", "last 3 days") and optional query/focus from the user's words. Do not guess specifics.
- For calendly_lookup, infer date_ref (e.g., "monday", ISO date) and daypart (morning/afternoon/evening) only if the user implies it.
- Output ONLY JSON matching the schema; no commentary.
"""

# Strict JSON Schema for intent extraction (used with response_format=json_schema)
INTENT_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["send_email","summarize_emails","calendly_lookup","send_scheduling_link","other"]},
        "account_email": {"type": ["string","null"]},
        "to": {"type": ["array","null"], "items": {"type": "string"}},
        "subject": {"type": ["string","null"]},
        "message": {"type": ["string","null"]},
        "cc": {"type": ["array","null"], "items": {"type": "string"}},
        "bcc": {"type": ["array","null"], "items": {"type": "string"}},
        "in_reply_to_hint": {"type": ["string","null"]},
        "time_window": {"type": ["string","null"]},
        "query": {"type": ["string","null"]},
        "focus": {"type": ["string","null"]},
        "calendly_key": {"type": ["string","null"]},
        "date_ref": {"type": ["string","null"]},
        "daypart": {"type": ["string","null"], "enum": ["morning","afternoon","evening", None]},
    },
    "required": ["kind"],
}

# Few-shot examples to ground behavior
FEW_SHOTS: list[dict] = [
    {"role": "user", "content": "send an email to john@example.com saying I can’t join tomorrow’s standup"},
    {"role": "assistant", "content": json.dumps({
        "kind": "send_email",
        "to": ["john@example.com"],
        "subject": "About tomorrow’s standup",
        "message": "Hi John, I won’t be able to join tomorrow’s standup.",
        "cc": None, "bcc": None, "account_email": None,
        "in_reply_to_hint": None, "time_window": None, "query": None, "focus": None,
        "calendly_key": None, "date_ref": None, "daypart": None,
    })},

    {"role": "user", "content": "summarize my important emails from yesterday about invoices"},
    {"role": "assistant", "content": json.dumps({
        "kind": "summarize_emails",
        "time_window": "yesterday",
        "query": None,
        "focus": "invoices",
        "to": None, "subject": None, "message": None, "cc": None, "bcc": None, "account_email": None,
        "in_reply_to_hint": None, "calendly_key": None, "date_ref": None, "daypart": None,
    })},

    {"role": "user", "content": "who did I meet on Calendly on Monday afternoon?"},
    {"role": "assistant", "content": json.dumps({
        "kind": "calendly_lookup",
        "date_ref": "monday",
        "daypart": "afternoon",
        "to": None, "subject": None, "message": None, "cc": None, "bcc": None, "account_email": None,
        "in_reply_to_hint": None, "time_window": None, "query": None, "focus": None, "calendly_key": None,
    })},

    {"role": "user", "content": "share a Calendly link with jane@example.com"},
    {"role": "assistant", "content": json.dumps({
        "kind": "send_scheduling_link",
        "to": ["jane@example.com"],
        "subject": "Schedule a time",
        "message": "Here is my Calendly link to book a time.",
        "cc": None, "bcc": None, "account_email": None,
        "in_reply_to_hint": None, "time_window": None, "query": None, "focus": None,
        "calendly_key": None, "date_ref": None, "daypart": None,
    })},

    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": json.dumps({"kind": "other", "to": None, "subject": None, "message": None, "cc": None, "bcc": None, "account_email": None, "in_reply_to_hint": None, "time_window": None, "query": None, "focus": None, "calendly_key": None, "date_ref": None, "daypart": None})},
]

def call_llm_for_intent(nl: str, account_email: Optional[str], calendly_key: Optional[str]) -> Intent:
    client = OpenAI()
    base_msgs = [{"role": "system", "content": SYSTEM}] + FEW_SHOTS + [
        {"role": "user", "content": nl},
        {"role": "user", "content": f"account_email={account_email or ''} calendly_key={calendly_key or ''}"},
    ]

    # Prefer strict schema; fall back to generic JSON if not supported
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=base_msgs,
            temperature=0.0,
            seed=42,  # best-effort determinism
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "intent", "schema": INTENT_JSON_SCHEMA, "strict": True},
            },
        )
    except Exception:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=base_msgs,
            temperature=0.0,
            response_format={"type": "json_object"},
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

def _draft_email(subject_hint: Optional[str], instruction: str, to: Optional[List[str]]) -> Tuple[str, str]:
    """
    Use the LLM to produce a professional subject and body from a terse instruction.
    Returns (subject, body_text). Appends DEFAULT_SIGNATURE if present.
    """
    client = OpenAI()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "subject": {"type": "string"},
            "body_text": {"type": "string"},
        },
        "required": ["subject", "body_text"],
    }
    recip = ", ".join(to or [])
    system = (
        "You are an expert communications assistant. Write a concise, professional email based on a short instruction. "
        "Tone: respectful, clear, and empathetic when the topic is sensitive (e.g., employment changes). "
        "Avoid slang or harsh phrasing. Do not include legal advice or confidential details. "
        "Prefer neutral wording (e.g., 'We regret to inform you...'). "
        "Return ONLY JSON with subject and body_text."
    )
    user = (
        f"Instruction: {instruction}\n"
        f"Recipient(s): {recip or '(not specified)'}\n"
        f"Subject hint: {subject_hint or '(none)'}\n"
        f"Signature: {DEFAULT_SIGNATURE or '(none)'}\n"
        "Constraints: <= 180 words. If no recipient name is known, use a generic greeting (e.g., 'Hello')."
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            seed=42,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "email_draft", "schema": schema, "strict": True},
            },
        )
    except Exception:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    raw = resp.choices[0].message.content
    try:
        data = json.loads(raw)
    except Exception:
        data = {"subject": subject_hint or "", "body_text": instruction}
    subject = (data.get("subject") or subject_hint or "").strip()
    body = (data.get("body_text") or instruction or "").strip()
    if DEFAULT_SIGNATURE and DEFAULT_SIGNATURE not in body:
        if not body.endswith("\n"):
            body += "\n"
        body += "\n" + DEFAULT_SIGNATURE
    return subject, body

def _gmail_query_from_window(time_window: Optional[str]) -> Optional[str]:
    if not time_window:
        return None
    tw = (time_window or "").strip().lower()
    today = dt.date.today()
    if tw in {"today"}:
        after = today.strftime("%Y/%m/%d")
        return f"after:{after}"
    if tw in {"yesterday", "yday"}:
        y = today - dt.timedelta(days=1)
        after = y.strftime("%Y/%m/%d")
        before = today.strftime("%Y/%m/%d")
        return f"after:{after} before:{before}"
    m = re.match(r"(last|past)\s+(\d+)\s+days?", tw)
    if m:
        n = int(m.group(2)); n = max(1, n)
        return f"newer_than:{n}d"
    m = re.match(r"(last|past)\s+(\d+)\s+weeks?", tw)
    if m:
        n = int(m.group(2)); n = max(1, n)
        return f"newer_than:{n*7}d"
    if tw in {"last week"}:
        return "newer_than:7d"
    # ISO-like date ranges: "2025-08-30", or "2025-08-01..2025-08-07"
    try:
        d = dt.date.fromisoformat(tw)
        after = d.strftime("%Y/%m/%d")
        before = (d + dt.timedelta(days=1)).strftime("%Y/%m/%d")
        return f"after:{after} before:{before}"
    except Exception:
        pass
    rng = re.match(r"(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})", tw)
    if rng:
        a = dt.date.fromisoformat(rng.group(1)).strftime("%Y/%m/%d")
        b = dt.date.fromisoformat(rng.group(2)).strftime("%Y/%m/%d")
        return f"after:{a} before:{b}"
    return None

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
        # Prefer last occurrence in the past (never 'today')
        delta = 7 if delta == 0 else delta
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
        # Always draft or refine the email for professionalism
        subject, body_text = _draft_email(intent.subject, intent.message or (nl or ""), intent.to)
        # Best-effort resolve a reply target from an in-reply hint
        reply_mid = None
        try:
            if intent.in_reply_to_hint:
                acct = intent.account_email or account_email
                hint = intent.in_reply_to_hint.strip()
                if hint:
                    q = f'subject:"{hint}"' if not re.search(r":|\(|\)|\s", hint) else hint
                    hits = gmail_read.search_emails(query=q, max_results=1, account_email=acct)
                    if hits:
                        reply_mid = hits[0]["id"]
        except Exception:
            reply_mid = None
        res = gmail_send.send_email(
            to=intent.to,
            subject=subject,
            body_text=body_text,
            cc=intent.cc, bcc=intent.bcc,
            account_email=intent.account_email or account_email,
            in_reply_to_message_id=reply_mid,
        )
        return f"Sent! id={res.get('id')} thread={res.get('threadId')}"

    if intent.kind == "summarize_emails":
        query = intent.query or _gmail_query_from_window(intent.time_window)
        acct = intent.account_email or account_email
        if query:
            messages = gmail_read.search_emails(query=query, max_results=40, account_email=acct)
        else:
            messages = gmail_read.list_recent_compact(max_results=40, account_email=acct)

        system_prompt = (
            "You summarize recent emails for the user. Output up to 5 bullets. "
            "Each bullet: [Sender] — Subject — 1-sentence gist — (date/time). "
            "End with 'Key actions:' and up to 3 bullets of next steps (if any). "
            "Respect any time window or focus the user asked for. Be concise (<= 1200 chars)."
        )
        client = OpenAI()
        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User request: {nl}"},
                {"role": "user", "content": f"Local timezone: {LOCAL_TZ}"},
                {"role": "user", "content": "Recent emails (JSON array):"},
                {"role": "user", "content": json.dumps(messages)[:100000]},
            ],
            temperature=0.2,
            seed=42,
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
        cal_system = (
            "Summarize hosted Calendly events for the requested date/daypart. "
            "Output up to 5 bullets with: Who (names, emails) — When (local time) — Topic/Type — Notable Q&A — Follow-ups. "
            "If none, reply: 'No hosted events on <date> (<window>)'. Keep <= 600 chars."
        )
        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": cal_system},
                {"role": "user", "content": f"Date: {date_iso}  Window: {window}  TZ: {LOCAL_TZ}"},
                {"role": "user", "content": json.dumps(events)[:100000]},
            ],
            temperature=0.2,
            seed=42,
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
