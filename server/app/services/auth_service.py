"""Authentication service — user verification + token generation."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.models.user import User
from server.app.security import verify_password, create_access_token, create_refresh_token


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.now()
    await db.commit()
    return user


def generate_tokens(user: User) -> dict:
    data = {"sub": user.username, "user_id": user.id}
    return {
        "access_token": create_access_token(data),
        "refresh_token": create_refresh_token(data),
        "token_type": "bearer",
    }
