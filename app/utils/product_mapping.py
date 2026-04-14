from typing import Dict, TypedDict

class ProductInfo(TypedDict):
    nombre_amigable: str
    articulo: str

SKU_PRODUCT_MAP: Dict[str, ProductInfo] = {
    "PC-MAXICA": {
        "nombre_amigable": "PC-MAXICA",
        "articulo": "una"
    },
    "MULTI-MX-1": {
        "nombre_amigable": "Impresora Multifuncional Brother",
        "articulo": "una"
    },
    "MULTI-MX-2": {
        "nombre_amigable": "Impresora HP Smart Tank",
        "articulo": "una"
    },
    "IDEAPAD114IGL7": {
        "nombre_amigable": "Laptop Lenovo IdeaPad",
        "articulo": "una"
    },
    "KIT-POS-MX": {
        "nombre_amigable": "Kit Punto de Venta",
        "articulo": "un"
    },
    "MX-KIT-POS": {
        "nombre_amigable": "Kit Punto de Venta",
        "articulo": "un"
    },
    "14DQ6011DX": {
        "nombre_amigable": "Laptop HP",
        "articulo": "una"
    },
    "KIT-AIRE-MX": {
        "nombre_amigable": "Kit de Aire Acondicionado tipo Minisplit",
        "articulo": "un"
    },
    "G9-1": {
        "nombre_amigable": "Laptop HP",
        "articulo": "una"
    },
    "G9": {
        "nombre_amigable": "Laptop HP",
        "articulo": "una"
    },
    "MX-KIT-VIDVIG": {
        "nombre_amigable": "Kit de Videovigilancia",
        "articulo": "un"
    },
    "G10": {
        "nombre_amigable": "Laptop HP",
        "articulo": "una"
    },
    "14-DQ00": {
        "nombre_amigable": "Laptop HP",
        "articulo": "una"
    },
    "CP2035CL": {
        "nombre_amigable": "Laptop HP",
        "articulo": "una"
    },
    "G9-2": {
        "nombre_amigable": "Laptop HP",
        "articulo": "una"
    },
    "E1404G": {
        "nombre_amigable": "Laptop ASUS Vivobook",
        "articulo": "una"
    }
}

def get_product_info(sku: str) -> ProductInfo:
    """
    Devuelve la información de un producto a partir de su SKU (ignorando mayúsculas/minúsculas).
    Si no se encuentra en el mapa, devuelve un diccionario por defecto utilizando el propio SKU.
    """
    sku_upper = (sku or "").upper()
    return SKU_PRODUCT_MAP.get(
        sku_upper,
        {"nombre_amigable": sku_upper or "Producto", "articulo": "un(a)"}
    )
