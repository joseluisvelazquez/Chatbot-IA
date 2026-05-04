from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.security.auth_dependencies import require_roles
from app.security.auth_models import PanelUser
from app.services.siga_bridge import (
    SigaBridgeBadRequestError,
    SigaBridgeConfigError,
    SigaBridgeContractError,
    SigaBridgeError,
    SigaBridgeRateLimitError,
    SigaBridgeServerError,
    SigaBridgeUnauthorizedError,
    SigaBridgeUnavailableError,
    get_siga_bridge_metrics,
    get_siga_bridge_client,
)

router = APIRouter(prefix="/api/panel/siga-bridge", tags=["panel"])


def require_siga_bridge_panel_user(
    request: Request,
    user: PanelUser = Depends(require_roles("admin", "jefe_operativo")),
) -> PanelUser:
    if "company_id" in request.query_params:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company_id no permitido; se usa la empresa de la sesión",
        )

    empresa_id = int(getattr(user, "empresa_id", 0) or 0)
    if empresa_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Empresa no autorizada para SIGA Bridge",
        )
    return user


def _map_bridge_error(exc: SigaBridgeError) -> HTTPException:
    if isinstance(exc, SigaBridgeBadRequestError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, SigaBridgeConfigError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, SigaBridgeRateLimitError):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    if isinstance(exc, (SigaBridgeUnauthorizedError, SigaBridgeContractError, SigaBridgeServerError)):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, SigaBridgeUnavailableError):
        return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="SIGA Bridge request failed")


async def _call_bridge(method_name: str, *args: Any, **kwargs: Any) -> Any:
    client = get_siga_bridge_client()
    method = getattr(client, method_name)
    try:
        return await method(*args, **kwargs)
    except SigaBridgeError as exc:
        raise _map_bridge_error(exc) from exc


@router.get("/ping")
async def siga_bridge_ping(
    _user: PanelUser = Depends(require_siga_bridge_panel_user),
):
    return await _call_bridge("ping")


@router.get("/customer")
async def siga_bridge_customer(
    phone: str = Query(..., min_length=10, max_length=15),
    user: PanelUser = Depends(require_siga_bridge_panel_user),
):
    return await _call_bridge("get_customer_by_phone", phone, user.empresa_id)


@router.get("/account")
async def siga_bridge_account(
    cuenta: str = Query(..., min_length=1, max_length=40),
    user: PanelUser = Depends(require_siga_bridge_panel_user),
):
    return await _call_bridge("get_account", cuenta, user.empresa_id)


@router.get("/metrics")
async def siga_bridge_metrics(
    _user: PanelUser = Depends(require_siga_bridge_panel_user),
):
    return get_siga_bridge_metrics()
