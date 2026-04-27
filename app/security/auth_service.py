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
from app.db.models import AuthToken, Colaboradores, Cuentas
from app.security.auth_models import PanelUser
import secrets
from app.db.models import PanelSession
from app.security.rbac import (
    ROLE_ADMIN,
    ROLE_GESTOR_COBRANZA,
    ROLE_JEFE_OPERATIVO,
    ROLE_LECTURA,
    ROLE_SOPORTE_TECNICO,
    normalize_role,
)
from app.services.panel_staff import normalize_username, panel_role_for_puesto

ROLE_MAP: dict[str, str] = {
    "GERENTE EJECUTIVO": ROLE_ADMIN,
    "GERENTE GENERAL": ROLE_ADMIN,
    "GERENTE DE VENTAS": ROLE_JEFE_OPERATIVO,
    "JEFE OPERATIVO": ROLE_JEFE_OPERATIVO,
    "JEFE DE COBRANZA": ROLE_JEFE_OPERATIVO,
    "SUPERVISOR DE COBRANZA": ROLE_GESTOR_COBRANZA,
    "ASESOR COMERCIAL": ROLE_LECTURA,
    "ASESOR COMERCIAL EXTERNO": ROLE_LECTURA,
    "GESTOR DE COBRANZA": ROLE_GESTOR_COBRANZA,
    "JEFE DE SISTEMAS": ROLE_SOPORTE_TECNICO,
    "SOPORTE TECNICO": ROLE_SOPORTE_TECNICO,
    "SOPORTE TÉCNICO": ROLE_SOPORTE_TECNICO,
    "DESARROLLOS DE WEB JR": ROLE_SOPORTE_TECNICO,
    "PROGRAMADOR": ROLE_SOPORTE_TECNICO,
}


class AuthError(HTTPException):
    def __init__(self, detail: str = "No autenticado") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )

def get_nombre_resumido(db: Session, username: str) -> str | None:
    normalized_username = normalize_username(username)
    colab = (
        db.query(Colaboradores)
        .filter(Colaboradores.nombre_usuario == normalized_username)
        .order_by(Colaboradores.estatus.desc(), Colaboradores.id.desc())
        .first()
    )

    if not colab:
        return None

    preferred_name = str(colab.nombre_resumido or "").strip()
    if preferred_name:
        return preferred_name

    return str(colab.nombre_completo or "").strip() or None


def get_active_colaborador(db: Session, username: str) -> Colaboradores | None:
    normalized_username = normalize_username(username)
    if not normalized_username:
        return None

    return (
        db.query(Colaboradores)
        .filter(
            Colaboradores.nombre_usuario == normalized_username,
            Colaboradores.estatus == 1,
        )
        .order_by(Colaboradores.id.desc())
        .first()
    )

def restrict_to_assigned(query, user, db):
    """
    Filtra registros según rol del usuario.
    """

    # Roles que ven todo
    role = normalize_role(user.role)

    if role in (ROLE_ADMIN, ROLE_JEFE_OPERATIVO, ROLE_LECTURA):
        return query

    # Gestor de cobranza → solo lo suyo
    if role == ROLE_GESTOR_COBRANZA:
        nombre_resumido = get_nombre_resumido(db, user.username)

        if not nombre_resumido:
            # No tiene asignación válida → no ve nada
            return query.filter(False)

        return query.filter(
            Cuentas.agente_verificador == nombre_resumido
        )

    # Cualquier otro rol → por defecto nada
    return query.filter(False)

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

    empresa_id = int(row.empresa_id or 0)
    if empresa_id <= 0:
        raise AuthError("Empresa inválida en sesión")

    role = normalize_role(row.role)

    return PanelUser(
        username=row.username,
        puesto=row.puesto,
        empresa_id=empresa_id,
        role=role,
        exp=row.exp,
        jti=row.jti,
        user_id=row.username,
    )

def create_panel_session_value(user: PanelUser) -> str:
    payload = {
        "user": user.username,
        "puesto": user.puesto,
        "empresa": user.empresa_id,
        "role": normalize_role(user.role),
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
        role=normalize_role(user.role),
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

    username = normalize_username(payload.get("user"))
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

    if empresa_id <= 0:
        raise AuthError("Empresa inválida")

    try:
        exp = int(exp_raw)
    except (TypeError, ValueError) as exc:
        raise AuthError("Expiración inválida") from exc

    now = int(time.time())

    CLOCK_SKEW = 120  # 2 minutos

    if exp <= now - CLOCK_SKEW:
        raise AuthError("Token expirado")

    active_colaborador = get_active_colaborador(db, username)
    if not active_colaborador:
        raise AuthError("Usuario inactivo o inexistente en SIGA")

    puesto_actual = str(active_colaborador.puesto or "").strip().upper()
    if puesto_actual:
        puesto = puesto_actual

    token_row = (
        db.query(AuthToken)
        .filter(AuthToken.jti == jti)
        .with_for_update()
        .first()
    )

    if not token_row:
        raise AuthError("Token no registrado")

    if token_row.used_at is not None:
        raise AuthError("Token ya utilizado")

    # Marcar como usado inmediatamente dentro de la transacción actual.
    token_row.used_at = int(time.time())
    db.flush()

    role = normalize_role(ROLE_MAP.get(puesto, panel_role_for_puesto(puesto) or ROLE_LECTURA))

    return PanelUser(
        username=username,
        puesto=puesto,
        empresa_id=empresa_id,
        role=role,
        exp=exp,
        jti=jti,
        user_id=username,
    )
