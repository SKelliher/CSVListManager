from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest

from csvlistmanager.config import Column, Schema
from csvlistmanager.csvfile import CSVDocument
from csvlistmanager.errors import ValidationError


SCHEMA = Schema(
    (
        Column("Name", "text"),
        Column("When", "date"),
        Column("Note", "note"),
    )
)


class CSVDocumentTests(unittest.TestCase):
    def parse(self, data: bytes) -> CSVDocument:
        return CSVDocument.parse(Path("synthetic.csv"), data)

    def test_quoted_commas_quotes_empty_fields_and_newlines(self):
        raw = (
            b'Name,When,Note\r\n'
            b'"Alpha, one",2026-01-01,"line 1\r\nline ""2"""\r\n'
            b'Beta,,""\r\n'
        )
        document = self.parse(raw)
        self.assertEqual(document.records[0].values[0], "Alpha, one")
        self.assertEqual(document.records[0].values[2], 'line 1\r\nline "2"')
        self.assertEqual(document.records[1].values[1:], ["", ""])

    def test_no_change_round_trip_is_byte_identical(self):
        raw = b'Name,When,Note\r\n"Alpha, one",2026-01-01,"line 1\r\nline 2"\r\n'
        document = self.parse(raw)
        plan = document.build_save(SCHEMA, [], [])
        self.assertFalse(plan.changed)
        self.assertEqual(plan.data, raw)
        self.assertEqual(plan.revision, document.revision)

    def test_cell_edit_changes_only_that_fields_bytes(self):
        raw = (
            b'Name,When,Note\r\n'
            b'"Alpha, one",2026-01-01,"line 1\r\nline ""2"""\r\n'
            b'Beta,2026-01-03,unchanged\r\n'
        )
        document = self.parse(raw)
        plan = document.build_save(SCHEMA, [{"row": 0, "values": {"When": "2026-02-02"}}], [])
        expected = raw.replace(b"2026-01-01", b"2026-02-02", 1)
        self.assertEqual(plan.data, expected)
        self.assertEqual(plan.edits, [{"row": 0, "column": "When", "old": "2026-01-01", "new": "2026-02-02"}])

    def test_note_edit_preserves_other_field_quoting(self):
        raw = b'Name,When,Note\n"Alpha, one",2026-01-01,"old\r\nnote"\n'
        plan = self.parse(raw).build_save(SCHEMA, [{"row": 0, "values": {"Note": "new\r\nnote"}}], [])
        self.assertEqual(plan.data, b'Name,When,Note\n"Alpha, one",2026-01-01,"new\r\nnote"\n')

    def test_new_rows_append_and_managed_columns_are_set(self):
        schema = Schema(
            (
                Column("Name", "text"),
                Column("Created", "datetime", on_create=True),
                Column("Updated", "datetime", on_update=True),
            )
        )
        raw = b"Name,Created,Updated\r\nOld,2020-01-01 00:00,2020-01-01 00:00"
        document = self.parse(raw)
        now = datetime(2030, 1, 2, 3, 4)
        plan = document.build_save(
            schema,
            [{"row": 0, "values": {"Name": "Changed"}}],
            [{"Name": "New", "Created": "ignored", "Updated": "ignored"}],
            now=now,
        )
        self.assertEqual(
            plan.data,
            b"Name,Created,Updated\r\n"
            b"Changed,2020-01-01 00:00,2030-01-02 03:04\r\n"
            b"New,2030-01-02 03:04,2030-01-02 03:04",
        )
        self.assertEqual(plan.additions[0]["row"], 1)

    def test_on_create_column_cannot_be_changed_later(self):
        schema = Schema((Column("Name", "text"), Column("Created", "datetime", on_create=True)))
        document = self.parse(b"Name,Created\nOld,2020-01-01 00:00\n")
        with self.assertRaisesRegex(ValidationError, "cannot be changed"):
            document.build_save(schema, [{"row": 0, "values": {"Created": "2030-01-01 00:00"}}], [])

    def test_rows_are_never_reordered_by_save(self):
        document = self.parse(b"Name,When,Note\nZ,,\nA,,\n")
        plan = document.build_save(SCHEMA, [], [{"Name": "Last", "When": "", "Note": ""}])
        self.assertEqual(plan.data, b"Name,When,Note\nZ,,\nA,,\nLast,,\n")

    def test_malformed_row_width_is_actionable(self):
        with self.assertRaisesRegex(ValidationError, "expected 3"):
            self.parse(b"Name,When,Note\nOnly,Two\n")

    def test_deletion_removes_only_that_records_bytes(self):
        raw = (
            b'Name,When,Note\r\n'
            b'"Alpha, one",2026-01-01,"line 1\r\nline ""2"""\r\n'
            b'Beta,2026-01-03,unchanged\r\n'
            b'Gamma,,\r\n'
        )
        document = self.parse(raw)
        plan = document.build_save(SCHEMA, [], [], [1])
        self.assertTrue(plan.changed)
        self.assertEqual(plan.deletions, [{"row": 1, "values": {"Name": "Beta", "When": "2026-01-03", "Note": "unchanged"}}])
        self.assertEqual(
            plan.data,
            b'Name,When,Note\r\n"Alpha, one",2026-01-01,"line 1\r\nline ""2"""\r\nGamma,,\r\n',
        )

    def test_deleting_first_last_and_all_rows(self):
        raw = b"Name,When,Note\nAlpha,,\nBeta,,\nGamma,,\n"
        first = self.parse(raw).build_save(SCHEMA, [], [], [0])
        self.assertEqual(first.data, b"Name,When,Note\nBeta,,\nGamma,,\n")
        last = self.parse(raw).build_save(SCHEMA, [], [], [2])
        self.assertEqual(last.data, b"Name,When,Note\nAlpha,,\nBeta,,\n")
        everything = self.parse(raw).build_save(SCHEMA, [], [], [0, 1, 2])
        self.assertEqual(everything.data, b"Name,When,Note\n")

    def test_deletion_without_trailing_newline(self):
        raw = b"Name,When,Note\nAlpha,,\nBeta,,"
        plan = self.parse(raw).build_save(SCHEMA, [], [], [1])
        self.assertEqual(plan.data, b"Name,When,Note\nAlpha,,\n")

    def test_deletion_combines_with_edits_and_additions(self):
        raw = b"Name,When,Note\nAlpha,,old\nBeta,,\n"
        plan = self.parse(raw).build_save(
            SCHEMA,
            [{"row": 1, "values": {"Note": "edited"}}],
            [{"Name": "New", "When": "", "Note": ""}],
            [0],
        )
        self.assertEqual(plan.data, b"Name,When,Note\nBeta,,edited\nNew,,\n")
        self.assertEqual(plan.additions[0]["row"], 1)  # index in the saved file
        self.assertEqual(len(plan.deletions), 1)

    def test_deletion_validation(self):
        document = self.parse(b"Name,When,Note\nAlpha,,\n")
        with self.assertRaisesRegex(ValidationError, "out of range"):
            document.build_save(SCHEMA, [], [], [1])
        with self.assertRaisesRegex(ValidationError, "more than once"):
            document.build_save(SCHEMA, [], [], [0, 0])
        with self.assertRaisesRegex(ValidationError, "marked for deletion"):
            document.build_save(SCHEMA, [{"row": 0, "values": {"Note": "x"}}], [], [0])
        with self.assertRaisesRegex(ValidationError, "integer row index"):
            document.build_save(SCHEMA, [], [], ["0"])


if __name__ == "__main__":
    unittest.main()
