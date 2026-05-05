from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config.settings import settings
from app.db.session import SessionLocal
from app.services.siga_bridge import (
    SigaBridgeError,
    SigaBridgeUnavailableError,
    get_siga_bridge_client,
)
from app.services.siga_bridge_sale import (
    bridge_sale_summary,
    bridge_verification_found,
    cache_bridge_verification_on_session,
)

logger = logging.getLogger(__name__)


def _first_record(data: Any, collection_keys: tuple[str, ...]) -> dict[str, Any] | None:
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else None

    if not isinstance(data, dict):
        return None

    for key in collection_keys:
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
        if isinstance(value, dict):
            return value

    return data


def _first_non_empty(record: dict[str, Any] | None, keys: tuple[str, ...]) -> Any | None:
    if not record:
        return None

    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value

    return None


def _verification_payload_found(payload: Any) -> bool:
    return bridge_verification_found(payload)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bridge_status(errors: list[str], available: bool) -> str:
    if any(error == SigaBridgeUnavailableError.__name__ for error in errors):
        return "timeout"
    if not available:
        return "fallback_local"
    return "ok"


def _persist_customer_lookup_cache(
    *,
    session_id: int,
    data: dict[str, Any] | list[Any] | None,
    found: bool,
    updated_at: str,
) -> None:
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT extra_json FROM chat_sessions WHERE id = :session_id"),
            {"session_id": session_id},
        ).mappings().first()

        if not row:
            return

        current = row.get("extra_json")
        if isinstance(current, str):
            try:
                current_payload = json.loads(current) if current else {}
            except json.JSONDecodeError:
                current_payload = {}
        elif isinstance(current, dict):
            current_payload = current
        else:
            current_payload = {}

        if not isinstance(current_payload, dict):
            current_payload = {}

        siga_payload = current_payload.get("siga_bridge")
        if not isinstance(siga_payload, dict):
            siga_payload = {}
            current_payload["siga_bridge"] = siga_payload

        siga_payload["customer_lookup"] = {
            "source": "siga_bridge_v1",
            "lookup_type": "phone",
            "authoritative": False,
            "updated_at": updated_at,
            "found": found,
            "data": data,
        }

        db.execute(
            text("UPDATE chat_sessions SET extra_json = :extra_json WHERE id = :session_id"),
            {
                "session_id": session_id,
                "extra_json": json.dumps(current_payload, ensure_ascii=False, default=str),
            },
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning(
            "siga_bridge_customer_lookup_cache_skipped",
            extra={"session_id": session_id, "error_type": exc.__class__.__name__},
        )
    finally:
        db.close()


async def _safe_bridge_call(
    label: str,
    action: Callable[[], Awaitable[dict[str, Any] | list[Any] | None]],
    *,
    company_id: int | None,
) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    try:
        return await action(), None
    except SigaBridgeError as exc:
        logger.warning(
            "siga_bridge_feature_call_failed",
            extra={
                "feature": label,
                "company_id": company_id,
                "status_code": exc.status_code,
                "error_type": exc.__class__.__name__,
            },
        )
        return None, exc.__class__.__name__
    except Exception:
        logger.exception(
            "siga_bridge_feature_call_unexpected",
            extra={
                "feature": label,
                "company_id": company_id,
            },
        )
        return None, "UnexpectedError"


async def enrich_verification_with_bridge(
    item: dict[str, Any],
    *,
    company_id: int | None = None,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    if not settings.SIGA_BRIDGE_ENABLED:
        return item

    enriched = dict(item)
    folio = str(enriched.get("folio") or "").strip()
    phone = str(enriched.get("phone") or "").strip()
    cuenta = str(enriched.get("no_cuenta") or "").strip()
    client = get_siga_bridge_client()
    errors: list[str] = []

    bridge: dict[str, Any] = {
        "enabled": True,
        "available": False,
        "verification": None,
        "customer": None,
        "phone_customer": None,
        "account": None,
        "payments": None,
        "error": None,
        "status": "fallback_local",
        "source": "local_fallback",
        "updated_at": _utc_timestamp(),
        "bypassed_cache": bool(bypass_cache),
        "lookup_strategy": "folio_or_account_authoritative",
        "phone_lookup_authoritative": False,
    }

    if folio:
        verification, error = await _safe_bridge_call(
            "verification_by_folio",
            lambda: client.get_verification(folio, company_id),
            company_id=company_id,
        )
        bridge["verification"] = verification
        if error:
            errors.append(error)
        elif _verification_payload_found(verification):
            if isinstance(verification.get("customer"), dict):
                bridge["customer"] = verification["customer"]
            if isinstance(verification.get("account"), dict):
                bridge["account"] = verification["account"]
            if verification.get("recent_payments") is not None:
                bridge["payments"] = verification.get("recent_payments")
        else:
            logger.info(
                "siga_bridge_verification_not_found_or_invalid",
                extra={
                    "company_id": company_id,
                    "folio": folio,
                    "payload_type": type(verification).__name__,
                },
            )

    if cuenta and bridge["account"] is None:
        account, error = await _safe_bridge_call(
            "verification_account",
            lambda: client.get_account(
                cuenta,
                company_id,
                bypass_cache=bypass_cache,
            ),
            company_id=company_id,
        )
        bridge["account"] = account
        if error:
            errors.append(error)

    if cuenta and bridge["payments"] is None:
        payments, error = await _safe_bridge_call(
            "verification_payments",
            lambda: client.get_payments(
                cuenta,
                company_id,
                limit=20,
                bypass_cache=bypass_cache,
            ),
            company_id=company_id,
        )
        bridge["payments"] = payments
        if error:
            errors.append(error)

    if phone and bridge["customer"] is None:
        phone_customer, error = await _safe_bridge_call(
            "verification_phone_customer_auxiliary",
            lambda: client.get_customer_by_phone(
                phone,
                company_id,
                bypass_cache=bypass_cache,
            ),
            company_id=company_id,
        )
        bridge["phone_customer"] = phone_customer
        if error:
            errors.append(error)
        else:
            phone_customer_record = _first_record(
                phone_customer,
                ("customers", "customer", "clientes", "cliente"),
            )
            if phone_customer_record:
                bridge["customer"] = phone_customer
                bridge["phone_lookup_used"] = True

    customer_record = _first_record(bridge["customer"], ("customers", "customer", "clientes", "cliente"))
    customer_name = _first_non_empty(
        customer_record,
        ("name", "nombre", "nombre_completo", "cliente"),
    )
    if not enriched.get("name") and customer_name:
        enriched["name"] = str(customer_name)

    account_record = _first_record(bridge["account"], ("accounts", "account", "cuentas", "cuenta"))
    bridge_cuenta = _first_non_empty(
        account_record,
        ("no_cuenta", "cuenta", "account", "account_number"),
    )
    if not enriched.get("no_cuenta") and bridge_cuenta:
        enriched["no_cuenta"] = str(bridge_cuenta)

    bridge["available"] = _verification_payload_found(bridge["verification"]) or any(
        bridge.get(key) is not None
        for key in ("customer", "account", "payments")
    )
    bridge["status"] = _bridge_status(errors, bridge["available"])
    bridge["source"] = "siga_bridge" if bridge["available"] else "local_fallback"
    bridge["error"] = "partial_failure" if errors and bridge["available"] else ("bridge_failed" if errors else None)
    enriched["siga_bridge"] = bridge

    logger.info(
        "siga_bridge_verification_enrichment_done",
        extra={
            "company_id": company_id,
            "folio_lookup": bool(folio),
            "available": bridge["available"],
            "has_customer": bridge["customer"] is not None,
            "has_phone_customer": bridge["phone_customer"] is not None,
            "has_account": bridge["account"] is not None,
            "has_payments": bridge["payments"] is not None,
            "status": bridge["status"],
            "error": bridge["error"],
        },
    )

    return enriched


async def lookup_verification_for_folio(
    folio: str,
    *,
    company_id: int | None = None,
    session: Any | None = None,
) -> dict[str, Any] | list[Any] | None:
    if not settings.SIGA_BRIDGE_ENABLED:
        return None

    normalized_folio = str(folio or "").strip()
    if not normalized_folio:
        return None

    logger.info(
        "siga_bridge_chatbot_verification_lookup_start",
        extra={
            "company_id": company_id,
            "folio": normalized_folio,
            "session_id": getattr(session, "id", None),
        },
    )

    client = get_siga_bridge_client()
    data, error = await _safe_bridge_call(
        "chatbot_verification_lookup",
        lambda: client.get_verification(normalized_folio, company_id),
        company_id=company_id,
    )
    if error:
        logger.warning(
            "siga_bridge_chatbot_verification_lookup_failed",
            extra={
                "company_id": company_id,
                "folio": normalized_folio,
                "session_id": getattr(session, "id", None),
                "error_type": error,
            },
        )
        return None

    found = bridge_verification_found(data)
    updated_at = _utc_timestamp()
    if session is not None:
        cache_bridge_verification_on_session(
            session,
            folio=normalized_folio,
            payload=data,
            found=found,
            updated_at=updated_at,
        )

    logger.info(
        "siga_bridge_chatbot_verification_lookup_done",
        extra={
            "company_id": company_id,
            "folio": normalized_folio,
            "session_id": getattr(session, "id", None),
            "found": found,
            "summary": bridge_sale_summary(data),
        },
    )
    return data


async def lookup_customer_for_incoming_phone(
    phone: str,
    *,
    company_id: int | None = None,
    session_id: int | None = None,
) -> dict[str, Any] | list[Any] | None:
    if not settings.SIGA_BRIDGE_ENABLED:
        return None

    normalized_phone = str(phone or "").strip()
    if not normalized_phone:
        return None

    client = get_siga_bridge_client()
    data, error = await _safe_bridge_call(
        "chatbot_customer_lookup",
        lambda: client.get_customer_by_phone(normalized_phone, company_id),
        company_id=company_id,
    )
    if error:
        return None

    customer_record = _first_record(data, ("customers", "customer", "clientes", "cliente"))
    updated_at = _utc_timestamp()
    if session_id is not None and customer_record is not None:
        await asyncio.to_thread(
            _persist_customer_lookup_cache,
            session_id=session_id,
            data=data,
            found=customer_record is not None,
            updated_at=updated_at,
        )
    elif session_id is not None:
        logger.info(
            "siga_bridge_phone_lookup_empty_not_cached",
            extra={
                "company_id": company_id,
                "session_id": session_id,
                "lookup_authoritative": False,
            },
        )

    logger.info(
        "siga_bridge_chatbot_lookup_done",
        extra={
            "company_id": company_id,
            "found": customer_record is not None,
        },
    )
    return data
