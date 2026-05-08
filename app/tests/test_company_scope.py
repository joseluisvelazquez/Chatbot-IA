from app.security.auth_service import is_allowed_panel_company


def test_panel_company_scope_allows_only_supported_companies():
    assert is_allowed_panel_company(1)
    assert is_allowed_panel_company(8)
    assert is_allowed_panel_company("8")
    assert not is_allowed_panel_company(2)
    assert not is_allowed_panel_company(None)
