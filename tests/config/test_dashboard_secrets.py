# tests/config/test_dashboard_secrets.py
from etorobot.config.settings import DashboardSecrets


def test_token_defaults_to_none(monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    assert DashboardSecrets(_env_file=None).token is None


def test_token_read_from_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "s3cret")
    assert DashboardSecrets(_env_file=None).token == "s3cret"
