import unicodedata
from .faq_data import FAQ_DATA

def _normalize(text: str) -> str:
    """Elimina acentos y pasa a minúsculas para mejorar el match."""
    text = text.lower()
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def find_faq_answer(text: str, venta=None) -> tuple[str | None, str | None]:
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
                    best_match, best_image = _build_faq_response(item, venta)

    # 2. Búsqueda Semántica con IA (Fallback si el keyword match es débil o nulo)
    if not best_match or max_words_matched < 1:
        from app.services.ai.ai_service import identify_faq_id
        
        faq_index = identify_faq_id(text)
        if faq_index is not None and 0 <= faq_index < len(FAQ_DATA):
            item = FAQ_DATA[faq_index]
            best_match, best_image = _build_faq_response(item, venta)

    if best_image:
        from app.config.settings import settings
        best_image = getattr(settings, best_image, None)

    return best_match, best_image

def _build_faq_response(item: dict, venta=None) -> tuple[str, str | None]:
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
            
            response = item["response_dinamica"].format(
                fecha_limite=calculos.get("fecha_limite", "la fecha indicada"),
                importe_quincenal=calculos.get("importe_quincenal", "0"),
                importe_mensual=calculos.get("importe_mensual", "0"),
                numero_cuenta=numero_cuenta or "",
                pago_minimo=calculos.get("pago_minimo", "215.00"),
                importe_semanal_3m=calculos_3m.get("importe_semanal_3m", "0")
            )
        except Exception:
            response = item["response"]
    else:
        response = item["response"]
        
    return response, image