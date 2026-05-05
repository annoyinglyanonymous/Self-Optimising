"""
Gmail SMTP sender.

For dev / small-scale testing only. Limits:
- Free Gmail: 500/day. Workspace: 2000/day.
- Single sender = single reputation. No warmup, no rotation.
- No native reply webhooks — fire fake webhook events to /webhooks/instantly
  to drive the bandit's reward signal during testing.

Credentials are passed in as a `creds` dict by the dispatcher in sender.py;
this module no longer reads pydantic settings directly. Required keys:
    GMAIL_USERNAME
    GMAIL_APP_PASSWORD
Optional keys:
    GMAIL_FROM_ADDRESS  (defaults to GMAIL_USERNAME)
    GMAIL_FROM_NAME     (display name; not required)
"""
import logging
from email.message import EmailMessage
from email.utils import make_msgid

import aiosmtplib

log = logging.getLogger(__name__)


async def send_email(
    *,
    creds: dict[str, str],
    to_email: str,
    to_name: str | None,
    subject: str,
    body: str,
) -> str:
    """Send a plain-text email via Gmail SMTP. Returns the Message-Id header."""
    username = creds.get("GMAIL_USERNAME", "")
    app_password = creds.get("GMAIL_APP_PASSWORD", "")
    if not username or not app_password:
        raise RuntimeError("GMAIL_USERNAME and GMAIL_APP_PASSWORD must be set")

    from_addr = creds.get("GMAIL_FROM_ADDRESS") or username
    from_name = creds.get("GMAIL_FROM_NAME", "")
    from_field = f"{from_name} <{from_addr}>" if from_name else from_addr
    to_field = f"{to_name} <{to_email}>" if to_name else to_email

    msg = EmailMessage()
    msg["From"] = from_field
    msg["To"] = to_field
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname="smtp.gmail.com",
        port=587,
        start_tls=True,
        username=username,
        password=app_password,
    )

    message_id = msg["Message-ID"]
    log.info("gmail send ok to=%s subject=%r msgid=%s", to_email, subject, message_id)
    return message_id


async def test_connection(creds: dict[str, str]) -> tuple[bool, str | None]:
    """Authenticate with Gmail SMTP without sending. Returns (ok, error_msg)."""
    username = creds.get("GMAIL_USERNAME", "")
    app_password = creds.get("GMAIL_APP_PASSWORD", "")
    if not username or not app_password:
        return False, "GMAIL_USERNAME or GMAIL_APP_PASSWORD is empty"

    smtp = aiosmtplib.SMTP(hostname="smtp.gmail.com", port=587, start_tls=True, timeout=15)
    try:
        await smtp.connect()
        await smtp.login(username, app_password)
        await smtp.quit()
        return True, None
    except aiosmtplib.SMTPAuthenticationError as e:
        return False, f"SMTP auth failed: {e}"
    except Exception as e:
        return False, f"SMTP error: {e}"
