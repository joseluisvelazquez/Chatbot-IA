from __future__ import annotations

import time
import unicodedata
from collections import Counter
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import ChatSessions, Colaboradores, PanelSession
from app.security.rbac import (
    ROLE_ADMIN,
    ROLE_GESTOR_COBRANZA,
    ROLE_JEFE_OPERATIVO,
    ROLE_SOPORTE_TECNICO,
    normalize_role,
)

_MANAGER_CACHE: dict[int, dict[str, object]] = {}

ACTIVE_EMPLOYEE_VALUES = {1, "1", "ACTIVO", "ACTIVA", "ACTIVE"}
GESTOR_PUESTO_TOKENS = ("GESTOR", "COBRANZA")
SUPPORT_PUESTO_TOKENS = ("SOPORTE", "SISTEMAS", "PROGRAMADOR", "DESARROLLO")
JEFE_PUESTO_PHRASES = ("JEFE OPERATIVO", "JEFE DE COBRANZA", "GERENTE DE VENTAS")
ACTIVE_CHAT_STATUSES = {"assigned_gestor", "assigned_soporte", "waiting_customer", "escalated"}


@dataclass(frozen=True)
class AvailableManager:
    username: str
    nombre: str
    jefe_directo: str | None
    puesto: str | None
    current_load: int
    is_online: bool
    duplicate_rows: int


@dataclass(frozen=True)
class StaffDirectoryEntry:
    source_id: int
    username: str
    nombre: str
    jefe_directo: str | None
    puesto: str | None
    duplicate_rows: int


def _normalize_text(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.upper().split())


def _clean_text(value) -> str:
    return str(value or "").strip()


def _optional_text(value) -> str | None:
    text = _clean_text(value)
    return text or None


def normalize_username(value: str | None) -> str:
    return _normalize_text(value)


def is_active_employee_value(value) -> bool:
    if value in ACTIVE_EMPLOYEE_VALUES:
        return True
    normalized = _normalize_text(value)
    return normalized in ACTIVE_EMPLOYEE_VALUES


def panel_role_for_puesto(puesto: str | None) -> str:
    normalized = _normalize_text(puesto)
    if not normalized:
        return "lectura"
    if all(token in normalized for token in GESTOR_PUESTO_TOKENS):
        return ROLE_GESTOR_COBRANZA
    if any(phrase in normalized for phrase in JEFE_PUESTO_PHRASES):
        return ROLE_JEFE_OPERATIVO
    if any(token in normalized for token in SUPPORT_PUESTO_TOKENS):
        return ROLE_SOPORTE_TECNICO
    if "GERENTE EJECUTIVO" in normalized:
        return ROLE_ADMIN
    if "GERENTE" in normalized and "GENERAL" in normalized:
        return ROLE_ADMIN
    return "lectura"


def clear_manager_cache() -> None:
    _MANAGER_CACHE.clear()


def _fetch_staff_rows(db: Session, *, empresa_id: int):
    username_expr = func.trim(Colaboradores.nombre_usuario)
    return (
        db.query(
            Colaboradores.id.label("source_id"),
            username_expr.label("username"),
            Colaboradores.estatus.label("estatus"),
            func.nullif(func.trim(Colaboradores.nombre_completo), "").label("nombre_completo"),
            func.nullif(func.trim(Colaboradores.nombre_resumido), "").label("nombre_resumido"),
            func.nullif(func.trim(Colaboradores.jefe_directo), "").label("jefe_directo"),
            Colaboradores.puesto.label("puesto"),
        )
        .filter(
            Colaboradores.id_emp_col == empresa_id,
            Colaboradores.nombre_usuario.isnot(None),
            username_expr != "",
        )
        .order_by(Colaboradores.id.desc())
        .all()
    )


def _build_manager_directory(rows) -> dict[str, StaffDirectoryEntry]:
    active_username_counts: Counter[str] = Counter()
    manager_candidates: dict[str, StaffDirectoryEntry] = {}

    for row in rows:
        raw_username = _clean_text(getattr(row, "username", None))
        normalized_username = normalize_username(raw_username)
        if not normalized_username:
            continue

        if not is_active_employee_value(getattr(row, "estatus", None)):
            continue

        active_username_counts[normalized_username] += 1

        if panel_role_for_puesto(getattr(row, "puesto", None)) != ROLE_GESTOR_COBRANZA:
            continue

        entry = StaffDirectoryEntry(
            source_id=int(getattr(row, "source_id", 0) or 0),
            username=normalized_username,
            nombre=(
                _clean_text(getattr(row, "nombre_completo", None))
                or _clean_text(getattr(row, "nombre_resumido", None))
                or normalized_username
            ),
            jefe_directo=_optional_text(getattr(row, "jefe_directo", None)),
            puesto=_optional_text(getattr(row, "puesto", None)),
            duplicate_rows=0,
        )

        current = manager_candidates.get(normalized_username)
        if current is None or entry.source_id > current.source_id:
            manager_candidates[normalized_username] = entry

    directory: dict[str, StaffDirectoryEntry] = {}
    for normalized_username, entry in manager_candidates.items():
        duplicate_rows = int(active_username_counts.get(normalized_username, 1) or 1)
        if duplicate_rows > 1:
            continue

        directory[normalized_username] = StaffDirectoryEntry(
            source_id=entry.source_id,
            username=entry.username,
            nombre=entry.nombre,
            jefe_directo=entry.jefe_directo,
            puesto=entry.puesto,
            duplicate_rows=duplicate_rows,
        )

    return directory


def _fetch_current_load_map(db: Session, *, usernames: list[str]) -> dict[str, int]:
    normalized_usernames = sorted({normalize_username(item) for item in usernames if normalize_username(item)})
    if not normalized_usernames:
        return {}

    username_expr = func.upper(func.trim(ChatSessions.assigned_user_id))
    rows = (
        db.query(
            username_expr.label("username"),
            func.count(ChatSessions.id).label("current_load"),
        )
        .filter(
            ChatSessions.assigned_user_id.isnot(None),
            func.trim(ChatSessions.assigned_user_id) != "",
            ChatSessions.status_operativo.in_(list(ACTIVE_CHAT_STATUSES)),
            username_expr.in_(normalized_usernames),
        )
        .group_by(username_expr)
        .all()
    )

    result: dict[str, int] = {}
    for row in rows:
        normalized_username = normalize_username(getattr(row, "username", None))
        if not normalized_username:
            continue
        result[normalized_username] = result.get(normalized_username, 0) + int(getattr(row, "current_load", 0) or 0)

    return result


def _fetch_online_usernames(db: Session, *, empresa_id: int, usernames: list[str]) -> set[str]:
    normalized_usernames = sorted({normalize_username(item) for item in usernames if normalize_username(item)})
    if not normalized_usernames:
        return set()

    username_expr = func.upper(func.trim(PanelSession.username))
    now_ts = int(time.time())
    rows = (
        db.query(username_expr.label("username"))
        .filter(
            PanelSession.empresa_id == empresa_id,
            PanelSession.revoked_at.is_(None),
            PanelSession.exp > now_ts,
            PanelSession.username.isnot(None),
            func.trim(PanelSession.username) != "",
            username_expr.in_(normalized_usernames),
        )
        .group_by(username_expr)
        .all()
    )

    return {
        normalized_username
        for normalized_username in (
            normalize_username(getattr(row, "username", None))
            for row in rows
        )
        if normalized_username
    }


def get_available_managers(db: Session, *, empresa_id: int) -> list[AvailableManager]:
    now = time.time()

    cache_entry = _MANAGER_CACHE.get(empresa_id)
    if cache_entry and now - float(cache_entry.get("ts", 0)) < 30:
        return list(cache_entry.get("data", []))

    staff_rows = _fetch_staff_rows(db, empresa_id=empresa_id)
    directory = _build_manager_directory(staff_rows)

    if not directory:
        _MANAGER_CACHE[empresa_id] = {"ts": now, "data": []}
        return []

    normalized_usernames = list(directory.keys())
    load_by_username = _fetch_current_load_map(db, usernames=normalized_usernames)
    online_usernames = _fetch_online_usernames(db, empresa_id=empresa_id, usernames=normalized_usernames)

    managers = [
        AvailableManager(
            username=entry.username,
            nombre=entry.nombre,
            jefe_directo=entry.jefe_directo,
            puesto=entry.puesto,
            current_load=int(load_by_username.get(normalized_username, 0) or 0),
            is_online=normalized_username in online_usernames,
            duplicate_rows=entry.duplicate_rows,
        )
        for normalized_username, entry in directory.items()
    ]

    managers.sort(
        key=lambda item: (
            0 if item.is_online else 1,
            int(item.current_load or 0),
            _normalize_text(item.nombre),
            item.username,
        )
    )

    _MANAGER_CACHE[empresa_id] = {
        "ts": now,
        "data": list(managers),
    }
    return managers


def get_active_staff_member(
    db: Session,
    *,
    username: str,
    empresa_id: int,
    expected_role: str | None = None,
):
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Username invalido")

    username_expr = func.trim(Colaboradores.nombre_usuario)
    rows = (
        db.query(Colaboradores)
        .filter(
            Colaboradores.id_emp_col == empresa_id,
            Colaboradores.estatus == 1,
            Colaboradores.nombre_usuario.isnot(None),
            func.upper(username_expr) == normalized_username,
        )
        .order_by(Colaboradores.id.desc())
        .all()
    )

    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario interno no encontrado o inactivo")

    if len(rows) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El username interno es ambiguo en SIGA; corrige colaboradores antes de asignar",
        )

    row = rows[0]
    detected_role = panel_role_for_puesto(row.puesto)
    if expected_role and normalize_role(expected_role) != normalize_role(detected_role):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El usuario interno no pertenece a la cola operativa requerida",
        )
    return row


def is_manager_active(db: Session, *, username: str, empresa_id: int) -> bool:
    try:
        row = get_active_staff_member(
            db,
            username=username,
            empresa_id=empresa_id,
            expected_role=ROLE_GESTOR_COBRANZA,
        )
    except HTTPException:
        return False
    return panel_role_for_puesto(row.puesto) == ROLE_GESTOR_COBRANZA


def is_panel_user_available(
    db: Session,
    *,
    username: str | None,
    empresa_id: int,
    expected_role: str | None = None,
) -> bool:
    if not username:
        return False

    try:
        get_active_staff_member(
            db,
            username=username,
            empresa_id=empresa_id,
            expected_role=expected_role,
        )
    except HTTPException:
        return False

    now_ts = int(time.time())
    normalized_username = normalize_username(username)
    username_expr = func.upper(func.trim(PanelSession.username))

    return bool(
        db.query(PanelSession.id)
        .filter(
            PanelSession.empresa_id == empresa_id,
            PanelSession.revoked_at.is_(None),
            PanelSession.exp > now_ts,
            PanelSession.username.isnot(None),
            username_expr == normalized_username,
        )
        .first()
    )


def get_default_inactive_manager_destination(setting_value: str | None) -> str:
    normalized = _normalize_text(setting_value).replace(" ", "_").lower()
    if normalized == "cola_general":
        return "cola_general"
    return "jefe_operativo"


def get_available_operational_heads(db: Session, *, empresa_id: int):
    rows = (
        db.query(Colaboradores)
        .filter(
            Colaboradores.id_emp_col == empresa_id,
            Colaboradores.estatus == 1,
        )
        .all()
    )

    result = []

    for row in rows:
        role = panel_role_for_puesto(row.puesto)

        if role != ROLE_JEFE_OPERATIVO:
            continue

        username = str(row.nombre_usuario or "").strip()

        if not username:
            continue

        result.append({
            "username": username,
            "nombre": str(
                row.nombre_completo
                or row.nombre_resumido
                or username
            ).strip()
        })

    return result
