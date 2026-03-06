from app.constants.estados import ESTADOS
from app.constants.vialidades import TIPO_VIALIDAD
from app.db.models import DomiciliosHorariosEntrega


def obtener_tipo_vialidad(tipo: str | int | None) -> str:
    if not tipo:
        return ""
    tipo_str = str(tipo).strip()
    return TIPO_VIALIDAD.get(tipo_str, tipo_str)


def obtener_estado_nombre(id_estado: str | int | None) -> str:
    if not id_estado:
        return ""
    id_str = str(id_estado).strip()
    if id_str.isdigit():
        id_str = str(int(id_str))
    return ESTADOS.get(id_str, id_str)


def capitalizar_texto(texto: str | None) -> str:
    """
    Convierte un texto en MAYÚSCULAS a formato Title Case (Primera Letra Mayúscula).
    """
    if not texto:
        return ""
        
    # Manejo básico de título, respetando acentos si la BD los tiene.
    # Excepciones comunes se pueden agregar aquí si es necesario (ej. de, la, el).
    palabras = texto.strip().split()
    palabras_capitalizadas = []
    
    # Palabras que no deberían ir en mayúscula inicial si están en medio
    excepciones = {"de", "del", "la", "las", "el", "los", "y", "en", "a"}
    
    for i, palabra in enumerate(palabras):
        p_lower = palabra.lower()
        if i > 0 and p_lower in excepciones:
            palabras_capitalizadas.append(p_lower)
        else:
            palabras_capitalizadas.append(p_lower.capitalize())
            
    return " ".join(palabras_capitalizadas)


def construir_domicilio(domicilio: DomiciliosHorariosEntrega) -> str:
    """
    Construye la dirección formateada a partir del registro de la base de datos,
    aplicando capitalización amigable y consultando los nombres de estado/vialidad
    desde los diccionarios locales.
    """
    if not domicilio:
        return "No disponible"
        
    tipo = obtener_tipo_vialidad(domicilio.tipo_de_vialidad)
    nombre = capitalizar_texto(domicilio.nombre_vialidad)
    no_ext = (domicilio.no_ext or "").strip()
    no_int = (domicilio.no_int or "").strip()
    colonia = capitalizar_texto(domicilio.colonia)
    cp = (domicilio.codigo_postal or "").strip()
    ciudad = capitalizar_texto(domicilio.ciudad)
    estado = capitalizar_texto(obtener_estado_nombre(domicilio.estado))

    # Línea principal
    linea1 = f"{tipo} {nombre} {no_ext}".strip()
    if no_int:
        linea1 += f" Int. {no_int}"
        
    partes = [linea1]
    
    # Colonia y CP
    if colonia and cp:
        partes.append(f"Col. {colonia} C.P. {cp}")
    elif colonia:
        partes.append(f"Col. {colonia}")
    elif cp:
        partes.append(f"C.P. {cp}")
        
    if ciudad or estado:
        partes.append(f"{ciudad}, {estado}".strip(", "))
        
    return ", ".join(partes)
