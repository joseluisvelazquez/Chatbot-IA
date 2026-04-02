from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import AuthToken
from app.security.auth_models import PanelUser


ROLE_MAP: dict[str, str] = {
    "GERENTE EJECUTIVO": "admin",
    "GERENTE GENERAL": "admin",
    "GERENTE DE VENTAS": "ventas",
    "ASESOR COMERCIAL": "ventas",
    "ASESOR COMERCIAL EXTERNO": "ventas",
    "GESTOR DE COBRANZA": "cobranza",
    "SUPERVISOR DE COBRANZA": "cobranza",
    "JEFE DE SISTEMAS": "sistemas",
    "DESARROLLOS DE WEB JR": "sistemas",
    "PROGRAMADOR": "sistemas",
}


class AuthError(HTTPException):
    def __init__(self, detail: str = "No autenticado") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


def _get_shared_secret() -> str:
    secret = getattr(settings, "PANEL_SHARED_SECRET", None)
    if not secret:
        raise RuntimeError("Falta PANEL_SHARED_SECRET en configuración")
    return secret


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _sign_payload(payload_json: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _parse_signed_token(token: str) -> dict[str, Any]:
    if not token or "." not in token:
        raise AuthError("Token inválido")

    try:
        encoded_payload, signature = token.split(".", 1)
        payload_json = _b64url_decode(encoded_payload).decode("utf-8")
    except Exception as exc:
        raise AuthError("Token mal formado") from exc

    expected_signature = _sign_payload(payload_json, _get_shared_secret())

    if not hmac.compare_digest(signature, expected_signature):
        raise AuthError("Firma inválida")

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise AuthError("Payload inválido") from exc

    return payload


def decode_siga_token(token: str, db: Session) -> PanelUser:
    """
    Token one-time firmado por SIGA.
    Formato:
    base64url(payload_json).hex_hmac_sha256(payload_json)

    Payload esperado:
    {
      "user": "...",
      "puesto": "...",
      "empresa": 1,
      "exp": 1730000000,
      "jti": "uuid-o-random-id"
    }
    """
    payload = _parse_signed_token(token)

    username = str(payload.get("user", "")).strip()
    puesto = str(payload.get("puesto", "")).strip().upper()
    empresa_raw = payload.get("empresa")
    exp_raw = payload.get("exp")
    jti = str(payload.get("jti", "")).strip()

    if not username:
        raise AuthError("Token sin usuario")

    if not puesto:
        raise AuthError("Token sin puesto")

    if not jti:
        raise AuthError("Token sin identificador")

    try:
        empresa_id = int(empresa_raw)
    except (TypeError, ValueError) as exc:
        raise AuthError("Empresa inválida") from exc

    try:
        exp = int(exp_raw)
    except (TypeError, ValueError) as exc:
        raise AuthError("Expiración inválida") from exc

    now = int(time.time())
    if exp <= now:
        raise AuthError("Token expirado")

    token_row = (
        db.query(AuthToken)
        .filter(AuthToken.jti == jti)
        .first()
    )

    if not token_row:
        raise AuthError("Token no registrado")

    if token_row.used_at is not None:
        raise AuthError("Token ya utilizado")

    # Marcar como usado inmediatamente dentro de la transacción actual.
    token_row.used_at = int(time.time())
    db.flush()

    role = ROLE_MAP.get(puesto, "viewer")

    return PanelUser(
        username=username,
        puesto=puesto,
        empresa_id=empresa_id,
        role=role,
        exp=exp,
        jti=jti,
    )


def create_panel_session_value(user: PanelUser) -> str:
    payload = {
        "user": user.username,
        "puesto": user.puesto,
        "empresa": user.empresa_id,
        "role": user.role,
        "exp": user.exp,
        "jti": user.jti,
    }
    payload_json = _canonical_json(payload)
    encoded_payload = _b64url_encode(payload_json.encode("utf-8"))
    signature = _sign_payload(payload_json, _get_shared_secret())
    return f"{encoded_payload}.{signature}"


def decode_panel_session(session_token: str) -> PanelUser:
    if not session_token or "." not in session_token:
        raise AuthError("Sesión inválida")

    payload = _parse_signed_token(session_token)

    username = str(payload.get("user", "")).strip()
    puesto = str(payload.get("puesto", "")).strip().upper()
    role = str(payload.get("role", "viewer")).strip()
    empresa_raw = payload.get("empresa")
    exp_raw = payload.get("exp")
    jti_raw = payload.get("jti")

    if not username or not puesto:
        raise AuthError("Sesión incompleta")

    try:
        empresa_id = int(empresa_raw)
        exp = int(exp_raw)
    except (TypeError, ValueError) as exc:
        raise AuthError("Sesión inválida") from exc

    if exp <= int(time.time()):
        raise AuthError("Sesión expirada")

    jti = str(jti_raw).strip() if jti_raw else None

    return PanelUser(
        username=username,
        puesto=puesto,
        empresa_id=empresa_id,
        role=role,  # type: ignore[arg-type]
        exp=exp,
        jti=jti,
    )