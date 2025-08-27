import asyncio
import json
import psutil
from datetime import datetime

# --- internal module state (no classes, no events) ---
_clients = set()         # connected websockets
_processes = []          # list of {"name": "..."}
_interval = 5.0          # global interval (seconds)
_last_statuses = []      # latest snapshot for new clients
_running = False         # loop on/off
_task = ""             # asyncio.Task for the loop


def time_stamp():
    return datetime.now().isoformat(timespec="seconds")


def is_running():
    return _running


def get_interval():
    return _interval


def get_last_statuses():
    return list(_last_statuses)


def ws_add(ws):
    _clients.add(ws)


def ws_discard(ws):
    _clients.discard(ws)


async def ws_initial(ws):
    await ws.send_text(json.dumps({
        "type": "status_update",
        "is_running": _running,
        "interval": _interval,
        "processes": _last_statuses,
        "timestamp": time_stamp(),
    }))


async def broadcast(msg):
    if not _clients:
        return
    data = json.dumps(msg)
    for ws in tuple(_clients):
        try:
            await ws.send_text(data)
        except Exception:
            _clients.discard(ws)


def _sample_process(name):
    target = (name or "").lower()
    proc = None
    for p in psutil.process_iter():
        try:
            if target in (p.name() or "").lower():
                proc = p
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    ts = time_stamp()
    if not proc:
        return {
            "name": name, "pid": None, "status": "not_found",
            "cpu_percent": 0.0, "memory_mb": 0.0, "last_checked": ts
        }
    try:
        with proc.oneshot():
            pid = proc.pid
            cpu = proc.cpu_percent(interval=None) or 0.0
            mem = proc.memory_info().rss if proc.is_running() else 0
        return {
            "name": name, "pid": pid, "status": "running",
            "cpu_percent": float(cpu), "memory_mb": round(mem / 1024 / 1024, 2),
            "last_checked": ts
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return {
            "name": name, "pid": None, "status": "not_found",
            "cpu_percent": 0.0, "memory_mb": 0.0, "last_checked": ts
        }


async def _run_loop():
    global _last_statuses
    while _running:
        names = [p.get("name") for p in (_processes or []) if p and p.get("name")]
        updated = [_sample_process(n) for n in names] if names else []
        _last_statuses = updated
        await broadcast({"type": "process_update", "processes": updated, "timestamp": time_stamp()})
        await asyncio.sleep(float(_interval))


async def start_monitoring(processes, interval=None):
    global _processes, _interval, _running, _task, _last_statuses
    if _running:
        raise RuntimeError("Monitoring already running")

    _processes = [p for p in (processes or []) if isinstance(p, dict) and p.get("name")]
    if interval is not None:
        _interval = float(interval)

    now = time_stamp()
    _last_statuses = [
        {"name": p["name"], "pid": None, "status": "initializing",
         "cpu_percent": 0.0, "memory_mb": 0.0, "last_checked": now}
        for p in _processes
    ]
    _running = True
    _task = asyncio.create_task(_run_loop())
    await broadcast({
        "type": "monitoring_started",
        "config": {"processes": _processes, "update_interval": _interval},
        "timestamp": now,
    })


async def stop_monitoring():
    global _running, _task, _processes, _last_statuses
    if not _running:
        return
    _running = False
    _task = None
    _processes = []
    _last_statuses = []


async def update_config(processes=None, interval=None):
    global _processes, _interval
    if interval is not None:
        _interval = float(interval)
    if processes is not None:
        _processes = [p for p in processes if isinstance(p, dict) and p.get("name")]

    await broadcast({
        "type": "config_updated",
        "interval": _interval,
        "processes": _processes,
        "timestamp": time_stamp(),
    })
    return {"update_interval": _interval, "processes": len(_processes)}
