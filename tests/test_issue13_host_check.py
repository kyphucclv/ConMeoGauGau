import pytest

from scripts.issue13_host_check import connection_budget, validate_origin


def test_https_origin_contract_accepts_only_one_clean_origin():
    assert validate_origin("https://english-class.example.internal") == ("english-class.example.internal", 443)
    assert validate_origin("https://english-class.example.internal:8443/") == ("english-class.example.internal", 8443)
    for invalid in (
        "http://english-class.example.internal",
        "https://user:secret@english-class.example.internal",
        "https://english-class.example.internal/app",
        "https://english-class.example.internal?token=secret",
    ):
        with pytest.raises(ValueError):
            validate_origin(invalid)


def test_connection_budget_accounts_for_workers_pool_and_existing_connections():
    passing = connection_budget(
        max_connections=100, reserved_connections=3, current_connections=20, workers=1, pool_max=5
    )
    failing = connection_budget(
        max_connections=30, reserved_connections=3, current_connections=20, workers=2, pool_max=5
    )
    assert passing["passes"] is True and passing["configured_app_max"] == 5
    assert failing["passes"] is False and failing["available_before_start"] == 7
