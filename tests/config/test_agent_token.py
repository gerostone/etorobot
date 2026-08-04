# tests/config/test_agent_token.py
from etorobot.config.settings import Secrets


def _clear(monkeypatch):
    for var in ("ETORO_API_KEY", "ETORO_USER_KEY", "ETORO_ENV",
                "ETORO_AGENT_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_agent_token_defaults_to_none(monkeypatch):
    _clear(monkeypatch)
    s = Secrets(api_key="ak", user_key="uk", _env_file=None)
    assert s.agent_token is None


def test_agent_token_read_from_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ETORO_AGENT_TOKEN", "agtok")
    s = Secrets(api_key="ak", user_key="uk", _env_file=None)
    assert s.agent_token == "agtok"
