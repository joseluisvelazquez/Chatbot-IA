import os

BASE_DOC_URL = os.getenv("DOC_BASE_URL", "https://tudominio.com/docs") # URL base para documentos, configurable vía .env


def build_document_url(doc_key: str, chat) -> str | None:
    """
    Convierte una clave del FLOW en una URL real descargable por Meta
    """

    if not doc_key:
        return None

    mapping = {

        # archivos estáticos
        "datos_bancarios_pdf": f"{BASE_DOC_URL}/bancos.pdf",
        "beneficios_pdf": f"{BASE_DOC_URL}/beneficios.pdf",

        # archivos dinámicos por cliente
        "contrato_pdf": f"{BASE_DOC_URL}/contratos/{chat.folio}.pdf",
    }

    return mapping.get(doc_key)
