"""
Instantly API client.

Pushes a generated draft into Instantly so it gets sent through Instantly's
warmed inboxes. Inbound events (sent/opened/replied/bounced) come back via
the /webhooks/instantly endpoint and drive the bandit's reward signal.

Credentials are passed in as a `creds` dict by the dispatcher in sender.py;
this module no longer reads pydantic settings directly. Required keys:
    INSTANTLY_API_KEY
    INSTANTLY_DEFAULT_CAMPAIGN_ID
Optional keys:
    INSTANTLY_API_BASE_URL  (defaults to https://api.instantly.ai/api/v2)
"""
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.instantly.ai/api/v2"


class InstantlyError(RuntimeError):
    pass


def _campaign_for(template_family: str, default_campaign: str, campaign_map: dict[str, str]) -> str:
    return campaign_map.get(template_family, default_campaign)


async def push_lead(
    *,
    creds: dict[str, str],
    campaign_map: dict[str, str] | None,
    email: str,
    first_name: str | None,
    last_name: str | None,
    company: str | None,
    template_family: str,
    custom_subject: str,
    custom_body: str,
) -> str:
    """Add a lead to the matching Instantly campaign with custom subject/body
    variables. Returns Instantly's lead id (or empty string if not in the
    response — varies by API version)."""
    api_key = creds.get("INSTANTLY_API_KEY", "")
    if not api_key:
        raise InstantlyError("INSTANTLY_API_KEY not set")

    default_campaign = creds.get("INSTANTLY_DEFAULT_CAMPAIGN_ID", "")
    base_url = creds.get("INSTANTLY_API_BASE_URL") or DEFAULT_BASE_URL

    campaign_id = _campaign_for(template_family, default_campaign, campaign_map or {})
    if not campaign_id:
        raise InstantlyError(
            f"No Instantly campaign configured for template_family={template_family!r}. "
            f"Set INSTANTLY_DEFAULT_CAMPAIGN_ID."
        )

    payload: dict[str, Any] = {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "company_name": company,
        "campaign": campaign_id,
        # Instantly's custom-variable field name has changed across API
        # versions ("personalization" / "custom_variables"). If pushes 4xx
        # with "unknown field", swap the key here per current Instantly docs.
        "custom_variables": {
            "custom_subject": custom_subject,
            "custom_body": custom_body,
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{base_url.rstrip('/')}/leads"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code >= 400:
        log.error("instantly push failed: %s %s", resp.status_code, resp.text)
        raise InstantlyError(f"Instantly returned {resp.status_code}: {resp.text}")

    data: dict[str, Any] = {}
    try:
        data = resp.json()
    except Exception:
        pass
    instantly_id = str(data.get("id") or data.get("lead_id") or "")
    log.info(
        "instantly push ok email=%s campaign=%s instantly_id=%s",
        email, campaign_id, instantly_id or "?",
    )
    return instantly_id


async def test_connection(creds: dict[str, str]) -> tuple[bool, str | None]:
    """Hit a cheap read-only endpoint with the API key. Returns (ok, error_msg)."""
    api_key = creds.get("INSTANTLY_API_KEY", "")
    if not api_key:
        return False, "INSTANTLY_API_KEY is empty"
    base_url = creds.get("INSTANTLY_API_BASE_URL") or DEFAULT_BASE_URL
    url = f"{base_url.rstrip('/')}/campaigns?limit=1"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return True, None
        return False, f"Instantly returned {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"HTTP error: {e}"
