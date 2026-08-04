# tests/dashboard/test_auth.py
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from etorobot.dashboard.auth import make_auth


def _app(token):
    app = FastAPI()
    auth = make_auth(token)

    @app.get("/ping")
    async def ping(_=Depends(auth)):
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=True)


def test_no_token_configured_allows_all():
    client = _app(None)
    assert client.get("/ping").status_code == 200


def test_missing_token_is_401():
    client = _app("s3cret")
    assert client.get("/ping").status_code == 401


def test_bearer_header_accepted():
    client = _app("s3cret")
    r = client.get("/ping", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_query_param_accepted():
    client = _app("s3cret")
    assert client.get("/ping?token=s3cret").status_code == 200


def test_cookie_accepted():
    client = _app("s3cret")
    client.cookies.set("dashboard_token", "s3cret")
    assert client.get("/ping").status_code == 200


def test_wrong_token_is_401():
    client = _app("s3cret")
    assert client.get("/ping?token=nope").status_code == 401
