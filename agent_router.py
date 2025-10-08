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
import os, sys, json, logging, re, datetime as dt, calendar
from typing import Any, Dict, List, Optional, Literal, Tuple
from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from openai import OpenAI

import agent_gmail_read as gmail_read
import agent_email_send as gmail_send
import agent_calendly as cal

logger = logging.getLogger(__name__)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LOCAL_TZ = os.getenv("LOCAL_TZ", "Europe/London")
DEFAULT_SIGNATURE = os.getenv("DEFAULT_SIGNATURE", "")

MAX_LOOKBACK_DAYS = 40

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

def _strip_markdown(text: str) -> str:
    """Return a UX-friendly plain text version of a Markdown-ish string."""
    if not text:
        return text or ""
    cleaned = text
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\_(.*?)\_", r"\1", cleaned)
    cleaned = re.sub(r"^[-\*]\s+", "- ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^(\d+)\.\s+", r"\1) ", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("`", "")
    return cleaned.strip()

def _strip_ordinals(value: str) -> str:
    return re.sub(r"(\d+)(st|nd|rd|th)", r"\1", value, flags=re.IGNORECASE)


MONTH_ALIASES = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
MONTH_ALIASES.update({name.lower(): index for index, name in enumerate(calendar.month_abbr) if name})


DATE_PATTERNS_WITH_YEAR = ["%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y"]
DATE_PATTERNS_WITHOUT_YEAR = ["%B %d", "%b %d", "%d %B", "%d %b"]


def _parse_single_day(value: str, today: dt.date) -> Optional[dt.date]:
    if not value:
        return None
    cleaned = _strip_ordinals(value.strip())
    cleaned = cleaned.replace(',', ' ')
    cleaned = re.sub(r"\s+", ' ', cleaned).strip()
    if not cleaned:
        return None
    normalized = cleaned.title()
    for pattern in DATE_PATTERNS_WITH_YEAR:
        try:
            return dt.datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    for pattern in DATE_PATTERNS_WITHOUT_YEAR:
        try:
            candidate = dt.datetime.strptime(normalized, pattern).date()
            candidate = candidate.replace(year=today.year)
            if candidate > today:
                candidate = candidate.replace(year=today.year - 1)
            return candidate
        except ValueError:
            continue
    if normalized.lower() in MONTH_ALIASES:
        month = MONTH_ALIASES[normalized.lower()]
        year = today.year if month <= today.month else today.year - 1
        return dt.date(year, month, 1)
    month_year = re.match(r"^(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})$", normalized, flags=re.IGNORECASE)
    if month_year:
        month = MONTH_ALIASES.get(month_year.group('month').lower())
        if month:
            year = int(month_year.group('year'))
            return dt.date(year, month, 1)
    try:
        return dt.datetime.strptime(cleaned, "%d/%m/%Y").date()
    except ValueError:
        return None


def _month_range(month: int, year: int) -> Tuple[dt.date, dt.date]:
    first_day = dt.date(year, month, 1)
    last_day = dt.date(year, month, calendar.monthrange(year, month)[1])
    return first_day, last_day


def _parse_time_window(time_window: Optional[str]) -> Optional[Tuple[dt.date, dt.date]]:
    if not time_window:
        return None
    original = time_window.strip()
    if not original:
        return None
    tw = original.lower()
    today = dt.date.today()
    earliest = today - dt.timedelta(days=MAX_LOOKBACK_DAYS)

    def clamp_range(start: dt.date, end: dt.date) -> Tuple[dt.date, dt.date]:
        if end < earliest:
            raise ValueError(f"I can only access emails from the last {MAX_LOOKBACK_DAYS} days.")
        if start < earliest:
            start = earliest
        if end > today:
            end = today
        if start > end:
            raise ValueError(f"I couldn't resolve the time window '{original}'.")
        return start, end

    if tw in {"today"}:
        return clamp_range(today, today)
    if tw in {"yesterday", "yday"}:
        day = today - dt.timedelta(days=1)
        return clamp_range(day, day)
    if tw in {"this week"}:
        start = today - dt.timedelta(days=today.weekday())
        return clamp_range(start, today)
    if tw in {"last week"}:
        start_of_this_week = today - dt.timedelta(days=today.weekday())
        end = start_of_this_week - dt.timedelta(days=1)
        start = end - dt.timedelta(days=6)
        return clamp_range(start, end)
    match = re.match(r"(last|past)\s+(\d+)\s+weeks?", tw)
    if match:
        n = int(match.group(2))
        n = max(1, min(n, 12))
        end = today
        start = end - dt.timedelta(days=7 * n)
        return clamp_range(start, end)
    match = re.match(r"(last|past)\s+(\d+)\s+days?", tw)
    if match:
        n = int(match.group(2))
        n = max(1, min(n, MAX_LOOKBACK_DAYS))
        start = today - dt.timedelta(days=n)
        return clamp_range(start, today)
    if tw in {"last month"}:
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - dt.timedelta(days=1)
        start = last_prev_month.replace(day=1)
        return clamp_range(start, last_prev_month)
    if tw in {"this month"}:
        start = today.replace(day=1)
        return clamp_range(start, today)
    match = re.match(r"(last|past)\s+(\d+)\s+months?", tw)
    if match:
        n = int(match.group(2))
        n = max(1, min(n, 3))
        year = today.year
        month = today.month
        for _ in range(n):
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        start, _ = _month_range(month, year)
        return clamp_range(start, today)

    range_split = [p.strip() for p in re.split(r"\s*(?:to|through|until)\s*|(?:\s*-\s*)", original) if p.strip()]
    if len(range_split) == 2:
        start = _parse_single_day(range_split[0], today)
        end = _parse_single_day(range_split[1], today)
        if start and end:
            if end < start:
                start, end = end, start
            return clamp_range(start, end)

    month_alias = MONTH_ALIASES.get(original.lower())
    if month_alias:
        year = today.year if month_alias <= today.month else today.year - 1
        start, end = _month_range(month_alias, year)
        return clamp_range(start, end)

    month_year = re.match(r"^(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})$", original.strip(), flags=re.IGNORECASE)
    if month_year:
        month = MONTH_ALIASES.get(month_year.group('month').lower())
        if month:
            year = int(month_year.group('year'))
            start, end = _month_range(month, year)
            return clamp_range(start, end)

    single = _parse_single_day(original, today)
    if single:
        return clamp_range(single, single)

    raise ValueError(f"I couldn't understand the time window '{original}'. Try 'yesterday', 'last week', or a specific date like 'July 14'.")


def _compose_gmail_query(user_query: Optional[str], date_range: Optional[Tuple[dt.date, dt.date]], focus: Optional[str]) -> Optional[str]:
    parts: List[str] = []
    if user_query:
        parts.append(user_query.strip())
    if date_range:
        start, end = date_range
        after = (start - dt.timedelta(days=1)).strftime("%Y/%m/%d")
        before = (end + dt.timedelta(days=1)).strftime("%Y/%m/%d")
        parts.append(f"after:{after}")
        parts.append(f"before:{before}")
    if focus:
        focus_l = focus.lower()
        if "important" in focus_l:
            parts.append("label:important")
        if "unread" in focus_l:
            parts.append("is:unread")
    if not parts:
        return None
    unique_parts: List[str] = []
    for part in parts:
        if part and part not in unique_parts:
            unique_parts.append(part)
    return " ".join(unique_parts)


def _filter_messages_by_date(messages: List[Dict[str, Any]], date_range: Optional[Tuple[dt.date, dt.date]]) -> List[Dict[str, Any]]:
    if not date_range:
        return messages
    start, end = date_range
    start_dt = dt.datetime.combine(start, dt.time.min, dt.timezone.utc)
    end_dt = dt.datetime.combine(end, dt.time.max, dt.timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    filtered: List[Dict[str, Any]] = []
    for msg in messages:
        try:
            ts = int(msg.get("internalDate", 0))
        except (TypeError, ValueError):
            filtered.append(msg)
            continue
        if start_ms <= ts <= end_ms:
            filtered.append(msg)
    return filtered

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
    except Exception as exc:
        logger.warning("Structured intent parsing failed; falling back to json_object", exc_info=exc)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=base_msgs,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    raw = resp.choices[0].message.content
    try:
        data = json.loads(raw)
    except Exception as exc:
        logger.exception("Failed to parse intent JSON", exc_info=exc)
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
    except Exception as exc:
        logger.warning("Draft email schema call failed; using relaxed format", exc_info=exc)
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
    except Exception as exc:
        logger.exception("Failed to parse drafted email JSON", exc_info=exc)
        data = {"subject": subject_hint or "", "body_text": instruction}
    subject = (data.get("subject") or subject_hint or "").strip()
    body = (data.get("body_text") or instruction or "").strip()
    if DEFAULT_SIGNATURE and DEFAULT_SIGNATURE not in body:
        if not body.endswith("\n"):
            body += "\n"
        body += "\n" + DEFAULT_SIGNATURE
    return subject, body

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
    except Exception as exc:
        logger.debug("Falling back to today for date ref %s", ref, exc_info=exc)
        return today.isoformat()

def handle_structured(nl: str, account_email: Optional[str] = None, calendly_key: Optional[str] = None) -> Dict[str, Any]:
    '''Return the router reply along with intent metadata for UI/clients.'''
    logger.debug("Handling NL request", extra={"account_email": account_email, "calendly_key": calendly_key})
    timestamp = dt.datetime.utcnow().isoformat() + "Z"
    intent = call_llm_for_intent(nl, account_email, calendly_key)
    intent_payload = intent.model_dump(exclude_none=True)

    details: Dict[str, Any] = {}
    text_reply: str

    if intent.kind == "send_email":
        if not intent.to:
            return {
                "text": "I couldn't find a recipient. Please include an email address.",
                "kind": intent.kind,
                "intent": intent_payload,
                "details": {
                    "action": "send_email",
                    "status": "error",
                    "account_email": intent.account_email or account_email,
                },
                "timestamp": timestamp,
                "status": "error",
            }
        subject, body_text = _draft_email(intent.subject, intent.message or (nl or ""), intent.to)
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
        except Exception as exc:
            logger.warning("Failed to resolve reply thread for hint %s", intent.in_reply_to_hint, exc_info=exc)
            reply_mid = None
        res = gmail_send.send_email(
            to=intent.to,
            subject=subject,
            body_text=body_text,
            cc=intent.cc,
            bcc=intent.bcc,
            account_email=intent.account_email or account_email,
            in_reply_to_message_id=reply_mid,
        )
        text_reply = f"Sent! id={res.get('id')} thread={res.get('threadId')}"
        details = {
            "action": "send_email",
            "status": "sent",
            "account_email": intent.account_email or account_email,
            "to": intent.to,
            "cc": intent.cc,
            "bcc": intent.bcc,
            "subject": subject,
            "message_id": res.get("id"),
            "thread_id": res.get("threadId"),
        }

    elif intent.kind == "summarize_emails":
        acct = intent.account_email or account_email
        try:
            date_range = _parse_time_window(intent.time_window)
        except ValueError as exc:
            text_reply = str(exc)
            details = {
                "action": "summarize_emails",
                "status": "error",
                "account_email": acct,
                "time_window": intent.time_window,
                "focus": intent.focus,
            }
        else:
            query = _compose_gmail_query(intent.query, date_range, intent.focus)
            fetch_limit = 120 if date_range else 60
            if query:
                raw_messages = gmail_read.search_emails(query=query, max_results=fetch_limit, account_email=acct)
            else:
                raw_messages = gmail_read.list_recent_compact(max_results=fetch_limit, account_email=acct)
            messages = _filter_messages_by_date(raw_messages, date_range)
            if not messages:
                if date_range:
                    start, end = date_range
                    text_reply = (
                        f"I couldn't find emails between {start.isoformat()} and {end.isoformat()} within the last {MAX_LOOKBACK_DAYS} days."
                    )
                else:
                    text_reply = "I couldn't find any emails that match that request."
                details = {
                    "action": "summarize_emails",
                    "status": "empty",
                    "account_email": acct,
                    "query": query,
                    "time_window": intent.time_window,
                    "focus": intent.focus,
                    "messages_considered": len(messages),
                }
                if date_range:
                    start, end = date_range
                    details["date_range"] = {"start": start.isoformat(), "end": end.isoformat()}
            else:
                summary_input = messages[:40]
                system_prompt = (
                    "You summarize recent emails for the user. Output up to 5 bullets. "
                    "Each bullet: [Sender] - Subject - 1-sentence gist - (date/time). "
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
                        {"role": "user", "content": json.dumps(summary_input)[:100000]},
                    ],
                    temperature=0.2,
                    seed=42,
                )
                text_reply = chat.choices[0].message.content
                details = {
                    "action": "summarize_emails",
                    "status": "summarized",
                    "account_email": acct,
                    "query": query,
                    "messages_considered": len(messages),
                    "focus": intent.focus,
                }
                if date_range:
                    start, end = date_range
                    details["date_range"] = {"start": start.isoformat(), "end": end.isoformat()}
                details["messages_preview"] = summary_input[:5]
    elif intent.kind == "send_scheduling_link":
        details = {
            "action": "send_scheduling_link",
            "status": "pending",
            "account_email": intent.account_email or account_email,
            "calendly_key": intent.calendly_key or calendly_key,
            "to": intent.to,
        }
        link = cal.create_scheduling_link(account_key=intent.calendly_key or calendly_key)
        if not link or not link.get("url"):
            text_reply = "I couldn't generate a Calendly scheduling link."
            details["link"] = None
            details["status"] = "error"
            details["error"] = "Calendly did not return a link"
        else:
            details["link"] = link
            if not intent.to:
                text_reply = f"Scheduling link: {link['url']}"
                details["status"] = "created"
            else:
                body = intent.message or f"Here is my Calendly link to book a time: {link['url']}"
                res = gmail_send.send_email(
                    to=intent.to,
                    subject=intent.subject or "Schedule a time",
                    body_text=body,
                    account_email=intent.account_email or account_email,
                )
                text_reply = f"Sent scheduling link ({link['url']}) to {', '.join(intent.to)}. id={res.get('id')}"
                details["status"] = "sent"
                details["message_id"] = res.get("id")
                details["thread_id"] = res.get("threadId")

    elif intent.kind == "calendly_lookup":
        date_iso = _resolve_date_ref(intent.date_ref)
        window = intent.daypart or "day"
        events = cal.list_events_on(date_iso, window=window, tz="Europe/London", account_key=intent.calendly_key or calendly_key)
        details = {
            "action": "calendly_lookup",
            "status": "ok",
            "calendly_key": intent.calendly_key or calendly_key,
            "date": date_iso,
            "window": window,
            "events": events,
        }
        if not events:
            text_reply = f"No hosted Calendly events found on {date_iso} ({window})."
            details["status"] = "empty"
        else:
            client = OpenAI()
            cal_system = (
                "Summarize hosted Calendly events for the requested date/daypart. "
                "Output up to 5 bullets with: Who (names, emails) - When (local time) - Topic/Type - Notable Q&A - Follow-ups. "
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
            text_reply = chat.choices[0].message.content

    else:
        client = OpenAI()
        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": nl}],
        )
        text_reply = chat.choices[0].message.content
        details = {
            "action": "freeform",
            "status": "ok",
        }


    plain_text = _strip_markdown(text_reply)
    payload: Dict[str, Any] = {
        "text": plain_text,
        "text_markdown": text_reply,
        "kind": intent.kind,
        "intent": intent_payload,
        "details": {k: v for k, v in details.items() if v is not None},
        "timestamp": timestamp,
    }
    if not payload["details"]:
        payload["details"] = None
    status_value = "ok"
    if isinstance(payload["details"], dict) and payload["details"].get("status"):
        status_value = payload["details"]["status"]
    payload["status"] = status_value
    return payload


def handle(nl: str, account_email: Optional[str] = None, calendly_key: Optional[str] = None) -> str:
    return handle_structured(nl, account_email=account_email, calendly_key=calendly_key)["text"]

# CLI
def _usage():
    print('Usage: python agent_router.py "your request here" [--account EMAIL] [--calendly-key KEY] [--json]')

def main():
    if len(sys.argv) < 2:
        _usage(); sys.exit(1)
    nl = sys.argv[1]
    args = sys.argv[2:]
    as_json = False
    if "--json" in args:
        as_json = True
        args = [a for a in args if a != "--json"]
    def get_opt(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i+1 < len(args): return args[i+1]
        return default
    account = get_opt("--account", os.getenv("DEFAULT_ACCOUNT_EMAIL"))
    calkey = get_opt("--calendly-key")
    if as_json:
        result = handle_structured(nl, account_email=account, calendly_key=calkey)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(handle(nl, account_email=account, calendly_key=calkey))

if __name__ == "__main__":
    main()
