from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.siga_bridge import (
    SigaBridgeClient,
    SigaBridgeConfigError,
    SigaBridgeContractError,
    SigaBridgeRateLimitError,
    SigaBridgeUnauthorizedError,
    get_siga_bridge_metrics,
    reset_siga_bridge_observability,
)


_DEFAULT_DATA = object()


def run(coro):
    return asyncio.run(coro)


def bridge_payload(
    *,
    action: str = "ping",
    ok: bool = True,
    data=_DEFAULT_DATA,
    error: str | None = None,
) -> dict:
    if data is _DEFAULT_DATA:
        data = {} if ok else None

    return {
        "ok": ok,
        "data": data,
        "error": error,
        "meta": {
            "version": "v1",
            "timestamp": "2026-04-27T12:00:00-06:00",
            "action": action,
        },
    }


def make_client(handler) -> SigaBridgeClient:
    return SigaBridgeClient(
        base_url="http://bridge.local/bridge/",
        token="test-token",
        enabled=True,
        transport=httpx.MockTransport(handler),
    )


@pytest.fixture(autouse=True)
def reset_bridge_observability():
    reset_siga_bridge_observability()
    yield
    reset_siga_bridge_observability()


def test_contract_ok_true_returns_data():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Bridge-Token"] == "test-token"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(
            200,
            json=bridge_payload(action="ping", data={"status": "ok"}),
        )

    client = make_client(handler)

    assert run(client.ping()) == {"status": "ok"}


def test_ok_false_with_2xx_raises_contract_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=bridge_payload(
                action="ping",
                ok=False,
                data=None,
                error="bridge_error: unexpected",
            ),
        )

    client = make_client(handler)

    with pytest.raises(SigaBridgeContractError):
        run(client.ping())


def test_html_2xx_raises_contract_error_with_body_preview():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content="<html><body>IONOS maintenance page</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    client = make_client(handler)

    with pytest.raises(SigaBridgeContractError) as exc_info:
        run(client.ping())

    assert "HTML instead of JSON" in str(exc_info.value)
    assert exc_info.value.status_code == 200
    assert "IONOS maintenance page" in (exc_info.value.bridge_error or "")


def test_invalid_json_content_type_raises_contract_error_with_preview():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content="{invalid",
            headers={"content-type": "application/json"},
        )

    client = make_client(handler)

    with pytest.raises(SigaBridgeContractError) as exc_info:
        run(client.ping())

    assert "invalid JSON" in str(exc_info.value)
    assert "{invalid" in (exc_info.value.bridge_error or "")


def test_401_maps_to_unauthorized_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json=bridge_payload(
                action="ping",
                ok=False,
                data=None,
                error="unauthorized: Missing or invalid bridge token.",
            ),
        )

    client = make_client(handler)

    with pytest.raises(SigaBridgeUnauthorizedError) as exc_info:
        run(client.ping())

    assert exc_info.value.status_code == 401
    assert "unauthorized" in str(exc_info.value)
    assert get_siga_bridge_metrics()["errors"]["401"] == 1


def test_401_html_maps_to_unauthorized_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            content="<html><body>Unauthorized</body></html>",
            headers={"content-type": "text/html"},
        )

    client = make_client(handler)

    with pytest.raises(SigaBridgeUnauthorizedError) as exc_info:
        run(client.ping())

    assert exc_info.value.status_code == 401
    assert "unauthorized" in str(exc_info.value).lower()
    assert "Unauthorized" in (exc_info.value.bridge_error or "")
    assert get_siga_bridge_metrics()["errors"]["401"] == 1


def test_redirects_are_followed_and_final_json_is_parsed():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.scheme == "http":
            return httpx.Response(
                302,
                headers={"location": "https://bridge.local/bridge/?action=ping"},
            )
        return httpx.Response(
            200,
            json=bridge_payload(action="ping", data={"status": "ok"}),
        )

    client = make_client(handler)

    assert run(client.ping()) == {"status": "ok"}
    assert len(calls) == 2
    assert calls[0].startswith("http://bridge.local/bridge/")
    assert calls[1].startswith("https://bridge.local/bridge/")


def test_timeout_retries_once_for_get():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("read timeout", request=request)
        return httpx.Response(
            200,
            json=bridge_payload(action="ping", data={"status": "ok"}),
        )

    client = make_client(handler)

    assert run(client.ping()) == {"status": "ok"}
    assert calls["count"] == 2
    metrics = get_siga_bridge_metrics()
    assert metrics["requests"] == 2
    assert metrics["timeouts"] == 1


def test_token_missing_config_raises_before_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("request should not be sent without token")

    client = SigaBridgeClient(
        base_url="http://bridge.local/bridge/",
        token="",
        enabled=True,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SigaBridgeConfigError):
        run(client.ping())


def test_params_are_sent_correctly_without_logging_token():
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["action"] == "payments"
        assert params["cuenta"] == "60436"
        assert params["company_id"] == "8"
        assert params["limit"] == "10"
        assert request.headers["X-Bridge-Token"] == "test-token"
        return httpx.Response(
            200,
            json=bridge_payload(
                action="payments",
                data={"account": "60436", "payments": []},
            ),
        )

    client = make_client(handler)

    assert run(client.get_payments("60436", company_id=8, limit=10)) == {
        "account": "60436",
        "payments": [],
    }


def test_customer_cache_records_hit_ratio_without_second_request():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json=bridge_payload(
                action="customer",
                data={"customers": [{"nombre": "Cliente Demo"}]},
            ),
        )

    client = make_client(handler)

    assert run(client.get_customer_by_phone("4421234567", company_id=1)) == {
        "customers": [{"nombre": "Cliente Demo"}],
    }
    assert run(client.get_customer_by_phone("4421234567", company_id=1)) == {
        "customers": [{"nombre": "Cliente Demo"}],
    }

    metrics = get_siga_bridge_metrics()
    assert calls["count"] == 1
    assert metrics["cache_hits"] == 1
    assert metrics["cache_misses"] == 1
    assert metrics["cache_hit_ratio"] == 0.5


def test_bypass_cache_forces_request_and_refreshes_cached_value():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json=bridge_payload(
                action="customer",
                data={"customers": [{"nombre": f"Cliente {calls['count']}"}]},
            ),
        )

    client = make_client(handler)

    assert run(client.get_customer_by_phone("4421234567")) == {
        "customers": [{"nombre": "Cliente 1"}],
    }
    assert run(client.get_customer_by_phone("4421234567", bypass_cache=True)) == {
        "customers": [{"nombre": "Cliente 2"}],
    }
    assert run(client.get_customer_by_phone("4421234567")) == {
        "customers": [{"nombre": "Cliente 2"}],
    }
    assert calls["count"] == 2


def test_cache_keeps_null_no_result_responses():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json=bridge_payload(action="customer", data=None),
        )

    client = make_client(handler)

    assert run(client.get_customer_by_phone("4420000000")) is None
    assert run(client.get_customer_by_phone("4420000000")) is None

    metrics = get_siga_bridge_metrics()
    assert calls["count"] == 1
    assert metrics["cache_hits"] == 1
    assert metrics["cache_misses"] == 1


def test_429_maps_to_rate_limit_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json=bridge_payload(
                action="customer",
                ok=False,
                data=None,
                error="rate_limited: too many requests",
            ),
        )

    client = make_client(handler)

    with pytest.raises(SigaBridgeRateLimitError):
        run(client.get_customer_by_phone("4421234567"))

    metrics = get_siga_bridge_metrics()
    assert metrics["errors"]["429"] == 1
    assert metrics["rate_limit_hits"] == 1
