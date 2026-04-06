from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Header, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api_gateway import SmartHomeRuntime
from .debug_log import configure_logging

WEB_DIR = Path(__file__).resolve().parent / "web"


CODE_HTTP_MAP = {
    "OK": 200,
    "BAD_REQUEST": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "ENTITY_NOT_FOUND": 404,
    "CONFLICT": 409,
    "POLICY_CONFIRM_REQUIRED": 409,
    "CONFIRM_TOKEN_EXPIRED": 410,
    "UPSTREAM_ERROR": 502,
    "UPSTREAM_TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
}


def _http_status(code: str) -> int:
    return CODE_HTTP_MAP.get(code, 500 if code != "OK" else 200)


def create_app(
    *,
    redis_url: str | None = None,
    redis_client: Any | None = None,
    adapter: Any | None = None,
) -> FastAPI:
    configure_logging()
    runtime = SmartHomeRuntime(redis_url=redis_url, redis_client=redis_client, adapter=adapter)
    app = FastAPI(title="SmartHome NLU Runtime", version="v1")
    app.state.runtime = runtime

    if WEB_DIR.exists():
        app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")

    @app.get("/")
    def web_index():
        index_path = WEB_DIR / "index.html"
        if not index_path.exists():
            return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "web ui not found"})
        return FileResponse(index_path)

    @app.post("/api/v1/command")
    def post_command(payload: Dict[str, Any], x_trace_id: str | None = Header(default=None, alias="X-Trace-Id")) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.post_api_v1_command(payload, headers=headers)
        return JSONResponse(status_code=_http_status(result["code"]), content=result)

    @app.post("/api/v1/confirm")
    def post_confirm(payload: Dict[str, Any], x_trace_id: str | None = Header(default=None, alias="X-Trace-Id")) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.post_api_v1_confirm(payload, headers=headers)
        return JSONResponse(status_code=_http_status(result["code"]), content=result)

    @app.post("/api/v1/compare-channels")
    def post_compare_channels(
        payload: Dict[str, Any],
        x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.post_api_v1_compare_channels(payload, headers=headers)
        return JSONResponse(status_code=_http_status(result["code"]), content=result)

    @app.post("/api/v1/nlu/parse")
    def post_nlu_parse(payload: Dict[str, Any], x_trace_id: str | None = Header(default=None, alias="X-Trace-Id")) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.post_api_v1_nlu_parse(payload, headers=headers)
        return JSONResponse(status_code=_http_status(result["code"]), content=result)

    @app.get("/api/v1/health")
    def get_health(x_trace_id: str | None = Header(default=None, alias="X-Trace-Id")) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.get_api_v1_health(headers=headers)
        return JSONResponse(status_code=200, content=result)

    @app.get("/api/v1/entities")
    def get_entities(
        query: str = Query(default=""),
        domain: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        hide_default: bool = Query(default=True),
        x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.get_api_v1_entities(
            query=query,
            domain=domain,
            limit=limit,
            hide_default=hide_default,
            headers=headers,
        )
        return JSONResponse(status_code=_http_status(result["code"]), content=result)

    @app.get("/api/v1/history")
    def get_history(
        session_id: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=200),
        x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.get_api_v1_history(session_id=session_id, limit=limit, headers=headers)
        return JSONResponse(status_code=_http_status(result["code"]), content=result)

    @app.delete("/api/v1/history")
    def delete_history(
        session_id: str = Query(default=""),
        x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        headers = {"X-Trace-Id": x_trace_id} if x_trace_id else None
        result = runtime.delete_api_v1_history(session_id=session_id, headers=headers)
        return JSONResponse(status_code=_http_status(result["code"]), content=result)

    return app


app = create_app(redis_url=os.getenv("SMARTHOME_REDIS_URL"))
