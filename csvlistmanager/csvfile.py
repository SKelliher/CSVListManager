"""RFC 4180 CSV parsing and revision-checked, byte-preserving save plans."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import io
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any

from .config import Schema
from .errors import ValidationError


def revision_of(data: bytes) -> str:
    return sha256(data).hexdigest()


@dataclass(frozen=True)
class Record:
    values: list[str]
    start: int
    content_end: int
    end: int
    field_spans: list[tuple[int, int]]


@dataclass(frozen=True)
class SavePlan:
    data: bytes
    revision: str
    edits: list[dict[str, Any]]
    additions: list[dict[str, Any]]
    deletions: list[dict[str, Any]]

    @property
    def changed(self) -> bool:
        return bool(self.edits or self.additions or self.deletions)


@dataclass(frozen=True)
class CSVDocument:
    path: Path
    data: bytes
    text: str
    header: Record
    records: list[Record]

    @property
    def revision(self) -> str:
        return revision_of(self.data)

    @property
    def newline(self) -> str:
        for record in (self.header, *self.records):
            ending = self.text[record.content_end : record.end]
            if ending:
                return ending
        return "\r\n"

    @property
    def has_final_newline(self) -> bool:
        return self.text.endswith(("\r", "\n"))

    @classmethod
    def load(cls, path: Path) -> "CSVDocument":
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ValidationError(f"Cannot read CSV store {path}: {error.strerror or error}") from error
        return cls.parse(path, data)

    @classmethod
    def parse(cls, path: Path, data: bytes) -> "CSVDocument":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValidationError(f"CSV store {path} must be UTF-8 (byte {error.start})") from error
        try:
            parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error as error:
            raise ValidationError(f"Invalid CSV in {path}: {error}") from error
        records = _records(text)
        if len(parsed) != len(records):
            raise ValidationError(f"Invalid CSV in {path}: blank or malformed records are not supported")
        populated: list[Record] = []
        for row_number, (values, record) in enumerate(zip(parsed, records), 1):
            if len(values) != len(record.field_spans):
                raise ValidationError(f"Invalid CSV in {path}: could not map fields on record {row_number}")
            populated.append(Record(values, record.start, record.content_end, record.end, record.field_spans))
        if not populated:
            raise ValidationError(f"CSV store {path} has no header row")
        header = populated[0]
        if any(not name for name in header.values):
            raise ValidationError(f"CSV store {path} has an empty header name")
        if len(set(header.values)) != len(header.values):
            raise ValidationError(f"CSV store {path} has duplicate header names")
        width = len(header.values)
        for row_number, record in enumerate(populated[1:], 2):
            if len(record.values) != width:
                raise ValidationError(
                    f"CSV store {path} record {row_number} has {len(record.values)} fields; expected {width}"
                )
        return cls(path, data, text, header, populated[1:])

    def validate_header(self, schema: Schema) -> None:
        expected = list(schema.names)
        if self.header.values != expected:
            raise ValidationError(
                f"CSV header in {self.path} does not match schema. Expected {expected!r}, found {self.header.values!r}"
            )

    def rows(self) -> list[dict[str, Any]]:
        return [
            {"index": index, "values": dict(zip(self.header.values, record.values))}
            for index, record in enumerate(self.records)
        ]

    def build_save(
        self,
        schema: Schema,
        changes: list[dict[str, Any]],
        new_rows: list[dict[str, Any]],
        deletions: list[int] | None = None,
        now: datetime | None = None,
    ) -> SavePlan:
        self.validate_header(schema)
        deletions = deletions if deletions is not None else []
        if not isinstance(changes, list) or not isinstance(new_rows, list) or not isinstance(deletions, list):
            raise ValidationError("changes, new_rows, and deletions must be lists")
        deleted_indexes: set[int] = set()
        for deletion in deletions:
            if not isinstance(deletion, int) or isinstance(deletion, bool):
                raise ValidationError("Each deletion needs an integer row index")
            if deletion < 0 or deletion >= len(self.records):
                raise ValidationError(f"Deletion row index {deletion} is out of range")
            if deletion in deleted_indexes:
                raise ValidationError(f"Row {deletion} is deleted more than once")
            deleted_indexes.add(deletion)
        timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
        positions = {column.name: index for index, column in enumerate(schema.columns)}
        created = {column.name for column in schema.columns if column.on_create}
        updated = {column.name for column in schema.columns if column.on_update}
        edits: list[dict[str, Any]] = []
        replacements: dict[int, dict[int, str]] = {}
        seen_rows: set[int] = set()

        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("row"), int) or isinstance(change.get("row"), bool):
                raise ValidationError("Each change needs an integer row index")
            row_index = change["row"]
            if row_index < 0 or row_index >= len(self.records):
                raise ValidationError(f"Row index {row_index} is out of range")
            if row_index in deleted_indexes:
                raise ValidationError(f"Row {row_index} is marked for deletion; remove the deletion before editing it")
            if row_index in seen_rows:
                raise ValidationError(f"Row {row_index} appears in more than one change")
            seen_rows.add(row_index)
            values = change.get("values")
            if not isinstance(values, dict):
                raise ValidationError(f"Change for row {row_index} needs a values object")
            unknown = sorted(set(values) - set(positions))
            if unknown:
                raise ValidationError(f"Unknown column(s) for row {row_index}: {', '.join(unknown)}")
            record = self.records[row_index]
            row_replacements: dict[int, str] = {}
            for name, value in values.items():
                if not isinstance(value, str):
                    raise ValidationError(f"Value for {name} on row {row_index} must be a string")
                position = positions[name]
                old = record.values[position]
                if old == value:
                    continue
                if name in created:
                    raise ValidationError(f"Managed on_create column {name} cannot be changed after row creation")
                row_replacements[position] = value
                edits.append({"row": row_index, "column": name, "old": old, "new": value})
            if row_replacements:
                for name in updated:
                    position = positions[name]
                    old = record.values[position]
                    current = row_replacements.get(position, old)
                    if current != timestamp:
                        row_replacements[position] = timestamp
                        edits.append({"row": row_index, "column": name, "old": current, "new": timestamp, "managed": True})
            replacements[row_index] = row_replacements

        # Reassemble the store record by record: deleted rows drop out, edited
        # rows are rebuilt from their original spans, and every untouched byte
        # (quoting, line endings, order) is preserved.
        body_start = self.records[0].start if self.records else self.header.end
        pieces = [self.text[:body_start]]
        for row_index, record in enumerate(self.records):
            if row_index in deleted_indexes:
                continue
            raw_record = self.text[record.start : record.content_end]
            for position in sorted(replacements.get(row_index, {}), reverse=True):
                start, end = record.field_spans[position]
                raw_record = (
                    raw_record[: start - record.start]
                    + _field(replacements[row_index][position])
                    + raw_record[end - record.start :]
                )
            pieces.append(raw_record)
            pieces.append(self.text[record.content_end : record.end])
        tail_start = self.records[-1].end if self.records else self.header.end
        pieces.append(self.text[tail_start:])
        text = "".join(pieces)

        additions: list[dict[str, Any]] = []
        serialized_rows: list[str] = []
        for offset, values in enumerate(new_rows):
            if not isinstance(values, dict):
                raise ValidationError("Each new row must be an object keyed by column name")
            unknown = sorted(set(values) - set(positions))
            if unknown:
                raise ValidationError(f"Unknown column(s) in new row: {', '.join(unknown)}")
            row_values = [""] * len(schema.columns)
            for name, value in values.items():
                if not isinstance(value, str):
                    raise ValidationError(f"Value for {name} in a new row must be a string")
                row_values[positions[name]] = value
            for name in created | updated:
                row_values[positions[name]] = timestamp
            serialized_rows.append(_row(row_values, self.newline))
            additions.append({"row": len(self.records) - len(deleted_indexes) + offset, "values": dict(zip(schema.names, row_values))})

        if serialized_rows:
            separator = "" if not text or text.endswith(("\r", "\n")) else self.newline
            suffix = self.newline if text.endswith(("\r", "\n")) or not text else ""
            text = text + separator + self.newline.join(serialized_rows) + suffix

        deletion_entries = [
            {"row": row_index, "values": dict(zip(schema.names, self.records[row_index].values))}
            for row_index in sorted(deleted_indexes)
        ]
        if not edits and not additions and not deletion_entries:
            return SavePlan(self.data, self.revision, [], [], [])
        data = text.encode("utf-8")
        return SavePlan(data, revision_of(data), edits, additions, deletion_entries)


def _records(text: str) -> list[Record]:
    records: list[Record] = []
    field_spans: list[tuple[int, int]] = []
    record_start = 0
    field_start = 0
    in_quotes = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_quotes:
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = False
            index += 1
            continue
        if char == '"' and index == field_start:
            in_quotes = True
        elif char == ",":
            field_spans.append((field_start, index))
            field_start = index + 1
        elif char in "\r\n":
            field_spans.append((field_start, index))
            content_end = index
            if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 1
            end = index + 1
            records.append(Record([], record_start, content_end, end, field_spans))
            field_spans = []
            record_start = end
            field_start = end
        index += 1
    if in_quotes:
        # csv.reader supplies the more useful parse error before this is used.
        return []
    if record_start < len(text) or field_spans or field_start > record_start:
        field_spans.append((field_start, len(text)))
        records.append(Record([], record_start, len(text), len(text), field_spans))
    return records


def _field(value: str) -> str:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="").writerow([value])
    return output.getvalue()


def _row(values: list[str], newline: str) -> str:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator=newline).writerow(values)
    result = output.getvalue()
    return result[: -len(newline)] if newline else result


def atomic_replace(path: Path, data: bytes) -> None:
    """Replace path atomically, retaining a backup if the operation fails."""
    temporary_name: str | None = None
    backup = path.with_name(path.name + ".bak")
    replaced = False
    try:
        shutil.copy2(path, backup)
        mode = stat.S_IMODE(path.stat().st_mode)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
        temporary_name = None
        replaced = True
    except Exception:
        if replaced and backup.exists():
            shutil.copy2(backup, path)
        raise
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        if replaced and backup.exists():
            backup.unlink()
        elif not replaced and backup.exists():
            # Keep the failure backup only when the original is unavailable.
            if path.exists():
                backup.unlink()
