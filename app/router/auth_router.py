from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.security.auth_dependencies import get_current_panel_user
from app.security.auth_models import PanelUser
from app.security.auth_service import (
    create_panel_session_value,
    decode_siga_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    return bool(getattr(settings, "PANEL_SESSION_SECURE_COOKIE", False))


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
        secure=False,
        samesite="lax",   # 🔥 CAMBIO CLAVE
        max_age=max_age,
        path="/",
    )


def _clear_panel_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_cookie_name(),
        path="/",
    )


@router.post("/dev-login")
def dev_login(request: Request, response: Response):
    if not settings.DEBUG:
        raise HTTPException(status_code=403, detail="No permitido")

    user = PanelUser(
        username="dev_user",
        puesto="GERENTE GENERAL",
        empresa_id=1,
        role="admin",
        exp=int(time.time()) + 3600,
        jti=None,
    )

    session_value = create_panel_session_value(user)

    _set_panel_session_cookie(
        response=response,
        session_value=session_value,
        max_age=3600,
    )

    return {"status": "ok"}


@router.post("/exchange", response_model=AuthUserResponse)
def exchange_siga_token(
    body: ExchangeTokenRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = decode_siga_token(body.token, db)

        session_value = create_panel_session_value(user)

        now = int(time.time())
        remaining_seconds = max(user.exp - now, 1)

        _set_panel_session_cookie(
            response=response,
            session_value=session_value,
            max_age=remaining_seconds,
        )

        db.commit()

        return AuthUserResponse(
            username=user.username,
            puesto=user.puesto,
            empresa_id=user.empresa_id,
            role=user.role,
            exp=user.exp,
        )

    except Exception:
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
def logout(response: Response):
    _clear_panel_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)