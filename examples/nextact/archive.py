#!/usr/bin/env python3
"""Archive completed synthetic nextact rows.

Moves every row whose Priority is ``Z`` (synthetic "done") from the store
CSV into ``archive.csv`` beside it, appending to the archive when it exists.
CSVListManager supplies the paths through CSVLIST_STORE and
CSVLIST_REPOSITORY_DIR. Writes are atomic: the store is replaced only after
the new content is fully written, and the script leaves the store untouched
when nothing qualifies.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
import sys
import tempfile


def main() -> int:
    store = Path(os.environ["CSVLIST_STORE"])
    directory = Path(os.environ["CSVLIST_REPOSITORY_DIR"])
    archive = directory / "archive.csv"

    with store.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        print("Store is empty; nothing to archive.")
        return 0
    header, *records = rows
    try:
        priority = header.index("Priority")
    except ValueError:
        print("Store has no Priority column.", file=sys.stderr)
        return 1

    done = [row for row in records if len(row) > priority and row[priority] == "Z"]
    if not done:
        print("No completed rows to archive.")
        return 0
    remaining = [row for row in records if not (len(row) > priority and row[priority] == "Z")]

    archive_exists = archive.exists() and archive.stat().st_size > 0
    with archive.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        if not archive_exists:
            writer.writerow(header)
        writer.writerows(done)
        handle.flush()
        os.fsync(handle.fileno())

    descriptor, temporary = tempfile.mkstemp(dir=store.parent, prefix=store.name, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(header)
            writer.writerows(remaining)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, store)
    except BaseException:
        os.unlink(temporary)
        raise

    print(f"Archived {len(done)} row{'s' if len(done) != 1 else ''}; {len(remaining)} remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
