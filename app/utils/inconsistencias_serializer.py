from app.db.models import Inconsistencias
def serialize_inconsistencias(inconsistencias: list[Inconsistencias]) -> list[dict]:
    result: list[dict] = []

    for inc in inconsistencias:
        extra = inc.extra_json or {}
        estatus = inc.estatus or "ABIERTA"

        for field_name, field_data in extra.items():
            if not isinstance(field_data, dict):
                continue

            if field_name == "evento":
                continue

            mensaje_cliente = field_data.get("mensaje_cliente")
            confirmado = field_data.get("confirmado")

            if confirmado is False or mensaje_cliente:
                result.append({
                    "campo": field_name,
                    "mensaje": mensaje_cliente or "Sin detalle",
                    "estado": estatus,
                })
                continue

            faltantes = field_data.get("faltantes")
            if isinstance(faltantes, list) and faltantes:
                result.append({
                    "campo": field_name,
                    "mensaje": f"Faltantes: {', '.join(str(x) for x in faltantes)}",
                    "estado": estatus,
                })

    return result