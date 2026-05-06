from __future__ import annotations

from urllib.parse import urljoin

from app.config.settings import settings


def build_siga_account_url(no_cuenta: str | None = None, folio: str | None = None) -> str:
    """Build a SIGA-compatible account entry URL without inventing REST routes."""

    base_url = (settings.SIGA_PANEL_BASE_URL or "https://siga.mxcomp.mx/").strip()
    if not base_url.endswith("/"):
        base_url += "/"

    path = (settings.SIGA_ACCOUNT_REDIRECT_PATH or "").strip()
    if not path:
        return base_url

    return urljoin(base_url, path.lstrip("/"))
