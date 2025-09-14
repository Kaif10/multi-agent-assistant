from __future__ import annotations
import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent_gmail_read as gmail_read
import agent_email_send as gmail_send
import agent_calendly as cal
import agent_router as router


class GmailListRequest(BaseModel):
    account_email: Optional[str] = Field(default=None)
    max_results: int = Field(default=25, ge=1, le=100)


class GmailSearchRequest(BaseModel):
    query: str
    account_email: Optional[str] = Field(default=None)
    max_results: int = Field(default=25, ge=1, le=100)


class GmailGetRequest(BaseModel):
    message_id: str
    account_email: Optional[str] = Field(default=None)
    download_attachments: bool = False


class GmailSendRequest(BaseModel):
    to: List[str]
    subject: str = ""
    body_text: str = ""
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    account_email: Optional[str] = None
    in_reply_to_message_id: Optional[str] = None


class CalendlyEventsRequest(BaseModel):
    date: str  # ISO date
    window: str = Field(default="day", description="morning|afternoon|evening|day")
    tz: str = Field(default=os.getenv("LOCAL_TZ", "UTC"))
    account_key: Optional[str] = None


class CalendlyLinkRequest(BaseModel):
    account_key: Optional[str] = None
    event_type: Optional[str] = None
    max_count: int = 1
    owner_type: str = "EventType"


class RouteRequest(BaseModel):
    text: str
    account_email: Optional[str] = None
    calendly_key: Optional[str] = None


app = FastAPI(title="Agent API", version="0.1.0")


@app.get("/")
def root():
    index_path = os.path.join(os.path.dirname(__file__), "..", "web", "index.html")
    index_path = os.path.abspath(index_path)
    if os.path.exists(index_path):
        return FileResponse(index_path)
    # Fallback to docs if UI not present
    return RedirectResponse(url="/docs", status_code=302)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    fav_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "favicon.svg"))
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/svg+xml")
    return Response(status_code=204)

# Static assets (css/js)
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/gmail/list")
def gmail_list(req: GmailListRequest):
    try:
        return gmail_read.list_recent_compact(
            max_results=req.max_results,
            account_email=req.account_email,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/gmail/search")
def gmail_search(req: GmailSearchRequest):
    try:
        return gmail_read.search_emails(
            query=req.query,
            max_results=req.max_results,
            account_email=req.account_email,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/gmail/get")
def gmail_get(req: GmailGetRequest):
    try:
        return gmail_read.get_email(
            message_id=req.message_id,
            download_attachments=req.download_attachments,
            account_email=req.account_email,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/gmail/send")
def gmail_send(req: GmailSendRequest):
    try:
        return gmail_send.send_email(
            to=req.to,
            subject=req.subject,
            body_text=req.body_text,
            cc=req.cc,
            bcc=req.bcc,
            account_email=req.account_email,
            in_reply_to_message_id=req.in_reply_to_message_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calendly/events")
def calendly_events(req: CalendlyEventsRequest):
    try:
        return cal.list_events_on(req.date, window=req.window, tz=req.tz, account_key=req.account_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calendly/link")
def calendly_link(req: CalendlyLinkRequest):
    try:
        return cal.create_scheduling_link(
            account_key=req.account_key,
            event_type=req.event_type,
            max_count=req.max_count,
            owner_type=req.owner_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/route")
def route_nl(req: RouteRequest):
    try:
        reply = router.handle(req.text, account_email=req.account_email, calendly_key=req.calendly_key)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
