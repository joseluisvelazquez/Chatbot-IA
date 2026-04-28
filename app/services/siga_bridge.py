from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

_CACHE_TTLS_SECONDS = {
    "customer": 300.0,
    "account": 60.0,
    "payments": 30.0,
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

        attempts = 2
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            started_at = time.perf_counter()
            try:
                _metrics["requests"] += 1
                async with httpx.AsyncClient(
                    timeout=self._timeout(),
                    transport=self.transport,
                ) as client:
                    response = await client.get(
                        self.base_url,
                        headers=self._headers(),
                        params=request_params,
                    )

                latency_ms = (time.perf_counter() - started_at) * 1000
                _metrics["latency_ms_total"] += latency_ms
                _metrics["latency_count"] += 1

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
        payload = self._decode_json(response, action)

        if response.status_code >= 400:
            self._raise_for_status(response.status_code, payload, action)

        ok, data, error, meta = self._validate_contract(payload, action)
        if not ok:
            raise SigaBridgeContractError(
                "SIGA Bridge returned ok=false with HTTP 2xx",
                action=action,
                bridge_error=error,
            )

        return data

    def _decode_json(self, response: httpx.Response, action: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SigaBridgeContractError(
                "SIGA Bridge returned non-JSON response",
                action=action,
                status_code=response.status_code,
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
        if set(payload.keys()) != required:
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
            _metrics["errors"]["400"] += 1
            raise SigaBridgeBadRequestError(message, **kwargs)
        if status_code == 401:
            _metrics["errors"]["401"] += 1
            raise SigaBridgeUnauthorizedError(message, **kwargs)
        if status_code == 429:
            _metrics["errors"]["429"] += 1
            raise SigaBridgeRateLimitError(message, **kwargs)
        if status_code >= 500:
            _metrics["errors"]["500"] += 1
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
