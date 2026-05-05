"""
Create a user from the command line.

    python create_user.py
    python create_user.py admin@example.com   # email as arg, prompts for password

The password is read with getpass so it's never echoed or stored in shell
history. If the email already exists, this updates the password instead of
creating a duplicate.
"""
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal, engine, Base
from app import models  # noqa: F401  register all models on Base.metadata
from app.models import User
from app.services.auth import hash_password


async def main(email: str | None) -> int:
    if not email:
        email = input("Email: ").strip().lower()
    else:
        email = email.strip().lower()
    if not email or "@" not in email:
        print("Invalid email.")
        return 1

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm: ")
    if password != confirm:
        print("Passwords don't match.")
        return 1
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return 1

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()

        if existing is None:
            db.add(User(email=email, password_hash=hash_password(password)))
            verb = "created"
        else:
            existing.password_hash = hash_password(password)
            existing.is_active = True
            verb = "updated"
        await db.commit()

    print(f"User {email} {verb}.")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    arg_email = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(asyncio.run(main(arg_email)))
