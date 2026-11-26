import json
import tempfile
import unittest
from pathlib import Path
from urllib import error, request

from app.api import SERVICE, ControlApiServer


class ControlApiTests(unittest.TestCase):
    def setUp(self):
        self.calls: list[str] = []
        self.status = 200
        self.resume_status = 200

        def dispatch(kind: str):
            self.calls.append(kind)
            if kind == "status":
                return self.status, {"ok": True, "state": "paused", "unchanged": 6}
            if kind == "resume":
                return self.resume_status, {
                    "ok": self.resume_status == 200,
                    "state": "monitoring" if self.resume_status == 200 else "idle",
                }
            return 404, {"ok": False, "error": "unknown"}

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.discovery = Path(self._tmp.name) / "control-api.json"
        self.server = ControlApiServer(
            dispatch, port=0, discovery_path=self.discovery, attempts=1
        )
        self.base_url = self.server.start()
        self.assertIsNotNone(self.base_url)
        self.addCleanup(self.server.stop)

    def _request(self, method: str, path: str, headers: dict | None = None):
        payload = b"{}" if method == "POST" else None
        req = request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={"content-type": "application/json", **(headers or {})},
        )
        try:
            with request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_descriptor(self):
        status, payload = self._request("GET", "/api")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], SERVICE)
        self.assertIn("resume", payload["endpoints"])

    def test_status(self):
        status, payload = self._request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "paused")
        self.assertIn("status", self.calls)

    def test_resume(self):
        status, payload = self._request("POST", "/api/resume")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("resume", self.calls)

    def test_resume_conflict(self):
        self.resume_status = 409
        status, payload = self._request("POST", "/api/resume")
        self.assertEqual(status, 409)
        self.assertFalse(payload["ok"])

    def test_unknown_path(self):
        status, _ = self._request("GET", "/api/nope")
        self.assertEqual(status, 404)

    def test_cross_origin_rejected(self):
        status, payload = self._request(
            "POST", "/api/resume", headers={"Origin": "http://evil.example"}
        )
        self.assertEqual(status, 403)
        self.assertIn("cross-origin", payload["error"])
        self.assertNotIn("resume", self.calls)

    def test_discovery_file(self):
        self.assertTrue(self.discovery.exists())
        data = json.loads(self.discovery.read_text(encoding="utf-8"))
        self.assertEqual(data["service"], SERVICE)
        self.assertEqual(data["baseUrl"], self.base_url)
        self.assertEqual(data["port"], self.server.port)

        self.server.stop()
        self.assertFalse(self.discovery.exists())


if __name__ == "__main__":
    unittest.main()
