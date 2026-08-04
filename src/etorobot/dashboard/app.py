# src/etorobot/dashboard/app.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from etorobot.dashboard.auth import make_auth
from etorobot.dashboard.reads import build_run_list, build_run_report
from etorobot.dashboard.sse import event_stream
from etorobot.dashboard.tailer import DbTailer
from etorobot.persistence.repo import Repository

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_url: str, token: str | None = None,
               poll_interval: float = 1.5) -> FastAPI:
    app = FastAPI(title="etorobot dashboard")
    repo = Repository(db_url)
    auth = make_auth(token)

    @app.exception_handler(Exception)
    async def _on_error(request: Request, exc: Exception):  # noqa: ANN001
        if isinstance(exc, HTTPException):
            return JSONResponse({"detail": exc.detail},
                                status_code=exc.status_code)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    @app.get("/api/runs")
    async def list_runs(_=Depends(auth)):
        return build_run_list(repo, now=datetime.now(timezone.utc))

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: int, _=Depends(auth)):
        report = build_run_report(repo, run_id,
                                  now=datetime.now(timezone.utc))
        if report is None:
            raise HTTPException(status_code=404, detail="run not found")
        return report

    @app.get("/api/runs/{run_id}/stream")
    async def stream_run(run_id: int, request: Request, _=Depends(auth)):
        if repo.get_run_row(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        tailer = DbTailer(repo, run_id)
        return StreamingResponse(
            event_stream(tailer, poll_interval, request),
            media_type="text/event-stream")

    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True),
              name="static")
    return app
