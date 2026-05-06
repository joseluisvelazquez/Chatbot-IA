import re
import unicodedata
from typing import Any, Dict, Iterable, TypedDict

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


def _safe_text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _fold_token(value: Any) -> str:
    text = _safe_text(value).upper()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", "-", text).strip("-")


def _candidate_records(product: Any) -> Iterable[Any]:
    if isinstance(product, (list, tuple)):
        return product
    return (product,)


def _candidate_value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def normalize_product_sku(value: Any) -> str | None:
    token = _fold_token(value)
    if not token:
        return None

    for sku in SKU_PRODUCT_MAP:
        sku_token = _fold_token(sku)
        if token == sku_token:
            return sku
        if re.search(rf"(^|[^A-Z0-9]){re.escape(sku_token)}([^A-Z0-9]|$)", token):
            return sku

    return None


def product_sku_from_sale(sale: Any) -> str | None:
    if not isinstance(sale, (dict, list, tuple)) and not hasattr(sale, "__dict__"):
        return normalize_product_sku(sale)

    identifier_keys = (
        "sku_bitacora_v",
        "sku",
        "codigo_barras_bv",
        "codigo_barras",
        "identificador",
        "product_sku",
        "product_code",
        "codigo",
    )
    descriptive_keys = (
        "nombre_producto",
        "product",
        "producto",
        "descripcion",
        "description",
    )

    records = tuple(_candidate_records(sale))
    for key in identifier_keys:
        for record in records:
            sku = normalize_product_sku(_candidate_value(record, key))
            if sku:
                return sku

    for key in descriptive_keys:
        for record in records:
            sku = normalize_product_sku(_candidate_value(record, key))
            if sku:
                return sku

    return None


def normalize_product_name(sale: Any) -> str:
    sku = product_sku_from_sale(sale)
    if sku:
        return get_product_info(sku)["nombre_amigable"]

    fallback_keys = (
        "nombre_producto",
        "product",
        "producto",
        "sku_bitacora_v",
        "sku",
        "descripcion",
        "description",
    )
    for key in fallback_keys:
        for record in _candidate_records(sale):
            text = _safe_text(_candidate_value(record, key))
            if text:
                return text

    text = _safe_text(sale)
    return text or "Producto"


def get_product_info_for_sale(sale: Any) -> ProductInfo:
    sku = product_sku_from_sale(sale)
    if sku:
        return get_product_info(sku)

    return {"nombre_amigable": normalize_product_name(sale), "articulo": "un(a)"}


def requires_components_check(product: Any) -> bool:
    return product_sku_from_sale(product) == "PC-MAXICA"


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
