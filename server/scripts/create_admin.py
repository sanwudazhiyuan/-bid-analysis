"""创建初始管理员账号。用法: python -m server.scripts.create_admin"""

import asyncio

from sqlalchemy import select

from server.app.database import async_session_factory, engine, Base
from server.app.models.user import User
from server.app.security import hash_password


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            print("Admin user already exists.")
            return
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            display_name="管理员",
            role="admin",
        )
        session.add(admin)
        await session.commit()
        print("Admin user created: admin / admin123")


if __name__ == "__main__":
    asyncio.run(main())
