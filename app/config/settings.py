from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ============================================================
    # Seguridad y autenticación (obligatorias)
    # ============================================================


    PANEL_SHARED_SECRET: str = Field(...)

    PANEL_SESSION_COOKIE_NAME: str = "panel_session"
    PANEL_SESSION_SECURE_COOKIE: bool | None = None
    PANEL_SESSION_SAMESITE: str = "lax"
    PANEL_ALLOWED_EMPRESA_ID: int = 1
    PANEL_INACTIVE_MANAGER_FALLBACK: str = "jefe_operativo"
    PANEL_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5500",
            "http://127.0.0.1:5500",
            "http://192.168.50.61:5500",
            "http://192.168.50.165:5500",
            "http://192.168.1.106:5500",
            "http://192.168.1.71:5500",
            "http://192.168.50.191:5500",
        ]
    )

    # ============================================================
    # WhatsApp Cloud API (obligatorias)
    # ============================================================

    VERIFY_TOKEN: str
    WHATSAPP_TOKEN: str
    PHONE_NUMBER_ID: str
    META_APP_SECRET: str | None = None

    # ============================================================
    # WhatsApp Cloud API (opcionales / IDs de Imágenes)
    # ============================================================

    META_API_VERSION: str = "v24.0"
    METODOS_PAGO_IMAGE_ID: str | None = None
    
    # IDs de imágenes para componentes
    IMAGE_ID_CPU: str | None = None
    IMAGE_ID_MONITOR: str | None = None
    IMAGE_ID_TECLADO: str | None = None
    IMAGE_ID_MOUSE: str | None = None
    IMAGE_ID_BOCINAS: str | None = None
    IMAGE_ID_REGULADOR: str | None = None
    IMAGE_ID_WIFI: str | None = None

    # ============================================================
    # URL base para servir archivos
    # ============================================================

    MEDIA_BASE_URL: str



    # ============================================================
    # Gemini API (obligatorias)
    # ============================================================
    GEMINI_API_KEY: str

    @property
    def BASE_URL(self) -> str:
        return f"https://graph.facebook.com/{self.META_API_VERSION}"

    # ============================================================
    # Base de datos
    # ============================================================

    DB_HOST: str
    DB_PORT: int = 3306
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    # ============================================================
    # development/testing
    # ============================================================
    TEST_PHONE_ONLY: list[str]
    DEBUG: bool = True

    # ============================================================
    # SIGA Bridge v1
    # ============================================================
    SIGA_BRIDGE_BASE_URL: str = "http://localhost/PruebasP/bridge/"
    SIGA_BRIDGE_TOKEN: str | None = None
    SIGA_BRIDGE_ENABLED: bool = False
    SIGA_BRIDGE_TIMEOUT_CONNECT: float = 2.0
    SIGA_BRIDGE_TIMEOUT_READ: float = 5.0
    SIGA_BRIDGE_ALLOW_INSECURE_LOCAL: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )

    class Config:
        env_file = ".env"
        case_sensitive = True
    


# Instancia global

settings = Settings()

