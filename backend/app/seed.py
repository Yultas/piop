import secrets
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.config import settings, INSECURE_ADMIN_PASSWORDS
from backend.app.models import User
from backend.app.auth import hash_password

async def seed_initial_data(session: AsyncSession):
    stmt = select(User).where(User.username == settings.SUPERADMIN_USERNAME)
    res = await session.execute(stmt)
    admin = res.scalar_one_or_none()

    if not admin:
        generated = settings.SUPERADMIN_PASSWORD in INSECURE_ADMIN_PASSWORDS
        if generated:
            settings.SUPERADMIN_PASSWORD = secrets.token_urlsafe(12)
        admin = User(
            username=settings.SUPERADMIN_USERNAME,
            hashed_password=hash_password(settings.SUPERADMIN_PASSWORD),
            is_global_admin=True,
            is_active=True
        )
        session.add(admin)
        await session.commit()
        print(f"[Seed] Superadmin created: {settings.SUPERADMIN_USERNAME}")
        if generated:
            print(f"[Seed] Generated superadmin password for '{settings.SUPERADMIN_USERNAME}': {settings.SUPERADMIN_PASSWORD} — change it after first login")
