from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from csvlistmanager.app import Application
from csvlistmanager.errors import ConflictError, ReadOnlyError, ValidationError

from tests.helpers import install_example


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = install_example(self.root)
        self.store = self.root / "examples" / "nextact" / "nextact.csv"
        self.app = Application.from_config(self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def test_load_has_synthetic_rows_schema_and_lookups(self):
        loaded = self.app.load_repository("sample")
        self.assertEqual(len(loaded["rows"]), 4)
        self.assertIn("\r\n", loaded["rows"][0]["values"]["Detail"])
        self.assertEqual([item["value"] for item in loaded["lookups"]["Priority"]], ["A", "B", "C", "L", "N", "Z"])
        self.assertEqual(loaded["mode"], "editable")

    def test_save_accepts_unknown_dropdown_value_and_appends_log(self):
        loaded = self.app.load_repository()
        before = self.store.read_bytes()
        result = self.app.save(
            {
                "repository": "sample",
                "revision": loaded["revision"],
                "changes": [{"row": 0, "values": {"Priority": "Q", "Label": "Changed synthetically"}}],
                "new_rows": [],
            }
        )
        self.assertTrue(result["changed"])
        after = self.store.read_bytes()
        self.assertNotEqual(after, before)
        self.assertIn(b"Q,2026-11-16", after)
        log = self.app.read_log("sample")["rows"]
        self.assertEqual([row["event"] for row in log], ["cell_edit", "cell_edit", "save"])
        details = json.loads(log[-1]["details"])
        self.assertEqual(details["edit_count"], 2)

    def test_stale_revision_never_overwrites_external_edit(self):
        loaded = self.app.load_repository()
        before = self.store.read_bytes()
        self.store.write_bytes(before + b"B,,,home,External edit,\r\n")
        external = self.store.read_bytes()
        with self.assertRaises(ConflictError):
            self.app.save(
                {
                    "revision": loaded["revision"],
                    "changes": [{"row": 0, "values": {"Label": "Must not win"}}],
                }
            )
        self.assertEqual(self.store.read_bytes(), external)

    def test_read_only_mode_is_enforced_and_persisted(self):
        self.app.set_mode("sample", "read-only")
        loaded = self.app.load_repository()
        before = self.store.read_bytes()
        with self.assertRaises(ReadOnlyError):
            self.app.save(
                {
                    "revision": loaded["revision"],
                    "changes": [{"row": 0, "values": {"Label": "Blocked"}}],
                }
            )
        self.assertEqual(self.store.read_bytes(), before)
        restarted = Application.from_config(self.config)
        self.assertEqual(restarted.load_repository()["mode"], "read-only")

    def test_view_preferences_are_validated_and_persisted(self):
        self.assertEqual(self.app.load_repository()["view"], {"note_visible": True, "column_widths": {}})
        view = self.app.set_view_preferences(
            {"repository": "sample", "note_visible": False, "column_widths": {"Label": 275, "Detail": 400}}
        )
        self.assertEqual(view, {"note_visible": False, "column_widths": {"Label": 275, "Detail": 400}})
        restarted = Application.from_config(self.config)
        self.assertEqual(restarted.load_repository()["view"], view)
        for invalid in (
            {"repository": "sample", "note_visible": "yes", "column_widths": {}},
            {"repository": "sample", "note_visible": True, "column_widths": {"Missing": 200}},
            {"repository": "sample", "note_visible": True, "column_widths": {"Label": 20}},
            {"repository": "sample", "note_visible": True, "column_widths": {"Label": True}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.app.set_view_preferences(invalid)

    def test_selected_repository_and_row_addition(self):
        selected = self.app.select_repository("sample")
        self.assertEqual(selected["selected_repository"], "sample")
        loaded = self.app.load_repository()
        result = self.app.save(
            {
                "revision": loaded["revision"],
                "new_rows": [{"Priority": "B", "Tag": "not-in-lookup", "Label": "Appended"}],
            }
        )
        self.assertEqual(result["additions"], 1)
        reloaded = self.app.load_repository()
        self.assertEqual(reloaded["rows"][-1]["values"]["Label"], "Appended")
        self.assertEqual(reloaded["rows"][-1]["values"]["Tag"], "not-in-lookup")
        self.assertEqual(len(reloaded["rows"]), 5)

    def test_schema_change_adds_column_without_code_changes(self):
        schema_path = self.root / "examples" / "nextact" / "schema.yaml"
        with schema_path.open("a", encoding="utf-8") as handle:
            handle.write("  - name: Reviewed\n    type: text\n")
        with self.store.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[0].append("Reviewed")
        for row in rows[1:]:
            row.append("")
        with self.store.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(rows)

        restarted = Application.from_config(self.config)
        loaded = restarted.load_repository()
        self.assertEqual(loaded["schema"]["columns"][-1], {"name": "Reviewed", "type": "text"})
        result = restarted.save(
            {
                "revision": loaded["revision"],
                "changes": [{"row": 0, "values": {"Reviewed": "yes"}}],
            }
        )
        self.assertEqual(result["edits"], 1)
        self.assertEqual(restarted.load_repository()["rows"][0]["values"]["Reviewed"], "yes")


if __name__ == "__main__":
    unittest.main()
