from app.services.siga_bridge_sale import (
    bridge_sale_from_payload,
    bridge_verification_found,
)


def test_bridge_verification_payload_builds_sale_fallback():
    payload = {
        "found": True,
        "source_table": "bitacora_ventas",
        "sale": {
            "folio": "16809",
            "no_cuenta": "60436",
            "nombre_completo": "CLIENTE DEMO",
            "sku_bitacora_v": "PC-MAXICA",
            "fecha_venta": "2026-05-05",
            "pago": "699.00",
        },
    }

    venta = bridge_sale_from_payload(payload)

    assert bridge_verification_found(payload) is True
    assert venta.folio == "16809"
    assert venta.no_cuenta == "60436"
    assert venta.nombre_completo == "CLIENTE DEMO"
    assert str(venta.pago) == "699.00"
