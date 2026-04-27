from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.router import panel_router
from app.services import panel_staff
from app.services.panel_staff import (
    is_active_employee_value,
    normalize_username,
    panel_role_for_puesto,
)


def staff_row(**overrides):
    values = {
        "source_id": 1,
        "username": "COL-GESTOR1",
        "estatus": 1,
        "nombre_completo": "Gestor Uno",
        "nombre_resumido": "Gestor 1",
        "jefe_directo": "Boss",
        "puesto": "Gestor de cobranza",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_normalize_username_uppercases_and_trims():
    assert normalize_username(" col-test01 ") == "COL-TEST01"


def test_active_employee_values_are_strict():
    assert is_active_employee_value(1)
    assert is_active_employee_value("activo")
    assert not is_active_employee_value(0)
    assert not is_active_employee_value("inactivo")


def test_panel_role_for_puesto_detects_manager():
    assert panel_role_for_puesto("Gestor de cobranza") == "gestor_cobranza"


def test_panel_role_for_puesto_keeps_supervisor_out_of_manager_queue():
    assert panel_role_for_puesto("Supervisor de cobranza") == "lectura"


def test_panel_role_for_puesto_detects_support_and_boss():
    assert panel_role_for_puesto("Soporte tecnico") == "soporte_tecnico"
    assert panel_role_for_puesto("Jefe de cobranza") == "jefe_operativo"


def test_build_manager_directory_excludes_ambiguous_usernames_and_non_managers():
    directory = panel_staff._build_manager_directory([
        staff_row(source_id=1, username=" gestor1 ", nombre_completo="Gestor Uno"),
        staff_row(source_id=2, username="dup01", nombre_completo="Dup Uno"),
        staff_row(
            source_id=3,
            username=" DUP01 ",
            nombre_completo="Dup Dos",
            puesto="Jefe de cobranza",
        ),
        staff_row(
            source_id=4,
            username="tech1",
            nombre_completo="Tech",
            puesto="Soporte tecnico",
        ),
        staff_row(
            source_id=5,
            username="inactive1",
            nombre_completo="Inactive",
            estatus=0,
        ),
    ])

    assert list(directory.keys()) == ["GESTOR1"]
    manager = directory["GESTOR1"]
    assert manager.username == "GESTOR1"
    assert manager.nombre == "Gestor Uno"
    assert manager.duplicate_rows == 1


def test_get_available_managers_merges_load_and_online_by_normalized_username(monkeypatch):
    panel_staff.clear_manager_cache()

    monkeypatch.setattr(
        panel_staff,
        "_fetch_staff_rows",
        lambda db, empresa_id: [
            staff_row(source_id=1, username=" gestor1 ", nombre_completo="Gestor Uno"),
            staff_row(source_id=2, username="gestor2", nombre_completo="Gestor Dos"),
        ],
    )
    monkeypatch.setattr(
        panel_staff,
        "_fetch_current_load_map",
        lambda db, usernames: {"GESTOR1": 2, "GESTOR2": 0},
    )
    monkeypatch.setattr(
        panel_staff,
        "_fetch_online_usernames",
        lambda db, empresa_id, usernames: {"GESTOR2"},
    )

    managers = panel_staff.get_available_managers(object(), empresa_id=1)

    assert [item.username for item in managers] == ["GESTOR2", "GESTOR1"]
    assert managers[0].is_online is True
    assert managers[0].current_load == 0
    assert managers[1].is_online is False
    assert managers[1].current_load == 2


def test_gestores_disponibles_returns_503_on_operational_error(monkeypatch):
    user = SimpleNamespace(role="admin", username="root", empresa_id=1)

    def raise_db_error(db, empresa_id):
        raise OperationalError("select", {}, Exception("db unavailable"))

    monkeypatch.setattr(panel_router, "get_available_managers", raise_db_error)

    with pytest.raises(HTTPException) as exc_info:
        panel_router.get_gestores_disponibles(db=object(), user=user)

    assert exc_info.value.status_code == 503


def test_gestores_disponibles_returns_500_on_unexpected_error(monkeypatch):
    user = SimpleNamespace(role="admin", username="root", empresa_id=1)

    monkeypatch.setattr(
        panel_router,
        "get_available_managers",
        lambda db, empresa_id: (_ for _ in ()).throw(ValueError("bad payload")),
    )

    with pytest.raises(HTTPException) as exc_info:
        panel_router.get_gestores_disponibles(db=object(), user=user)

    assert exc_info.value.status_code == 500
