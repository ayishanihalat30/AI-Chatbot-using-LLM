from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter

from app.config import get_settings
from app.db import get_session
from app.models import User
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


_s = get_settings()
limiter = Limiter(
    key_func=client_key,
    storage_uri=_s.redis_url or "memory://",
    default_limits=[_s.rate_limit_default],
)


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session=Depends(get_session),
) -> User:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    user_id = decode_access_token(creds.credentials)
    if not user_id:
        raise HTTPException(401, "Invalid or expired token")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(401, "User not found")
    return user
