from sqlalchemy.orm import Session
from app.db.models import BitacoraVentas, DomiciliosHorariosEntrega, Estado
import unicodedata


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
# OBTENER DOMICILIO POR MOVIMIENTO
# ===============================
def obtener_estado(db: Session, idestado: str) -> Estado | None:
    estado = db.query(Estado).filter(Estado.idestado == idestado).first()
    return estado.estado


# ===============================
# CONSTRUIR NOMBRE
# ===============================
def construir_nombre(venta: BitacoraVentas) -> str:
    return venta.nombre_completo or "No disponible"


# ===============================
# CONSTRUIR PRODUCTO
# ===============================
def construir_producto(venta: BitacoraVentas) -> str:
    return venta.sku_bitacora_v or "No disponible"


# ===============================
# CONSTRUIR FECHA
# ===============================
def construir_fecha(venta: BitacoraVentas) -> str:
    if not venta.fecha_venta:
        return "No disponible"
    return venta.fecha_venta.strftime("%d/%m/%Y")


# ===============================
# QUITAR CARACTERES
# ===============================
def limpiar_texto_danado(texto: str) -> str:
    if not texto:
        return texto
    # Caso específico detectado
    texto = texto.replace("R??O", "RÍO")
    # Elimina caracteres raros invisibles
    texto = texto.encode("utf-8", "ignore").decode("utf-8")
    return texto


# ===============================
# TIPO DE VIALIDAD
# ===============================
TIPO_VIALIDAD = {
    "01": "Ampliación",
    "02": "Andador",
    "03": "Avenida",
    "04": "Boulevard",
    "05": "Calle",
    "06": "Callejón",
    "07": "Calzada",
    "08": "Cerrada",
    "09": "Circuito",
    "10": "Circunvalación",
    "11": "Continuación",
    "12": "Corredor",
    "13": "Diagonal",
    "14": "Eje Vial",
    "15": "Pasaje",
    "16": "Peatonal",
    "17": "Periférico",
    "18": "Privada",
    "19": "Prolongación",
    "20": "Retorno",
    "21": "Viaducto",
}


# ===============================
# ORDEN EN LOS NUMEROS DE ESTADO
# ===============================
def obtener_estado_abrev(estado: str) -> Estado | None:
    if not estado:
        return "Nimodillo"
    return Estado.estado


# ===============================
# ORDEN EN TIPO VIALIDAD
# ===============================
def obtener_tipo_vialidad(tipo):
    if not tipo:
        return ""
    tipo_str = str(tipo).zfill(2)
    return TIPO_VIALIDAD.get(tipo_str, tipo_str)


# ===============================
# CONSTRUIR DOMICILIO COMPLETO
# ===============================
def construir_domicilio(
    domicilio: DomiciliosHorariosEntrega,
    db: Session,
) -> str:
    if not domicilio:
        return "No disponible"
    tipo = obtener_tipo_vialidad(domicilio.tipo_de_vialidad)
    nombre = (domicilio.nombre_vialidad or "").strip()
    no_ext = (domicilio.no_ext or "").strip()
    no_int = (domicilio.no_int or "").strip()
    colonia = (domicilio.colonia or "").strip()
    cp = (domicilio.codigo_postal or "").strip()
    ciudad = (domicilio.ciudad or "").strip()
    referencias = (domicilio.referencias or "").strip()

    estado = obtener_estado(db, domicilio.estado)

    # Línea principal
    linea1 = f"{tipo} {nombre} {no_ext}".strip()
    if no_int:
        linea1 += f" Int. {no_int}"
    lineas = [linea1]
    if colonia:
        lineas.append(f"COL. {colonia}")
    if cp:
        lineas.append(f"C.P. {cp}")
    if ciudad or estado:
        lineas.append(f"{ciudad}, {estado}".strip(", "))
    if referencias and referencias.upper() != "S/N":
        lineas.append(f"Ref: {referencias}")
    return "\n".join(lineas)
