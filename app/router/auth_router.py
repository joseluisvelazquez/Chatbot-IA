from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.security.auth_dependencies import enforce_panel_origin, get_current_panel_user
from app.security.auth_models import PanelUser

from app.security.auth_service import (
    create_panel_session,
    decode_siga_token,
    revoke_panel_session,
)

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(enforce_panel_origin)])
logger = logging.getLogger(__name__)
_AUTH_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
AUTH_RATE_LIMIT_WINDOW_SECONDS = 300
AUTH_RATE_LIMIT_MAX_ATTEMPTS = 20


class ExchangeTokenRequest(BaseModel):
    token: str = Field(..., min_length=20)


class AuthUserResponse(BaseModel):
    username: str
    puesto: str
    empresa_id: int
    role: str
    exp: int


def _cookie_name() -> str:
    return getattr(settings, "PANEL_SESSION_COOKIE_NAME", "panel_session")


def _cookie_secure() -> bool:
    configured = getattr(settings, "PANEL_SESSION_SECURE_COOKIE", None)
    if configured is not None:
        return bool(configured)
    return not bool(getattr(settings, "DEBUG", False))


def _cookie_samesite() -> str:
    value = str(getattr(settings, "PANEL_SESSION_SAMESITE", "lax")).lower()
    if value not in {"lax", "strict", "none"}:
        return "lax"
    return value


def _set_panel_session_cookie(response: Response, session_value: str, max_age: int) -> None:
    response.set_cookie(
        key=_cookie_name(),
        value=session_value,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        max_age=max_age,
        path="/",
    )


def _clear_panel_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_cookie_name(),
        path="/",
    )


def _ensure_panel_company_allowed(user: PanelUser) -> None:
    allowed_empresa_id = int(getattr(settings, "PANEL_ALLOWED_EMPRESA_ID", 1) or 1)
    if int(user.empresa_id or 0) != allowed_empresa_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Empresa no autorizada para panel",
        )


def _rate_limit_auth(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _AUTH_ATTEMPTS[ip]

    while bucket and now - bucket[0] > AUTH_RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()

    if len(bucket) >= AUTH_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos")

    bucket.append(now)


@router.post("/dev-login")
def dev_login(request: Request, response: Response, db: Session = Depends(get_db)):
    _rate_limit_auth(request)
    if not settings.DEBUG:
        raise HTTPException(403, "No permitido")

    host = request.headers.get("host", "")

    if not host.startswith(("localhost", "127.0.0.1")):
        raise HTTPException(403, "Solo localhost")
    

    user = PanelUser(
        username="dev_user",
        puesto="GERENTE GENERAL",
        empresa_id=1,
        role="admin",
        exp=int(time.time()) + 3600,
        jti=None,
    )

    session_value = create_panel_session(
        db,
        user,
        request.client.host,
        request.headers.get("user-agent"),
    )

    _set_panel_session_cookie(response, session_value, 3600)

    db.commit()
    return {"status": "ok"}


@router.post("/exchange", response_model=AuthUserResponse)
def exchange_siga_token(
    body: ExchangeTokenRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _rate_limit_auth(request)
    try:
        user = decode_siga_token(body.token, db)
        _ensure_panel_company_allowed(user)

        SESSION_DURATION = 60 * 60 * 8
        remaining_seconds = SESSION_DURATION

        ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        session_value = create_panel_session(db, user, ip, user_agent)

        _set_panel_session_cookie(
            response=response,
            session_value=session_value,
            max_age=remaining_seconds,
        )

        db.commit()

        logger.info(
            "panel_auth_exchange_success",
            extra={
                "username": user.username,
                "role": user.role,
                "empresa_id": user.empresa_id,
                "cookie_name": _cookie_name(),
                "client_host": request.client.host if request.client else None,
            },
        )

        return AuthUserResponse(
            username=user.username,
            puesto=user.puesto,
            empresa_id=user.empresa_id,
            role=user.role,
            exp=user.exp,
        )

    except HTTPException as error:
        logger.warning(
            "panel_auth_exchange_denied",
            extra={
                "status_code": error.status_code,
                "detail": error.detail,
                "cookie_present": bool(request.cookies.get(_cookie_name())),
                "origin": request.headers.get("origin"),
                "client_host": request.client.host if request.client else None,
            },
        )
        db.rollback()
        raise
    except Exception:
        logger.exception(
            "panel_auth_exchange_failed",
            extra={
                "cookie_present": bool(request.cookies.get(_cookie_name())),
                "origin": request.headers.get("origin"),
                "client_host": request.client.host if request.client else None,
            },
        )
        db.rollback()
        raise

@router.get("/me", response_model=AuthUserResponse)
def get_me(user: PanelUser = Depends(get_current_panel_user)):
    return AuthUserResponse(
        username=user.username,
        puesto=user.puesto,
        empresa_id=user.empresa_id,
        role=user.role,
        exp=user.exp,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    session_token = request.cookies.get(_cookie_name())

    if session_token:
        revoke_panel_session(session_token, db)
        db.commit()

    _clear_panel_session_cookie(response)

    response.status_code = status.HTTP_204_NO_CONTENT
    return response
