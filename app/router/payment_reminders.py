from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.security.auth_dependencies import get_current_panel_user
from app.security.auth_service import is_allowed_panel_company
from app.services.payment_reminder_service import (
    dry_run_payment_reminder,
    run_due_payment_reminders,
    sync_payment_reminder_candidates,
)


router = APIRouter(
    prefix="/api/panel/payment-reminders",
    tags=["payment-reminders"],
)


def require_payment_reminder_permission(user) -> None:
    if user.role not in ("admin", "jefe_operativo", "sistemas"):
        raise HTTPException(403, "No autorizado")


def resolve_payment_reminder_company_id(user, company_id: int | None) -> int:
    target_company_id = int(company_id or user.empresa_id)
    if not is_allowed_panel_company(target_company_id):
        raise HTTPException(403, "No autorizado")
    if company_id and target_company_id != int(user.empresa_id) and user.role not in ("admin", "sistemas"):
        raise HTTPException(403, "No autorizado")
    return target_company_id


@router.post("/dry-run")
async def dry_run_payment_reminder_endpoint(
    cuenta: str | None = None,
    folio: str | None = None,
    company_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_panel_user),
):
    require_payment_reminder_permission(user)
    if not cuenta and not folio:
        raise HTTPException(400, "Debes enviar cuenta o folio")

    return await dry_run_payment_reminder(
        db,
        cuenta=cuenta,
        folio=folio,
        company_id=resolve_payment_reminder_company_id(user, company_id),
    )


@router.post("/run-due")
async def run_due_payment_reminders_endpoint(
    dry_run: bool = True,
    limit: int = 50,
    company_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_panel_user),
):
    require_payment_reminder_permission(user)
    if not dry_run and not settings.PAYMENT_REMINDERS_ENABLED:
        raise HTTPException(400, "PAYMENT_REMINDERS_ENABLED debe estar activo para envios reales")

    return await run_due_payment_reminders(
        db,
        company_id=resolve_payment_reminder_company_id(user, company_id),
        limit=limit,
        dry_run=dry_run,
    )


@router.post("/sync")
async def sync_payment_reminders_endpoint(
    dry_run: bool = True,
    limit: int | None = None,
    company_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_panel_user),
):
    require_payment_reminder_permission(user)
    if not dry_run and not settings.PAYMENT_REMINDERS_ENABLED:
        raise HTTPException(400, "PAYMENT_REMINDERS_ENABLED debe estar activo para escribir programacion")

    return await sync_payment_reminder_candidates(
        db,
        company_id=resolve_payment_reminder_company_id(user, company_id),
        limit=limit,
        dry_run=dry_run,
    )
