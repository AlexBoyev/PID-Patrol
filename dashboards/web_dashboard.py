"""
PID Patrol – JSON-only UI endpoints (no duplicate routes, no redirects)

Exposed routes:
- GET  "/"                 -> render dashboard (SSR via Jinja2)
- POST "/ui/add"           -> JSON only: {"names": "chrome, python"} OR {"names": ["chrome","python"]}
- POST "/ui/remove"        -> JSON only: {"name": "chrome"}
- POST "/ui/interval"      -> JSON only: {"interval": 2}   (>= 1.0 sec)
- POST "/ui/start"         -> JSON only: {} (optionally {"interval": 2, "processes": [...]})
- POST "/ui/stop"          -> JSON only: {}
- WS   "/ws"               -> optional live snapshots

Success -> HTTP 200 with JSON
Error   -> HTTP 409 with JSON {"ok": false, "error": "..."}
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from . import utils

app = FastAPI(title="PID Patrol", version="3.6.0")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    # moved to utils._render_index
    return await utils._render_index(request, templates)


@app.post("/ui/add")
async def ui_add(request: Request):
    try:
        payload = await request.json()
    except Exception as e:
        print(f"[/ui/add] invalid payload (expected JSON): {e}")
        return JSONResponse({"ok": False, "error": "invalid payload (expected JSON)"}, status_code=409)
    raw = payload.get("names") or payload.get("processes")
    if raw is None:
        return JSONResponse({"ok": False, "error": "missing 'names' or 'processes'"}, status_code=409)
    if isinstance(raw, list):
        new_names = utils.normalize_names([str(x) for x in raw])
    else:
        # moved splitter into utils._split_names
        new_names = utils.normalize_names(utils._split_names(str(raw)))
    if not new_names:
        return JSONResponse({"ok": False, "error": "empty names"}, status_code=409)
    merged = utils.process_names + new_names
    normalized = utils.normalize_names(merged)
    result = await utils.configure_processes({"processes": normalized})
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/ui/remove")
async def ui_remove(request: Request):
    try:
        payload = await request.json()
    except Exception as e:
        print(f"[/ui/remove] invalid payload (expected JSON): {e}")
        return JSONResponse({"ok": False, "error": "invalid payload (expected JSON)"}, status_code=409)
    raw = payload.get("name")
    tgt = str(raw or "").strip()
    if not tgt:
        return JSONResponse({"ok": False, "error": "missing name"}, status_code=409)
    lower_tgt = tgt.lower()
    remaining = [n for n in utils.process_names if n.lower() != lower_tgt]
    result = await utils.configure_processes({"processes": remaining})
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/ui/interval")
async def ui_interval(request: Request):
    try:
        payload = await request.json()
        f = float(payload.get("interval") or payload.get("update_interval"))
    except Exception as e:
        print(f"[/ui/interval] invalid interval payload: {e}")
        return JSONResponse({"ok": False, "error": "invalid interval"}, status_code=409)
    if f < 1.0:
        return JSONResponse({"ok": False, "error": "interval must be >= 1.0"}, status_code=409)
    result = await utils.update_interval(f)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/ui/start")
async def ui_start(request: Request):
    payload: Dict[str, Any] = {}
    try:
        payload = await request.json()
    except Exception as e:
        print(f"[/ui/start] payload parse error: {e}")
        payload = {}
    result = await utils.api_start(payload)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/ui/stop")
async def ui_stop():
    result = await utils.api_stop()
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.websocket("/ws")
async def ws_snapshots(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            if utils.running and utils.process_names:
                rows = [await asyncio.to_thread(utils.row_for_name, n) for n in utils.process_names]
            else:
                rows = []
            await ws.send_json(
                {
                    "type": "snapshot",
                    "timestamp": utils.time_stamp(),
                    "running": utils.running,
                    "interval": utils.interval,
                    "processes": [{"name": n} for n in utils.process_names],
                    "rows": rows,
                }
            )
            await asyncio.sleep(max(0.5, float(utils.interval)))
    except WebSocketDisconnect as e:
        print(f"[/ws] WebSocket disconnected: {e}")
    except Exception as e:
        print(f"[/ws] unexpected error: {e}")


@app.get("/ui/status")
async def ui_status() -> JSONResponse:
    """
    Return current monitoring state for tests and UI polling.
    JSON-only, HTTP 200.
    """
    return JSONResponse(
        {
            "ok": True,
            "running": utils.running,
            "interval": utils.interval,
            "processes": [{"name": n} for n in utils.process_names],
            "timestamp": utils.time_stamp(),
        }
    )


@app.get("/ui/results")
async def ui_results():
    names = list(utils.process_names or [])
    if not utils.running or not utils.process_names:
        return Response(status_code=204)

    async def _one(n: str):
        return await asyncio.to_thread(utils.row_for_name, n)

    rows = [await _one(n) for n in names]
    results = []
    for r in rows:
        results.append(
            {
                "name": r.get("name"),
                "pids": r.get("pids") or [],
                "status": (r.get("status") or "unknown").replace("_", " "),
                "cpu_percent": round(float(r.get("cpu_percent") or 0.0), 3),
                "memory_mb": round(float(r.get("memory_mb") or 0.0), 3),
                "last_checked": r.get("last_checked") or utils.time_stamp(),
            }
        )
    return JSONResponse(
        {
            "ok": True,
            "running": utils.running,
            "interval": utils.interval,
            "count": len(results),
            "results": results,
            "timestamp": utils.time_stamp(),
        },
        status_code=200,
    )
