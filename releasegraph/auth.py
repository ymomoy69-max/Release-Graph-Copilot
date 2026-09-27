"""Auth helpers. The UI is open (no login); JWT is optional for tests/API clients."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.config import settings
from releasegraph.database import get_db
from releasegraph.models import Organization, User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

DEMO_EMAIL = "admin@acme.demo"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "email": email, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _demo_admin(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is not None:
        return user
    org = db.scalar(select(Organization).order_by(Organization.id))
    if org is None:
        org = Organization(slug="acme", name="Acme Commerce")
        db.add(org)
        db.flush()
    user = User(
        email=DEMO_EMAIL,
        full_name="Admin User",
        hashed_password=hash_password("admin123!"),
        role=UserRole.ADMIN,
        organization_id=org.id,
    )
    db.add(user)
    db.flush()
    return user


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Open demo auth: no token required. A valid Bearer JWT still selects that user."""
    if creds is not None and creds.credentials:
        try:
            payload = jwt.decode(
                creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
            )
            user_id = int(payload.get("sub", "0"))
            user = db.get(User, user_id)
            if user is not None:
                return user
        except (JWTError, ValueError, TypeError):
            pass
    return _demo_admin(db)


def require_roles(*roles: UserRole):
    def _dep(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles and user.role != UserRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dep
