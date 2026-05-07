import random
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models import PolicyStat, RuleVersion


def make_segment_key(persona: str, channel: str, angle: str) -> str:
    return f"{persona}|{channel}|{angle}"


async def get_or_create_stat(
    db: AsyncSession, persona: str, channel: str, angle: str
) -> PolicyStat:
    key = make_segment_key(persona, channel, angle)
    result = await db.execute(
        select(PolicyStat).where(PolicyStat.segment_key == key)
    )
    stat = result.scalar_one_or_none()
    if stat is None:
        stat = PolicyStat(
            segment_key=key,
            persona=persona,
            channel=channel,
            angle=angle,
        )
        db.add(stat)
        await db.flush()
    return stat


async def sample_best_action(
    db: AsyncSession,
    persona: str,
    channels: list[str],
    angles: list[str],
) -> tuple[str, str, bool]:
    if random.random() < settings.EXPLORATION_RATE:
        return random.choice(channels), random.choice(angles), True
    best_channel, best_angle, best_sample = channels[0], angles[0], -1.0

    for channel in channels:
        for angle in angles:
            stat = await get_or_create_stat(db, persona, channel, angle)
            sample = random.betavariate(stat.alpha, stat.beta_param)
            if sample > best_sample:
                best_sample = sample
                best_channel = channel
                best_angle = angle

    return best_channel, best_angle, False


async def record_reward(
    db: AsyncSession,
    persona: str,
    channel: str,
    angle: str,
    reward: float,
) -> None:
    stat = await get_or_create_stat(db, persona, channel, angle)
    stat.trials += 1
    stat.successes += max(reward, 0)

    normalized = max(0.0, min(1.0, (reward + 10) / 20))

    if reward > 0:
        stat.alpha += normalized
    else:
        stat.beta_param += (1 - normalized)

    await db.flush()

    if stat.trials >= settings.MIN_BANDIT_TRIALS and stat.trials % 10 == 0:
        await _log_rule_change(db, stat)


async def _log_rule_change(db: AsyncSession, stat: PolicyStat) -> None:
    confidence = max(0.0, min(1.0, stat.alpha / (stat.alpha + stat.beta_param)))
    rule = {
        "segment_key": stat.segment_key,
        "alpha": stat.alpha,
        "beta": stat.beta_param,
        "trials": stat.trials,
        "estimated_success_rate": confidence,
    }
    version = RuleVersion(
        segment_key=stat.segment_key,
        new_rule=rule,
        confidence=confidence,
        trials_at_change=stat.trials,
        approved=confidence >= 0.80,
    )
    db.add(version)
    await db.flush()