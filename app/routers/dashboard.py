from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.models import Lead, Touch, Event, Outcome, PolicyStat
from app.services.auth import current_user

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(current_user)],
)


SENT_TYPES = {"email_sent"}
OPEN_TYPES = {"email_opened"}
CLICK_TYPES = {"email_clicked"}
REPLY_TYPES = {
    "reply_received",
    "reply_classified_positive",
    "reply_classified_objection",
    "reply_classified_ooo",
    "reply_classified_unsubscribe",
    "reply_classified_wrong_contact",
}
POSITIVE_TYPES = {"reply_classified_positive"}
NEGATIVE_TYPES = {
    "reply_classified_objection",
    "reply_classified_unsubscribe",
    "reply_classified_wrong_contact",
}


def _parse_window(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/stats")
async def get_stats(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    since = _parse_window(days)

    total_leads = (await db.execute(select(func.count(Lead.id)))).scalar_one()
    leads_in_window = (
        await db.execute(
            select(func.count(Lead.id)).where(Lead.created_at >= since)
        )
    ).scalar_one()

    total_touches = (
        await db.execute(
            select(func.count(Touch.id)).where(Touch.created_at >= since)
        )
    ).scalar_one()

    counts_q = await db.execute(
        select(Event.event_type, func.count(Event.id))
        .where(Event.created_at >= since)
        .group_by(Event.event_type)
    )
    counts = {row[0]: row[1] for row in counts_q.all()}

    sent = sum(counts.get(t, 0) for t in SENT_TYPES)
    opened = sum(counts.get(t, 0) for t in OPEN_TYPES)
    clicked = sum(counts.get(t, 0) for t in CLICK_TYPES)
    replied = sum(counts.get(t, 0) for t in REPLY_TYPES)
    positive = sum(counts.get(t, 0) for t in POSITIVE_TYPES)
    negative = sum(counts.get(t, 0) for t in NEGATIVE_TYPES)

    def rate(num, denom):
        return round(num / denom, 4) if denom else 0.0

    return {
        "window_days": days,
        "total_leads": total_leads,
        "leads_in_window": leads_in_window,
        "touches_in_window": total_touches,
        "events": {
            "sent": sent,
            "opened": opened,
            "clicked": clicked,
            "replied": replied,
            "positive": positive,
            "negative": negative,
        },
        "rates": {
            "open_rate": rate(opened, sent),
            "click_rate": rate(clicked, sent),
            "reply_rate": rate(replied, sent),
            "positive_rate": rate(positive, sent),
        },
        "event_counts": counts,
    }


@router.get("/timeseries")
async def get_timeseries(
    days: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    since = _parse_window(days)
    day = func.date_trunc("day", Event.created_at).label("day")

    q = await db.execute(
        select(day, Event.event_type, func.count(Event.id))
        .where(Event.created_at >= since)
        .group_by(day, Event.event_type)
        .order_by(day)
    )
    rows = q.all()

    by_day: dict[str, dict[str, int]] = {}
    for d, et, c in rows:
        key = d.date().isoformat()
        by_day.setdefault(key, {"sent": 0, "opened": 0, "replied": 0})
        if et in SENT_TYPES:
            by_day[key]["sent"] += c
        elif et in OPEN_TYPES:
            by_day[key]["opened"] += c
        elif et in REPLY_TYPES:
            by_day[key]["replied"] += c

    series = [{"date": d, **vals} for d, vals in sorted(by_day.items())]
    return {"days": days, "series": series}


@router.get("/leads")
async def list_leads(
    persona: str | None = None,
    enrichment_status: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if persona:
        filters.append(Lead.persona == persona)
    if enrichment_status:
        filters.append(Lead.enrichment_status == enrichment_status)
    if search:
        like = f"%{search.lower()}%"
        filters.append(
            func.lower(Lead.email).like(like)
            | func.lower(func.coalesce(Lead.company, "")).like(like)
            | func.lower(func.coalesce(Lead.first_name, "")).like(like)
            | func.lower(func.coalesce(Lead.last_name, "")).like(like)
        )

    where = and_(*filters) if filters else None

    total_q = select(func.count(Lead.id))
    if where is not None:
        total_q = total_q.where(where)
    total = (await db.execute(total_q)).scalar_one()

    q = select(Lead).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    if where is not None:
        q = q.where(where)
    rows = (await db.execute(q)).scalars().all()

    items = [
        {
            "id": str(l.id),
            "email": l.email,
            "first_name": l.first_name,
            "last_name": l.last_name,
            "company": l.company,
            "domain": l.domain,
            "title": l.title,
            "persona": l.persona,
            "company_size": l.company_size,
            "state": l.state,
            "growth_stage": l.growth_stage,
            "enrichment_status": l.enrichment_status,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/leads/{lead_id}")
async def get_lead_detail(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
):
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    touches = (
        await db.execute(
            select(Touch)
            .where(Touch.lead_id == lead.id)
            .order_by(Touch.created_at.desc())
        )
    ).scalars().all()

    events = (
        await db.execute(
            select(Event)
            .where(Event.lead_id == lead.id)
            .order_by(Event.created_at.desc())
            .limit(200)
        )
    ).scalars().all()

    return {
        "lead": {
            "id": str(lead.id),
            "email": lead.email,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "company": lead.company,
            "domain": lead.domain,
            "title": lead.title,
            "linkedin_url": lead.linkedin_url,
            "persona": lead.persona,
            "company_size": lead.company_size,
            "state": lead.state,
            "growth_stage": lead.growth_stage,
            "tech_stack": lead.tech_stack,
            "enrichment_status": lead.enrichment_status,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        },
        "touches": [
            {
                "id": str(t.id),
                "channel": t.channel,
                "angle": t.angle,
                "template_family": t.template_family,
                "subject": t.subject,
                "body": t.body,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "sent_at": t.sent_at.isoformat() if t.sent_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in touches
        ],
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "channel": e.channel,
                "touch_id": str(e.touch_id) if e.touch_id else None,
                "extradata": e.extradata,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.get("/policy-stats")
async def policy_stats(
    persona: str | None = None,
    channel: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(PolicyStat)
    filters = []
    if persona:
        filters.append(PolicyStat.persona == persona)
    if channel:
        filters.append(PolicyStat.channel == channel)
    if filters:
        q = q.where(and_(*filters))
    q = q.order_by(PolicyStat.trials.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    items = []
    for r in rows:
        success_rate = round(r.successes / r.trials, 4) if r.trials else 0.0
        posterior = round(r.alpha / (r.alpha + r.beta_param), 4)
        items.append(
            {
                "segment_key": r.segment_key,
                "persona": r.persona,
                "channel": r.channel,
                "angle": r.angle,
                "trials": r.trials,
                "successes": r.successes,
                "success_rate": success_rate,
                "alpha": r.alpha,
                "beta": r.beta_param,
                "posterior_mean": posterior,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return {"items": items}


@router.get("/activity")
async def recent_activity(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Event, Lead.email, Lead.company)
        .join(Lead, Lead.id == Event.lead_id)
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).all()

    items = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "channel": e.channel,
            "lead_id": str(e.lead_id),
            "lead_email": email,
            "lead_company": company,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for (e, email, company) in rows
    ]
    return {"items": items}


@router.get("/personas")
async def personas(db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(Lead.persona, func.count(Lead.id))
        .where(Lead.persona.is_not(None))
        .group_by(Lead.persona)
        .order_by(func.count(Lead.id).desc())
    )
    return {"items": [{"persona": p, "count": c} for p, c in q.all()]}
