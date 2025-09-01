#!/usr/bin/env python3
"""
Calendly helper (multi-user capable).

By default reads CALENDLY_TOKEN from environment (single-user). For multi-user,
store per-user PATs under: TOKENS_DIR/calendly-{key}.txt and pass account_key.

Functions:
    list_events_between(start_iso, end_iso, account_key=None) -> list[dict]
Convenience:
    list_events_on(date_str="2025-08-30", window="afternoon", account_key=None)

New:
    create_scheduling_link(account_key=None, event_type=None, max_count=1, owner_type="users")
      -> {"url": "<booking url>", ...}

Notes:
- This lists events the PAT owner HOSTS. Calendly API v2.
"""
from __future__ import annotations
import os, sys, json, datetime as dt, httpx, pathlib, re
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()

BASE_URL = "https://api.calendly.com"
TOKENS_DIR = os.getenv("GOOGLE_TOKENS_DIR", "tokens")  # reuse same dir
DEFAULT_PAT = os.getenv("CALENDLY_TOKEN")

def _pat_for(account_key: Optional[str]) -> str:
    if account_key:
        p = os.path.join(TOKENS_DIR, f"calendly-{re.sub(r'[^a-zA-Z0-9_.+-]+','_',account_key)}.txt")
        if os.path.exists(p):
            return open(p,"r").read().strip()
    if DEFAULT_PAT:
        return DEFAULT_PAT
    raise RuntimeError("No Calendly token found. Set CALENDLY_TOKEN or create tokens/calendly-<key>.txt")

async def _get(ac: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = await ac.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

async def _follow(ac: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_url, next_params = url, dict(params or {})
    while True:
        data = await _get(ac, next_url, next_params)
        items += data.get("collection", [])
        nxt = (data.get("pagination") or {}).get("next_page")
        if not nxt: break
        next_url, next_params = nxt, {}
    return items

async def list_events_between_async(start_iso: str, end_iso: str, account_key: Optional[str] = None) -> List[Dict[str, Any]]:
    pat = _pat_for(account_key)
    headers = {"Authorization": f"Bearer {pat}"}
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers) as ac:
        me = await _get(ac, "/users/me", {})
        org = me["resource"]["current_organization"]
        events = await _follow(ac, "/scheduled_events", {"organization": org, "min_start_time": start_iso, "max_start_time": end_iso, "count": 100})
        enriched = []
        for ev in events:
            ev_uri = ev["uri"]
            invitees = await _follow(ac, "/scheduled_events/invitees", {"event": ev_uri, "count": 100})
            enriched.append({
                "name": ev.get("name"),
                "start_time": ev.get("start_time"),
                "end_time": ev.get("end_time"),
                "status": ev.get("status"),
                "location": ev.get("location", {}).get("location", ""),
                "invitees": [
                    {
                        "name": it.get("name"),
                        "email": it.get("email"),
                        "questions_and_answers": it.get("questions_and_answers", []),
                        "timezone": it.get("timezone"),
                    } for it in invitees
                ],
            })
        return enriched

def list_events_between(start_iso: str, end_iso: str, account_key: Optional[str] = None) -> List[Dict[str, Any]]:
    import anyio
    return anyio.run(list_events_between_async, start_iso, end_iso, account_key)

def list_events_on(date_str: str, window: str = "day", tz: str = "UTC", account_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    window: 'morning' (08:00-12:00), 'afternoon' (12:00-17:00), 'evening' (17:00-21:00), 'day' (00:00-23:59)
    """
    z = ZoneInfo(tz)
    date = dt.date.fromisoformat(date_str)
    if window == "morning":
        start = dt.datetime.combine(date, dt.time(8,0), tzinfo=z)
        end = dt.datetime.combine(date, dt.time(12,0), tzinfo=z)
    elif window == "afternoon":
        start = dt.datetime.combine(date, dt.time(12,0), tzinfo=z)
        end = dt.datetime.combine(date, dt.time(17,0), tzinfo=z)
    elif window == "evening":
        start = dt.datetime.combine(date, dt.time(17,0), tzinfo=z)
        end = dt.datetime.combine(date, dt.time(21,0), tzinfo=z)
    else:
        start = dt.datetime.combine(date, dt.time(0,0), tzinfo=z)
        end = dt.datetime.combine(date, dt.time(23,59,59), tzinfo=z)
    return list_events_between(start.isoformat(), end.isoformat(), account_key)

# ---- Scheduling links --------------------------------------------------

# ---- Scheduling links --------------------------------------------------

async def _pick_event_type_uri(ac: httpx.AsyncClient, user_uri: str, preferred_uri: Optional[str]) -> str:
    """
    Return an Event Type URI to use for scheduling links.
    Priority:
      1) preferred_uri if provided
      2) the first active event type owned by the user
    """
    if preferred_uri:
        return preferred_uri

    # List event types for this user
    # Calendly API: GET /event_types?user=<user_uri>&count=100
    data = await _get(ac, "/event_types", {"user": user_uri, "count": 100})
    collection = data.get("collection", [])
    if not collection:
        raise RuntimeError("No Calendly event types found for this user. Create at least one event type in Calendly.")

    # Prefer active/public types if present, else just take the first
    def is_active(et):
        # be lenient; different tenants expose slightly different flags
        return (
            et.get("active", True) and
            not et.get("deleted_at")
        )

    for et in collection:
        if is_active(et):
            return et["uri"]
    # fallback to first one if nothing flagged active
    return collection[0]["uri"]

async def create_scheduling_link_async(
    account_key: Optional[str] = None,
    event_type: Optional[str] = None,  # full URI preferred; if None we auto-pick
    max_count: int = 1,
    owner_type: str = "EventType",     # required by your tenant
) -> Dict[str, Any]:
    """
    Create a Calendly scheduling link for a specific Event Type.
    Returns {"url": "...", ...}. Surfaces Calendly's error JSON on failure.
    """
    pat = _pat_for(account_key)
    headers = {"Authorization": f"Bearer {pat}"}
    preferred_et_uri = event_type or os.getenv("CALENDLY_EVENT_TYPE_URI")

    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers) as ac:
        me = await _get(ac, "/users/me", {})
        user_uri = me["resource"]["uri"]  # https://api.calendly.com/users/UUID

        et_uri = await _pick_event_type_uri(ac, user_uri, preferred_et_uri)

        payload = {
            "owner": et_uri,
            "owner_type": "EventType",   # <-- critical fix
            "max_event_count": max_count,
        }

        r = await ac.post("/scheduling_links", json=payload, timeout=30)
        if r.status_code >= 400:
            try:
                err = r.json()
            except Exception:
                err = {"error": r.text}
            raise httpx.HTTPStatusError(
                f"Calendly scheduling_links error {r.status_code}: {err}",
                request=r.request, response=r
            )

        data = r.json()
        res = data.get("resource", {})
        url = res.get("booking_url") or res.get("url")
        return {"url": url, **res}

def create_scheduling_link(
    account_key: Optional[str] = None,
    event_type: Optional[str] = None,
    max_count: int = 1,
    owner_type: str = "EventType"
) -> Dict[str, Any]:
    import anyio
    return anyio.run(create_scheduling_link_async, account_key, event_type, max_count, owner_type)




# CLI
def _usage():
    print("Usage: python agent_calendly.py 2025-08-30 afternoon [--tz Europe/London] [--key user1]")

def main():
    args = sys.argv[1:]
    date = args[0] if len(args) >= 1 else dt.date.today().isoformat()
    window = args[1] if len(args) >= 2 else "day"
    tz = "Europe/London"
    key = None
    if "--tz" in args:
        i = args.index("--tz"); tz = args[i+1]
    if "--key" in args:
        i = args.index("--key"); key = args[i+1]
    data = list_events_on(date, window=window, tz=tz, account_key=key)
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    main()
