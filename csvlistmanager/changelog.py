"""Append-only CSV change logs."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .errors import ValidationError


HEADER = ["timestamp", "event", "repository", "details"]


class ChangeLog:
    def __init__(self, path: Path, repository: str):
        self.path = path
        self.repository = repository
        self.validate()

    def validate(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        try:
            with self.path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, None)
        except (OSError, csv.Error) as error:
            raise ValidationError(f"Cannot read change log {self.path}: {error}") from error
        if header != HEADER:
            raise ValidationError(f"Change log {self.path} has an invalid header; expected {HEADER!r}")

    def append_many(self, event_entries: list[tuple[str, dict[str, Any]]]) -> None:
        if not event_entries:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        needs_header = not self.path.exists() or self.path.stat().st_size == 0
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with self.path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\r\n")
                if needs_header:
                    writer.writerow(HEADER)
                for event, details in event_entries:
                    writer.writerow(
                        [timestamp, event, self.repository, json.dumps(details, ensure_ascii=False, separators=(",", ":"))]
                    )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise ValidationError(f"Cannot append change log {self.path}: {error.strerror or error}") from error

    def read(self, limit: int = 500) -> list[dict[str, str]]:
        self.validate()
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            with self.path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, csv.Error) as error:
            raise ValidationError(f"Cannot read change log {self.path}: {error}") from error
        return rows[-limit:] if limit else rows
