"""DB-backed tests for the bandit's reward update math.

Skipped unless TEST_DATABASE_URL is set. See conftest.py.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models import PolicyStat
from app.services.bandit import record_reward, make_segment_key


pytestmark = pytest.mark.asyncio


async def _stat_for(db, persona, channel, angle) -> PolicyStat:
    key = make_segment_key(persona, channel, angle)
    return (await db.execute(
        select(PolicyStat).where(PolicyStat.segment_key == key)
    )).scalar_one()


async def test_first_positive_reward_creates_stat_and_increments_alpha(db_session):
    suffix = uuid.uuid4().hex[:8]
    persona = f"agent_{suffix}"
    await record_reward(db_session, persona, "email", "pain", reward=10.0)
    await db_session.commit()

    stat = await _stat_for(db_session, persona, "email", "pain")
    assert stat.trials == 1
    assert stat.alpha > 1.0       # alpha grew from default 1.0
    assert stat.beta_param == 1.0  # beta unchanged on positive reward


async def test_negative_reward_increments_beta(db_session):
    suffix = uuid.uuid4().hex[:8]
    persona = f"agent_{suffix}"
    await record_reward(db_session, persona, "email", "pain", reward=-5.0)
    await db_session.commit()

    stat = await _stat_for(db_session, persona, "email", "pain")
    assert stat.trials == 1
    assert stat.alpha == 1.0       # alpha unchanged on negative reward
    assert stat.beta_param > 1.0   # beta grew


async def test_repeated_positive_rewards_keep_growing_alpha(db_session):
    suffix = uuid.uuid4().hex[:8]
    persona = f"agent_{suffix}"
    for _ in range(5):
        await record_reward(db_session, persona, "email", "growth", reward=10.0)
    await db_session.commit()

    stat = await _stat_for(db_session, persona, "email", "growth")
    assert stat.trials == 5
    # 5 positive rewards of 10.0 → normalized 1.0 each → alpha = 1 + 5 = 6
    assert stat.alpha == pytest.approx(6.0)
    assert stat.beta_param == 1.0


async def test_segments_are_isolated(db_session):
    """A reward to (agent, email, pain) must not bleed into (agent, email, growth)."""
    suffix = uuid.uuid4().hex[:8]
    persona = f"agent_{suffix}"
    await record_reward(db_session, persona, "email", "pain", reward=10.0)
    await record_reward(db_session, persona, "email", "growth", reward=-5.0)
    await db_session.commit()

    pain = await _stat_for(db_session, persona, "email", "pain")
    growth = await _stat_for(db_session, persona, "email", "growth")
    assert pain.alpha > 1.0 and pain.beta_param == 1.0
    assert growth.alpha == 1.0 and growth.beta_param > 1.0
