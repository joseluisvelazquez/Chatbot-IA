from sqlalchemy.orm import Session
from app.db.models import BitacoraVentas, DomiciliosHorariosEntrega


# ===============================
# OBTENER VENTA POR FOLIO
# ===============================
def obtener_venta_por_folio(db: Session, folio: str) -> BitacoraVentas | None:
    return (
        db.query(BitacoraVentas)
        .filter(BitacoraVentas.folio == folio)
        .first()
    )


# ===============================
# OBTENER DOMICILIO POR MOVIMIENTO
# ===============================
def obtener_domicilio_por_movimiento(
    db: Session,
    id_movimiento: str
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
    return venta.nombre_completo or "No disponible"


# ===============================
# CONSTRUIR PRODUCTO
# ===============================
def construir_producto(venta: BitacoraVentas) -> str:
    return venta.descripcion or "No disponible"


# ===============================
# CONSTRUIR FECHA
# ===============================
def construir_fecha(venta: BitacoraVentas) -> str:
    if not venta.fecha_venta:
        return "No disponible"

    return venta.fecha_venta.strftime("%d/%m/%Y")


# ===============================
# CONSTRUIR DOMICILIO COMPLETO
# ===============================
def construir_domicilio(domicilio: DomiciliosHorariosEntrega) -> str:
    if not domicilio:
        return "No disponible"

    partes = [
        domicilio.tipo_de_vialidad,
        domicilio.nombre_vialidad,
        domicilio.no_ext,
        domicilio.colonia,
        domicilio.ciudad,
        domicilio.estado,
    ]

    return ", ".join(filter(None, partes))