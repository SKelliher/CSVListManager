"""Script runner behaviour: success, failure, logging, and store reload."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from csvlistmanager.app import Application
from csvlistmanager.errors import NotFoundError

from tests.helpers import install_example


def read_store(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


class ScriptRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = install_example(self.root)
        self.directory = self.root / "examples" / "nextact"
        self.store = self.directory / "nextact.csv"
        self.log = self.directory / "changes.csv"
        self.app = Application.from_config(self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def log_events(self) -> list[tuple[str, dict]]:
        with self.log.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [(row["event"], json.loads(row["details"])) for row in rows]

    def add_script(self, name: str, command: list[str]) -> None:
        text = self.config.read_text(encoding="utf-8")
        marker = "        description: Move completed (priority Z) rows into archive.csv"
        self.assertIn(marker, text)
        extra = "\n      - name: " + name + "\n        command: [" + ", ".join(command) + "]\n"
        self.config.write_text(text.replace(marker, marker + extra), encoding="utf-8")
        self.app = Application.from_config(self.config)

    def add_python_script(self, name: str, code: str) -> None:
        (self.directory / f"{name}.py").write_text(code, encoding="utf-8")
        self.add_script(name, ["python3", f"{name}.py"])

    def test_archive_moves_completed_rows_and_logs_the_run(self):
        before = read_store(self.store)
        self.assertEqual(len(before), 5)
        result = self.app.run_script("sample", "archive")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("Archived 1 row", result["output"])

        after = read_store(self.store)
        self.assertEqual(len(after), 4)
        self.assertNotIn("Z", [row[0] for row in after[1:]])
        self.assertEqual(after[1:], before[1:4])  # remaining rows untouched and in order

        archive = read_store(self.directory / "archive.csv")
        self.assertEqual(archive[0], before[0])
        self.assertEqual(len(archive), 2)
        self.assertEqual(archive[1][0], "Z")

        events = self.log_events()
        self.assertEqual(events[-1][0], "script_run")
        self.assertEqual(events[-1][1]["script"], "archive")
        self.assertEqual(events[-1][1]["status"], "success")

        # A second run archives nothing and leaves both files stable.
        store_bytes = self.store.read_bytes()
        second = self.app.run_script("sample", "archive")
        self.assertEqual(second["status"], "success")
        self.assertIn("No completed rows", second["output"])
        self.assertEqual(self.store.read_bytes(), store_bytes)

    def test_reload_after_run_reflects_script_changes(self):
        before_revision = self.app.load_repository("sample")["revision"]
        result = self.app.run_script("sample", "archive")
        self.assertNotEqual(result["revision"], before_revision)
        loaded = self.app.load_repository("sample")
        self.assertEqual(loaded["revision"], result["revision"])
        self.assertEqual(len(loaded["rows"]), 3)

    def test_failing_script_reports_failure_and_logs_it(self):
        self.add_python_script("explode", "import sys\nprint('boom')\nsys.exit(3)\n")
        store_bytes = self.store.read_bytes()
        result = self.app.run_script("sample", "explode")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 3)
        self.assertEqual(result["detail"], "Exited with status 3")
        self.assertIn("boom", result["output"])
        self.assertEqual(self.store.read_bytes(), store_bytes)
        events = self.log_events()
        self.assertEqual(events[-1][1]["status"], "failed")
        self.assertEqual(events[-1][1]["exit_code"], 3)

    def test_successful_script_that_corrupts_the_store_is_a_failure(self):
        self.add_python_script("corrupt", "import os\nwith open(os.environ['CSVLIST_STORE'], 'w') as handle:\n    handle.write('not,the,schema\\n')\n")
        result = self.app.run_script("sample", "corrupt")
        self.assertEqual(result["status"], "failed")
        self.assertIn("no longer loads", result["detail"])
        events = self.log_events()
        self.assertEqual(events[-2][1]["status"], "success")
        self.assertEqual(events[-1][1]["status"], "failed")
        self.assertIn("no longer loads", events[-1][1]["detail"])

    def test_missing_command_is_a_failure(self):
        self.add_script("missing", ["definitely-not-a-real-command-csvlistmanager"])
        result = self.app.run_script("sample", "missing")
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["exit_code"])
        self.assertIn("Command not found", result["detail"])

    def test_unknown_script_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.app.run_script("sample", "nope")

    def test_script_receives_repository_paths(self):
        self.add_python_script(
            "paths",
            "import os\nprint(os.environ['CSVLIST_STORE'])\nprint(os.environ['CSVLIST_REPOSITORY_DIR'])\n",
        )
        result = self.app.run_script("sample", "paths")
        self.assertEqual(result["status"], "success")
        self.assertIn(str(self.store), result["output"])
        self.assertIn(str(self.directory), result["output"])


if __name__ == "__main__":
    unittest.main()
