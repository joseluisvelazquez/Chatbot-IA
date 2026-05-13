from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.config.settings import settings
from app.services import collections_panel_service as service
from app.services.collections_panel_service import (
    build_collection_filters,
    list_collection_managers,
    list_collections,
    normalize_collection_record,
    normalize_payments,
)


def run(coro):
    return asyncio.run(coro)


class FakeCollectionsBridge:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get_collections(self, company_id, **kwargs):
        self.calls.append({"company_id": company_id, **kwargs})
        return self.payload

    async def get_collection_managers(self, company_id, **kwargs):
        self.calls.append({"action": "collection_managers", "company_id": company_id, **kwargs})
        return self.payload

    async def get_account(self, *_args, **_kwargs):
        raise AssertionError("list_collections must not fetch account per row")

    async def get_payments(self, *_args, **_kwargs):
        raise AssertionError("list_collections must not fetch payments per row")


def user(role="admin"):
    return SimpleNamespace(role=role, empresa_id=8, username=f"{role}_user")


def enable_bridge(monkeypatch, fake_bridge):
    monkeypatch.setattr(settings, "SIGA_BRIDGE_ENABLED", True)
    monkeypatch.setattr(service, "get_siga_bridge_client", lambda: fake_bridge)


def test_collection_normalizer_uses_flat_account_values():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "folio": "16809",
            "phone": "4421234567",
            "customer_name": "CLIENTE DEMO",
            "account_status": "SANO",
            "balance": "1200.50",
            "overdue_amount": "0",
            "days_overdue": "0",
            "total_paid": "699",
            "last_payment": "2026-05-05",
            "sale_date": "2026-04-30",
        }
    )

    assert item["no_cuenta"] == "60436"
    assert item["classification"] == "sano"
    assert item["customer_name"] == "CLIENTE DEMO"
    assert item["balance"] == "1200.50"
    assert "[object Object]" not in str(item)


def test_collection_normalizer_marks_paid_by_balance_first():
    item = normalize_collection_record(
        {
            "account": {
                "account": "60436",
                "status": "JURIDICO",
                "amounts": {"stored_balance": 0},
            },
            "customer": {"name": "CLIENTE DEMO", "phones": ["4421234567"]},
            "payment_summary": {"paid_total": "1000"},
        }
    )

    assert item["classification"] == "pagado"
    assert item["is_paid"] is True
    assert item["phone"] == "4421234567"


def test_collection_normalizer_classifies_sano_critico_otro():
    sano = normalize_collection_record(
        {
            "no_cuenta": "1",
            "account_status": "ACTIVA",
            "balance": "100",
            "days_overdue": 0,
            "overdue_amount": 0,
        }
    )
    critico = normalize_collection_record(
        {
            "no_cuenta": "2",
            "account_status": "ACTIVA",
            "balance": "100",
            "days_overdue": 45,
        }
    )
    otro = normalize_collection_record({"no_cuenta": "3", "balance": "100"})

    assert sano["classification"] == "sano"
    assert critico["classification"] == "critico"
    assert otro["classification"] == "otro"


def test_collection_payments_normalize_bridge_shape():
    payments = normalize_payments(
        {
            "payments": [
                {
                    "id": 1,
                    "account": "60436",
                    "concept": "ABONO",
                    "amount": 215,
                    "paid_at": "2026-05-05 10:00:00",
                    "balance_after_payment": 1000,
                }
            ]
        }
    )

    assert payments == [
        {
            "id": "1",
            "account": "60436",
            "concept": "ABONO",
            "product": None,
            "payment_method": None,
            "amount": "215.00",
            "paid_at": "2026-05-05 10:00:00",
            "balance_after_payment": "1000.00",
            "user": None,
        }
    ]


def test_collection_filters_default_active_and_limit_max():
    filters = build_collection_filters(
        account="60436",
        folio="16809",
        phone="4421234567",
        status="critico",
        overdue_only=True,
        limit=500,
    )

    assert filters.account == "60436"
    assert filters.folio == "16809"
    assert filters.phone == "4421234567"
    assert filters.status == "critico"
    assert filters.classification == "critico"
    assert filters.overdue_only is True
    assert filters.include_paid is False
    assert filters.active_only is True
    assert filters.limit == 50


def test_status_pagado_enables_include_paid():
    filters = build_collection_filters(status="pagado")

    assert filters.status == "pagado"
    assert filters.include_paid is True
    assert filters.active_only is False


def test_collections_do_not_return_paid_by_default(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {"no_cuenta": "PAID", "balance": 0, "account_status": "LIQUIDADO"},
                {"no_cuenta": "ACTIVE", "balance": 100, "account_status": "ACTIVA"},
            ],
            "total": 2,
        }
    )
    enable_bridge(monkeypatch, fake_bridge)

    response = run(list_collections(None, user("admin"), build_collection_filters()))

    assert [item["no_cuenta"] for item in response["items"]] == ["ACTIVE"]
    assert fake_bridge.calls[0]["limit"] == 25
    assert fake_bridge.calls[0]["include_paid"] is False
    assert fake_bridge.calls[0]["active_only"] is True


def test_collections_return_paid_only_when_requested(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {"no_cuenta": "PAID", "balance": 0, "account_status": "LIQUIDADO"},
                {"no_cuenta": "ACTIVE", "balance": 100, "account_status": "ACTIVA"},
            ],
            "total": 2,
        }
    )
    enable_bridge(monkeypatch, fake_bridge)

    response = run(
        list_collections(
            None,
            user("admin"),
            build_collection_filters(status="pagado"),
        )
    )

    assert [item["no_cuenta"] for item in response["items"]] == ["PAID"]
    assert fake_bridge.calls[0]["include_paid"] is True
    assert fake_bridge.calls[0]["active_only"] is False


def test_collections_response_uses_offset_cursor_without_n_plus_one(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {"no_cuenta": "1", "balance": 100, "account_status": "ACTIVA"},
                {"no_cuenta": "2", "balance": 100, "account_status": "ACTIVA"},
            ],
            "total": 5,
        }
    )
    enable_bridge(monkeypatch, fake_bridge)

    response = run(
        list_collections(
            None,
            user("admin"),
            build_collection_filters(limit=2, offset=2),
        )
    )

    assert response["has_more"] is True
    assert response["next_cursor"] == "4"
    assert len(fake_bridge.calls) == 1


def test_folio_search_is_delegated_to_bridge_with_limit(monkeypatch):
    fake_bridge = FakeCollectionsBridge({"items": [], "has_more": False})
    enable_bridge(monkeypatch, fake_bridge)

    run(
        list_collections(
            None,
            user("admin"),
            build_collection_filters(folio="16809", limit=500),
        )
    )

    assert fake_bridge.calls[0]["folio"] == "16809"
    assert fake_bridge.calls[0]["limit"] == 50
    assert len(fake_bridge.calls) == 1


def test_account_search_is_delegated_to_bridge_with_page_limit(monkeypatch):
    fake_bridge = FakeCollectionsBridge({"items": [], "has_more": False})
    enable_bridge(monkeypatch, fake_bridge)

    run(
        list_collections(
            None,
            user("admin"),
            build_collection_filters(account="60436"),
        )
    )

    assert fake_bridge.calls[0]["cuenta"] == "60436"
    assert fake_bridge.calls[0]["limit"] == 25
    assert len(fake_bridge.calls) == 1


def test_phone_search_is_delegated_to_bridge(monkeypatch):
    fake_bridge = FakeCollectionsBridge({"items": [], "has_more": False})
    enable_bridge(monkeypatch, fake_bridge)

    run(
        list_collections(
            None,
            user("admin"),
            build_collection_filters(phone="4421234567"),
        )
    )

    assert fake_bridge.calls[0]["phone"] == "4421234567"
    assert fake_bridge.calls[0]["limit"] == 25
    assert len(fake_bridge.calls) == 1


def test_cobranza_role_forces_own_gestor(monkeypatch):
    fake_bridge = FakeCollectionsBridge({"items": [], "total": 0})
    enable_bridge(monkeypatch, fake_bridge)
    monkeypatch.setattr(service, "get_nombre_resumido", lambda _db, _username: "GESTOR PROPIO")

    response = run(
        list_collections(
            None,
            user("cobranza"),
            build_collection_filters(gestor="GESTOR AJENO"),
        )
    )

    assert fake_bridge.calls[0]["collector"] == "GESTOR PROPIO"
    assert "gestor_filter_ignored_for_role" in response["meta"]["warnings"]


def test_jefe_operativo_can_filter_by_gestor(monkeypatch):
    fake_bridge = FakeCollectionsBridge({"items": [], "total": 0})
    enable_bridge(monkeypatch, fake_bridge)

    run(
        list_collections(
            None,
            user("jefe_operativo"),
            build_collection_filters(gestor="GESTOR UNO"),
        )
    )

    assert fake_bridge.calls[0]["collector"] == "GESTOR UNO"


def test_fallback_without_gestor_scope_limits_cobranza(monkeypatch):
    monkeypatch.setattr(settings, "SIGA_BRIDGE_ENABLED", False)
    monkeypatch.setattr(service, "get_nombre_resumido", lambda _db, _username: None)

    response = run(list_collections(None, user("cobranza"), build_collection_filters()))

    assert response["items"] == []
    assert response["bridge_status"] == "no_scope"
    assert "gestor_scope_missing" in response["meta"]["warnings"]


def test_collection_managers_catalog_comes_from_bridge(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {
                    "value": "GESTOR UNO",
                    "label": "GESTOR UNO",
                    "accounts_count": 10,
                    "source_field": "cuentas.agente_verificador",
                }
            ]
        }
    )
    enable_bridge(monkeypatch, fake_bridge)

    response = run(list_collection_managers(None, user("admin")))

    assert response["items"] == [
        {
            "value": "GESTOR UNO",
            "label": "GESTOR UNO",
            "accounts_count": 10,
            "source_field": "cuentas.agente_verificador",
        }
    ]
    assert fake_bridge.calls[0]["action"] == "collection_managers"
    assert fake_bridge.calls[0]["limit"] == 100


def test_cobranza_role_cannot_load_manager_catalog(monkeypatch):
    fake_bridge = FakeCollectionsBridge({"items": [{"value": "GESTOR UNO"}]})
    enable_bridge(monkeypatch, fake_bridge)

    response = run(list_collection_managers(None, user("cobranza")))

    assert response["items"] == []
    assert response["meta"]["warnings"] == ["gestor_catalog_not_allowed"]
    assert fake_bridge.calls == []
