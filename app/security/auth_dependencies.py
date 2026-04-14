from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.auth_models import PanelUser
from app.security.auth_service import decode_panel_session


def get_current_panel_user(
    panel_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> PanelUser:
    if not panel_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión no iniciada",
        )

    return decode_panel_session(panel_session, db)


def require_roles(*allowed_roles: str):
    def dependency(user: PanelUser = Depends(get_current_panel_user)) -> PanelUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No autorizado",
            )
        return user

    return dependency