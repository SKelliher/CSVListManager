"""Persistent local UI preferences, kept outside source and data files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from .config import MODES
from .errors import ValidationError


class PreferenceStore:
    def __init__(self, path: Path, repository_ids: list[str]):
        self.path = path
        self.repository_ids = repository_ids
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        default = {"selected_repository": self.repository_ids[0], "modes": {}, "views": {}}
        if not self.path.exists():
            return default
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValidationError(f"Cannot load preferences {self.path}: {error}") from error
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("modes", {}), dict)
            or not isinstance(value.get("views", {}), dict)
        ):
            raise ValidationError(f"Preferences {self.path} must contain JSON objects for modes and views")
        selected = value.get("selected_repository", self.repository_ids[0])
        if selected not in self.repository_ids:
            selected = self.repository_ids[0]
        modes = {
            repository: mode
            for repository, mode in value.get("modes", {}).items()
            if repository in self.repository_ids and mode in MODES
        }
        views: dict[str, Any] = {}
        for repository, raw_view in value.get("views", {}).items():
            if repository not in self.repository_ids or not isinstance(raw_view, dict):
                continue
            raw_widths = raw_view.get("column_widths", {})
            widths = {}
            if isinstance(raw_widths, dict):
                widths = {
                    name: width
                    for name, width in raw_widths.items()
                    if isinstance(name, str)
                    and name
                    and isinstance(width, int)
                    and not isinstance(width, bool)
                    and 80 <= width <= 600
                }
            note_visible = raw_view.get("note_visible", True)
            views[repository] = {
                "note_visible": note_visible if isinstance(note_visible, bool) else True,
                "column_widths": widths,
            }
        return {"selected_repository": selected, "modes": modes, "views": views}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, prefix=self.path.name + ".", mode="w", encoding="utf-8", delete=False
            ) as handle:
                temporary_name = handle.name
                json.dump(self._data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
            temporary_name = None
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def _view_unlocked(self, repository: str) -> dict[str, Any]:
        view = self._data["views"].get(repository, {})
        return {
            "note_visible": view.get("note_visible", True),
            "column_widths": dict(view.get("column_widths", {})),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            modes = {repository: self._data["modes"].get(repository, "editable") for repository in self.repository_ids}
            views = {repository: self._view_unlocked(repository) for repository in self.repository_ids}
            return {"selected_repository": self._data["selected_repository"], "modes": modes, "views": views}

    @property
    def selected(self) -> str:
        with self._lock:
            return self._data["selected_repository"]

    def select(self, repository: str) -> dict[str, Any]:
        with self._lock:
            self._data["selected_repository"] = repository
            self._save()
            return self.snapshot()

    def set_mode(self, repository: str, mode: str) -> dict[str, Any]:
        with self._lock:
            self._data["modes"][repository] = mode
            self._save()
            return self.snapshot()

    def mode(self, repository: str) -> str:
        with self._lock:
            return self._data["modes"].get(repository, "editable")

    def view(self, repository: str) -> dict[str, Any]:
        with self._lock:
            return self._view_unlocked(repository)

    def set_view(
        self, repository: str, note_visible: bool, column_widths: dict[str, int]
    ) -> dict[str, Any]:
        with self._lock:
            self._data["views"][repository] = {
                "note_visible": note_visible,
                "column_widths": dict(column_widths),
            }
            self._save()
            return self._view_unlocked(repository)
