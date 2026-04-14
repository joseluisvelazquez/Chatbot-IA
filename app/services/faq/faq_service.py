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

    for item in FAQ_DATA:
        for keyword in item["keywords"]:
            norm_keyword = _normalize(keyword)
            words = norm_keyword.split()
            # Verifica si TODAS las palabras de la keyword están en el texto del usuario
            if all(word in norm_text for word in words):
                # Priorizar el keyword que contenga más palabras (match más específico)
                match_score = len(words)
                if match_score > max_words_matched:
                    max_words_matched = match_score
                    best_image = item.get("image_env")
                    
                    if venta and "response_dinamica" in item:
                        from app.pricing.payment_plans import calcular_info_pagos, calcular_info_plan_3_meses
                        from app.siga.siga_repository import construir_no_cuenta
                        
                        try:
                            calculos = calcular_info_pagos(venta) or {}
                            calculos_3m = calcular_info_plan_3_meses(venta) or {}
                            numero_cuenta = construir_no_cuenta(venta)
                            
                            best_match = item["response_dinamica"].format(
                                fecha_limite=calculos.get("fecha_limite", "la fecha indicada"),
                                importe_quincenal=calculos.get("importe_quincenal", "0"),
                                importe_mensual=calculos.get("importe_mensual", "0"),
                                numero_cuenta=numero_cuenta or "",
                                pago_minimo=calculos.get("pago_minimo", "215.00"),
                                importe_semanal_3m=calculos_3m.get("importe_semanal_3m", "0")
                            )
                        except Exception as e:
                            # Fallback si falla el format
                            best_match = item["response"]
                    else:
                        best_match = item["response"]

    if best_image:
        from app.config.settings import settings
        best_image = getattr(settings, best_image, None)

    return best_match, best_image