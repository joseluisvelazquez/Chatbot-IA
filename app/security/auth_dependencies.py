from urllib.parse import urlparse

from fastapi import (
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketException,
    status,
)
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.security.auth_models import PanelUser
from app.security.auth_service import decode_panel_session
from app.security.rbac import normalize_role


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def _host_without_port(value: str | None) -> str:
    return str(value or "").split(":", 1)[0].strip().lower()


def _normalize_origin_value(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)

    scheme = (parsed.scheme or "").strip().lower()
    netloc = (parsed.netloc or parsed.path or "").strip().lower().rstrip("/")

    if not scheme or not netloc:
        return None

    return f"{scheme}://{netloc}"


def _allowed_panel_origins() -> set[str]:
    raw_values = getattr(settings, "PANEL_ALLOWED_ORIGINS", []) or []

    return {
        normalized
        for normalized in (
            _normalize_origin_value(item)
            for item in raw_values
        )
        if normalized
    }


def _is_debug() -> bool:
    return bool(getattr(settings, "DEBUG", False))


def panel_session_cookie_name() -> str:
    return str(getattr(settings, "PANEL_SESSION_COOKIE_NAME", "panel_session"))


def is_allowed_panel_origin(
    host: str | None,
    origin_or_referer: str | None,
) -> bool:
    request_host = _host_without_port(host)

    if not origin_or_referer:
        return _is_debug() and request_host in LOCAL_HOSTS

    normalized = _normalize_origin_value(origin_or_referer)

    if normalized and normalized in _allowed_panel_origins():
        return True

    parsed = urlparse(origin_or_referer)
    origin_host = _host_without_port(parsed.netloc or parsed.path)

    if not origin_host or not request_host:
        return False

    if origin_host == request_host:
        return True

    if _is_debug() and origin_host in LOCAL_HOSTS:
        return True

    return False
def enforce_panel_origin(request: Request) -> None:
    """
    Solo HTTP requests.
    Dependency global para routers REST.
    """

    method = request.method.upper()

    if method in SAFE_METHODS:
        return

    host = request.headers.get("host")
    origin = request.headers.get("origin") or request.headers.get("referer")

    if not is_allowed_panel_origin(host, origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origen no autorizado",
        )

def enforce_panel_ws_origin(websocket: WebSocket) -> None:
    host = websocket.headers.get("host")
    origin = websocket.headers.get("origin")

    if is_allowed_panel_origin(host, origin):
        return

    raise WebSocketException(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Origen no autorizado",
    )


def get_current_panel_user(
    request: Request,
    db: Session = Depends(get_db),
) -> PanelUser:
    panel_session = request.cookies.get(panel_session_cookie_name())

    if not panel_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Sesión no iniciada: cookie {panel_session_cookie_name()} ausente",
        )

    return decode_panel_session(panel_session, db)


def require_roles(*allowed_roles: str):
    normalized_allowed = {
        normalize_role(role)
        for role in allowed_roles
    }

    def dependency(
        user: PanelUser = Depends(get_current_panel_user),
    ) -> PanelUser:
        current_role = normalize_role(user.role)

        if current_role not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No autorizado",
            )

        return user

    return dependency
