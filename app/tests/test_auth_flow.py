import json
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.router.auth_router import _ensure_panel_company_allowed
from app.security import auth_service


class FakeQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.row


class FakeDb:
    def __init__(self, row):
        self.row = row

    def query(self, model):
        return FakeQuery(self.row)


def signed_token(payload):
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    encoded_payload = auth_service._b64url_encode(payload_json.encode("utf-8"))
    signature = auth_service._sign_payload(payload_json, auth_service._get_shared_secret())
    return f"{encoded_payload}.{signature}"


def test_decode_siga_token_rejects_invalid_empresa_before_db_lookup():
    token = signed_token({
        "user": "JEFEPANEL",
        "puesto": "JEFE DE COBRANZA",
        "empresa": 0,
        "exp": int(time.time()) + 300,
        "jti": "test-jti",
    })

    with pytest.raises(auth_service.AuthError) as exc_info:
        auth_service.decode_siga_token(token, db=object())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Empresa inválida"


def test_decode_panel_session_rejects_invalid_empresa():
    row = SimpleNamespace(
        username="JEFEPANEL",
        puesto="JEFE DE COBRANZA",
        empresa_id=0,
        role="jefe_operativo",
        exp=int(time.time()) + 3600,
        jti="session-jti",
        revoked_at=None,
    )

    with pytest.raises(auth_service.AuthError) as exc_info:
        auth_service.decode_panel_session("session-token", FakeDb(row))

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Empresa inválida en sesión"


def test_exchange_rejects_empresa_not_allowed_for_panel():
    user = SimpleNamespace(username="OTHER", role="jefe_operativo", empresa_id=8)

    with pytest.raises(HTTPException) as exc_info:
        _ensure_panel_company_allowed(user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Empresa no autorizada para panel"
