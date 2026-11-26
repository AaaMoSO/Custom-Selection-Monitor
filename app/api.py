"""本地控制 API：把「继续监控」暴露成 HTTP 接口，方便其他程序/Agent 调用。

设计：
* 只绑定 ``127.0.0.1``，不对外网开放；
* ``GET  /api/status`` 查询当前状态；
* ``POST /api/resume`` 继续监控（仅在「已暂停」时有效）；
* 动作通过 Qt 信号切回主线程执行，HTTP 线程不直接碰 QTimer；
* 启动后写 ``data/control-api.json``，其他程序可据此发现实际端口。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal

SERVICE = "pause-recognition-control"


class ControlRequest:
    """一次跨线程的控制请求：HTTP 线程发信号，主线程填结果。"""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.status = 500
        self.payload: dict = {"ok": False, "error": "no response"}
        self.done = threading.Event()

    def respond(self, status: int, payload: dict) -> None:
        self.status = int(status)
        self.payload = payload
        self.done.set()


class ControlBridge(QObject):
    """把 HTTP 线程的请求排队到主线程执行。"""

    requested = Signal(object)

    def call(self, kind: str, timeout: float = 3.0) -> tuple[int, dict]:
        request = ControlRequest(kind)
        self.requested.emit(request)
        if not request.done.wait(timeout):
            return 503, {"ok": False, "error": "main window is not responding"}
        return request.status, request.payload


class ControlApiServer:
    """极简 HTTP 服务；``dispatch(kind) -> (status, payload)`` 由调用方提供。"""

    def __init__(
        self,
        dispatch,
        host: str = "127.0.0.1",
        port: int = 8765,
        discovery_path: str | Path | None = None,
        attempts: int = 10,
    ) -> None:
        self._dispatch = dispatch
        self._host = host
        self._port = int(port)
        self._attempts = max(1, int(attempts))
        self._discovery = Path(discovery_path) if discovery_path else None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._base_url = ""

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> str | None:
        """启动服务；端口被占用时顺延尝试，全部失败返回 None。"""
        handler = _make_handler(self._dispatch)
        for offset in range(self._attempts):
            candidate = self._port + offset
            try:
                httpd = ThreadingHTTPServer((self._host, candidate), handler)
            except OSError:
                continue
            httpd.daemon_threads = True
            self._httpd = httpd
            self._port = int(httpd.server_address[1])
            self._base_url = f"http://{self._host}:{self._port}"
            self._thread = threading.Thread(
                target=httpd.serve_forever, name="control-api", daemon=True
            )
            self._thread.start()
            self._write_discovery()
            return self._base_url
        return None

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._remove_discovery()
        self._base_url = ""

    def _write_discovery(self) -> None:
        if self._discovery is None:
            return
        try:
            self._discovery.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "service": SERVICE,
                "baseUrl": self._base_url,
                "port": self._port,
                "pid": os.getpid(),
                "status": f"{self._base_url}/api/status",
                "resume": f"{self._base_url}/api/resume",
            }
            self._discovery.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def _remove_discovery(self) -> None:
        if self._discovery is None:
            return
        try:
            self._discovery.unlink(missing_ok=True)
        except OSError:
            pass


def _make_handler(dispatch):
    class _Handler(BaseHTTPRequestHandler):
        server_version = "PauseRecognitionControl/1.0"

        def log_message(self, *args):  # 静音，避免刷屏
            pass

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/api", "/api/"):
                self._json(
                    200,
                    {
                        "ok": True,
                        "service": SERVICE,
                        "endpoints": {
                            "status": "GET /api/status",
                            "resume": "POST /api/resume",
                        },
                    },
                )
            elif path == "/api/status":
                self._result("status")
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):  # noqa: N802
            if self._reject_cross_origin():
                return
            path = urlparse(self.path).path
            if path == "/api/resume":
                self._result("resume")
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def _reject_cross_origin(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return False
            self._json(
                403,
                {
                    "ok": False,
                    "error": "cross-origin calls are refused; call from a local client",
                },
            )
            return True

        def _result(self, kind: str) -> None:
            try:
                status, payload = dispatch(kind)
            except Exception as exc:  # 任何异常都转成 JSON
                status, payload = 500, {"ok": False, "error": str(exc)}
            self._json(status, payload)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(int(status))
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    return _Handler
