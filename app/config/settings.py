from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ============================================================
    # Seguridad y autenticación (obligatorias)
    # ============================================================


    PANEL_SHARED_SECRET: str = Field(...)

    PANEL_SESSION_COOKIE_NAME: str = "panel_session"
    PANEL_SESSION_SECURE_COOKIE: bool = False
    PANEL_SESSION_SAMESITE: str = "lax"

    # ============================================================
    # WhatsApp Cloud API (obligatorias)
    # ============================================================

    VERIFY_TOKEN: str
    WHATSAPP_TOKEN: str
    PHONE_NUMBER_ID: str

    # ============================================================
    # Opcionales
    # ============================================================

    META_API_VERSION: str = "v24.0"
    METODOS_PAGO_IMAGE_ID: str | None = None


    # ============================================================
    # Base URL (propiedad dinámica)
    # ============================================================

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
