"""
Drop and recreate all tables. DESTRUCTIVE — wipes every row.

Run:  python reset_db.py
"""
import asyncio

from app.database import engine, Base
from app import models  # noqa: F401  ensure all models are registered on Base.metadata


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Schema reset.")


if __name__ == "__main__":
    asyncio.run(main())
