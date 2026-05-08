from sqlalchemy.orm import Session
from app.db.models import BitacoraVentas, DomiciliosHorariosEntrega, Estado, VerificacionCuenta
from app.utils.address_formatter import capitalizar_texto
from typing import Optional

# ===============================
# OBTENER VENTA POR FOLIO
# ===============================
def obtener_venta_por_folio(
    db: Session,
    folio: str,
    company_id: int = 1,
) -> Optional[BitacoraVentas]:
    return (
        db.query(BitacoraVentas)
        .filter(
            BitacoraVentas.folio == folio,
            BitacoraVentas.id_emp_bv == company_id
        )
        .first()
    )

# ===============================
# OBTENER FOLIOS PENDIENTES POR TELÉFONO
# ===============================
def obtener_folios_pendientes_por_telefono(db: Session, phone: str) -> list[str]:
    from app.db.models import BitacoraVentas, ChatSessions
    # 1. Obtener todas las ventas del cliente por tel_1
    ventas = db.query(BitacoraVentas).filter(BitacoraVentas.tel_1 == phone).all()
    
    # 2. Obtener la sesión actual del teléfono para revisar si hay algo finalizado
    chat = db.query(ChatSessions).filter(ChatSessions.phone == phone).first()
    
    folios_pendientes = []
    for v in ventas:
        if not v.folio:
            continue
            
        # Si la venta coincide con el folio actual de la sesión y el estado es FINALIZADO, ya se verificó
        if chat and chat.folio == v.folio and chat.state == "FINALIZADO":
            continue
            
        folios_pendientes.append(v.folio)
        
    return list(set(folios_pendientes))


def obtener_verificacion_por_no_cuenta(db: Session, no_cuenta: str) -> Optional[VerificacionCuenta]:
    return (
        db.query(VerificacionCuenta)
        .filter(
            VerificacionCuenta.no_cuenta == no_cuenta
        )
        .first()
    )


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
# CONSTRUIR PAGO INICIAL
# ===============================
def construir_pago_inicial(venta: BitacoraVentas) -> float | int:
    # Retorna el pago (o 0) para que pueda ser formateado en el mensaje
    return venta.pago or 0

# ===============================
# CONSTRUIR NÚMERO DE CUENTA
# ===============================
def construir_no_cuenta(venta: BitacoraVentas) -> str:
    return venta.no_cuenta or "No disponible"
