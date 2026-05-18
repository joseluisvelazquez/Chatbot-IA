import unicodedata
from .faq_data import FAQ_DATA
from app.content.message_builder import format_account_reference
from app.services.siga_bridge_sale import (
    get_cached_bridge_verification_payload,
    normalize_siga_verification_snapshot,
)

def _normalize(text: str) -> str:
    """Elimina acentos y pasa a minúsculas para mejorar el match."""
    text = text.lower()
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def _clean_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"-", "null", "none", "undefined", "no disponible"}:
        return None
    return text


def _comprobante_access_values(venta=None, session=None, bridge_verification=None) -> tuple[str | None, str | None]:
    numero_cuenta = None
    codigo_cliente = None

    if venta:
        from app.siga.siga_repository import construir_no_cuenta

        numero_cuenta = construir_no_cuenta(venta)
        codigo_cliente = getattr(venta, "codigo_cliente", None)

    snapshot = getattr(venta, "_bridge_payload", None) if venta else None
    if not isinstance(snapshot, dict) and isinstance(bridge_verification, dict):
        snapshot = bridge_verification
    if not isinstance(snapshot, dict) and session is not None and getattr(session, "folio", None):
        payload = get_cached_bridge_verification_payload(session, session.folio)
        snapshot = normalize_siga_verification_snapshot(payload) if isinstance(payload, dict) else None

    if isinstance(snapshot, dict):
        numero_cuenta = _clean_text(numero_cuenta) or snapshot.get("no_cuenta")
        codigo_cliente = _clean_text(codigo_cliente) or snapshot.get("codigo_cliente")

    return format_account_reference(numero_cuenta), _clean_text(codigo_cliente)


def find_faq_answer(text: str, venta=None, session=None, bridge_verification=None) -> tuple[str | None, str | None]:
    if not text:
        return None, None

    norm_text = _normalize(text)
    
    best_match = None
    best_image = None
    max_words_matched = 0

    # 1. Búsqueda por palabras clave (Match exacto/rápido)
    for i, item in enumerate(FAQ_DATA):
        for keyword in item["keywords"]:
            norm_keyword = _normalize(keyword)
            words = norm_keyword.split()
            if all(word in norm_text for word in words):
                match_score = len(words)
                if match_score > max_words_matched:
                    max_words_matched = match_score
                    best_match, best_image = _build_faq_response(item, venta, session, bridge_verification)

    # 2. Búsqueda Semántica con IA (Fallback si el keyword match es débil o nulo)
    generic_doubt_texts = {
        "duda",
        "tengo duda",
        "tengo una duda",
        "tengo dudas",
        "una duda",
        "pregunta",
        "una pregunta",
        "tengo una pregunta",
    }
    if norm_text in generic_doubt_texts:
        return best_match, best_image

    if not best_match or max_words_matched < 1:
        from app.services.ai.ai_service import identify_faq_id
        
        faq_index = identify_faq_id(text)
        if faq_index is not None and 0 <= faq_index < len(FAQ_DATA):
            item = FAQ_DATA[faq_index]
            best_match, best_image = _build_faq_response(item, venta, session, bridge_verification)

    if best_image:
        from app.config.settings import settings
        best_image = getattr(settings, best_image, None)

    return best_match, best_image

def _build_faq_response(item: dict, venta=None, session=None, bridge_verification=None) -> tuple[str, str | None]:
    """Helper para construir la respuesta (dinámica o estática) de un item de FAQ."""
    response = None
    image = item.get("image_env")
    
    if venta and "response_dinamica" in item:
        from app.pricing.payment_plans import calcular_info_pagos, calcular_info_plan_3_meses
        from app.siga.siga_repository import construir_no_cuenta
        
        try:
            calculos = calcular_info_pagos(venta) or {}
            calculos_3m = calcular_info_plan_3_meses(venta) or {}
            numero_cuenta = construir_no_cuenta(venta)
            numero_cuenta_referencia, codigo_cliente = _comprobante_access_values(
                venta,
                session,
                bridge_verification,
            )
            
            response = item["response_dinamica"].format(
                fecha_limite=calculos.get("fecha_limite", "la fecha indicada"),
                importe_quincenal=calculos.get("importe_quincenal") or "no disponible",
                importe_mensual=calculos.get("importe_mensual") or "no disponible",
                numero_cuenta=numero_cuenta or "",
                numero_cuenta_referencia=numero_cuenta_referencia or "el numero de cuenta mostrado",
                codigo_cliente=codigo_cliente or "el codigo de cliente mostrado",
                pago_minimo=calculos.get("pago_minimo") or "no disponible",
                importe_semanal_3m=calculos_3m.get("importe_semanal_3m") or "no disponible"
            )
        except Exception:
            response = item["response"]
    else:
        response = item["response"]
        
    return response, image
