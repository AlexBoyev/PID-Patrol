"""
driver.py — Entry point to start the PID Patrol FastAPI app with Uvicorn.

Usage:
    python -m dashboards.driver
    # or
    python dashboards/driver.py
Note:
    Binding to port 80 may require administrator/root privileges or be in use.
    If you hit a permission error, try a higher port (e.g., 8000) or run with elevated privileges.
"""

import uvicorn
from dashboards.web_dashboard import app


def main(host: str = "127.0.0.1", port: int = 80) -> None:
    """
    Launch the FastAPI application using Uvicorn.
    :param host: Interface to bind (e.g., "127.0.0.1" for local only, "0.0.0.0" to listen on all interfaces).
    :param port: TCP port to listen on (port 80 may require admin/root privileges).
    """
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
