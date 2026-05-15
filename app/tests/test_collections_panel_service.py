from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.config.settings import settings
from app.services import collections_panel_service as service
from app.services.collections_panel_service import (
    attach_conversation_links,
    build_collection_filters,
    get_collection_detail,
    get_collection_payments,
    list_collection_managers,
    list_collections,
    normalize_collection_record,
    normalize_collection_managers,
    normalize_payments,
)


def run(coro):
    return asyncio.run(coro)


class FakeCollectionsBridge:
    def __init__(self, payload, payments_payloads=None):
        self.payload = payload
        self.payments_payloads = payments_payloads or {}
        self.calls = []

    async def get_collections(self, company_id, **kwargs):
        self.calls.append({"company_id": company_id, **kwargs})
        return self.payload

    async def get_collection_managers(self, company_id, **kwargs):
        self.calls.append({"action": "collection_managers", "company_id": company_id, **kwargs})
        return self.payload

    async def get_account(self, *_args, **_kwargs):
        raise AssertionError("list_collections must not fetch account per row")

    async def get_payments(self, cuenta, *_args, **_kwargs):
        self.calls.append({"action": "payments", "cuenta": cuenta, **_kwargs})
        return self.payments_payloads.get(str(cuenta), {"summary": {"paid_total": None}, "payments": []})


class FakeDetailBridge:
    def __init__(
        self,
        account_payload=None,
        payments_payload=None,
        collections_payload=None,
        account_error=None,
        payments_error=None,
        collections_error=None,
    ):
        self.account_payload = account_payload or {}
        self.payments_payload = payments_payload or {"payments": []}
        self.collections_payload = collections_payload or {"items": []}
        self.account_error = account_error
        self.payments_error = payments_error
        self.collections_error = collections_error
        self.calls = []

    async def get_account(self, cuenta, company_id, **kwargs):
        self.calls.append({"action": "account", "cuenta": cuenta, "company_id": company_id, **kwargs})
        if self.account_error:
            raise self.account_error
        return self.account_payload

    async def get_payments(self, cuenta, company_id, **kwargs):
        self.calls.append({"action": "payments", "cuenta": cuenta, "company_id": company_id, **kwargs})
        if self.payments_error:
            raise self.payments_error
        return self.payments_payload

    async def get_collections(self, company_id, **kwargs):
        self.calls.append({"action": "collections", "company_id": company_id, **kwargs})
        if self.collections_error:
            raise self.collections_error
        return self.collections_payload


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


def test_collection_normalizer_uses_bridge_payment_summary_total_pagado():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "payment_summary": {"total_pagado": "430.50"},
        },
        source="siga_bridge",
    )

    assert item["total_paid"] == "430.50"
    assert item["total_pagado"] == "430.50"
    assert item["total_paid_source"] == "payment_summary.total_pagado"


def test_collection_normalizer_builds_address_from_bridge_components():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "customer": {
                "name": "CLIENTE DEMO",
                "address": {
                    "street": "CALLE UNO",
                    "external_number": "12",
                    "internal_number": "",
                    "neighborhood": "CENTRO",
                    "city": "CADEREYTA",
                    "state": "QRO",
                    "postal_code": "76500",
                    "full": None,
                },
            },
        }
    )

    assert item["customer"]["address_text"] == "CALLE UNO 12, CENTRO, CADEREYTA, QRO, CP 76500"


def test_collection_normalizer_sums_valid_bridge_payments():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "payments": [
                {"amount": "100.00", "status": "APLICADO"},
                {"importe": "50.25", "concepto": "ABONO"},
            ],
        },
        source="siga_bridge",
    )

    assert item["total_paid"] == "150.25"
    assert item["payments_count"] == 2


def test_collection_detail_prefers_clicked_client_payment_rows_for_total():
    payments = normalize_payments(
        {
            "pagos": [
                {"amount": "100.00", "status": "APLICADO"},
                {"importe": "25.00", "concepto": "ABONO"},
            ]
        }
    )
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "payment_summary": {"total_pagado": "999.00"},
            "pagos": [
                {"amount": "100.00", "status": "APLICADO"},
                {"importe": "25.00", "concepto": "ABONO"},
            ],
        },
        payments=payments,
        source="siga_bridge",
    )

    assert item["total_paid"] == "125.00"
    assert item["financial_summary"]["total_paid"] == "125.00"
    assert item["total_paid_source"] == "payments.sum"


def test_collection_detail_includes_initial_payment_in_history_and_total():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "pago_inicial": "300.00",
            "sale_date": "2026-05-01",
            "payments": [
                {"amount": "100.00", "status": "APLICADO", "paid_at": "2026-05-08"},
            ],
        },
        source="siga_bridge",
        payments=normalize_payments(
            {
                "payments": [
                    {"amount": "100.00", "status": "APLICADO", "paid_at": "2026-05-08"},
                ],
            }
        ),
    )

    assert item["total_paid"] == "400.00"
    assert item["payments_count"] == 2
    assert [payment["concept"] for payment in item["payments"]] == [None, "Pago inicial"]


def test_local_collection_total_uses_payments_sum_plus_initial_payment():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "payments_sum": "125.00",
            "pago_inicial": "300.00",
            "sale_date": "2026-05-01",
        },
        source="local_fallback",
    )

    assert item["total_paid"] == "425.00"
    assert item["total_paid_source"] == "local.payments_sum+initial_payment"


def test_bridge_list_does_not_use_initial_only_without_payment_payload():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "pago_inicial": "300.00",
            "sale_date": "2026-05-01",
        },
        source="siga_bridge",
    )

    assert item["total_paid"] is None
    assert item["payments"][0]["concept"] == "Pago inicial"


def test_collection_detail_does_not_replace_summary_when_payment_payload_unknown():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "payment_summary": {"total_pagado": "999.00"},
            "unknown_payments_wrapper": [],
        },
        payments=[],
        source="siga_bridge",
    )

    assert item["total_paid"] == "999.00"
    assert item["total_paid_source"] == "payment_summary.total_pagado"


def test_collection_normalizer_excludes_cancelled_and_refund_payments():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "payments": [
                {"amount": "100.00", "status": "APLICADO"},
                {"amount": "200.00", "status": "CANCELADO"},
                {"amount": "50.00", "concepto": "DEVOLUCION"},
                {"amount": "-20.00", "concepto": "ABONO"},
            ],
        },
        source="siga_bridge",
    )

    assert item["total_paid"] == "100.00"


def test_collection_normalizer_empty_bridge_payments_render_zero():
    item = normalize_collection_record(
        {
            "no_cuenta": "60436",
            "balance": "1200.00",
            "account_status": "ACTIVA",
            "payments": [],
        },
        source="siga_bridge",
    )

    assert item["total_paid"] == "0.00"


def test_collection_list_enriches_missing_bridge_total_from_local_summary(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {
                    "no_cuenta": "60436",
                    "balance": "1200.00",
                    "account_status": "ACTIVA",
                }
            ],
            "total": 1,
        }
    )
    enable_bridge(monkeypatch, fake_bridge)
    monkeypatch.setattr(service, "attach_conversation_links", lambda _db, _user, items: items)
    monkeypatch.setattr(
        service,
        "_local_payment_summaries_for_accounts",
        lambda _db, _user, accounts: {
            "60436": {
                "total_paid": "425.00",
                "total_paid_source": "local.payments_sum+initial_payment",
                "payments_count": 3,
                "initial_payment": "300.00",
            }
        },
    )

    response = run(list_collections(object(), user("admin"), build_collection_filters(limit=25)))

    assert response["items"][0]["total_paid"] == "425.00"
    assert response["items"][0]["financial_summary"]["total_paid"] == "425.00"
    assert response["items"][0]["financial_summary"]["initial_payment"] == "300.00"
    assert response["items"][0]["payments_count"] == 3


def test_collection_list_enriches_missing_bridge_total_from_bridge_payments(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {
                    "no_cuenta": "1260413",
                    "balance": "1200.00",
                    "account_status": "ACTIVA",
                    "total_paid": None,
                }
            ],
            "total": 1,
        },
        payments_payloads={
            "1260413": {
                "summary": {"initial_payment": "367.00", "paid_total": "1507.00"},
                "payments": [
                    {"amount": "380.00", "status": "APLICADO"},
                ],
            }
        },
    )
    enable_bridge(monkeypatch, fake_bridge)
    monkeypatch.setattr(service, "attach_conversation_links", lambda _db, _user, items: items)
    monkeypatch.setattr(service, "_local_payment_summaries_for_accounts", lambda *_args, **_kwargs: {})

    response = run(list_collections(object(), user("admin"), build_collection_filters(limit=25)))

    assert response["items"][0]["total_paid"] == "1507.00"
    assert response["items"][0]["financial_summary"]["total_paid"] == "1507.00"
    assert response["items"][0]["payments_count"] == 2
    assert response["items"][0]["financial_summary"]["payments_count"] == 2
    assert any(call.get("action") == "payments" for call in fake_bridge.calls)


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
            "status": None,
            "cancelled": False,
        }
    ]


def test_collection_payments_accept_nested_importe_and_drop_cancelled():
    payments = normalize_payments(
        {
            "data": {
                "pagos": [
                    {"id": "ok", "importe": "125.50", "fecha": "2026-05-06", "estatus": "APLICADO"},
                    {"id": "bad", "importe": "999.00", "estatus": "CANCELADO"},
                    {"id": "refund", "monto": "50.00", "concepto": "DEVOLUCION"},
                ]
            }
        }
    )

    assert [payment["id"] for payment in payments] == ["ok"]
    assert payments[0]["amount"] == "125.50"
    assert payments[0]["paid_at"] == "2026-05-06"


def test_collection_payments_accept_bridge_history_rows_shape():
    payments = normalize_payments(
        {
            "data": {
                "historial_pagos": {
                    "rows": [
                        {
                            "id": "row-1",
                            "cuenta": "60436",
                            "monto_pago": "225.75",
                            "fecha_movimiento": "2026-05-09",
                            "tipo_movimiento": "ABONO",
                        }
                    ]
                }
            }
        }
    )

    assert payments[0]["account"] == "60436"
    assert payments[0]["amount"] == "225.75"
    assert payments[0]["paid_at"] == "2026-05-09"
    assert payments[0]["concept"] == "ABONO"


def test_collection_detail_loads_payments_when_bridge_account_lacks_account_number(monkeypatch):
    bridge = FakeDetailBridge(
        account_payload={"account_status": "ACTIVA", "balance": "1200.00"},
        payments_payload={
            "payments": [
                {"amount": "100.00", "status": "APLICADO", "paid_at": "2026-05-08"},
            ]
        },
    )
    enable_bridge(monkeypatch, bridge)
    monkeypatch.setattr(service, "attach_conversation_links", lambda _db, _user, items: items)
    monkeypatch.setattr(
        service,
        "_local_collection_detail",
        lambda *_args, **_kwargs: normalize_collection_record(
            {
                "no_cuenta": "60436",
                "balance": "1200.00",
                "account_status": "ACTIVA",
                "pago_inicial": "300.00",
                "sale_date": "2026-05-01",
            },
            source="local_fallback",
        ),
    )

    item = run(get_collection_detail(object(), user("admin"), "60436"))

    assert item["no_cuenta"] == "60436"
    assert item["total_paid"] == "400.00"
    assert [payment["amount"] for payment in item["payments"]] == ["100.00", "300.00"]
    assert [call["action"] for call in bridge.calls] == ["collections", "account", "payments"]


def test_collection_detail_loads_from_bridge_even_without_local_account(monkeypatch):
    bridge = FakeDetailBridge(
        account_payload={
            "account": {
                "account": "1260413",
                "amounts": {"balance": "1200.00"},
                "product": "Equipo test",
                "status": "ACTIVA",
            }
        },
        payments_payload={
            "account": "1260413",
            "summary": {"initial_payment": "367.00", "paid_total": "1507.00"},
            "payments": [
                {"amount": "380.00", "status": "APLICADO", "paid_at": "2026-05-08"},
            ],
        },
    )
    enable_bridge(monkeypatch, bridge)
    monkeypatch.setattr(service, "attach_conversation_links", lambda _db, _user, items: items)
    monkeypatch.setattr(service, "_local_collection_detail", lambda *_args, **_kwargs: None)

    item = run(get_collection_detail(object(), user("admin"), "1260413"))

    assert item["no_cuenta"] == "1260413"
    assert item["balance"] == "1200.00"
    assert item["product"] == "Equipo test"
    assert item["total_paid"] == "747.00"
    assert [payment["amount"] for payment in item["payments"]] == ["380.00", "367.00"]


def test_collection_detail_preserves_collection_context_for_drawer(monkeypatch):
    bridge = FakeDetailBridge(
        collections_payload={
            "items": [
                {
                    "no_cuenta": "5260510",
                    "folio": "16774",
                    "days_overdue": "-15.21",
                    "customer_name": "CLIENTE DEMO",
                    "account_status": "ACTIVA",
                }
            ]
        },
        account_payload={
            "account": {
                "account": "5260510",
                "amounts": {"balance": "13499.00"},
                "status": "ACTIVA",
            },
            "customer": {
                "name": "CLIENTE DEMO",
                "address": {
                    "street": "CALLE UNO",
                    "external_number": "12",
                    "neighborhood": "CENTRO",
                    "city": "CADEREYTA",
                    "state": "QRO",
                    "postal_code": "76500",
                    "full": None,
                },
            },
        },
        payments_payload={
            "account": "5260510",
            "summary": {"initial_payment": "3500.00", "paid_total": "3500.00"},
            "payments": [],
        },
    )
    enable_bridge(monkeypatch, bridge)
    monkeypatch.setattr(service, "attach_conversation_links", lambda _db, _user, items: items)
    monkeypatch.setattr(service, "_local_collection_detail", lambda *_args, **_kwargs: None)

    item = run(get_collection_detail(object(), user("admin"), "5260510", include_paid=True))

    assert item["folio"] == "16774"
    assert item["days_overdue"] == -15.21
    assert item["customer"]["address_text"] == "CALLE UNO 12, CENTRO, CADEREYTA, QRO, CP 76500"
    assert item["total_paid"] == "3500.00"


def test_collection_detail_falls_back_to_collections_when_account_fails(monkeypatch):
    bridge = FakeDetailBridge(
        account_error=service.SigaBridgeError("account unavailable", action="account", status_code=404),
        collections_payload={
            "items": [
                {
                    "no_cuenta": "2260430",
                    "folio": "16874",
                    "days_overdue": "1",
                    "customer_name": "CLIENTE DEMO",
                    "account_status": "ACTIVA",
                    "balance": "16769.00",
                    "total_paid": None,
                }
            ]
        },
        payments_payload={
            "account": "2260430",
            "summary": {"initial_payment": "230.00", "paid_total": "230.00"},
            "payments": [],
        },
    )
    enable_bridge(monkeypatch, bridge)
    monkeypatch.setattr(service, "attach_conversation_links", lambda _db, _user, items: items)
    monkeypatch.setattr(service, "_local_collection_detail", lambda *_args, **_kwargs: None)

    item = run(get_collection_detail(object(), user("admin"), "2260430", include_paid=True))

    assert item["no_cuenta"] == "2260430"
    assert item["folio"] == "16874"
    assert item["days_overdue"] == 1
    assert item["total_paid"] == "230.00"
    assert [payment["amount"] for payment in item["payments"]] == ["230.00"]


def test_collection_payments_loads_from_bridge_even_without_local_account(monkeypatch):
    bridge = FakeDetailBridge(
        payments_payload={
            "summary": {"initial_payment": "367.00"},
            "payments": [
                {"amount": "380.00", "status": "APLICADO", "paid_at": "2026-05-08"},
            ],
        },
    )
    enable_bridge(monkeypatch, bridge)
    monkeypatch.setattr(service, "_local_collection_detail", lambda *_args, **_kwargs: None)

    payments = run(get_collection_payments(object(), user("admin"), "1260413"))

    assert [payment["amount"] for payment in payments] == ["380.00", "367.00"]


def test_collection_payments_endpoint_returns_paid_account_payments(monkeypatch):
    monkeypatch.setattr(settings, "SIGA_BRIDGE_ENABLED", False)
    monkeypatch.setattr(
        service,
        "_local_collection_detail",
        lambda *_args, **_kwargs: normalize_collection_record(
            {
                "no_cuenta": "60436",
                "balance": "0.00",
                "account_status": "PAGADO",
                "pago_inicial": "300.00",
                "sale_date": "2026-05-01",
            },
            source="local_fallback",
        ),
    )
    monkeypatch.setattr(
        service,
        "_local_payments",
        lambda *_args, **_kwargs: [
            {
                "id": "p1",
                "account": "60436",
                "concept": "ABONO",
                "amount": "100.00",
                "paid_at": "2026-05-08",
                "balance_after_payment": "0.00",
                "status": "APLICADO",
                "cancelled": False,
            }
        ],
    )

    payments = run(get_collection_payments(object(), user("admin"), "60436"))

    assert [payment["amount"] for payment in payments] == ["100.00", "300.00"]


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


def test_collections_response_uses_offset_cursor_and_payment_enrichment(monkeypatch):
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
    assert [call.get("action") for call in fake_bridge.calls[1:]] == ["payments", "payments"]


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
            "id": None,
            "value": "GESTOR UNO",
            "label": "GESTOR UNO",
            "nombre": "GESTOR UNO",
            "usuario": None,
            "activo": True,
            "empresa_id": None,
            "accounts_count": 10,
            "source": "siga_bridge",
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


def test_collection_managers_keep_only_active_collection_roles_and_dedupe():
    managers = normalize_collection_managers(
        {
            "items": [
                {
                    "id": 1,
                    "nombre_resumido": "GESTOR UNO",
                    "nombre_usuario": "gestor1",
                    "puesto": "GESTOR DE COBRANZA",
                    "estatus": 1,
                    "id_emp_col": 8,
                    "accounts_count": 3,
                },
                {
                    "value": "GESTOR UNO",
                    "puesto": "GESTOR DE COBRANZA",
                    "activo": True,
                    "empresa_id": 8,
                    "accounts_count": 5,
                },
                {
                    "value": "GESTOR INACTIVO",
                    "puesto": "GESTOR DE COBRANZA",
                    "estatus": 0,
                },
                {
                    "value": "ASESOR VENTAS",
                    "puesto": "ASESOR COMERCIAL",
                    "estatus": 1,
                },
            ]
        }
    )

    assert [manager["value"] for manager in managers] == ["GESTOR UNO"]
    assert managers[0]["accounts_count"] == 5
    assert managers[0]["activo"] is True
    assert managers[0]["empresa_id"] == 8


def test_collection_managers_bridge_catalog_is_filtered_by_local_active_keys(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {"value": "GESTOR ACTIVO", "label": "GESTOR ACTIVO", "accounts_count": 10},
                {"value": "GESTOR BAJA", "label": "GESTOR BAJA", "accounts_count": 20},
            ]
        }
    )
    enable_bridge(monkeypatch, fake_bridge)
    monkeypatch.setattr(
        service,
        "_local_collection_managers",
        lambda *_args, **_kwargs: [
            {
                "value": "GESTOR ACTIVO",
                "label": "GESTOR ACTIVO",
                "activo": True,
                "empresa_id": 8,
                "accounts_count": 1,
            }
        ],
    )

    response = run(list_collection_managers(object(), user("admin")))

    assert [manager["value"] for manager in response["items"]] == ["GESTOR ACTIVO"]


def test_collections_endpoint_response_includes_total_paid_from_bridge(monkeypatch):
    fake_bridge = FakeCollectionsBridge(
        {
            "items": [
                {
                    "no_cuenta": "60436",
                    "balance": "1200.00",
                    "account_status": "ACTIVA",
                    "payment_summary": {"total_pagado": "321.50"},
                }
            ],
            "total": 1,
        }
    )
    enable_bridge(monkeypatch, fake_bridge)

    response = run(list_collections(None, user("admin"), build_collection_filters()))

    assert response["items"][0]["total_paid"] == "321.50"
    assert response["items"][0]["financial_summary"]["total_pagado"] == "321.50"


def test_collection_conversation_link_uses_latest_phone_match(monkeypatch):
    candidates = [
        {
            "id": 24,
            "folio": None,
            "phone_match": "4421234567",
            "accounts": set(),
            "last_message_at": "2026-05-01T10:00:00",
        },
        {
            "id": 25,
            "folio": None,
            "phone_match": "4421234567",
            "accounts": set(),
            "last_message_at": "2026-05-02T10:00:00",
        },
    ]
    monkeypatch.setattr(service, "_conversation_candidates", lambda _db, _user, _items: candidates)
    items = [{"no_cuenta": "60436", "phone": "5214421234567"}]

    attach_conversation_links(object(), user("admin"), items)

    assert items[0]["has_conversation"] is True
    assert items[0]["conversation_session_id"] == "25"
    assert items[0]["conversation_url"] == "/panel/?view=conversations&session_id=25"
