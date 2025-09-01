from datetime import datetime
from typing import Any, Dict, List
import psutil
from collections import Counter
import time

import re
import asyncio
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
# -----------------------------------------

running: bool = False
interval: float = 5.0                   # Default interval in seconds
process_names: List[str] = []           # names/partials to watch


def time_stamp() -> str:
    """
    Return timestamp in the local timezone
    :return: Timestamp string, e.g. '2025-08-30T19:12:03+03:00'.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_names(raw) -> List[str]:
    """
    Normalize  list of process identifiers into a unique, ordered list of names.
    Accepts either:
      - A list of dicts like ``[{"name": "python"}, ...]``
      - A list of strings like ``["python", ...]``
    Behavior:
      - Trims whitespace
      - Drops empty values
      - De-duplicates case-insensitively while preserving the first-seen order
      - Returns an empty list if input is not a list
    :param raw: List of dicts with ``name`` keys or list of strings.
    :return: Ordered list of unique, non-empty process names (strings).
    """
    if not isinstance(raw, list):
        return []
    names: List[str] = []
    for item in raw:
        n = str(item.get("name", "") if isinstance(item, dict) else item).strip()
        if n:
            names.append(n)
    seen, out = set(), []
    for n in names:
        k = n.lower()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


def row_for_name(name: str) -> Dict[str, Any]:
    """
    Aggregate CPU and memory metrics across all PIDs whose process name
    equals `name` case-insensitively (EXACT match, no substrings).
    Example on Windows: use "chrome.exe" (not "chrome").
    """
    last_checked = time_stamp()
    target = (name or "").strip().lower()
    if not target:
        return {
            "name": name, "pid": None, "pids": [], "status": "not_found",
            "cpu_percent": 0.0, "cpu_percent_sum": 0.0,
            "memory_mb": 0.0, "last_checked": last_checked
        }

    procs: List[psutil.Process] = []
    for pi in psutil.process_iter(attrs=["pid", "name"]):
        try:
            nm = (pi.info.get("name") or "")
            if nm.lower() == target:  # <-- exact match, case-insensitive
                procs.append(psutil.Process(pi.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print(f"Error - {e}")
            continue

    if not procs:
        return {
            "name": name, "pid": None, "pids": [], "status": "not_found",
            "cpu_percent": 0.0, "cpu_percent_sum": 0.0,
            "memory_mb": 0.0, "last_checked": last_checked
        }

    alive: List[psutil.Process] = []
    for p in procs:
        try:
            p.cpu_percent(None)
            alive.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print(f"Error - {e}")
            pass

    time.sleep(0.1)
    total_cpu = 0.0
    total_mem = 0
    status_cnt = Counter()
    pid_list: List[int] = []
    for p in alive:
        try:
            total_cpu += float(p.cpu_percent(None) or 0.0)
            with p.oneshot():
                total_mem += p.memory_info().rss
                st = getattr(p, "status", lambda: "running")() or "running"
            status_cnt[st] += 1
            pid_list.append(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            print(f"Error - {e}")
            continue

    if not pid_list:
        return {
            "name": name, "pid": None, "pids": [], "status": "not_found",
            "cpu_percent": 0.0, "cpu_percent_sum": 0.0,
            "memory_mb": 0.0, "last_checked": last_checked
        }

    logical = max(1, psutil.cpu_count(logical=True) or 1)
    cpu_norm = min(100.0, total_cpu / logical)
    status = "running" if status_cnt.get("running") else status_cnt.most_common(1)[0][0]
    return {
        "name": name,
        "pid": pid_list[0],
        "pids": pid_list,
        "status": status,
        "cpu_percent": round(cpu_norm, 3),
        "cpu_percent_sum": round(total_cpu, 3),
        "memory_mb": round(total_mem / (1024 * 1024), 3),
        "last_checked": last_checked,
    }


async def api_start(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start monitoring with optional process list and interval override.
    Accepted payload keys:
      - ``processes``: list of dicts ``{"name": str}`` or list of strings to **replace** the monitored list.
    :param payload: Configuration dict (see keys above).
    :return: Dict containing ``ok``, ``timestamp``, ``interval``, ``processes`` (normalized), and ``is_running``.
    """
    global running, interval, process_names
    if "processes" in payload:
        names = normalize_names(payload["processes"])
        if names:
            process_names = names
    v = payload.get("interval", payload.get("update_interval"))
    if v is not None:
        try:
            interval = max(1.0, float(v))
        except (TypeError, ValueError) as e:
            print(f"Error - {e}")
            pass
    running = True
    return {
        "ok": True,
        "timestamp": time_stamp(),
        "interval": interval,
        "processes": [{"name": n} for n in process_names],
        "is_running": running,
    }


async def api_stop() -> Dict[str, Any]:
    """
    Stop monitoring.
    :return: Dict with ``ok``, ``timestamp``, and ``is_running`` (False).
    """
    global running
    running = False
    return {"ok": True, "timestamp": time_stamp(), "is_running": running}


async def update_interval(new_interval: float) -> Dict[str, Any]:
    """
    Update only the global polling interval.
    Validation:
      - Coerces to float
      - Minimum value is 1.0 seconds
      - On invalid input, returns ``{"ok": False, "error": "invalid interval"}`` and leaves the interval unchanged.
    :param new_interval: Desired polling interval in seconds.
    :return: Dict with ``ok``, the current ``interval`` (possibly clamped), and a ``timestamp``.
    """
    global interval
    try:
        interval = max(1.0, float(new_interval))
    except (TypeError, ValueError) as e:
        print(f"Error - {e}")
        return {"ok": False, "error": "invalid interval"}
    return {"ok": True, "interval": interval, "timestamp": time_stamp()}


async def configure_processes(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Replace the monitored process list.
    Expected payload:
      - ``processes``: list of dicts ``{"name": str}`` or list of strings. Values are normalized and de-duplicated.
    :param payload: Dict containing the ``processes`` key.
    :return: Dict with ``ok``, normalized ``processes``, and ``timestamp``.
    """
    global process_names
    if "processes" not in payload:
        return {"ok": False, "error": "missing processes"}
    process_names = normalize_names(payload["processes"])
    return {
        "ok": True,
        "processes": [{"name": n} for n in process_names],
        "timestamp": time_stamp(),
    }


def _split_names(raw: str) -> List[str]:
    """Split by commas/semicolons/newlines and trim."""
    parts = re.split(r"[,\n;]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


async def _render_index(request: Request, templates: Jinja2Templates) -> HTMLResponse:
    rows: List[Dict[str, Any]] = []
    if running and process_names:
        rows = [await asyncio.to_thread(row_for_name, n) for n in process_names]
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "PID Patrol",
            "running": running,
            "interval": interval,
            "process_names": process_names,
            "rows": rows,
        },
    )
