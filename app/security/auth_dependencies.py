from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status

from app.security.auth_models import PanelUser
from app.security.auth_service import decode_panel_session


def get_current_panel_user(
    panel_session: str | None = Cookie(default=None),
) -> PanelUser:
    if not panel_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión no iniciada",
        )

    return decode_panel_session(panel_session)


def require_roles(*allowed_roles: str):
    def dependency(user: PanelUser = Depends(get_current_panel_user)) -> PanelUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No autorizado para este recurso",
            )
        return user

    return dependency