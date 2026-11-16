"""Narrow application operations behind the HTTP interface."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from .changelog import ChangeLog
from .config import AppConfig, Repository, load_config, load_schema, read_lookup
from .csvfile import CSVDocument, atomic_replace
from .errors import ConflictError, NotFoundError, ReadOnlyError, ValidationError
from .preferences import PreferenceStore


class Application:
    def __init__(self, config: AppConfig):
        self.config = config
        self._lock = threading.RLock()
        self.schemas = {}
        for repository in config.repositories.values():
            schema = load_schema(repository)
            document = CSVDocument.load(repository.store)
            document.validate_header(schema)
            for column in schema.columns:
                if column.type == "dropdown":
                    read_lookup(column)
            ChangeLog(repository.log, repository.id)
            self.schemas[repository.id] = schema
        self.preferences = PreferenceStore(config.preferences, list(config.repositories))

    @classmethod
    def from_config(cls, path: str | Path) -> "Application":
        return cls(load_config(path))

    def repository(self, repository_id: str | None) -> Repository:
        selected = repository_id or self.preferences.selected
        try:
            return self.config.repositories[selected]
        except KeyError as error:
            raise NotFoundError(f"Unknown repository {selected!r}") from error

    def list_repositories(self) -> dict[str, Any]:
        preferences = self.preferences.snapshot()
        return {
            "repositories": [repository.to_dict() for repository in self.config.repositories.values()],
            **preferences,
        }

    def select_repository(self, repository_id: Any) -> dict[str, Any]:
        if not isinstance(repository_id, str):
            raise ValidationError("repository must be a string")
        repository = self.repository(repository_id)
        return self.preferences.select(repository.id)

    def set_mode(self, repository_id: Any, mode: Any) -> dict[str, Any]:
        if not isinstance(mode, str) or mode not in {"editable", "read-only"}:
            raise ValidationError("mode must be 'editable' or 'read-only'")
        repository = self.repository(repository_id if isinstance(repository_id, str) else None)
        return self.preferences.set_mode(repository.id, mode)

    def set_view_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        repository_id = payload.get("repository")
        repository = self.repository(repository_id if isinstance(repository_id, str) else None)
        note_visible = payload.get("note_visible")
        column_widths = payload.get("column_widths")
        if not isinstance(note_visible, bool):
            raise ValidationError("note_visible must be true or false")
        if not isinstance(column_widths, dict):
            raise ValidationError("column_widths must be an object")
        schema_names = set(self.schemas[repository.id].names)
        for name, width in column_widths.items():
            if not isinstance(name, str) or name not in schema_names:
                raise ValidationError(f"Unknown column in column_widths: {name!r}")
            if not isinstance(width, int) or isinstance(width, bool) or not 80 <= width <= 600:
                raise ValidationError(f"Width for {name} must be an integer between 80 and 600")
        return self.preferences.set_view(repository.id, note_visible, column_widths)

    def load_repository(self, repository_id: str | None = None) -> dict[str, Any]:
        repository = self.repository(repository_id)
        schema = self.schemas[repository.id]
        document = CSVDocument.load(repository.store)
        document.validate_header(schema)
        lookups = {
            column.name: read_lookup(column)
            for column in schema.columns
            if column.type == "dropdown"
        }
        return {
            "repository": repository.to_dict(),
            "mode": self.preferences.mode(repository.id),
            "view": self.preferences.view(repository.id),
            "revision": document.revision,
            "schema": schema.to_dict(),
            "lookups": lookups,
            "rows": document.rows(),
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            repository = self.repository(payload.get("repository"))
            if self.preferences.mode(repository.id) == "read-only":
                raise ReadOnlyError(f"Repository {repository.id} is read-only; switch to editable mode before saving")
            expected_revision = payload.get("revision")
            if not isinstance(expected_revision, str):
                raise ValidationError("A revision string is required for save")
            document = CSVDocument.load(repository.store)
            document.validate_header(self.schemas[repository.id])
            if document.revision != expected_revision:
                raise ConflictError("The CSV file changed after it was loaded. Reload before saving; no edits were written.")
            plan = document.build_save(
                self.schemas[repository.id],
                payload.get("changes", []),
                payload.get("new_rows", []),
            )
            if not plan.changed:
                return {"revision": document.revision, "edits": 0, "additions": 0, "changed": False}
            try:
                atomic_replace(repository.store, plan.data)
            except OSError as error:
                raise ValidationError(f"Could not save {repository.store}: {error.strerror or error}") from error
            entries = [("cell_edit", edit) for edit in plan.edits]
            entries.extend(("row_add", addition) for addition in plan.additions)
            entries.append(
                (
                    "save",
                    {
                        "previous_revision": expected_revision,
                        "revision": plan.revision,
                        "edit_count": len(plan.edits),
                        "addition_count": len(plan.additions),
                    },
                )
            )
            ChangeLog(repository.log, repository.id).append_many(entries)
            return {
                "revision": plan.revision,
                "edits": len(plan.edits),
                "additions": len(plan.additions),
                "changed": True,
            }

    def read_log(self, repository_id: str | None, limit: Any = 500) -> dict[str, Any]:
        repository = self.repository(repository_id)
        if isinstance(limit, str):
            try:
                limit = int(limit)
            except ValueError as error:
                raise ValidationError("Log limit must be an integer") from error
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0 or limit > 5000:
            raise ValidationError("Log limit must be between 0 and 5000")
        return {"repository": repository.to_dict(), "rows": ChangeLog(repository.log, repository.id).read(limit)}
