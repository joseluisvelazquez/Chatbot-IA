from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from app.config.settings import settings
from app.db.models import AuthToken
from app.security.auth_models import PanelUser
import secrets
from app.db.models import PanelSession

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

        # usar EXACTAMENTE el payload recibido
        payload_bytes = _b64url_decode(encoded_payload)
        payload_json = payload_bytes.decode("utf-8")

    except Exception as exc:
        raise AuthError("Token mal formado") from exc

    secret = _get_shared_secret()

    # recalcular firma usando el JSON original (NO reconstruido)
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,  #  CLAVE: usar bytes directos
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        print("❌ Firma inválida")
        print("Payload:", payload_json)
        print("Expected:", expected_signature)
        print("Received:", signature)
        raise AuthError("Firma inválida")

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise AuthError("Payload inválido") from exc

    return payload

def decode_panel_session(session_token: str, db: Session) -> PanelUser:
    if not session_token:
        raise AuthError("Sesión inválida")

    row = (
        db.query(PanelSession)
        .filter(PanelSession.session_id == session_token)
        .first()
    )

    if not row:
        raise AuthError("Sesión no encontrada")

    now = int(time.time())

    if row.revoked_at is not None:
        raise AuthError("Sesión cerrada")

    if row.exp <= now:
        raise AuthError("Sesión expirada")

    return PanelUser(
        username=row.username,
        puesto=row.puesto,
        empresa_id=row.empresa_id,
        role=row.role,
        exp=row.exp,
        jti=row.jti,
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

def revoke_panel_session(session_token: str, db: Session) -> None:
    if not session_token:
        return

    row = (
        db.query(PanelSession)
        .filter(
            PanelSession.session_id == session_token,
            PanelSession.revoked_at.is_(None),
        )
        .first()
    )

    if row:
        row.revoked_at = int(time.time())
        db.flush()

def create_panel_session(db: Session, user: PanelUser, ip: str | None, user_agent: str | None) -> str:
    session_id = secrets.token_urlsafe(32)

    SESSION_DURATION = 60 * 60 * 8  # 8 horas

    now = int(time.time())

    row = PanelSession(
        session_id=session_id,
        username=user.username,
        puesto=user.puesto,
        empresa_id=user.empresa_id,
        role=user.role,
        jti=user.jti,
        exp=now + SESSION_DURATION,  
        ip=ip,
        user_agent=user_agent,
        revoked_at=None,
        created_at=datetime.utcnow(),
    )

    db.add(row)
    db.flush()

    return session_id

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
    print("JTI:", jti)

    token_row = (
        db.query(AuthToken)
        .filter(AuthToken.jti == jti)
        .first()
    )

    print("TOKEN_ROW:", token_row)

    if token_row:
        print("USED_AT:", token_row.used_at)

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

    print("DIFF:", exp - now)
    CLOCK_SKEW = 120  # 2 minutos

    if exp <= now - CLOCK_SKEW:
        
        print("NOW:", now)
        print("EXP:", exp)
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
