import uvicorn
import threading
import asyncio
import json

from urllib import request, parse, error
HOST = "127.0.0.1"
PORT = 80
timeout = 3


class UvicornServerManager:
    """
    Run a Uvicorn server in a background thread for tests.
    """

    def __init__(self, app, host, port):
        """
        Set up the manager with the app and bind address.

        :params app: The ASGI/FastAPI app to serve.
        :params host: Host/IP to bind the server to.
        :params port: TCP port to listen on.
        :return: None
        :raise: None
        """
        self.app = app
        self.host = host
        self.port = port
        self.thread = None
        self.server = None
        self.is_running = threading.Event()

    def run(self):
        """
        Run uvicorn in this thread until it stops.

        :params: None
        :return: None
        :raise: Exception on unexpected uvicorn/asyncio failure.
        """
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="error", access_log=False)
        self.server = uvicorn.Server(config)
        self.is_running.set()
        asyncio.run(self.server.serve())

    def start(self):
        """
        Start the server in a daemon thread and wait briefly for readiness.

        :params: None
        :return: None
        :raise: TimeoutError if the server wasn't ready in time.
        """
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        # Wait for the server to be ready before proceeding
        if not self.is_running.wait(5):
            raise TimeoutError("Server failed to start")

    def stop(self):
        """
        Ask the server to exit and join the thread.

        :params: None
        :return: None
        :raise: RuntimeError if the server was never started.
               AssertionError if the thread failed to terminate in time.
        """
        if not self.server:
            raise RuntimeError("Server was not started")
        self.server.should_exit = True
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), "Server thread did not terminate"


def _post_json(path: str, payload: dict):
    """
    POST JSON to the app and parse the JSON response.

    :params path: Endpoint path starting with '/' (e.g., '/ui/start').
    :params payload: JSON-serializable body to send.
    :return: (status_code: int, data: dict) parsed from the response.
    :raise: urllib.error.HTTPError for non-2xx responses,
            urllib.error.URLError for network issues,
            json.JSONDecodeError if the body isn't valid JSON.
    """
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"http://{HOST}:{PORT}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
        return r.getcode(), json.loads(body)


def _get_json(path: str):
    """
    GET JSON from the app and parse the JSON response.

    :params path: Endpoint path starting with '/' (e.g., '/ui/results').
    :return: (status_code: int, data: dict) where data may be {} for 204/empty.
    :raise: urllib.error.HTTPError for non-2xx responses,
            urllib.error.URLError for network issues,
            json.JSONDecodeError if the body isn't valid JSON.
    """
    req = request.Request(f"http://{HOST}:{PORT}{path}", method="GET")
    with request.urlopen(req, timeout=3.0) as r:
        status = r.getcode()
        raw = r.read()  # may be empty for 204
        if status == 204 or not raw or not raw.strip():
            return status, {}
        return status, json.loads(raw.decode("utf-8"))
