from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.config.settings import settings
from app.core.states.states import ChatState
from app.services.siga_bridge import SigaBridgeClient, SigaBridgeError
from app.services.siga_bridge_sale import (
    bridge_sale_summary,
    normalize_siga_verification_snapshot,
)

logger = logging.getLogger(__name__)

_folio_locks: dict[str, asyncio.Lock] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _session_finalized(session: Any) -> bool:
    state = getattr(session, "state", None)
    value = getattr(state, "value", state)
    return str(value or "") == ChatState.FINALIZADO.value


def _mask(value: Any, *, visible: int = 4) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


def _snapshot_log_meta(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {"found": False}

    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    return {
        "found": bool(snapshot.get("found")),
        "folio_masked": _mask(snapshot.get("folio")),
        "no_cuenta_masked": _mask(snapshot.get("no_cuenta")),
        "phone_last4": _mask(snapshot.get("phone")),
        "source_table": source.get("table"),
    }


def _read_extra_json(session: Any) -> dict[str, Any]:
    current = getattr(session, "extra_json", None)
    if isinstance(current, str):
        try:
            current = json.loads(current) if current else {}
        except json.JSONDecodeError:
            current = {}
    if not isinstance(current, dict):
        return {}
    return copy.deepcopy(current)


def _write_extra_json(session: Any, payload: dict[str, Any]) -> None:
    if session is None:
        return
    session.extra_json = payload
    try:
        flag_modified(session, "extra_json")
    except Exception:
        pass


def _siga_payload(extra_json: dict[str, Any]) -> dict[str, Any]:
    siga_payload = extra_json.get("siga_bridge")
    if not isinstance(siga_payload, dict):
        siga_payload = {}
        extra_json["siga_bridge"] = siga_payload
    return siga_payload


def _lock_for_folio(folio: str) -> asyncio.Lock:
    lock = _folio_locks.get(folio)
    if lock is None:
        lock = asyncio.Lock()
        _folio_locks[folio] = lock
    return lock


def _normalize_for_cache(payload: Any, folio: str, fetched_at: str | None = None) -> dict[str, Any]:
    snapshot = normalize_siga_verification_snapshot(payload, fetched_at=fetched_at)
    if not snapshot.get("folio"):
        snapshot["folio"] = str(folio)
    return snapshot


def _legacy_lookup_as_cache_row(siga_payload: dict[str, Any], folio: str | None) -> dict[str, Any] | None:
    lookup = siga_payload.get("verification_lookup")
    if not isinstance(lookup, dict):
        return None
    if folio and str(lookup.get("folio") or "") != str(folio):
        return None

    payload = lookup.get("data")
    if payload is None:
        return None

    updated_at = lookup.get("updated_at")
    fetched_at = updated_at if isinstance(updated_at, str) else None
    snapshot = _normalize_for_cache(payload, str(lookup.get("folio") or folio or ""), fetched_at=fetched_at)
    fetched_dt = _parse_dt(fetched_at)
    expires_at = (
        _iso(fetched_dt + timedelta(seconds=settings.SIGA_BRIDGE_VERIFICATION_CACHE_TTL_SECONDS))
        if fetched_dt
        else None
    )
    return {
        "folio": str(lookup.get("folio") or folio or ""),
        "snapshot": snapshot,
        "fetched_at": fetched_at,
        "expires_at": expires_at,
        "last_error": None,
        "legacy": True,
    }


def get_cached_verification_row(
    session: Any,
    folio: str | None = None,
    *,
    allow_stale: bool = False,
) -> dict[str, Any] | None:
    extra_json = _read_extra_json(session)
    siga_payload = extra_json.get("siga_bridge")
    if not isinstance(siga_payload, dict):
        return None

    row = siga_payload.get("verification_cache")
    if not isinstance(row, dict):
        row = _legacy_lookup_as_cache_row(siga_payload, folio)
    if not isinstance(row, dict):
        return None

    if folio and str(row.get("folio") or "") != str(folio):
        return None

    snapshot = row.get("snapshot")
    if not isinstance(snapshot, dict):
        return None

    if not allow_stale and not is_cache_valid(row, session=session):
        return None

    return copy.deepcopy(row)


def get_cached_verification(
    session: Any,
    folio: str | None = None,
    *,
    allow_stale: bool = False,
) -> dict[str, Any] | None:
    row = get_cached_verification_row(session, folio, allow_stale=allow_stale)
    if not row:
        return None
    snapshot = row.get("snapshot")
    return copy.deepcopy(snapshot) if isinstance(snapshot, dict) else None


def is_cache_valid(cache_row: dict[str, Any] | None, *, session: Any = None) -> bool:
    if not isinstance(cache_row, dict):
        return False
    if _session_finalized(session):
        return True

    expires_at = _parse_dt(cache_row.get("expires_at"))
    return bool(expires_at and expires_at > _utcnow())


def upsert_cached_verification(
    session: Any,
    folio: str,
    snapshot: Any,
    raw: Any = None,
    *,
    ttl_seconds: int | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    normalized_folio = str(folio or "").strip()
    now = _utcnow()
    ttl = ttl_seconds or settings.SIGA_BRIDGE_VERIFICATION_CACHE_TTL_SECONDS
    normalized_snapshot = _normalize_for_cache(snapshot, normalized_folio, fetched_at=_iso(now))

    extra_json = _read_extra_json(session)
    siga_payload = _siga_payload(extra_json)
    row = {
        "folio": normalized_folio,
        "snapshot": normalized_snapshot,
        "raw_summary": bridge_sale_summary(raw if raw is not None else snapshot),
        "fetched_at": normalized_snapshot.get("source", {}).get("fetched_at") if isinstance(normalized_snapshot.get("source"), dict) else _iso(now),
        "expires_at": _iso(now + timedelta(seconds=ttl)),
        "last_error": last_error,
    }

    siga_payload["verification_cache"] = row
    siga_payload["verification_lookup"] = {
        "source": "siga_bridge_v1",
        "lookup_type": "folio",
        "authoritative": True,
        "updated_at": row["fetched_at"],
        "folio": normalized_folio,
        "found": bool(normalized_snapshot.get("found")),
        "data": normalized_snapshot,
        "summary": bridge_sale_summary(normalized_snapshot),
    }
    _write_extra_json(session, extra_json)

    logger.info(
        "siga_bridge_cache_upsert",
        extra={
            "session_id": getattr(session, "id", None),
            "folio_masked": _mask(normalized_folio),
            "ttl_seconds": ttl,
            **_snapshot_log_meta(normalized_snapshot),
        },
    )
    return normalized_snapshot


def record_verification_cache_error(session: Any, folio: str, error_type: str) -> None:
    extra_json = _read_extra_json(session)
    siga_payload = extra_json.get("siga_bridge")
    if not isinstance(siga_payload, dict):
        return

    row = siga_payload.get("verification_cache")
    if not isinstance(row, dict) or str(row.get("folio") or "") != str(folio):
        return

    row["last_error"] = error_type
    row["last_error_at"] = _iso(_utcnow())
    siga_payload["verification_cache"] = row
    _write_extra_json(session, extra_json)


async def get_or_fetch_verification(
    session: Any,
    folio: str,
    *,
    company_id: int | None = None,
    force_refresh: bool = False,
    bridge_client: SigaBridgeClient | None = None,
    allow_stale_on_error: bool = True,
) -> dict[str, Any] | None:
    normalized_folio = str(folio or "").strip()
    if not normalized_folio:
        return None

    if not force_refresh:
        cached = get_cached_verification(session, normalized_folio)
        if cached is not None:
            logger.info(
                "siga_bridge_cache_hit",
                extra={
                    "session_id": getattr(session, "id", None),
                    "folio_masked": _mask(normalized_folio),
                    **_snapshot_log_meta(cached),
                },
            )
            return cached

    logger.info(
        "siga_bridge_cache_miss",
        extra={
            "session_id": getattr(session, "id", None),
            "folio_masked": _mask(normalized_folio),
            "force_refresh": force_refresh,
        },
    )

    if not settings.SIGA_BRIDGE_ENABLED:
        return get_cached_verification(session, normalized_folio, allow_stale=True)

    async with _lock_for_folio(normalized_folio):
        if not force_refresh:
            cached = get_cached_verification(session, normalized_folio)
            if cached is not None:
                logger.info(
                    "siga_bridge_cache_hit",
                    extra={
                        "session_id": getattr(session, "id", None),
                        "folio_masked": _mask(normalized_folio),
                        "after_wait": True,
                        **_snapshot_log_meta(cached),
                    },
                )
                return cached

        client = bridge_client or SigaBridgeClient(
            timeout_connect=settings.SIGA_BRIDGE_VERIFICATION_TIMEOUT_CONNECT,
            timeout_read=settings.SIGA_BRIDGE_VERIFICATION_TIMEOUT_READ,
            max_attempts=settings.SIGA_BRIDGE_VERIFICATION_MAX_ATTEMPTS,
        )
        started_at = time.perf_counter()
        try:
            raw = await client.get_verification(normalized_folio, company_id)
            snapshot = _normalize_for_cache(raw, normalized_folio)
            snapshot = upsert_cached_verification(session, normalized_folio, snapshot, raw)
            logger.info(
                "chatbot_folio_resolution_decision",
                extra={
                    "session_id": getattr(session, "id", None),
                    "folio_masked": _mask(normalized_folio),
                    "source": "bridge",
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    **_snapshot_log_meta(snapshot),
                },
            )
            return snapshot
        except SigaBridgeError as exc:
            record_verification_cache_error(session, normalized_folio, exc.__class__.__name__)
            logger.warning(
                "siga_bridge_cache_fetch_failed",
                extra={
                    "session_id": getattr(session, "id", None),
                    "folio_masked": _mask(normalized_folio),
                    "company_id": company_id,
                    "error_type": exc.__class__.__name__,
                    "status_code": exc.status_code,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
        except Exception:
            record_verification_cache_error(session, normalized_folio, "UnexpectedError")
            logger.exception(
                "siga_bridge_cache_fetch_unexpected",
                extra={
                    "session_id": getattr(session, "id", None),
                    "folio_masked": _mask(normalized_folio),
                    "company_id": company_id,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )

    if allow_stale_on_error:
        stale = get_cached_verification(session, normalized_folio, allow_stale=True)
        if stale is not None:
            logger.info(
                "siga_bridge_cache_stale_used",
                extra={
                    "session_id": getattr(session, "id", None),
                    "folio_masked": _mask(normalized_folio),
                    **_snapshot_log_meta(stale),
                },
            )
            return stale

    return None


def apply_siga_snapshot_to_panel_item(
    item: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    cache_valid: bool | None = None,
    refreshed: bool = False,
) -> dict[str, Any]:
    enriched = item
    if not isinstance(snapshot, dict):
        enriched.setdefault(
            "siga",
            {
                "available": False,
                "fetched_at": None,
                "source_table": None,
            },
        )
        enriched.setdefault(
            "siga_bridge",
            {
                "enabled": bool(settings.SIGA_BRIDGE_ENABLED),
                "available": False,
                "status": "fallback_local",
                "source": "local_fallback",
                "updated_at": None,
            },
        )
        return enriched

    customer = snapshot.get("customer") if isinstance(snapshot.get("customer"), dict) else {}
    sale = snapshot.get("sale") if isinstance(snapshot.get("sale"), dict) else {}
    payment = snapshot.get("payment") if isinstance(snapshot.get("payment"), dict) else {}
    components = snapshot.get("components") if isinstance(snapshot.get("components"), dict) else {}
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    available = bool(snapshot.get("found"))
    fetched_at = source.get("fetched_at")

    if not enriched.get("no_cuenta") and snapshot.get("no_cuenta"):
        enriched["no_cuenta"] = str(snapshot["no_cuenta"])
    if not enriched.get("phone") and snapshot.get("phone"):
        enriched["phone"] = str(snapshot["phone"])
    if not enriched.get("name") and customer.get("name"):
        enriched["name"] = str(customer["name"])

    enriched["siga"] = {
        "available": available,
        "fetched_at": fetched_at,
        "source_table": source.get("table"),
        "customer": customer,
        "sale": sale,
        "payment": payment,
        "components": components,
        "cache_valid": cache_valid,
    }
    enriched["siga_bridge"] = {
        "enabled": bool(settings.SIGA_BRIDGE_ENABLED),
        "available": available,
        "status": "ok" if available else "fallback_local",
        "source": "siga_bridge" if available else "local_fallback",
        "updated_at": fetched_at,
        "normalized": snapshot,
        "refreshed": bool(refreshed),
    }
    return enriched
