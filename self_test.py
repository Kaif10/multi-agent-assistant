
import os, json
import agent_gmail_read as gmail_read
import agent_email_send as gmail_send
import agent_calendly as cal

def main():
    # safer default: don't actually send during self-test
    os.environ.setdefault("DRY_RUN", "1")

    acct = os.getenv("DEFAULT_ACCOUNT_EMAIL")
    print(f"[self_test] DEFAULT_ACCOUNT_EMAIL={acct or '(not set)'}")

    # 1) Gmail list recent (triggers OAuth on first run)
    try:
        msgs = gmail_read.list_recent_compact(max_results=5, account_email=acct)
        print(f"[gmail_read] ok, {len(msgs)} messages listed")
        print(json.dumps(msgs[:2], indent=2))
    except Exception as e:
        print(f"[gmail_read] FAILED: {e}")

    # 2) Gmail send (DRY_RUN=1 means no real email is sent)
    try:
        res = gmail_send.send_email(
            to="you@example.com",
            subject="[self_test] hello",
            body_text="this is a self-test (no send if DRY_RUN=1)",
            account_email=acct,
        )
        print(f"[gmail_send] ok: {res}")
    except Exception as e:
        print(f"[gmail_send] FAILED: {e}")

    # 3) Calendly scheduling link (requires CALENDLY_TOKEN or per-user token)
    try:
        link = cal.create_scheduling_link()
        print(f"[calendly] ok: {link.get('url')}")
    except Exception as e:
        print(f"[calendly] FAILED: {e}")

if __name__ == "__main__":
    main()
