from sqlalchemy.orm import Session
from app.db.models import BitacoraVentas, DomiciliosHorariosEntrega, Estado
from app.utils.address_formatter import capitalizar_texto

# ===============================
# OBTENER VENTA POR FOLIO
# ===============================
def obtener_venta_por_folio(db: Session, folio: str) -> BitacoraVentas | None:
    return db.query(BitacoraVentas).filter(BitacoraVentas.folio == folio).first()


# ===============================
# OBTENER DOMICILIO POR MOVIMIENTO
# ===============================
def obtener_domicilio_por_movimiento(
    db: Session, id_movimiento: str
) -> DomiciliosHorariosEntrega | None:

    return (
        db.query(DomiciliosHorariosEntrega)
        .filter(DomiciliosHorariosEntrega.id_movimiento == id_movimiento)
        .first()
    )


# ===============================
# CONSTRUIR NOMBRE
# ===============================
def construir_nombre(venta: BitacoraVentas) -> str:
    return capitalizar_texto(venta.nombre_completo) or "No disponible"


# ===============================
# CONSTRUIR PRODUCTO
# ===============================
def construir_producto(venta: BitacoraVentas) -> str:
    return capitalizar_texto(venta.sku_bitacora_v) or "No disponible"


# ===============================
# CONSTRUIR FECHA
# ===============================
def construir_fecha(venta: BitacoraVentas) -> str:
    if not venta.fecha_venta:
        return "No disponible"
    return venta.fecha_venta.strftime("%d/%m/%Y")


# ===============================
# CONSTRUIR NÚMERO DE CUENTA
# ===============================
def construir_no_cuenta(venta: BitacoraVentas) -> str:
    return venta.no_cuenta or "No disponible"

def construir_pago_inicial(venta: BitacoraVentas) -> int:
    return venta.importe or 0




