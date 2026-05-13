from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config.settings import settings
from app.services.siga_bridge_sale import bridge_sale_summary

logger = logging.getLogger(__name__)

_BODY_PREVIEW_LIMIT = 500
_SENSITIVE_QUERY_KEYS = {
    "phone",
    "folio",
    "cuenta",
    "name",
    "nombre",
    "gestor",
    "collector",
    "search",
    "token",
    "bridge_token",
    "x-bridge-token",
}
_SENSITIVE_HEADER_MARKERS = ("authorization", "cookie", "token")
_FLAT_VERIFICATION_KEYS = {
    "found",
    "folio",
    "sale",
    "sales",
    "customer",
    "account",
    "components",
    "payment_summary",
    "recent_payments",
    "source_table",
}
_CACHE_TTLS_SECONDS = {
    "customer": 300.0,
    "account": 60.0,
    "payments": 30.0,
    "collections": 30.0,
    "collection_managers": 300.0,
}
_cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, Any]] = {}
_CACHE_MISS = object()
_metrics: dict[str, Any] = {
    "requests": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "timeouts": 0,
    "errors": {
        "400": 0,
        "401": 0,
        "429": 0,
        "500": 0,
    },
    "latency_ms_total": 0.0,
    "latency_count": 0,
}


def _mask(value: Any, *, visible: int = 4) -> str:
    text = str(value or "")
    if not text:
        return "[empty]"
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


def _sanitize_url(url: httpx.URL | str) -> str:
    try:
        parts = urlsplit(str(url))
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        redacted_pairs = []
        for key, value in query_pairs:
            key_lower = key.lower()
            if key_lower in _SENSITIVE_QUERY_KEYS or "token" in key_lower:
                redacted_pairs.append((key, "[redacted]"))
            else:
                redacted_pairs.append((key, value))

        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(redacted_pairs),
                parts.fragment,
            )
        )
    except Exception:
        return "[unavailable]"


def _sanitize_headers(headers: httpx.Headers) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if any(marker in key_lower for marker in _SENSITIVE_HEADER_MARKERS):
            sanitized[key] = "[redacted]"
        else:
            sanitized[key] = value
    return sanitized


def _debug_request_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in params.items():
        key_lower = str(key).lower()
        if key_lower in _SENSITIVE_QUERY_KEYS or "token" in key_lower:
            sanitized[key] = _mask(value)
        else:
            sanitized[key] = value
    return sanitized


def _record_http_error(status_code: int) -> None:
    if status_code == 400:
        _metrics["errors"]["400"] += 1
    elif status_code == 401:
        _metrics["errors"]["401"] += 1
    elif status_code == 429:
        _metrics["errors"]["429"] += 1
    elif status_code >= 500:
        _metrics["errors"]["500"] += 1


def _cache_key(action: str, request_params: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return (
        action,
        tuple(
            sorted(
                (str(key), str(value))
                for key, value in request_params.items()
                if key != "action" and value is not None
            )
        ),
    )


def _get_cached(action: str, request_params: dict[str, Any]) -> Any:
    ttl = _CACHE_TTLS_SECONDS.get(action)
    if ttl is None:
        return _CACHE_MISS

    key = _cache_key(action, request_params)
    cached = _cache.get(key)
    if not cached:
        _metrics["cache_misses"] += 1
        return _CACHE_MISS

    expires_at, value = cached
    if time.monotonic() >= expires_at:
        _cache.pop(key, None)
        _metrics["cache_misses"] += 1
        return _CACHE_MISS

    _metrics["cache_hits"] += 1
    logger.info("siga_bridge_cache_hit", extra={"action": action})
    return copy.deepcopy(value)


def _set_cached(action: str, request_params: dict[str, Any], value: Any) -> None:
    ttl = _CACHE_TTLS_SECONDS.get(action)
    if ttl is None:
        return

    if action == "customer" and isinstance(value, dict):
        customers = value.get("customers")
        if isinstance(customers, list) and len(customers) == 0:
            logger.info(
                "siga_bridge_customer_empty_not_cached",
                extra={
                    "action": action,
                    "company_id": request_params.get("company_id"),
                },
            )
            return

    _cache[_cache_key(action, request_params)] = (
        time.monotonic() + ttl,
        copy.deepcopy(value),
    )


def clear_siga_bridge_cache() -> None:
    _cache.clear()


def reset_siga_bridge_metrics() -> None:
    _metrics["requests"] = 0
    _metrics["cache_hits"] = 0
    _metrics["cache_misses"] = 0
    _metrics["timeouts"] = 0
    _metrics["latency_ms_total"] = 0.0
    _metrics["latency_count"] = 0
    for key in _metrics["errors"]:
        _metrics["errors"][key] = 0


def get_siga_bridge_metrics() -> dict[str, Any]:
    requests = int(_metrics["requests"])
    cache_hits = int(_metrics["cache_hits"])
    cache_misses = int(_metrics["cache_misses"])
    cache_total = cache_hits + cache_misses
    latency_count = int(_metrics["latency_count"])

    return {
        "requests": requests,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_ratio": round(cache_hits / cache_total, 4) if cache_total else 0.0,
        "timeouts": int(_metrics["timeouts"]),
        "errors": dict(_metrics["errors"]),
        "rate_limit_hits": int(_metrics["errors"]["429"]),
        "avg_latency_ms": (
            round(float(_metrics["latency_ms_total"]) / latency_count, 2)
            if latency_count
            else 0.0
        ),
    }


def reset_siga_bridge_observability() -> None:
    clear_siga_bridge_cache()
    reset_siga_bridge_metrics()


class SigaBridgeError(Exception):
    def __init__(
        self,
        message: str,
        *,
        action: str | None = None,
        status_code: int | None = None,
        bridge_error: str | None = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.status_code = status_code
        self.bridge_error = bridge_error


class SigaBridgeConfigError(SigaBridgeError):
    pass


class SigaBridgeContractError(SigaBridgeError):
    pass


class SigaBridgeBadRequestError(SigaBridgeError):
    pass


class SigaBridgeUnauthorizedError(SigaBridgeError):
    pass


class SigaBridgeRateLimitError(SigaBridgeError):
    pass


class SigaBridgeServerError(SigaBridgeError):
    pass


class SigaBridgeUnavailableError(SigaBridgeError):
    pass


class SigaBridgeClient:
    _TRANSIENT_STATUS_CODES = {502, 503, 504}

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        enabled: bool | None = None,
        timeout_connect: float | None = None,
        timeout_read: float | None = None,
        max_attempts: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.SIGA_BRIDGE_BASE_URL).strip()
        self.token = token if token is not None else settings.SIGA_BRIDGE_TOKEN
        self.enabled = settings.SIGA_BRIDGE_ENABLED if enabled is None else enabled
        self.timeout_connect = (
            settings.SIGA_BRIDGE_TIMEOUT_CONNECT
            if timeout_connect is None
            else timeout_connect
        )
        self.timeout_read = (
            settings.SIGA_BRIDGE_TIMEOUT_READ
            if timeout_read is None
            else timeout_read
        )
        self.max_attempts = max(1, int(max_attempts or 2))
        self.transport = transport

    async def ping(self) -> dict[str, Any] | list[Any] | None:
        return await self._get("ping")

    async def get_customer_by_phone(
        self,
        phone: str,
        company_id: int | None = None,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any] | list[Any] | None:
        params: dict[str, Any] = {"phone": phone}
        if company_id is not None:
            params["company_id"] = company_id
        digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
        logger.info(
            "siga_bridge_customer_lookup_input",
            extra={
                "company_id": company_id,
                "phone_digits_len": len(digits),
                "phone_last4": digits[-4:] if digits else None,
                "lookup_authoritative": False,
            },
        )
        return await self._get("customer", params, bypass_cache=bypass_cache)

    async def get_folio(
        self,
        folio: str,
        company_id: int | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        params: dict[str, Any] = {"folio": folio}
        if company_id is not None:
            params["company_id"] = company_id
        return await self._get("folio", params)

    async def get_verification(
        self,
        folio: str,
        company_id: int | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        params: dict[str, Any] = {"folio": folio}
        if company_id is not None:
            params["company_id"] = company_id
        logger.info(
            "siga_bridge_verification_lookup_input",
            extra={
                "company_id": company_id,
                "folio_masked": _mask(folio),
                "lookup_authoritative": True,
            },
        )
        return await self._get("verification", params)

    async def get_account(
        self,
        cuenta: str,
        company_id: int | None = None,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any] | list[Any] | None:
        params: dict[str, Any] = {"cuenta": cuenta}
        if company_id is not None:
            params["company_id"] = company_id
        return await self._get("account", params, bypass_cache=bypass_cache)

    async def get_payments(
        self,
        cuenta: str,
        company_id: int | None = None,
        limit: int | None = None,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any] | list[Any] | None:
        params: dict[str, Any] = {"cuenta": cuenta}
        if company_id is not None:
            params["company_id"] = company_id
        if limit is not None:
            params["limit"] = limit
        return await self._get("payments", params, bypass_cache=bypass_cache)

    async def get_collections(
        self,
        company_id: int,
        *,
        cuenta: str | None = None,
        folio: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        status: str | None = None,
        classification: str | None = None,
        gestor: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        overdue_only: bool = False,
        paid_only: bool = False,
        include_paid: bool = False,
        active_only: bool = False,
        collector: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        bypass_cache: bool = False,
    ) -> dict[str, Any] | list[Any] | None:
        params: dict[str, Any] = {"company_id": company_id}
        optional_params = {
            "cuenta": cuenta,
            "folio": folio,
            "phone": phone,
            "name": name,
            "status": status,
            "classification": classification,
            "date_from": date_from,
            "date_to": date_to,
            "collector": collector,
            "gestor": gestor,
            "limit": limit,
            "offset": offset,
        }
        params.update({
            key: value
            for key, value in optional_params.items()
            if value not in (None, "")
        })
        if overdue_only:
            params["overdue_only"] = "1"
        if paid_only:
            params["paid_only"] = "1"
        if include_paid:
            params["include_paid"] = "1"
        if active_only:
            params["active_only"] = "1"
        return await self._get("collections", params, bypass_cache=bypass_cache)

    async def get_collection_managers(
        self,
        company_id: int,
        *,
        search: str | None = None,
        limit: int | None = None,
        bypass_cache: bool = False,
    ) -> dict[str, Any] | list[Any] | None:
        params: dict[str, Any] = {"company_id": company_id}
        if search:
            params["search"] = search
        if limit is not None:
            params["limit"] = limit
        return await self._get("collection_managers", params, bypass_cache=bypass_cache)

    def _validate_config(self) -> None:
        if not self.enabled:
            raise SigaBridgeConfigError("SIGA Bridge is disabled")
        if not self.base_url:
            raise SigaBridgeConfigError("SIGA Bridge base URL is not configured")
        if not self.token:
            raise SigaBridgeConfigError("SIGA Bridge token is not configured")

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.timeout_connect,
            read=self.timeout_read,
            write=2.0,
            pool=2.0,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "X-Bridge-Token": str(self.token),
            "Accept": "application/json",
        }

    async def _get(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any] | list[Any] | None:
        self._validate_config()

        request_params = {"action": action}
        if params:
            request_params.update(params)

        if not bypass_cache:
            cached = _get_cached(action, request_params)
            if cached is not _CACHE_MISS:
                return cached

        attempts = self.max_attempts
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            started_at = time.perf_counter()
            try:
                _metrics["requests"] += 1
                logger.info(
                    "siga_bridge_request_outgoing",
                    extra={
                        "action": action,
                        "base_url": _sanitize_url(self.base_url),
                        "params": _debug_request_params(action, request_params),
                        "attempt": attempt,
                    },
                )
                async with httpx.AsyncClient(
                    timeout=self._timeout(),
                    transport=self.transport,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(
                        self.base_url,
                        headers=self._headers(),
                        params=request_params,
                    )

                latency_ms = (time.perf_counter() - started_at) * 1000
                _metrics["latency_ms_total"] += latency_ms
                _metrics["latency_count"] += 1
                self._log_response_debug(response, action, latency_ms)

                if response.status_code in self._TRANSIENT_STATUS_CODES and attempt < attempts:
                    logger.warning(
                        "siga_bridge_transient_http_status",
                        extra={
                            "action": action,
                            "attempt": attempt,
                            "status_code": response.status_code,
                        },
                    )
                    await asyncio.sleep(0)
                    continue

                data = self._handle_response(response, action)
                logger.info(
                    "siga_bridge_request_ok",
                    extra={
                        "action": action,
                        "status_code": response.status_code,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
                _set_cached(action, request_params, data)
                return data

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                latency_ms = (time.perf_counter() - started_at) * 1000
                _metrics["latency_ms_total"] += latency_ms
                _metrics["latency_count"] += 1
                if isinstance(exc, httpx.TimeoutException):
                    _metrics["timeouts"] += 1
                logger.warning(
                    "siga_bridge_transport_error",
                    extra={
                        "action": action,
                        "attempt": attempt,
                        "error_type": exc.__class__.__name__,
                    },
                )
                if attempt < attempts:
                    await asyncio.sleep(0)
                    continue

        raise SigaBridgeUnavailableError(
            "SIGA Bridge is unavailable",
            action=action,
            bridge_error=last_error.__class__.__name__ if last_error else None,
        )

    def _handle_response(
        self,
        response: httpx.Response,
        action: str,
    ) -> dict[str, Any] | list[Any] | None:
        if not self._is_json_response(response):
            self._raise_non_json_response(response, action)

        payload = self._decode_json(response, action)
        self._log_parsed_json_debug(payload, action, response.status_code)

        if response.status_code >= 400:
            self._raise_for_status(response.status_code, payload, action)

        ok, data, error, meta = self._validate_contract(payload, action)
        self._log_contract_decision_debug(action, ok, data, error, meta)
        if not ok:
            raise SigaBridgeContractError(
                "SIGA Bridge returned ok=false with HTTP 2xx",
                action=action,
                bridge_error=error,
            )

        return data

    def _log_response_debug(
        self,
        response: httpx.Response,
        action: str,
        latency_ms: float,
    ) -> None:
        redirect_chain = [
            {
                "status_code": item.status_code,
                "url": _sanitize_url(item.url),
                "location": (
                    _sanitize_url(item.headers["location"])
                    if item.headers.get("location")
                    else None
                ),
            }
            for item in response.history
        ]
        try:
            request_url = response.request.url
        except RuntimeError:
            request_url = response.url

        should_log_body = (
            response.status_code >= 400
            or not self._is_json_response(response)
            or bool(settings.SIGA_BRIDGE_LOG_RAW_SUCCESS)
        )
        logger.info(
            "siga_bridge_response_debug",
            extra={
                "action": action,
                "status_code": response.status_code,
                "url": _sanitize_url(request_url),
                "final_url": _sanitize_url(response.url),
                "headers": _sanitize_headers(response.headers),
                "content_type": self._content_type(response),
                "body_preview": (
                    self._body_preview(response)
                    if should_log_body
                    else "[omitted_json_success]"
                ),
                "latency_ms": round(latency_ms, 2),
                "redirect_count": len(response.history),
                "redirect_chain": redirect_chain,
            },
        )

    def _log_parsed_json_debug(
        self,
        payload: dict[str, Any],
        action: str,
        status_code: int,
    ) -> None:
        logger.info(
            "siga_bridge_parsed_json",
            extra={
                "action": action,
                "status_code": status_code,
                "top_level_keys": sorted(str(key) for key in payload.keys()),
                "has_v1_wrapper": {"ok", "data", "error", "meta"}.issubset(payload.keys()),
                "flat_summary": bridge_sale_summary(payload)
                if action == "verification"
                else None,
            },
        )

    def _log_contract_decision_debug(
        self,
        action: str,
        ok: bool,
        data: dict[str, Any] | list[Any] | None,
        error: str | None,
        meta: dict[str, Any],
    ) -> None:
        logger.info(
            "siga_bridge_contract_decision",
            extra={
                "action": action,
                "ok": ok,
                "error": error,
                "meta_action": meta.get("action"),
                "contract_shape": meta.get("contract_shape", "v1"),
                "data_summary": bridge_sale_summary(data)
                if action == "verification"
                else {
                    "payload_type": type(data).__name__,
                    "keys": sorted(str(key) for key in data.keys())
                    if isinstance(data, dict)
                    else None,
                    "items_count": len(data) if isinstance(data, list) else None,
                },
            },
        )

    def _content_type(self, response: httpx.Response) -> str:
        return response.headers.get("content-type", "")

    def _is_json_response(self, response: httpx.Response) -> bool:
        return "application/json" in self._content_type(response).lower()

    def _body_preview(self, response: httpx.Response) -> str:
        try:
            return response.text[:_BODY_PREVIEW_LIMIT]
        except UnicodeDecodeError:
            return response.content[:_BODY_PREVIEW_LIMIT].decode("utf-8", errors="replace")
        except Exception:
            return "[unavailable]"

    def _looks_like_html(self, body_preview: str, content_type: str) -> bool:
        normalized_body = body_preview.lstrip().lower()
        normalized_type = content_type.lower()
        return (
            "text/html" in normalized_type
            or normalized_body.startswith("<!doctype html")
            or normalized_body.startswith("<html")
            or "<html" in normalized_body[:120]
        )

    def _raise_non_json_response(self, response: httpx.Response, action: str) -> None:
        status_code = response.status_code
        content_type = self._content_type(response)
        body_preview = self._body_preview(response)
        is_html = self._looks_like_html(body_preview, content_type)
        response_kind = "HTML instead of JSON" if is_html else "non-JSON response"
        message = f"SIGA Bridge returned {response_kind}"
        bridge_error = (
            f"status={status_code}; content_type={content_type or '[missing]'}; "
            f"body_preview={body_preview}"
        )

        logger.warning(
            "siga_bridge_non_json_response",
            extra={
                "action": action,
                "status_code": status_code,
                "content_type": content_type,
                "body_preview": body_preview,
                "final_url": _sanitize_url(response.url),
                "redirect_count": len(response.history),
            },
        )

        kwargs = {
            "action": action,
            "status_code": status_code,
            "bridge_error": bridge_error,
        }

        if status_code >= 400:
            _record_http_error(status_code)
        if status_code == 400:
            raise SigaBridgeBadRequestError(message, **kwargs)
        if status_code == 401:
            raise SigaBridgeUnauthorizedError("SIGA Bridge unauthorized", **kwargs)
        if status_code == 429:
            raise SigaBridgeRateLimitError(message, **kwargs)
        if status_code >= 500:
            raise SigaBridgeServerError(message, **kwargs)

        raise SigaBridgeContractError(message, **kwargs)

    def _decode_json(self, response: httpx.Response, action: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SigaBridgeContractError(
                "SIGA Bridge returned invalid JSON response",
                action=action,
                status_code=response.status_code,
                bridge_error=self._body_preview(response),
            ) from exc

        if not isinstance(payload, dict):
            raise SigaBridgeContractError(
                "SIGA Bridge JSON payload must be an object",
                action=action,
                status_code=response.status_code,
            )
        return payload

    def _validate_contract(
        self,
        payload: dict[str, Any],
        action: str,
    ) -> tuple[bool, dict[str, Any] | list[Any] | None, str | None, dict[str, Any]]:
        required = {"ok", "data", "error", "meta"}
        if required.issubset(payload.keys()):
            ok, data, error, meta = self._validate_v1_contract(payload, action)
            has_flat_verification_data = any(key in payload for key in _FLAT_VERIFICATION_KEYS)
            if action == "verification" and has_flat_verification_data and data in (None, {}):
                _flat_ok, flat_data, _flat_error, _flat_meta = self._validate_flat_contract(
                    payload,
                    action,
                )
                return ok, flat_data, error, {
                    **meta,
                    "contract_shape": "v1_flat",
                }
            return ok, data, error, meta

        return self._validate_flat_contract(payload, action)

    def _validate_v1_contract(
        self,
        payload: dict[str, Any],
        action: str,
    ) -> tuple[bool, dict[str, Any] | list[Any] | None, str | None, dict[str, Any]]:
        required = {"ok", "data", "error", "meta"}
        if not required.issubset(payload.keys()):
            raise SigaBridgeContractError(
                "SIGA Bridge response contract mismatch",
                action=action,
            )

        ok = payload["ok"]
        data = payload["data"]
        error = payload["error"]
        meta = payload["meta"]

        if not isinstance(ok, bool):
            raise SigaBridgeContractError("SIGA Bridge ok must be boolean", action=action)
        if data is not None and not isinstance(data, (dict, list)):
            raise SigaBridgeContractError("SIGA Bridge data must be object, array or null", action=action)
        if error is not None and not isinstance(error, str):
            raise SigaBridgeContractError("SIGA Bridge error must be string or null", action=action)
        if not isinstance(meta, dict):
            raise SigaBridgeContractError("SIGA Bridge meta must be object", action=action)
        if meta.get("version") != "v1":
            raise SigaBridgeContractError("SIGA Bridge version mismatch", action=action)
        if not isinstance(meta.get("timestamp"), str):
            raise SigaBridgeContractError("SIGA Bridge timestamp missing", action=action)
        if meta.get("action") != action:
            raise SigaBridgeContractError("SIGA Bridge action mismatch", action=action)

        return ok, data, error, meta

    def _validate_flat_contract(
        self,
        payload: dict[str, Any],
        action: str,
    ) -> tuple[bool, dict[str, Any] | list[Any] | None, str | None, dict[str, Any]]:
        if "ok" not in payload:
            raise SigaBridgeContractError(
                "SIGA Bridge response contract mismatch",
                action=action,
            )

        ok = payload["ok"]
        error = payload.get("error")
        payload_action = payload.get("action") or action
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

        if not isinstance(ok, bool):
            raise SigaBridgeContractError("SIGA Bridge ok must be boolean", action=action)
        if error is not None and not isinstance(error, str):
            raise SigaBridgeContractError("SIGA Bridge error must be string or null", action=action)
        if payload_action != action:
            raise SigaBridgeContractError("SIGA Bridge action mismatch", action=action)

        data = {
            key: value
            for key, value in payload.items()
            if key not in {"ok", "error", "meta"}
        }
        if not data:
            data = None

        return ok, data, error, {
            "version": meta.get("version") or "flat",
            "timestamp": meta.get("timestamp"),
            "action": payload_action,
            "contract_shape": "flat",
        }

    def _raise_for_status(
        self,
        status_code: int,
        payload: dict[str, Any],
        action: str,
    ) -> None:
        try:
            ok, _data, error, _meta = self._validate_contract(payload, action)
        except SigaBridgeContractError:
            error = None
            ok = False

        message = error or f"SIGA Bridge HTTP error {status_code}"
        kwargs = {
            "action": action,
            "status_code": status_code,
            "bridge_error": error,
        }

        if status_code == 400:
            _record_http_error(status_code)
            raise SigaBridgeBadRequestError(message, **kwargs)
        if status_code == 401:
            _record_http_error(status_code)
            raise SigaBridgeUnauthorizedError(message, **kwargs)
        if status_code == 429:
            _record_http_error(status_code)
            raise SigaBridgeRateLimitError(message, **kwargs)
        if status_code >= 500:
            _record_http_error(status_code)
            raise SigaBridgeServerError(message, **kwargs)

        if ok is False:
            raise SigaBridgeError(message, **kwargs)
        raise SigaBridgeError(message, **kwargs)


def get_siga_bridge_client() -> SigaBridgeClient:
    return SigaBridgeClient()


async def ping() -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().ping()


async def get_customer_by_phone(
    phone: str,
    company_id: int | None = None,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().get_customer_by_phone(
        phone,
        company_id,
        bypass_cache=bypass_cache,
    )


async def get_folio(
    folio: str,
    company_id: int | None = None,
) -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().get_folio(folio, company_id)


async def get_verification(
    folio: str,
    company_id: int | None = None,
) -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().get_verification(folio, company_id)


async def get_account(
    cuenta: str,
    company_id: int | None = None,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().get_account(
        cuenta,
        company_id,
        bypass_cache=bypass_cache,
    )


async def get_payments(
    cuenta: str,
    company_id: int | None = None,
    limit: int | None = None,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().get_payments(
        cuenta,
        company_id,
        limit,
        bypass_cache=bypass_cache,
    )


async def get_collections(
    company_id: int,
    **kwargs: Any,
) -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().get_collections(company_id, **kwargs)


async def get_collection_managers(
    company_id: int,
    **kwargs: Any,
) -> dict[str, Any] | list[Any] | None:
    return await get_siga_bridge_client().get_collection_managers(company_id, **kwargs)
