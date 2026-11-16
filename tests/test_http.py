from __future__ import annotations

from http.client import HTTPResponse
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from csvlistmanager.app import Application
from csvlistmanager.errors import ValidationError
from csvlistmanager.server import make_server

from tests.helpers import install_example


class HTTPServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = Application.from_config(install_example(self.root))
        self.server = make_server(self.app, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def request(self, method: str, path: str, payload=None, expected: int = 200):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            response: HTTPResponse
            with urlopen(request, timeout=5) as response:
                status = response.status
                body = json.load(response)
        except HTTPError as error:
            status = error.code
            body = json.load(error)
        self.assertEqual(status, expected, body)
        return body

    def test_health_repositories_and_load(self):
        self.assertEqual(self.request("GET", "/api/health"), {"status": "ok"})
        repositories = self.request("GET", "/api/repositories")
        self.assertEqual(repositories["repositories"][0]["id"], "sample")
        loaded = self.request("GET", "/api/repository?repository=sample")
        self.assertEqual(len(loaded["rows"]), 4)

    def test_save_mode_and_log_over_http(self):
        loaded = self.request("GET", "/api/repository")
        saved = self.request(
            "POST",
            "/api/save",
            {
                "revision": loaded["revision"],
                "changes": [{"row": 1, "values": {"Next": "2027-01-02"}}],
            },
        )
        self.assertEqual(saved["edits"], 1)
        log = self.request("GET", "/api/log")
        self.assertEqual([row["event"] for row in log["rows"]], ["cell_edit", "save"])
        self.request("POST", "/api/preferences/mode", {"repository": "sample", "mode": "read-only"})
        loaded = self.request("GET", "/api/repository")
        error = self.request(
            "POST",
            "/api/save",
            {
                "revision": loaded["revision"],
                "changes": [{"row": 1, "values": {"Next": "2028-01-01"}}],
            },
            expected=403,
        )
        self.assertEqual(error["error"]["code"], "read_only")

    def test_unknown_repository_is_404(self):
        error = self.request("GET", "/api/repository?repository=missing", expected=404)
        self.assertEqual(error["error"]["code"], "not_found")

    def test_non_loopback_binding_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_server(self.app, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
