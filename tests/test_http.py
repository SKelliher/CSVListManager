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

    def test_browser_interface_is_served_with_local_only_assets(self):
        for path, content_type, marker in (
            ("/", "text/html; charset=utf-8", b"CSVListManager"),
            ("/app.js", "text/javascript; charset=utf-8", b"loadRepositories"),
            ("/model.js", "text/javascript; charset=utf-8", b"sortedRows"),
            ("/styles.css", "text/css; charset=utf-8", b"position: sticky"),
        ):
            with self.subTest(path=path), urlopen(self.base + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], content_type)
                self.assertIn(marker, response.read())
                self.assertEqual(response.headers["Content-Security-Policy"].split(";")[0], "default-src 'self'")

    def test_unknown_interface_asset_is_404(self):
        self.request("GET", "/missing.js", expected=404)

    def test_view_preferences_over_http(self):
        view = self.request(
            "POST",
            "/api/preferences/view",
            {"repository": "sample", "note_visible": False, "column_widths": {"Next": 180}},
        )
        self.assertFalse(view["note_visible"])
        self.assertEqual(view["column_widths"], {"Next": 180})
        loaded = self.request("GET", "/api/repository")
        self.assertEqual(loaded["view"], view)
        error = self.request(
            "POST",
            "/api/preferences/view",
            {"repository": "sample", "note_visible": True, "column_widths": {"Next": 1000}},
            expected=400,
        )
        self.assertEqual(error["error"]["code"], "validation_error")

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

    def test_save_with_deletion_over_http(self):
        loaded = self.request("GET", "/api/repository")
        row_count = len(loaded["rows"])
        saved = self.request(
            "POST",
            "/api/save",
            {"revision": loaded["revision"], "deletions": [1]},
        )
        self.assertEqual(saved["deletions"], 1)
        reloaded = self.request("GET", "/api/repository")
        self.assertEqual(len(reloaded["rows"]), row_count - 1)
        labels = [row["values"]["Label"] for row in reloaded["rows"]]
        self.assertNotIn("Review, synthetic notes", labels)
        log = self.request("GET", "/api/log")
        events = [row["event"] for row in log["rows"]]
        self.assertEqual(events, ["row_delete", "save"])
        self.assertIn('"deletion_count":1', log["rows"][-1]["details"])

    def test_save_deletion_validation_over_http(self):
        loaded = self.request("GET", "/api/repository")
        error = self.request(
            "POST",
            "/api/save",
            {"revision": loaded["revision"], "changes": [{"row": 0, "values": {"Label": "x"}}], "deletions": [0]},
            expected=400,
        )
        self.assertIn("marked for deletion", error["error"]["message"])

    def test_script_run_and_log_over_http(self):
        loaded = self.request("GET", "/api/repository")
        self.assertEqual(loaded["repository"]["scripts"][0]["name"], "archive")
        result = self.request("POST", "/api/scripts/run", {"repository": "sample", "script": "archive"})
        self.assertEqual(result["status"], "success")
        reloaded = self.request("GET", "/api/repository?repository=sample")
        self.assertEqual(reloaded["revision"], result["revision"])
        self.assertEqual(len(reloaded["rows"]), 3)
        log = self.request("GET", "/api/log")
        self.assertEqual(log["rows"][-1]["event"], "script_run")
        self.assertIn('"status":"success"', log["rows"][-1]["details"])

    def test_unknown_script_is_404(self):
        error = self.request("POST", "/api/scripts/run", {"script": "nope"}, expected=404)
        self.assertEqual(error["error"]["code"], "not_found")

    def test_unknown_repository_is_404(self):
        error = self.request("GET", "/api/repository?repository=missing", expected=404)
        self.assertEqual(error["error"]["code"], "not_found")

    def test_non_loopback_binding_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_server(self.app, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
