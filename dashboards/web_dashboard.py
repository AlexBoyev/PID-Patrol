import json
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from dashboards.utils import *

app = FastAPI(title="PID Patrol", version="0.1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "PID Patrol"})


@app.post("/api/monitoring/start")
async def api_start(cfg: dict = Body(...)):
    if is_running():
        return JSONResponse(status_code=400, content={"error": "Monitoring already running"})
    cfg = dict(cfg or {})
    processes = [p for p in cfg.get("processes", []) if isinstance(p, dict) and p.get("name")]
    interval = cfg.get("update_interval", None)
    await start_monitoring(processes=processes, interval=interval)
    return {"status": "started", "processes": len(processes), "interval": get_interval()}


@app.post("/api/monitoring/stop")
async def api_stop():
    if not is_running():
        return JSONResponse(status_code=400, content={"error": "Monitoring is not running"})
    await stop_monitoring()
    return {"status": "stopped"}


@app.post("/api/monitoring/update")
async def api_update(patch: dict = Body(...)):
    changes = await update_config(
        processes=patch.get("processes"),
        interval=patch.get("update_interval"),
    )
    return {"status": "updated", **changes}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_add(ws)
    try:
        await ws_initial(ws)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_discard(ws)
