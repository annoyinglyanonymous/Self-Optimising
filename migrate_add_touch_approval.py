"""
One-off migration: add approval workflow columns to the `touches` table.

Adds:
    status              VARCHAR(50)    NOT NULL DEFAULT 'approved'
    approved_by_user_id UUID           NULL    REFERENCES users(id) ON DELETE SET NULL
    decided_at          TIMESTAMPTZ    NULL

Existing rows get status='approved' by default (they were already sent or
in-flight before approval existed, so retroactively treated as approved).

Idempotent — uses IF NOT EXISTS so re-running is safe.

Run:  python migrate_add_touch_approval.py
"""
import asyncio

from sqlalchemy import text

from app.database import engine


SQL_STATEMENTS = [
    """ALTER TABLE touches ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'approved'""",
    """ALTER TABLE touches ADD COLUMN IF NOT EXISTS approved_by_user_id UUID""",
    # Add the FK separately so ADD COLUMN is idempotent independently of the constraint.
    """DO $$
       BEGIN
         IF NOT EXISTS (
           SELECT 1 FROM information_schema.table_constraints
           WHERE table_name='touches' AND constraint_name='touches_approved_by_user_id_fkey'
         ) THEN
           ALTER TABLE touches
             ADD CONSTRAINT touches_approved_by_user_id_fkey
             FOREIGN KEY (approved_by_user_id) REFERENCES users(id) ON DELETE SET NULL;
         END IF;
       END $$""",
    """ALTER TABLE touches ADD COLUMN IF NOT EXISTS decided_at TIMESTAMP WITH TIME ZONE""",
    """CREATE INDEX IF NOT EXISTS ix_touches_status ON touches(status)""",
]


async def main() -> None:
    async with engine.begin() as conn:
        for sql in SQL_STATEMENTS:
            await conn.execute(text(sql))
    await engine.dispose()
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
