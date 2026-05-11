"""Authentication business logic."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import TokenResponse, UserRegister
from app.utils.logger import logger, persist_alert, security_monitor


def register_user(db: Session, payload: UserRegister) -> User:
    """Create a new user, rejecting duplicate username/email."""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User registered: %s (%s)", user.username, user.role)
    return user


def authenticate(db: Session, username: str, password: str) -> TokenResponse:
    """Verify credentials and return a JWT token."""
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        rate = security_monitor.record_auth_failure()
        # SOC: persist a categorized auth event so the security panel can show it
        severity = "critical" if rate >= 5 else "warning"
        persist_alert(
            db,
            "auth",
            severity,
            f"Failed login attempt for user '{username}' (rate={rate}/min)",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    if user.role == "admin":
        # Track admin logins separately as info-level SOC events
        persist_alert(
            db, "auth", "info", f"Admin login: '{user.username}'"
        )

    token = create_access_token(subject=user.username, role=user.role)
    return TokenResponse(access_token=token, role=user.role, username=user.username)