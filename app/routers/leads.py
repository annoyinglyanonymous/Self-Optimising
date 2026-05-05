import csv
import io
import re
from datetime import datetime, timezone

from fastapi import APIRouter,Depends,HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.database import get_db
from app.models import Lead,Event,Touch,User
from app.services.policy_engine import decide_policy
from app.services.message_gen import generate_email
from app.services.safety import assert_safe_to_send, SafetyViolation
from app.services.sender import send as send_message
from app.services.auth import current_user
from app.services import app_settings
router=APIRouter(
    prefix="/leads",
    tags=["leads"],
    dependencies=[Depends(current_user)],
)
VALID_ENRICHMENT_STATUSES = {"pending", "in_progress", "complete", "failed"}


class LeadIngest(BaseModel):#pydantic schema
    email: str
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    domain: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    persona: str | None = None
    company_size: str | None = None
    state: str | None = None
    growth_stage: str | None = None
    tech_stack: list[str] | None = None
    enrichment_status: str | None = None  # defaults to "complete" if not supplied


class LeadUpdate(BaseModel):
    """Same fields as LeadIngest but every field is optional — used for PATCH."""
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    domain: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    persona: str | None = None
    company_size: str | None = None
    state: str | None = None
    growth_stage: str | None = None
    tech_stack: list[str] | None = None
    enrichment_status: str | None = None


async def _require_approval_enabled(db: AsyncSession) -> bool:
    return (await app_settings.get(db, "REQUIRE_APPROVAL") or "").lower() in ("1", "true", "yes")


@router.post("/{lead_id}/generate")
async def generate_message(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(current_user),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead Not Found")
    try:
        await assert_safe_to_send(db, lead.domain or "")
    except SafetyViolation as e:
        raise HTTPException(status_code=423, detail=str(e))

    policy = await decide_policy(db, lead)
    message = await generate_email(lead, policy)

    require_approval = await _require_approval_enabled(db)
    initial_status = "pending_approval" if require_approval else "approved"

    touch = Touch(
        lead_id=lead.id,
        channel=policy.channel,
        angle=policy.angle,
        template_family=policy.template_family,
        subject=message["subject"],
        body=message["body"],
        status=initial_status,
    )
    db.add(touch)
    await db.flush()

    if require_approval:
        # Stop here — human will approve/reject from the dashboard.
        return {
            "policy": {
                "channel": policy.channel,
                "angle": policy.angle,
                "is_exploration": policy.is_exploration,
            },
            "message": message,
            "touch_id": str(touch.id),
            "status": "pending_approval",
            "send_ref": "",
        }

    # Auto-approved path — send immediately.
    send_ref = ""
    if policy.channel == "email":
        try:
            send_ref = await send_message(
                db=db,
                email=lead.email,
                first_name=lead.first_name,
                last_name=lead.last_name,
                company=lead.company,
                template_family=policy.template_family,
                subject=message["subject"],
                body=message["body"],
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Send failed: {e}")
    touch.decided_at = datetime.now(timezone.utc)
    if user is not None:
        touch.approved_by_user_id = user.id
    return {
        "policy": {
            "channel": policy.channel,
            "angle": policy.angle,
            "is_exploration": policy.is_exploration,
        },
        "message": message,
        "touch_id": str(touch.id),
        "status": "approved",
        "send_ref": send_ref,
    }


# -------- Approval workflow endpoints ---------------------------------------

class TouchEdit(BaseModel):
    subject: str | None = None
    body: str | None = None


@router.get("/touches/pending")
async def list_pending_touches(db: AsyncSession = Depends(get_db)):
    """Touches awaiting human approval, with their lead context. Newest first."""
    q = (
        select(Touch, Lead)
        .join(Lead, Lead.id == Touch.lead_id)
        .where(Touch.status == "pending_approval")
        .order_by(Touch.created_at.desc())
    )
    rows = (await db.execute(q)).all()
    return {
        "items": [
            {
                "touch_id": str(t.id),
                "lead_id": str(t.lead_id),
                "lead": {
                    "email": l.email,
                    "first_name": l.first_name,
                    "last_name": l.last_name,
                    "company": l.company,
                    "title": l.title,
                    "persona": l.persona,
                },
                "channel": t.channel,
                "angle": t.angle,
                "template_family": t.template_family,
                "subject": t.subject,
                "body": t.body,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for (t, l) in rows
        ]
    }


@router.patch("/touches/{touch_id}")
async def edit_touch(
    touch_id: str,
    data: TouchEdit,
    db: AsyncSession = Depends(get_db),
):
    """Edit subject/body on a pending touch. Only allowed while pending."""
    touch = (await db.execute(select(Touch).where(Touch.id == touch_id))).scalar_one_or_none()
    if touch is None:
        raise HTTPException(status_code=404, detail="Touch not found")
    if touch.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Cannot edit a touch in status {touch.status!r}")
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(touch, field, value)
    await db.flush()
    return {"id": str(touch.id), "subject": touch.subject, "body": touch.body, "status": touch.status}


@router.post("/touches/{touch_id}/approve")
async def approve_touch(
    touch_id: str,
    data: TouchEdit,  # optional last-minute edits
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Approve a pending touch and send it. Body fields (if supplied) overwrite
    the touch's subject/body just before sending — for last-minute edits."""
    touch = (await db.execute(select(Touch).where(Touch.id == touch_id))).scalar_one_or_none()
    if touch is None:
        raise HTTPException(status_code=404, detail="Touch not found")
    if touch.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Touch is {touch.status!r}, not pending_approval")

    # Apply any last-minute edits.
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        if value is not None:
            setattr(touch, field, value)

    lead = (await db.execute(select(Lead).where(Lead.id == touch.lead_id))).scalar_one()

    try:
        await assert_safe_to_send(db, lead.domain or "")
    except SafetyViolation as e:
        raise HTTPException(status_code=423, detail=str(e))

    send_ref = ""
    if touch.channel == "email":
        try:
            send_ref = await send_message(
                db=db,
                email=lead.email,
                first_name=lead.first_name,
                last_name=lead.last_name,
                company=lead.company,
                template_family=touch.template_family or "",
                subject=touch.subject or "",
                body=touch.body or "",
            )
        except Exception as e:
            # Leave touch as pending so user can retry / fix creds.
            raise HTTPException(status_code=502, detail=f"Send failed: {e}")

    touch.status = "approved"
    touch.decided_at = datetime.now(timezone.utc)
    if user is not None:
        touch.approved_by_user_id = user.id
    await db.flush()
    return {"touch_id": str(touch.id), "status": "approved", "send_ref": send_ref}


@router.post("/touches/{touch_id}/reject")
async def reject_touch(
    touch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(current_user),
):
    touch = (await db.execute(select(Touch).where(Touch.id == touch_id))).scalar_one_or_none()
    if touch is None:
        raise HTTPException(status_code=404, detail="Touch not found")
    if touch.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Touch is {touch.status!r}, not pending_approval")
    touch.status = "rejected"
    touch.decided_at = datetime.now(timezone.utc)
    if user is not None:
        touch.approved_by_user_id = user.id
    await db.flush()
    return {"touch_id": str(touch.id), "status": "rejected"}
@router.patch("/{lead_id}")
async def update_lead(
    lead_id: str,
    data: LeadUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update fields on an existing lead. Fields omitted from the request body
    are left unchanged; explicit `null` clears the field. `email` can be
    changed but must remain unique."""
    lead = (await db.execute(
        select(Lead).where(Lead.id == lead_id)
    )).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    payload = data.model_dump(exclude_unset=True)

    if "enrichment_status" in payload and payload["enrichment_status"] is not None:
        if payload["enrichment_status"] not in VALID_ENRICHMENT_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"enrichment_status must be one of {sorted(VALID_ENRICHMENT_STATUSES)}",
            )

    if "email" in payload and payload["email"] and payload["email"].lower() != lead.email:
        # Block email collisions with other leads.
        new_email = payload["email"].lower()
        clash = (await db.execute(
            select(Lead).where(Lead.email == new_email, Lead.id != lead.id)
        )).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(status_code=409, detail="email already used by another lead")
        payload["email"] = new_email

    for field, value in payload.items():
        setattr(lead, field, value)

    await db.flush()
    db.add(Event(lead_id=lead.id, event_type="enrichment_completed"))
    await db.flush()
    return {"id": str(lead.id), "email": lead.email}


@router.post("/ingest")
async def ingest_lead(
    data: LeadIngest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Lead).where(Lead.email == data.email)
    )
    existing = result.scalar_one_or_none()
    payload = data.model_dump()
    supplied_status = payload.pop("enrichment_status", None)
    if supplied_status is not None and supplied_status not in VALID_ENRICHMENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"enrichment_status must be one of {sorted(VALID_ENRICHMENT_STATUSES)}",
        )
    if existing is None:
        lead = Lead(**payload, enrichment_status=supplied_status or "complete")
        db.add(lead)
        event_type = "lead_created"
    else:
        lead = existing
        for field, value in payload.items():
            if value is not None:
                setattr(lead, field, value)
        if supplied_status is not None:
            lead.enrichment_status = supplied_status
        event_type = "enrichment_completed"

    await db.flush()
    db.add(Event(
        lead_id=lead.id,
        event_type=event_type,
    ))
    await db.flush()

    return {"id": str(lead.id), "email": lead.email}


# -------- CSV bulk import ----------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STRING_COLS = (
    "first_name", "last_name", "company", "domain", "title",
    "linkedin_url", "persona", "company_size", "state", "growth_stage",
)
MAX_CSV_ROWS = 5000
MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CSV_ERRORS_RETURNED = 100

_TEMPLATE_CSV = (
    "email,first_name,last_name,company,domain,title,linkedin_url,persona,"
    "company_size,state,growth_stage,tech_stack\n"
    "alex.chen@example.com,Alex,Chen,Acme Insurance,acme.example,Insurance Agent,"
    "https://linkedin.com/in/alex-chen,insurance_agent,11-50,CA,growth,"
    '"Salesforce, AMS360"\n'
)


def _row_to_lead_dict(row: dict[str, str]) -> tuple[dict | None, str | None]:
    """Parse a CSV DictReader row into a dict suitable for Lead(**out).

    Returns (data, None) on success, (None, error_msg) on failure. Empty
    cells become None so updates don't blank existing fields. tech_stack
    is split on commas. Unknown columns are silently ignored.
    """
    email = (row.get("email") or "").strip().lower()
    if not email:
        return None, "missing email"
    if not _EMAIL_RE.match(email):
        return None, "invalid email format"

    out: dict = {"email": email}
    for col in _STRING_COLS:
        v = (row.get(col) or "").strip()
        out[col] = v or None

    ts = (row.get("tech_stack") or "").strip()
    if ts:
        out["tech_stack"] = [s.strip() for s in ts.split(",") if s.strip()]
    else:
        out["tech_stack"] = None

    return out, None


@router.get("/import-csv/template")
async def import_csv_template():
    """Download a CSV template — headers + one example row."""
    return Response(
        content=_TEMPLATE_CSV,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="leads_template.csv"',
        },
    )


@router.post("/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-upsert leads from a CSV.

    Per-row tolerant: bad rows are reported in the `errors` list, rest are
    processed. Up to MAX_CSV_ROWS rows and MAX_CSV_BYTES bytes per upload.
    """
    content = await file.read()
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {MAX_CSV_BYTES} bytes",
        )

    try:
        text = content.decode("utf-8-sig")  # handles Excel BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="file is not valid UTF-8")

    reader = csv.DictReader(io.StringIO(text))

    parsed: list[tuple[int, dict]] = []
    errors: list[dict] = []
    seen_emails: set[str] = set()
    total = 0

    # Row 1 is the header, so DictReader's first row is line 2.
    for row_num, raw in enumerate(reader, start=2):
        total += 1
        if total > MAX_CSV_ROWS:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds {MAX_CSV_ROWS} rows",
            )

        data, err = _row_to_lead_dict(raw)
        if err:
            if len(errors) < MAX_CSV_ERRORS_RETURNED:
                errors.append({
                    "row": row_num,
                    "email": (raw.get("email") or "").strip(),
                    "reason": err,
                })
            continue

        if data["email"] in seen_emails:
            if len(errors) < MAX_CSV_ERRORS_RETURNED:
                errors.append({
                    "row": row_num,
                    "email": data["email"],
                    "reason": "duplicate email in file",
                })
            continue
        seen_emails.add(data["email"])
        parsed.append((row_num, data))

    if not parsed:
        return {
            "total_rows": total,
            "created": 0,
            "updated": 0,
            "skipped": total,
            "errors": errors,
        }

    # Single batched lookup of all emails.
    emails = [d["email"] for _, d in parsed]
    existing_q = await db.execute(select(Lead).where(Lead.email.in_(emails)))
    existing: dict[str, Lead] = {l.email: l for l in existing_q.scalars().all()}

    operations: list[tuple[str, Lead]] = []
    created = 0
    updated = 0

    for _row_num, data in parsed:
        email = data["email"]
        if email in existing:
            lead = existing[email]
            for field, value in data.items():
                if value is not None:
                    setattr(lead, field, value)
            updated += 1
            operations.append(("enrichment_completed", lead))
        else:
            lead = Lead(**data, enrichment_status="complete")
            db.add(lead)
            created += 1
            operations.append(("lead_created", lead))

    # Flush so new leads pick up their UUIDs before we attach Events.
    await db.flush()

    for event_type, lead in operations:
        db.add(Event(lead_id=lead.id, event_type=event_type))

    # get_db dependency commits when the route returns successfully.
    return {
        "total_rows": total,
        "created": created,
        "updated": updated,
        "skipped": total - created - updated,
        "errors": errors,
    }