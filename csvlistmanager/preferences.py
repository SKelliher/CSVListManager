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
        default = {"selected_repository": self.repository_ids[0], "modes": {}}
        if not self.path.exists():
            return default
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValidationError(f"Cannot load preferences {self.path}: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("modes", {}), dict):
            raise ValidationError(f"Preferences {self.path} must contain a JSON object with a modes object")
        selected = value.get("selected_repository", self.repository_ids[0])
        if selected not in self.repository_ids:
            selected = self.repository_ids[0]
        modes = {
            repository: mode
            for repository, mode in value.get("modes", {}).items()
            if repository in self.repository_ids and mode in MODES
        }
        return {"selected_repository": selected, "modes": modes}

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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            modes = {repository: self._data["modes"].get(repository, "editable") for repository in self.repository_ids}
            return {"selected_repository": self._data["selected_repository"], "modes": modes}

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
